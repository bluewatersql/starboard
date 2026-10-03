# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.discovery`` — deterministic discovery CLI (Phase-2 D4).

Thin ``argparse`` wrapper over the discovery engine's ``data_only`` path. Every
invocation emits the stable JSON envelope (:mod:`starboard_x.contract`) and uses
the Phase-0 exit-code contract (``0 ok · 1 auth · 2 not-found · 3 api-error ·
4 arg-error``).

Verbs:
    run --data-only [--packs D ...] [--lookback-days N] [--max-parallelism N]
        [--profile NAME] [--host URL] [--warehouse-id ID]

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
import os
from typing import Any

from starboard_x import _cli
from starboard_x.contract import ArgError, AuthError, to_jsonable

# Shared, dep-light result serializers — the SAME shape the internal
# ``starboard --discover --json`` path emits, so the two entry points cannot
# drift. Re-exported here so ``disc.<name>`` references keep resolving.
from starboard_x.discovery._serialize import (  # noqa: F401  (re-exported)
    _MAX_ROWS_PER_QUERY,
    _query_rows,
    _safe_pack_name,
    _serialize_query,
    serialize_result,
    write_result_files,
)

_DOMAIN = "discovery"

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

    Raises:
        AuthError: when the workspace client / config cannot be constructed.
    """
    try:
        from starboard.bootstrap import (
            AsyncDatabricksClient,
            AsyncSQLExecutor,
            DiscoveryEngine,
            EngineConfig,
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
        if getattr(args, "profile", None):
            os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile

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

    engine_config = EngineConfig(
        lookback_days=args.lookback_days,
        max_parallelism=args.max_parallelism,
        domains=args.packs,
        exact_packs=getattr(args, "only", None),
        data_only=True,  # deterministic path — never run the LLM phases
    )
    engine = DiscoveryEngine(
        sql_executor=sql_executor,
        llm_client=None,  # no LLM: analysis/synthesis are skipped
        config=engine_config,
        query_registry=registry,
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
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001 - classify init vs run failures
        if not entered:
            raise AuthError(
                f"could not authenticate the Databricks client: {exc}"
            ) from exc
        raise
    finally:
        if entered:
            await client.__aexit__(None, None, None)


def _cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    engine = build_engine(args)
    result = asyncio.run(_run_engine(engine))

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
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        if not entered:
            raise AuthError(f"could not authenticate the Databricks client: {exc}") from exc
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
    engine = build_engine(args)
    plan = asyncio.run(_run_plan(engine))
    return serialize_plan(plan, lookback_days=args.lookback_days)


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
            "effect on query execution."
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
    p_run.set_defaults(func=_cmd_run)

    p_plan = subparsers.add_parser(
        "plan",
        help="Audit-only: list recommended domains to run (no query packs execute).",
    )
    p_plan.add_argument("--lookback-days", type=int, default=30)
    p_plan.add_argument("--profile", default=None, metavar="NAME")
    p_plan.add_argument("--host", default=None, metavar="URL")
    p_plan.add_argument("--warehouse-id", dest="warehouse_id", default=None, metavar="ID")
    p_plan.add_argument("--max-parallelism", type=int, default=4)
    p_plan.set_defaults(func=_cmd_plan, packs=None)

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
