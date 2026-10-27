"""Job domain helper — fetch Databricks job data."""
import base64
import itertools

from starboard_skills.helpers.contract import (
    ACQUIRE_DEFAULT_BYTES,
    ArgError,
    CodeNotInWorkspaceError,
    HelperError,
    NotFoundError,
    byte_budget,
    clip_text,
    raise_api_error,
    redact_emails,
    scrub_identity,
)
from starboard_skills.helpers.contract import make_client as _client

#: Gap code: the task's code is not a workspace object ``job code`` can export.
CODE_NOT_IN_WORKSPACE = "code_not_in_workspace"


def register(subparsers) -> None:
    p = subparsers.add_parser("job", help="Job operations")
    sp = p.add_subparsers(dest="command", required=True)

    fetch = sp.add_parser("fetch", help="Fetch job details")
    fetch.add_argument("--job-id", required=True, type=int)
    fetch.set_defaults(func=cmd_fetch)

    runs = sp.add_parser("runs", help="List recent runs")
    runs.add_argument("--job-id", required=True, type=int)
    runs.add_argument("--limit", type=int, default=10)
    runs.set_defaults(func=cmd_runs)

    list_jobs = sp.add_parser("list", help="List all jobs")
    list_jobs.add_argument("--limit", type=int, default=25)
    list_jobs.add_argument("--name-filter", type=str, default=None)
    list_jobs.set_defaults(func=cmd_list)

    run_output = sp.add_parser(
        "run-output",
        help="Fetch a task run's error, trace, logs and notebook result (identity scrubbed)",
    )
    run_output.add_argument("--run-id", required=True, type=int)
    run_output.add_argument(
        "--task-key", type=str, default=None,
        help="Task to read; required when the run has more than one task",
    )
    run_output.add_argument(
        "--max-bytes", type=byte_budget, default=ACQUIRE_DEFAULT_BYTES,
        help=f"Cap per text field in bytes (default {ACQUIRE_DEFAULT_BYTES})",
    )
    run_output.set_defaults(func=cmd_run_output)

    code = sp.add_parser(
        "code", help="Export a notebook / Python-file task's workspace source"
    )
    code.add_argument("--job-id", required=True, type=int)
    code.add_argument(
        "--task-key", type=str, default=None,
        help="Task to read; required when the job has more than one task",
    )
    code.add_argument(
        "--max-bytes", type=byte_budget, default=ACQUIRE_DEFAULT_BYTES,
        help=f"Cap on the exported source in bytes (default {ACQUIRE_DEFAULT_BYTES})",
    )
    code.set_defaults(func=cmd_code)


def cmd_fetch(args):
    w = _client()
    try:
        job = w.jobs.get(args.job_id)
        return {
            "job_id": job.job_id,
            "name": job.settings.name if job.settings else None,
            "settings": job.settings.as_dict() if job.settings else {},
        }
    except Exception as e:
        raise_api_error(e, not_found_message=f"Job {args.job_id} not found")


def cmd_runs(args):
    w = _client()
    try:
        # SDK `limit` is the page size on an auto-paginating iterator, not a total
        # cap — enforce the requested cap client-side with islice.
        runs = list(
            itertools.islice(w.jobs.list_runs(job_id=args.job_id), args.limit)
        )
        return {
            "job_id": args.job_id,
            "runs": [
                {
                    "run_id": r.run_id,
                    "state": r.state.as_dict() if r.state else {},
                    "start_time": r.start_time,
                    "end_time": r.end_time,
                    "execution_duration": r.execution_duration,
                }
                for r in runs
            ],
        }
    except Exception as e:
        raise_api_error(e, not_found_message=f"Job {args.job_id} not found")


def cmd_list(args):
    w = _client()
    try:
        # `w.jobs.list()` is an auto-paginating iterator (the SDK `limit` is only
        # the page size), so materializing it returns ALL jobs. Iterate and stop
        # once we have `--limit` results — applying `--name-filter` inline so the
        # cap counts matches, not raw rows.
        name_filter = args.name_filter.lower() if args.name_filter else None
        result = []
        for j in w.jobs.list():
            name = j.settings.name if j.settings else None
            if name_filter and name_filter not in (name or "").lower():
                continue
            result.append({"job_id": j.job_id, "name": name})
            if len(result) >= args.limit:
                break
        return {"jobs": result, "count": len(result)}
    except Exception as e:
        raise_api_error(e)


def _pick_task(tasks, task_key, *, owner: str):
    """The task ``task_key`` names (the only task when unset); the latest attempt wins.

    More than one task without ``--task-key`` is exit 4 listing the keys; an unknown
    key is exit 2.
    """
    keys = sorted({t.task_key for t in tasks if t.task_key})
    if task_key is None:
        if len(keys) > 1:
            raise ArgError(
                f"{owner} has {len(keys)} tasks; pass --task-key (one of: {', '.join(keys)})"
            )
        task_key = keys[0] if keys else None
    matches = [t for t in tasks if t.task_key == task_key]
    if not matches:
        raise NotFoundError(
            f"Task {task_key!r} not in {owner} (tasks: {', '.join(keys) or 'none'})"
        )
    return max(matches, key=lambda t: getattr(t, "attempt_number", None) or 0)


def cmd_run_output(args):
    """``jobs.get_run`` → the task run → ``jobs.get_run_output``, scrubbed and capped.

    ``logs`` / ``error_trace`` keep their tail (the failure is at the end) and the
    notebook result its head; ``truncated`` says which were cut here, while the
    SDK's own ``logs_truncated`` is passed through unchanged.
    """
    w = _client()
    try:
        run = w.jobs.get_run(args.run_id)
        tasks = run.tasks or []
        if tasks:
            task = _pick_task(tasks, args.task_key, owner=f"Run {args.run_id}")
            task_run_id, task_key = task.run_id, task.task_key
        else:
            task_run_id, task_key = args.run_id, args.task_key
        out = w.jobs.get_run_output(task_run_id)
    except HelperError:
        raise
    except Exception as e:
        raise_api_error(e, not_found_message=f"Run {args.run_id} not found")
    cap = args.max_bytes
    error_trace, trace_cut = clip_text(redact_emails(out.error_trace), cap, tail=True)
    logs, logs_cut = clip_text(redact_emails(out.logs), cap, tail=True)
    notebook = None
    result_cut = False
    if out.notebook_output is not None:
        result, result_cut = clip_text(redact_emails(out.notebook_output.result), cap)
        notebook = {"result": result, "truncated": out.notebook_output.truncated}
    meta = out.metadata
    return scrub_identity(
        {
            "run_id": args.run_id,
            "task_run_id": task_run_id,
            "task_key": task_key or getattr(meta, "task_key", None),
            "state": meta.state.as_dict() if meta is not None and meta.state else {},
            "error": clip_text(redact_emails(out.error), cap)[0],
            "error_trace": error_trace,
            "logs": logs,
            "logs_truncated": out.logs_truncated,
            "notebook_output": notebook,
            "truncated": {
                "error_trace": trace_cut, "logs": logs_cut, "notebook_result": result_cut,
            },
            "max_bytes": cap,
        }
    )


def _workspace_code_path(task, git_source) -> tuple[str, str]:
    """``(kind, workspace path)`` of a notebook / Python-file task, else exit 2 (gap).

    The gap is :class:`CodeNotInWorkspaceError` (``errors[0].code`` = ``CODE_NOT_IN_WORKSPACE``),
    not a missing resource.
    """
    from databricks.sdk.service.jobs import Source

    if task.notebook_task is not None:
        kind, path, source = "notebook", task.notebook_task.notebook_path, task.notebook_task.source
    elif task.spark_python_task is not None:
        kind, path = "python_file", task.spark_python_task.python_file
        source = task.spark_python_task.source
    else:
        raise CodeNotInWorkspaceError(
            f"{CODE_NOT_IN_WORKSPACE}: task {task.task_key!r} is not a notebook or "
            "Python-file task"
        )
    # An unset source means GIT when the job has a git_source (SDK ``Source`` doc).
    from_git = source == Source.GIT or (source is None and git_source is not None)
    if from_git or not path.startswith("/"):
        where = "a Git source" if from_git else "a non-workspace path"
        raise CodeNotInWorkspaceError(
            f"{CODE_NOT_IN_WORKSPACE}: task {task.task_key!r} runs {kind} code from "
            f"{where}; it cannot be exported from the workspace"
        )
    return kind, path


def cmd_code(args):
    """``jobs.get`` → the task's workspace path → ``workspace.export(SOURCE)``, capped."""
    from databricks.sdk.service.workspace import ExportFormat

    w = _client()
    try:
        job = w.jobs.get(args.job_id)
        settings = job.settings
        tasks = (settings.tasks if settings else None) or []
        task = _pick_task(tasks, args.task_key, owner=f"Job {args.job_id}")
        kind, path = _workspace_code_path(task, settings.git_source if settings else None)
        export = w.workspace.export(path, format=ExportFormat.SOURCE)
    except HelperError:
        raise
    except Exception as e:
        raise_api_error(e, not_found_message=f"Job {args.job_id} code not found")
    raw = base64.b64decode(export.content or "")
    code, cut = clip_text(redact_emails(raw.decode("utf-8", errors="replace")), args.max_bytes)
    return scrub_identity(
        {
            "job_id": args.job_id,
            "task_key": task.task_key,
            "kind": kind,
            "path": path,
            "file_type": export.file_type,
            "bytes": len(raw),
            "truncated": cut,
            "max_bytes": args.max_bytes,
            "code": code,
        }
    )
