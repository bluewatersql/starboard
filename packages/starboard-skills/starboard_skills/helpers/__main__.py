#!/usr/bin/env python3
"""starboard-helper <domain> <command> [options]

Thin Databricks data-fetching helper for Starboard skills (any host).

All output is a stable JSON envelope on stdout::

    {"ok": bool, "domain": str|null, "command": str|null,
     "data": <result>|null, "error": str|null,
     "meta": {"format": "json", "contract_version": "1.0"}}

Exit codes:
  0 = ok
  1 = authentication error
  2 = not found
  3 = API error
  4 = argument error
  7 = storage / integrity / access failure on an engagement run (message starts
      ``BLOCKED_ACCESS`` / ``STORAGE_INTEGRITY`` / ``NOT_FOUND`` / ``STORAGE_ERROR``)
  8 = transient Drive failure (``STORAGE_TRANSIENT``; retryable, nothing refused)

A failure with a machine code also carries ``errors: [{code, message, retryable}]``
(``error`` stays the message): e.g. ``WORKSPACE_TIMEOUT`` (retryable, exit 3: the SDK's
retry budget ran out) and ``CODE_NOT_IN_WORKSPACE`` (exit 2: ``job code`` on code that
lives outside the workspace — not a missing resource).

Engagement storage: a fetch command also takes ``--run-folder ID`` (outputs go to
that Drive run folder; ``--out`` becomes a run-relative path) and ``--stdout``
(print the full envelope; refused on a covered run). With ``--run-folder`` the
stdout envelope is bounded (24 000 bytes) and printed compact. A storage policy
refusal exits 2 with a message starting ``LOCAL_STORAGE_REFUSED`` /
``STORAGE_UNAVAILABLE``.

Workspace identity: every fetch command takes ``--profile NAME`` (a
``~/.databrickscfg`` profile; masks ambient ``DATABRICKS_HOST`` /
``DATABRICKS_TOKEN`` env auth), before or after the subcommand. Every client the
command builds uses it. On a ``--run-folder`` run whose identity was verified it
defaults to the verified profile, and a different one exits 2 with a message
starting ``PROFILE_MISMATCH``. The account-level ``finops budgets`` /
``finops log-delivery`` take an *account* profile instead and never inherit the
run's workspace profile.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from starboard_skills.helpers.contract import (
    EXIT_API,
    EXIT_ARG,
    EXIT_OK,
    ArgError,
    HelperError,
    HelperRun,
    NotFoundError,
    ProfileMismatchError,
    RunResult,
    api_error_text,
    bounded,
    build_meta,
    envelope,
    helper_writer,
    local_run_dir,
    record_evidence,
    redact_emails,
    refuse_local,
    relpath_flag,
    run_result,
    scrub_identity,
    storage_failure,
    use_profile,
)


class _HelperArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises :class:`ArgError` instead of exiting(2).

    This funnels every argparse failure (missing required args, bad choices,
    unknown subcommands) through the same envelope + exit-code path as runtime
    errors, so bad args deterministically produce exit code 4.
    """

    def error(self, message: str):  # type: ignore[override]
        raise ArgError(message)


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _HelperArgumentParser(
        prog="starboard-helper",
        description=(
            "Thin Databricks data-fetching helper for Starboard skills (any host). "
            "Fetch commands take --profile NAME (before or after the subcommand) to "
            "read as that ~/.databrickscfg profile; on a --run-folder run it defaults "
            "to the run's verified profile and any other profile is refused "
            "(PROFILE_MISMATCH, exit 2)."
        ),
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format (json is the default and only supported format).",
    )
    parser.add_argument(
        "--out",
        metavar="FILE",
        default=None,
        help=(
            "Write the full result envelope to FILE (parent dirs created) and "
            "print a compact summary to stdout instead. Use for large fetches "
            "(query history, job/table lists) to avoid truncating the payload "
            "in the tool result, then read FILE for the rows. May be placed "
            "before or after the subcommand. Errors are always printed, never "
            "redirected. Fetch commands also take --run-folder ID (write to that "
            "Drive run folder; FILE is then a run-relative path and stdout is a "
            "bounded envelope) and --stdout (print the full envelope; refused on "
            "a covered run), before or after the subcommand."
        ),
    )
    subparsers = parser.add_subparsers(dest="domain", required=True)

    from starboard_skills.helpers import (
        analyze,
        charts_render,
        cluster,
        database,
        diagnostic,
        discovery,
        engagement,
        finops,
        job,
        notebook,
        pipeline,
        query,
        run,
        serving,
        uc,
        verify,
        warehouse,
    )

    for mod in [
        job,
        pipeline,
        serving,
        query,
        warehouse,
        uc,
        cluster,
        finops,
        diagnostic,
        analyze,
        discovery,
        charts_render,
        database,
        run,
        verify,
        notebook,
        engagement,
    ]:
        mod.register(subparsers)

    _document_profile(subparsers)
    _document_global_flags(subparsers)
    return parser


_PROFILE_HELP = (
    "Databricks CLI profile (~/.databrickscfg) to read as; masks DATABRICKS_HOST / "
    "DATABRICKS_TOKEN env auth (default: ambient SDK credential chain). Global: may "
    "come before or after the subcommand. With --run-folder it defaults to the run's "
    "verified profile; a different one is refused (PROFILE_MISMATCH, exit 2)."
)
_ACCOUNT_PROFILE_HELP = (
    "Account-level Databricks CLI profile (accounts-console host + account_id) to "
    "read as; masks ambient auth env (default: ambient SDK credential chain). Never "
    "defaults to a run's verified workspace profile."
)


def _document_profile(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """List the global ``--profile`` in every fetch command's ``--help``.

    :func:`_extract_run_flags` strips the flag before parsing, so this option only
    documents it (and keeps a dangling ``--profile`` an argument error).
    """
    for domain, domain_parser in subparsers.choices.items():
        if domain not in _FETCH_DOMAINS:
            continue
        for action in domain_parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for leaf in action.choices.values():
                if any("--profile" in a.option_strings for a in leaf._actions):
                    continue
                account = bool(leaf.get_default("account_level"))
                leaf.add_argument(
                    "--profile",
                    default=None,
                    metavar="NAME",
                    help=_ACCOUNT_PROFILE_HELP if account else _PROFILE_HELP,
                )


_GLOBAL_FLAGS_EPILOG = (
    "global flags (accepted before or after the subcommand): --profile NAME (workspace "
    "profile), --out FILE (write the full envelope to FILE; with --run-folder a "
    "run-relative path), --run-folder ID (write into that Drive run folder), --stdout "
    "(print the full envelope; refused on a covered run)."
)


def _document_global_flags(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Name the global flags in every fetch command's ``--help`` epilog.

    They are stripped from argv before parsing, so a leaf's own flag list never shows
    them; the epilog does.
    """
    for domain, domain_parser in subparsers.choices.items():
        if domain not in _FETCH_DOMAINS:
            continue
        for action in domain_parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for leaf in action.choices.values():
                leaf.epilog = (
                    f"{leaf.epilog}\n\n{_GLOBAL_FLAGS_EPILOG}"
                    if leaf.epilog
                    else _GLOBAL_FLAGS_EPILOG
                )


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _emit_bounded(payload: dict[str, Any]) -> None:
    """Print ``payload`` within the stdout budget, compact (as the budget measures it)."""
    print(json.dumps(bounded(payload), default=str))


#: Data-fetching domains: the root ``--run-folder`` / ``--stdout`` flags apply to
#: these only (``run`` / ``verify`` / ``notebook`` / ``charts`` / ``engagement`` own
#: theirs).
_FETCH_DOMAINS = frozenset(
    {
        "job",
        "pipeline",
        "serving",
        "query",
        "warehouse",
        "uc",
        "cluster",
        "finops",
        "diagnostic",
        "analyze",
        "discovery",
        "database",
    }
)
#: Fetch domains that read no workload data (the self-describing catalog).
_NON_ACQUIRING_DOMAINS = frozenset({"discovery"})


# Domains whose subcommand owns ``--out`` as a real output path (not the global
# envelope-redirect). For these, the global ``--out`` extraction is skipped so
# the flag reaches the subparser intact. ``charts render --out chart.png`` writes
# a rendered PNG/SVG; redirecting its JSON envelope to that path would clobber the
# image and starve the subparser of its required argument. ``verify run`` and
# ``notebook render`` take ``--out DIR`` (the evidence / notebook directory).
_OUT_OWNING_DOMAINS = frozenset({"charts", "verify", "notebook"})


def _leading_domain(argv: list[str]) -> str | None:
    """Return the domain (first positional) token, skipping global value-flags.

    Global options that take a value (``--format``/``--out``/``--run-folder``/``--profile``) and their values,
    plus any other leading flags, are skipped so the first positional token —
    the subcommand domain — is found regardless of preceding global flags.
    """
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--format", "--out", "--run-folder", "--profile"):
            i += 2  # skip the flag and its value
            continue
        if a.startswith(("--format=", "--out=", "--run-folder=", "--profile=")):
            i += 1
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return None


def _extract_out(argv: list[str]) -> tuple[str | None, list[str]]:
    """Pull ``--out FILE`` / ``--out=FILE`` from anywhere in argv.

    Returns ``(out_path, remaining_argv)``. Stripping it before argparse lets
    ``--out`` appear either before or after the subcommand (argparse otherwise
    only accepts a top-level option before the subcommand). A trailing ``--out``
    with no value is left in place so argparse reports the argument error.

    For domains whose subcommand owns ``--out`` as a real output path
    (:data:`_OUT_OWNING_DOMAINS`, e.g. ``charts render``), extraction is skipped
    entirely so the flag reaches the subparser — the global envelope-redirect
    does not apply there.
    """
    if _leading_domain(argv) in _OUT_OWNING_DOMAINS:
        return None, list(argv)

    out: str | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--out":
            if i + 1 < len(argv):
                out = argv[i + 1]
                i += 2
                continue
            rest.append(arg)  # dangling --out → let argparse error on it
            i += 1
            continue
        if arg.startswith("--out="):
            out = arg.split("=", 1)[1]
            i += 1
            continue
        rest.append(arg)
        i += 1
    return out, rest


def _extract_run_flags(
    argv: list[str],
) -> tuple[str | None, bool, str | None, list[str]]:
    """Pull ``--run-folder ID``, ``--stdout`` and ``--profile NAME`` for fetch domains.

    Returns ``(run_folder, stdout, profile, remaining_argv)``; the ``=`` forms are
    accepted too, and a dangling ``--run-folder`` / ``--profile`` is left for
    argparse to reject. Other domains own these flags on their subcommands, so
    their argv is returned unchanged.
    """
    if _leading_domain(argv) not in _FETCH_DOMAINS:
        return None, False, None, list(argv)
    run_folder: str | None = None
    stdout = False
    profile: str | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--run-folder" and i + 1 < len(argv):
            run_folder = argv[i + 1]
            i += 2
            continue
        if arg == "--profile" and i + 1 < len(argv):
            profile = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--run-folder="):
            run_folder = arg.split("=", 1)[1]
        elif arg.startswith("--profile="):
            profile = arg.split("=", 1)[1]
        elif arg == "--stdout":
            stdout = True
        else:
            rest.append(arg)
        i += 1
    return run_folder, stdout, profile, rest


def _count_rows(data: Any) -> int | None:
    """Best-effort total row count for the stdout summary (no shape coupling).

    Prefers ``data["row_count"]``, then ``data["count"]``, when present (W27:
    avoids counting the ``columns`` list as rows, which inflated the count when a
    query result dict contained both ``columns`` and ``rows`` keys; run 7: nor an
    id list such as ``query slow``'s ``excluded_warehouse_ids``).
    """
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        # Prefer an explicit count — avoids counting column-name or id lists as rows.
        for key in ("row_count", "count"):
            if isinstance(data.get(key), int) and not isinstance(data[key], bool):
                return data[key]
        total = 0
        found = False
        for value in data.values():
            if isinstance(value, list):
                total += len(value)
                found = True
        return total if found else None
    return None


def _write_out(
    payload: dict[str, Any],
    path: str,
    run: HelperRun,
    *,
    source_kind: str | None = None,
) -> None:
    """Write the full envelope to ``path`` through the artifact sink; print a summary.

    Public / local: ``path`` is a local file and the summary is printed indented, as
    before. Drive (``--run-folder``): ``path`` is a run-relative path, the envelope
    becomes run evidence, and the summary is the bounded compact envelope.
    """
    text = json.dumps(payload, indent=2, default=str)
    data = text.encode("utf-8")
    rows = _count_rows(payload.get("data"))
    if not run.drive:
        out_path = Path(path)
        run.write(out_path, data, "application/json")
        summary: dict[str, Any] = {
            "ok": payload.get("ok"),
            "domain": payload.get("domain"),
            "command": payload.get("command"),
            "out": str(out_path),
            "bytes": len(data),
            "meta": payload.get("meta"),
        }
        if rows is not None:
            summary["rows"] = rows
        summary["note"] = (
            f"Full JSON written to {out_path}. Read that file for the data."
        )
        print(json.dumps(summary, indent=2, default=str))
        return

    rel = relpath_flag("--out", path, covered=run.covered)
    ref = run.write(rel, data, "application/json")
    domain, command = payload.get("domain"), payload.get("command")
    if ref is not None and source_kind:
        record_evidence(
            run,
            [(ref, f"starboard-helper {domain} {command}", rows, False)],
            source_kind=source_kind,
        )
    result = run_result(
        run,
        {
            "counts": {"rows": rows},
            "summary": {"out": rel, "bytes": len(data)},
            "note": f"Full JSON written to run artifact {rel}. Read it with --run-folder.",
        },
    )
    _emit_bounded(
        {
            "ok": True,
            "domain": domain,
            "command": command,
            "data": result,
            "meta": payload.get("meta"),
        }
    )


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    out_path, raw_argv = _extract_out(raw_argv)
    run_folder, want_stdout, profile, raw_argv = _extract_run_flags(raw_argv)

    try:
        args = parser.parse_args(raw_argv)
    except ArgError as exc:
        _emit(
            envelope(
                ok=False,
                domain=None,
                command=None,
                error=exc.message,
                meta=build_meta(),
            )
        )
        sys.exit(EXIT_ARG)

    # Expose the extracted global --out to commands that emit their own envelope (run check).
    # (Never set for _OUT_OWNING_DOMAINS: their extraction is skipped, so out_path is None.)
    if out_path is not None:
        args.out = out_path
    domain = getattr(args, "domain", None)
    command = getattr(args, "command", None)
    meta = build_meta(getattr(args, "format", "json"))

    try:
        if domain in _FETCH_DOMAINS:
            _fetch(
                args, domain, command, meta, out_path, run_folder, want_stdout, profile
            )
        data = args.func(args)
        success = envelope(
            ok=True, domain=domain, command=command, data=data, meta=meta
        )
        if isinstance(data, RunResult):
            _emit_bounded(success)
        elif out_path:
            with helper_writer(
                run_folder=None, local_root=local_run_dir(out_path), acquires=False
            ) as run:
                _write_out(success, out_path, run)
        else:
            _emit(success)
    except HelperError as exc:
        _emit(
            envelope(
                ok=False,
                domain=domain,
                command=command,
                error=exc.message,
                meta=meta,
                code=exc.code or None,
                retryable=exc.retryable,
            )
        )
        sys.exit(exc.exit_code)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - map any stray error to api-error
        failure = storage_failure(exc)
        _emit(
            envelope(
                ok=False,
                domain=domain,
                command=command,
                error=failure.message
                if failure
                else f"API error: {api_error_text(exc)}",
                meta=meta,
                code=(failure.code or None) if failure else None,
                retryable=failure.retryable if failure else False,
            )
        )
        sys.exit(failure.exit_code if failure else EXIT_API)
    sys.exit(EXIT_OK)


def _effective_profile(
    args: argparse.Namespace, run: HelperRun, profile: str | None, *, acquires: bool
) -> str | None:
    """The profile this fetch reads as.

    On a Drive run that reads customer workspace data the run's verified identity
    decides (:func:`~starboard_core.engagement.identity.run_profile`): an omitted
    ``--profile`` becomes the verified one and a different one raises
    ``PROFILE_MISMATCH`` (exit 2). Account-level commands, internal-source reads,
    the catalog domain and non-Drive runs use the explicit ``--profile`` as given.
    """
    if not (run.drive and acquires) or getattr(args, "account_level", False):
        return profile
    from starboard_core.engagement.identity import (  # lazy – kernel dep
        ProfileMismatch,
        run_profile,
    )

    try:
        return run_profile(run.descriptor(), profile)
    except ProfileMismatch as exc:
        raise ProfileMismatchError(str(exc)) from exc


def _write_not_found(
    exc: NotFoundError,
    domain: str | None,
    command: str | None,
    meta: dict[str, Any],
    out_path: str,
    run: HelperRun,
) -> None:
    """Write a not-found envelope (``ok: false``) to ``--out`` so the negative lookup is evidence.

    The exit code and stdout envelope are unchanged. On a Drive run ``out_path`` is a
    run-relative path written through the sink (nothing lands locally). A write failure
    is swallowed: the not-found error is what the caller must see.
    """
    failure = envelope(
        ok=False,
        domain=domain,
        command=command,
        error=exc.message,
        meta=meta,
        code=exc.code or None,
        retryable=exc.retryable,
    )
    data = json.dumps(failure, indent=2, default=str).encode("utf-8")
    with contextlib.suppress(Exception):
        target = (
            relpath_flag("--out", out_path, covered=run.covered)
            if run.drive
            else Path(out_path)
        )
        run.write(target, data, "application/json")


def _write_sql_sibling(args: argparse.Namespace, out_path: str, run: HelperRun) -> None:
    """``query sql --out X.json``: also write the statement to ``X.sql`` (the evidence pair).

    Bound ``--param`` values are listed as leading ``--`` comment lines. Drive: a
    run-relative sibling through the sink; local: next to ``--out``.
    """
    base = out_path[: -len(".json")] if out_path.lower().endswith(".json") else out_path
    lines = [f"-- param {p}" for p in (getattr(args, "param", None) or [])]
    text = "\n".join([*lines, str(args.sql).rstrip(), ""])
    target: Path | str = Path(f"{base}.sql")
    if run.drive:
        target = relpath_flag("--out", f"{base}.sql", covered=run.covered)
    run.write(target, (redact_emails(text) or text).encode("utf-8"), "text/plain")


def _fetch(
    args: argparse.Namespace,
    domain: str,
    command: str | None,
    meta: dict[str, Any],
    out_path: str | None,
    run_folder: str | None,
    want_stdout: bool,
    profile: str | None = None,
) -> None:
    """Run a fetch command under the storage policy, print, and exit (never returns).

    The decision is made, and any refusal raised, before the fetch runs. A covered
    run keeps the local write guard armed for the whole fetch. Workload data passes
    the identity scrub (D3-24) before it is printed or written: user-name / email /
    user-id keys are dropped and email-shaped values become ``<email>`` (so an
    ``owner`` that is a user still reads as set, and a group name is kept).

    Every client the command builds uses the effective ``--profile``
    (:func:`_effective_profile`), exposed to the command as ``args.profile``.
    """
    internal = bool(getattr(args, "internal_workspace_id", None))
    acquires = domain not in _NON_ACQUIRING_DOMAINS and not internal
    # Evidence names where the rows came from; the catalog domain reads none.
    source_kind = (
        None
        if domain in _NON_ACQUIRING_DOMAINS
        else ("internal_mirror" if internal else "customer_workspace")
    )
    with helper_writer(
        run_folder=run_folder, local_root=None, acquires=acquires
    ) as run:
        refuse_local(run, stdout=want_stdout)
        if run.drive and out_path:
            relpath_flag("--out", out_path, covered=run.covered)
        args.profile = _effective_profile(args, run, profile, acquires=acquires)
        try:
            with use_profile(args.profile):
                data = args.func(args)
        except NotFoundError as exc:
            if out_path:
                _write_not_found(exc, domain, command, meta, out_path, run)
            raise
        if domain not in _NON_ACQUIRING_DOMAINS:
            data = scrub_identity(data)
        success = envelope(
            ok=True, domain=domain, command=command, data=data, meta=meta
        )
        if out_path and domain == "query" and command == "sql":
            _write_sql_sibling(args, out_path, run)
        if out_path:
            _write_out(
                success,
                out_path,
                run,
                source_kind=source_kind,
            )
        elif run.drive and not want_stdout:
            _emit_bounded({**success, "data": run_result(run, {"result": data})})
        else:
            _emit(success)
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
