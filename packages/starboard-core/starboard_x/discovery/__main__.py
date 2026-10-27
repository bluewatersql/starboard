# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.discovery`` — deterministic discovery CLI.

Thin ``argparse`` wrapper over the discovery engine's ``data_only`` path. Every
invocation emits the stable JSON envelope (:mod:`starboard_x.contract`) and uses
the Phase-0 exit-code contract (``0 ok · 1 auth · 2 not-found · 3 api-error ·
4 arg-error``), plus ``9`` (``CAPTURE_INCOMPLETE``) for a budget-stopped
``run --run-folder`` capture.

Verbs:
    run --data-only [--packs D ...] [--lookback-days N] [--max-parallelism N]
        [--profile NAME] [--host URL] [--warehouse-id ID]
        [--authorization RUN_DIR|FILE | --run-folder ID] [--max-seconds N]
        [--stdout]

``--run-folder ID`` (``run`` and ``plan``) targets the run's Drive
folder. The authorized scope is read from the run folder's immutable descriptor and
verified identity check (no local ``--authorization``); ``--out-dir`` /
``--output-path`` become run-relative paths; nothing is written to local disk, and
stdout carries a bounded summary (IDs, refs, counts) instead of the row data. On an
internal-overlay install every customer-workspace run is covered: ``--run-folder`` is
required, and ``--authorization`` / ``--stdout`` are refused with exit 2
(``LOCAL_STORAGE_REFUSED``).

A run capture (``run --run-folder``, or ``run --authorization <run-dir>``) is
resumable: every finished query is recorded in the run (its ``capture/`` folder), and
re-running the same command reuses that work (``--no-cache`` does not change this). ``--max-seconds N`` (default
``DEFAULT_MAX_SECONDS``; ``0`` = no budget) bounds the capture: at the deadline no
new query starts, in-flight ones are cancelled, progress is saved and the command
exits ``9`` with a retryable ``CAPTURE_INCOMPLETE`` envelope whose ``data`` holds
the ``resume`` command and the ``progress`` (done/remaining/reused) counts.

``--authorization`` (``run`` and ``plan``) reads the run descriptor
(``<run-dir>/analysis/run-authorization.json``, or the given file) and limits
discovery to its ``authorized_scope.workspace_ids``: the connected workspace's
server ID must be authorized, and every workspace-grained ``system.*`` read is
filtered to those IDs. A missing or invalid descriptor is an arg-error.

``run`` always executes the **deterministic** path: it forces
``EngineConfig(data_only=True)`` and passes ``llm_client=None`` so no LLM
analysis or synthesis happens (the middle tier has no LLM wiring). The
``--data-only`` flag is accepted for interface parity and is implied.

The envelope's ``data`` block carries the **actual query result rows** per pack
(columns + rows, capped per query with a ``truncated`` flag) — not just counts —
so a host agent (Isaac / Claude / Codex) can reason over the data directly
without any server-side LLM call.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NoReturn

from starboard_core.domain.models.discovery.capture import (
    CAPTURE_INCOMPLETE,
    DEFAULT_MAX_SECONDS,
    EXIT_CAPTURE_INCOMPLETE,
    CaptureIncomplete,
    is_capture_path,
    resume_command,
)
from starboard_core.engagement.enforce import (
    WriterContext,
    covered,
    decide_for_writer,
    refuse_local,
    writer_context,
)
from starboard_core.engagement.overlay import detect_overlay
from starboard_core.engagement.reads import run_relpath
from starboard_core.engagement.row_scope import WorkspaceAuthorizationError
from starboard_core.engagement.sink import (
    ArtifactSink,
    LocalStorageRefused,
    load_engagement_storage,
)
from starboard_core.engagement.write_guard import LocalWriteRefused
from starboard_core.ports.engagement_storage import EngagementStoragePort

from starboard_x import _cli
from starboard_x.contract import ArgError, AuthError, build_meta, envelope, to_jsonable
from starboard_x.discovery._authorization import (  # noqa: F401  (re-exported)
    AUTHORIZATION_HELP,
    ENVELOPE_RESERVE,
    OVERLAY_AUTHORIZATION_REQUIRED,
    bounded_stdout,
    load_authorized_workspace_ids,
    load_authorized_workspace_ids_from_run_folder,
    local_capture_sink,
    resolve_run_folder_profile,
    storage_refusals,
)

# Shared, dep-light result serializers — the SAME shape the internal
# ``starboard --discover --json`` path emits, so the two entry points cannot
# drift. Re-exported here so ``disc.<name>`` references keep resolving.
from starboard_x.discovery._serialize import (  # noqa: F401  (re-exported)
    _MAX_ROWS_PER_QUERY,
    _query_rows,
    _safe_pack_name,
    _serialize_query,
    fit_summary,
    serialize_result,
    write_envelope_file,
    write_result_files,
)

_DOMAIN = "discovery"

#: Stdout budget of a covered ``--run-folder`` summary (the shared default is 24 000).
_SUMMARY_MAX_BYTES = 8_000

# Attribute under which ``build_engine`` stashes the async Databricks client on
# the engine so :func:`_cmd_run` can drive its async lifecycle (auth + warehouse
# resolution happen inside ``async with client``). Absent on fake engines that
# tests inject, in which case the run path simply skips initialization.
_CLIENT_ATTR = "_starboard_databricks_client"


def build_engine(args: argparse.Namespace) -> Any:
    """Build a discovery engine for the deterministic (data-only) path.

    Lazily imports the ``starboard`` server package so that importing this CLI
    module stays dep-light and SDK-free. Enforces ``data_only=True`` and
    ``llm_client=None``. Tests patch this function to inject a fake engine.

    CLI auth targeting (``--profile`` / ``--host`` / ``--warehouse-id``) is
    threaded through the shared config + resolver: ``--profile`` is applied via
    ``DATABRICKS_CONFIG_PROFILE`` (the resolver's profile source), while
    ``--host`` / ``--warehouse-id`` override the resolved :class:`EnvConfig`.

    A run capture sets ``args.capture_sink`` (the ``--run-folder`` sink, or the local
    run directory of ``--authorization``) and ``args.capture_deadline`` (monotonic
    seconds or ``None``): the engine then keeps a resumable capture record there,
    bounded by the deadline. Only a run-folder sink is also the report sink.

    Raises:
        AuthError: when the workspace client / config cannot be constructed.
        ArgError: ``--authorization`` names a missing or invalid run descriptor,
            or is absent on an internal-overlay install.
    """
    # ``--run-folder`` runs: the caller already read the scope from the run's Drive
    # descriptor (``args.authorized_workspace_ids``); no local descriptor is involved.
    authorized_ids = getattr(args, "authorized_workspace_ids", None)
    if authorized_ids is None:
        authorization = getattr(args, "authorization", None)
        if not authorization and detect_overlay().enabled:
            raise ArgError(OVERLAY_AUTHORIZATION_REQUIRED)
        authorized_ids = (
            load_authorized_workspace_ids(authorization) if authorization else None
        )

    try:
        from starboard.bootstrap import (
            AsyncDatabricksClient,
            AsyncSQLExecutor,
            DiscoveryEngine,
            EngineConfig,
            apply_cli_target,
            create_default_registry,
            get_config,
        )
    except Exception as exc:  # noqa: BLE001 - missing server package / extra
        raise AuthError(
            "the discovery engine is unavailable — install the server package "
            'and extra: pip install "starboard[discovery]". '
            f"(import failed: {exc})"
        ) from exc

    # Validate --packs up front so an unknown domain/pack fails fast (arg-error)
    # rather than silently selecting nothing. Selectors are pack ids or domains.
    registry = create_default_registry()
    if getattr(args, "packs", None):
        known = registry.known_selectors()
        unknown = [p for p in args.packs if p not in known]
        if unknown:
            raise ArgError(
                "unknown --packs value(s): "
                + ", ".join(sorted(unknown))
                + ". Valid domains/packs: "
                + ", ".join(sorted(known))
            )

    if getattr(args, "only", None):
        known = registry.known_selectors()
        unknown = [p for p in args.only if p not in known]
        if unknown:
            raise ArgError(
                "unknown --only value(s): "
                + ", ".join(sorted(unknown))
                + ". Valid domains/packs: "
                + ", ".join(sorted(known))
            )

    try:
        # Profile is resolved from the environment by the unified auth resolver
        # (WorkspaceTarget.resolve); set it before building the client. Never
        # auto-selected — only applied when the user passes --profile.
        # An explicit --host without --profile drops the ambient profile.
        apply_cli_target(getattr(args, "profile", None), getattr(args, "host", None))

        config = get_config()
        overrides: dict[str, Any] = {}
        if getattr(args, "host", None):
            overrides["databricks_host"] = args.host
        if getattr(args, "warehouse_id", None):
            overrides["databricks_warehouse_id"] = args.warehouse_id
        if overrides:
            config = config.model_copy(update=overrides)

        client = AsyncDatabricksClient(cfg=config)
        sql_executor = AsyncSQLExecutor(client)
    except Exception as exc:  # noqa: BLE001 - auth / config resolution failure
        raise AuthError(f"could not build a Databricks client: {exc}") from exc

    capture_sink = getattr(args, "capture_sink", None)
    engine_config = EngineConfig(
        lookback_days=args.lookback_days,
        max_parallelism=args.max_parallelism,
        domains=args.packs,
        exact_packs=getattr(args, "only", None),
        data_only=True,  # deterministic path — never run the LLM phases
        authorized_workspace_ids=authorized_ids,
        sink=None if getattr(capture_sink, "kind", None) == "local" else capture_sink,
        capture=capture_sink is not None,
        capture_sink=capture_sink,
        deadline=getattr(args, "capture_deadline", None),
    )

    engine = DiscoveryEngine(
        sql_executor=sql_executor,
        llm_client=None,  # no LLM: analysis/synthesis are skipped
        config=engine_config,
        query_registry=registry,
        workspace_id_probe=client.get_workspace_id,  # client entered first
    )
    # Stash the client so the run path can initialize it (resolve auth +
    # warehouse, incl. autocreate) within the event loop before queries run.
    setattr(engine, _CLIENT_ATTR, client)
    return engine


async def _run_engine(engine: Any) -> Any:
    """Initialize the Databricks client (if present) then run the engine.

    The async client resolves auth and the SQL warehouse (including autocreate)
    inside ``__aenter__``; without this the executor would fail with a "No SQL
    warehouse configured" error. Fake engines injected by tests carry no client,
    so initialization is skipped and the engine runs directly.

    Failures while entering the client's context (auth / config / warehouse
    resolution) are classified as :class:`AuthError` so they map to the exit-1
    auth code; failures during ``engine.run`` propagate as api-errors (exit 3).
    """
    client = getattr(engine, _CLIENT_ATTR, None)
    if client is None or not hasattr(client, "__aenter__"):
        return await engine.run()

    entered = False
    try:
        await client.__aenter__()
        entered = True
        return await engine.run()
    except (AuthError, LocalWriteRefused):
        raise
    except WorkspaceAuthorizationError as exc:
        raise AuthError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - classify init vs run failures
        if not entered:
            raise AuthError(
                f"could not authenticate the Databricks client: {exc}"
            ) from exc
        raise
    finally:
        if entered:
            await client.__aexit__(None, None, None)


@dataclass(frozen=True)
class _RunTarget:
    """Where a command's outputs go: the Drive run (``ctx``) or the local public path."""

    ctx: WriterContext | None
    storage: EngagementStoragePort | None

    @property
    def sink(self) -> ArtifactSink | None:
        return None if self.ctx is None else self.ctx.sink

    @property
    def covered(self) -> bool:
        return self.ctx is not None and covered(self.ctx.decision)


@contextmanager
def _run_target(args: argparse.Namespace) -> Iterator[_RunTarget]:
    """Decide, gate and guard a customer-workspace command.

    * ``--run-folder``: a Drive sink; the authorized scope is read from the run
      folder and handed to :func:`build_engine` as ``args.authorized_workspace_ids``,
      and ``args.profile`` defaults to the run's verified profile (another one is
      refused: ``PROFILE_MISMATCH``, exit 2).
      On an overlay install the run is covered: the write guard is armed for the
      whole command and ``--authorization`` / ``--stdout`` are refused.
    * No ``--run-folder`` on an overlay install: refused (exit 2).
    * No ``--run-folder`` on a public install: the unchanged local path.

    Storage refusals leave as exit-2 errors (``LOCAL_STORAGE_REFUSED``,
    ``STORAGE_UNAVAILABLE``).
    """
    run_folder: str | None = getattr(args, "run_folder", None)
    authorization = getattr(args, "authorization", None)
    overlay = detect_overlay()
    cache: list[EngagementStoragePort] = []

    def storage_factory() -> EngagementStoragePort:
        if not cache:
            cache.append(load_engagement_storage())
        return cache[0]

    with storage_refusals():
        decision = decide_for_writer(
            run_folder_id=run_folder,
            local_run_dir=None,
            acquires_customer_data=True,
            overlay=overlay,
        )
        refuse_local(
            decision,
            authorization=authorization,
            stdout=getattr(args, "stdout", False),
        )
        if covered(decision) and not run_folder:
            raise LocalStorageRefused(
                decision.refusal or "outputs must go to the run's Drive folder",
                flag="--run-folder",
            )
        if run_folder and authorization:
            raise ArgError(
                "--authorization reads a local run directory; with --run-folder the "
                "authorization is the run descriptor in Drive. Drop --authorization"
            )
        if not run_folder and not covered(decision):
            yield _RunTarget(None, None)
            return
        with writer_context(
            run_folder_id=run_folder,
            local_root=None,
            acquires_customer_data=True,
            storage_factory=storage_factory,
            overlay=overlay,
        ) as ctx:
            storage = storage_factory()
            assert run_folder is not None  # noqa: S101 - covered decisions refuse without one
            args.authorized_workspace_ids = (
                load_authorized_workspace_ids_from_run_folder(storage, run_folder)
            )
            # The verified identity reads: --profile defaults to the verified one.
            args.profile = resolve_run_folder_profile(
                storage,
                run_folder,
                getattr(args, "profile", None),
                getattr(args, "host", None),
            )
            yield _RunTarget(ctx, storage)


def _count(result: Any) -> dict[str, int]:
    packs = getattr(result, "pack_results", []) or []
    queries = [qr for pr in packs for qr in (getattr(pr, "results", []) or [])]
    return {
        "packs": len(packs),
        "queries": len(queries),
        "succeeded": sum(1 for qr in queries if getattr(qr, "succeeded", False)),
    }


def _write_to_run(
    result: Any, target: _RunTarget, args: argparse.Namespace
) -> dict[str, Any]:
    """Write the discovery outputs to the run's sink; return the bounded summary data."""
    sink = target.sink
    assert sink is not None  # noqa: S101 - callers check target.ctx
    run_folder: str = args.run_folder
    scope = tuple(args.authorized_workspace_ids)
    is_covered = target.covered
    out_dir: str | None = getattr(args, "out_dir", None)
    output_path: str | None = getattr(args, "output_path", None)
    counts = _count(result)

    if output_path and output_path.lower().endswith(".json"):
        relpath = run_relpath(
            "--output-path", output_path, covered_run=is_covered, arg_error=ArgError
        )
        data = serialize_result(result)
        refs = write_envelope_file(data, sink, relpath, scope_workspace_ids=scope)
        summary: dict[str, Any] = {
            "envelope_path": relpath,
            "pack_count": data.get("pack_count", 0),
            "facts": data.get("facts"),
        }
    else:
        prefix = ""
        chosen = output_path or out_dir
        if chosen:
            flag = "--output-path" if output_path else "--out-dir"
            prefix = run_relpath(
                flag, chosen, covered_run=is_covered, arg_error=ArgError
            )
        layout = write_result_files(
            result, sink, prefix=prefix, scope_workspace_ids=scope
        )
        refs = layout["refs"]
        summary = {
            "layout_prefix": prefix,
            "facts": layout["facts"],
            "packs": layout["manifest"],
        }
    # Verdict first, compact refs last (the per-object revision/md5/mime made the
    # summary most of its size); same shape as ``starboard --discover --run-folder``.
    payload: dict[str, Any] = {
        "counts": counts,
        "errors": list(getattr(result, "errors", []) or []),
        "run_id": sink.run_id,
        "run_folder_id": run_folder,
        "summary": summary,
        "resumed": getattr(result, "resumed", None),
        "refs": [
            {k: v for k, v in r.items() if k in ("path", "object_id", "size")}
            for r in refs
            if not is_capture_path(r["path"])
        ],
        "note": "Rows are in the run folder (refs). Read bounded excerpts with "
        "`starboard-helper engagement read`.",
    }
    if not is_covered:
        return payload
    fitted = fit_summary(payload, max_bytes=_SUMMARY_MAX_BYTES - ENVELOPE_RESERVE)
    return bounded_stdout(fitted, max_bytes=_SUMMARY_MAX_BYTES)


def _cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    max_seconds: int | None = getattr(args, "max_seconds", None)
    authorization = getattr(args, "authorization", None)
    if max_seconds is not None and (
        max_seconds < 0 or not (getattr(args, "run_folder", None) or authorization)
    ):
        raise ArgError(
            "--max-seconds bounds a resumable run capture: pass it with --run-folder "
            "or --authorization <run-dir>, as 0 (no budget) or a positive number of "
            "seconds"
        )
    with _run_target(args) as target:
        # A run capture resumes from the run: its Drive folder, or the local run
        # directory of --authorization.
        sink = target.sink
        if sink is None and authorization:
            sink = local_capture_sink(authorization)
        if sink is not None:
            budget = DEFAULT_MAX_SECONDS if max_seconds is None else max_seconds
            args.capture_sink = sink
            args.capture_deadline = started + budget if budget > 0 else None
        engine = build_engine(args)
        try:
            result = asyncio.run(_run_engine(engine))
        except CaptureIncomplete as exc:
            _exit_capture_incomplete(exc)
        if target.ctx is not None:
            return _write_to_run(result, target, args)
        return _write_local(result, args)


def _exit_capture_incomplete(exc: CaptureIncomplete) -> NoReturn:
    """Emit the retryable ``CAPTURE_INCOMPLETE`` envelope and exit 9."""
    _cli.emit(
        envelope(
            ok=False,
            domain=_DOMAIN,
            command="run",
            data={
                "progress": exc.progress(),
                "resume": resume_command(
                    ["python", "-m", "starboard_x.discovery"], sys.argv[1:]
                ),
                "hint": "Progress is saved in the run (capture/); re-run the "
                "same command to resume.",
            },
            error=str(exc),
            meta=build_meta(),
            code=CAPTURE_INCOMPLETE,
            retryable=True,
        )
    )
    sys.exit(EXIT_CAPTURE_INCOMPLETE)


def _write_local(result: Any, args: argparse.Namespace) -> dict[str, Any]:
    """The public path: local ``--output-path`` / ``--out-dir``, or the full envelope."""
    # W33: --output-path support.
    # A path ending in .json writes the full serialized envelope there and
    # returns a compact one-liner manifest (same pattern as --out-dir but for
    # a single file).  A directory path (no .json suffix) is treated exactly
    # like the existing --out-dir.
    output_path: str | None = getattr(args, "output_path", None)
    if output_path:
        import json as _json
        from pathlib import Path as _Path

        p = _Path(output_path)
        if p.suffix.lower() == ".json":
            data = serialize_result(result)
            p.parent.mkdir(parents=True, exist_ok=True)
            text = _json.dumps(data, indent=2, default=str)
            p.write_text(text)
            return {
                "output_path": str(p),
                "bytes": len(text.encode()),
                "pack_count": data.get("pack_count", 0),
                "note": f"Full JSON written to {p}. Read that file for the data.",
            }
        # Directory path — delegate to the existing write_result_files path.
        return write_result_files(result, output_path)

    if getattr(args, "out_dir", None):
        return write_result_files(result, args.out_dir)
    return serialize_result(result)


async def _run_plan(engine: Any) -> Any:
    """Enter the client context (auth + warehouse) then run ``engine.plan()``."""
    client = getattr(engine, _CLIENT_ATTR, None)
    if client is None or not hasattr(client, "__aenter__"):
        return await engine.plan()
    entered = False
    try:
        await client.__aenter__()
        entered = True
        return await engine.plan()
    except (AuthError, LocalWriteRefused):
        raise
    except WorkspaceAuthorizationError as exc:
        raise AuthError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        if not entered:
            raise AuthError(
                f"could not authenticate the Databricks client: {exc}"
            ) from exc
        raise
    finally:
        if entered:
            await client.__aexit__(None, None, None)


def serialize_plan(plan: Any, lookback_days: int) -> dict[str, Any]:
    """Serialize a ``PlanResult`` into the plan envelope data block."""
    selection = plan.selection
    return {
        "lookback_days": lookback_days,
        "products": to_jsonable(
            dict(
                sorted(
                    (getattr(plan, "products", {}) or {}).items(),
                    key=lambda kv: -kv[1],
                )
            )
        ),
        "recommended": [
            {"domain": d.domain, "packs": list(d.packs), "dbus": d.dbus}
            for d in getattr(selection, "recommended", [])
        ],
        "always_recommended": list(getattr(selection, "always_recommended", [])),
        "contextual": list(getattr(selection, "contextual", [])),
        "audit_succeeded": bool(getattr(plan, "audit_succeeded", False)),
        "trace_id": getattr(plan, "trace_id", ""),
    }


def _cmd_plan(args: argparse.Namespace) -> dict[str, Any]:
    with _run_target(args) as target:
        engine = build_engine(args)
        plan = asyncio.run(_run_plan(engine))
        data = serialize_plan(plan, lookback_days=args.lookback_days)
        if not target.covered:
            return data
        return bounded_stdout(
            {
                "run_id": target.sink.run_id if target.sink else None,
                "run_folder_id": args.run_folder,
                "summary": data,
            }
        )


RUN_FOLDER_HELP = (
    "Drive run folder ID (from `starboard-helper engagement route`). Outputs go to "
    "the run folder, never to local disk: --out-dir / --output-path become "
    "run-relative paths, the authorized scope is the run's Drive descriptor, and "
    "stdout is a bounded summary. Required on internal-overlay installs."
)


def _add_run_folder_flags(parser: argparse.ArgumentParser, *, stdout: bool) -> None:
    parser.add_argument(
        "--run-folder",
        dest="run_folder",
        default=None,
        metavar="ID",
        help=RUN_FOLDER_HELP,
    )
    if stdout:
        parser.add_argument(
            "--stdout",
            action="store_true",
            default=False,
            help=(
                "Print the full data envelope on stdout (the public default when no "
                "--out-dir/--output-path is given). Refused on covered runs, which "
                "never print rows."
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.discovery",
        description="Deterministic workspace discovery (data-only, no LLM).",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_run = subparsers.add_parser(
        "run", help="Run the deterministic (data-only) discovery pipeline."
    )
    p_run.add_argument(
        "--data-only",
        action="store_true",
        help="Skip LLM analysis/synthesis (implied — this path is always data-only).",
    )
    selector = p_run.add_mutually_exclusive_group()
    selector.add_argument(
        "--packs",
        nargs="+",
        default=None,
        metavar="DOMAIN",
        help=(
            "Restrict discovery to these domain/pack names (product-selected "
            "subset; always-run packs still run). Unknown names are rejected."
        ),
    )
    selector.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="PACK",
        help=(
            "Run EXACTLY these packs — no audit, no always-run injection. "
            "Use after `plan` for a cheap per-domain loop."
        ),
    )
    p_run.add_argument(
        "--out-dir",
        dest="out_dir",
        default=None,
        metavar="DIR",
        help=(
            "Write each pack's rows to DIR/raw/<pack>.json and print a compact "
            "manifest to stdout instead of the full envelope. Avoids truncating "
            "large payloads through stdout capture."
        ),
    )
    p_run.add_argument(
        "--output-path",
        dest="output_path",
        default=None,
        metavar="PATH",
        help=(
            "Output destination for discovery results. "
            "A path ending in .json writes the full serialized envelope to exactly "
            "that file and prints a compact summary to stdout (same as "
            "starboard --discover --output-path). "
            "A directory path writes per-pack raw files (same as --out-dir). "
            "Mutually preferred over --out-dir when both are given."
        ),
    )
    p_run.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        default=False,
        help=(
            "Accept and document flag for interface parity with "
            "``starboard --discover --no-cache``. "
            "This path has no server-side cache; the flag is accepted but has no "
            "effect on query execution. It does not affect --run-folder resume."
        ),
    )
    p_run.add_argument(
        "--max-seconds",
        dest="max_seconds",
        type=int,
        default=None,
        metavar="N",
        help=(
            f"Wall-clock budget of a run capture (default {DEFAULT_MAX_SECONDS}; "
            f"0 = none). At the deadline progress is saved in the run (capture/) "
            f"and the command exits {EXIT_CAPTURE_INCOMPLETE} (CAPTURE_INCOMPLETE); "
            "re-run the same command to resume. Needs --run-folder or "
            "--authorization <run-dir>."
        ),
    )
    p_run.add_argument("--lookback-days", type=int, default=30)
    p_run.add_argument("--max-parallelism", type=int, default=4)
    p_run.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help=(
            "~/.databrickscfg profile to authenticate with (overrides "
            "DATABRICKS_CONFIG_PROFILE / ambient). Never auto-selected."
        ),
    )
    p_run.add_argument(
        "--host",
        default=None,
        metavar="URL",
        help="Databricks workspace URL to target (overrides config).",
    )
    p_run.add_argument(
        "--warehouse-id",
        dest="warehouse_id",
        default=None,
        metavar="ID",
        help=(
            "SQL warehouse to run discovery scans on (overrides "
            "DATABRICKS_WAREHOUSE_ID; skips warehouse autocreate)."
        ),
    )
    p_run.add_argument(
        "--authorization",
        default=None,
        metavar="RUN_DIR|FILE",
        help=AUTHORIZATION_HELP,
    )
    _add_run_folder_flags(p_run, stdout=True)
    p_run.set_defaults(func=_cmd_run)

    p_plan = subparsers.add_parser(
        "plan",
        help="Audit-only: list recommended domains to run (no query packs execute).",
    )
    p_plan.add_argument("--lookback-days", type=int, default=30)
    p_plan.add_argument("--profile", default=None, metavar="NAME")
    p_plan.add_argument("--host", default=None, metavar="URL")
    p_plan.add_argument(
        "--warehouse-id", dest="warehouse_id", default=None, metavar="ID"
    )
    p_plan.add_argument("--max-parallelism", type=int, default=4)
    p_plan.add_argument(
        "--authorization", default=None, metavar="RUN_DIR|FILE", help=AUTHORIZATION_HELP
    )
    _add_run_folder_flags(p_plan, stdout=False)
    p_plan.set_defaults(func=_cmd_plan, packs=None)

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
