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


# Per-query row cap for the emitted data. Discovery packs are curated aggregate
# scans (small result sets by design); this is a safety net against pathological
# outputs. When exceeded, the query's ``truncated`` flag is set.
_MAX_ROWS_PER_QUERY = 10_000


def _query_rows(df: Any) -> tuple[list[str], list[dict[str, Any]], bool]:
    """Extract (columns, capped-rows, truncated) from a DataFrame-like result.

    Duck-typed on ``to_dicts()`` / ``columns`` (polars) so this module stays
    dep-light and testable without importing polars. Returns empty values when
    there is no data (e.g. a failed query).
    """
    if df is None:
        return [], [], False
    to_dicts = getattr(df, "to_dicts", None)
    if not callable(to_dicts):
        return [], [], False
    records = to_dicts()
    columns = [str(c) for c in (getattr(df, "columns", None) or [])]
    truncated = len(records) > _MAX_ROWS_PER_QUERY
    rows = to_jsonable(records[:_MAX_ROWS_PER_QUERY])
    return columns, rows, truncated


def _serialize_query(qr: Any) -> dict[str, Any]:
    """Serialize one ``QueryResult`` including its actual data rows."""
    columns, rows, truncated = _query_rows(getattr(qr, "data", None))
    return {
        "query_id": getattr(qr, "query_id", None),
        "domain": getattr(qr, "domain", None),
        "succeeded": bool(getattr(qr, "succeeded", False)),
        "error": getattr(qr, "error", None),
        "row_count": getattr(qr, "row_count", len(rows)),
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
    }


def serialize_result(result: Any) -> dict[str, Any]:
    """Serialize an ``EngineResult`` into a JSON-able data-only report.

    Emits the actual query result rows (not just counts) so a host agent
    (Isaac / Claude / Codex) can reason over the deterministic data directly —
    the data-only path runs no LLM itself.
    """
    audit = None
    audit_result = getattr(result, "audit_result", None)
    if audit_result is not None:
        audit = {"succeeded": getattr(audit_result, "succeeded", None)}

    packs: list[dict[str, Any]] = []
    for pr in getattr(result, "pack_results", []) or []:
        results = getattr(pr, "results", []) or []
        packs.append(
            {
                "pack": (
                    getattr(pr, "pack_name", None)
                    or getattr(pr, "name", None)
                    or getattr(pr, "domain", None)
                ),
                "queries": len(results),
                "succeeded": sum(
                    1 for qr in results if getattr(qr, "succeeded", False)
                ),
                "results": [_serialize_query(qr) for qr in results],
            }
        )

    return {
        "data_only": True,
        "trace_id": getattr(result, "trace_id", ""),
        "elapsed_ms": getattr(result, "elapsed_ms", 0.0),
        "errors": list(getattr(result, "errors", []) or []),
        "audit": audit,
        "pack_count": len(packs),
        "packs": packs,
        # Always empty on the data-only path (proves no LLM analysis ran).
        "domain_analyses": to_jsonable(getattr(result, "domain_analyses", []) or []),
    }


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
    return serialize_result(result)


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
    p_run.add_argument(
        "--packs",
        nargs="+",
        default=None,
        metavar="DOMAIN",
        help=(
            "Restrict discovery to these domain/pack names (default: all "
            "active). Unknown names are rejected (arg-error). The always-run "
            "core packs (audit, billing, governance, migration) run regardless."
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

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
