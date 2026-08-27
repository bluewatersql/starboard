# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.discovery`` — deterministic discovery CLI (Phase-2 D4).

Thin ``argparse`` wrapper over the discovery engine's ``data_only`` path. Every
invocation emits the stable JSON envelope (:mod:`starboard_x.contract`) and uses
the Phase-0 exit-code contract (``0 ok · 1 auth · 2 not-found · 3 api-error ·
4 arg-error``).

Verbs:
    run --data-only [--packs D ...] [--lookback-days N] [--max-parallelism N]

``run`` always executes the **deterministic** path: it forces
``EngineConfig(data_only=True)`` and passes ``llm_client=None`` so no LLM
analysis or synthesis happens (the middle tier has no LLM wiring). The
``--data-only`` flag is accepted for interface parity and is implied.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from starboard_x import _cli
from starboard_x.contract import AuthError, to_jsonable

_DOMAIN = "discovery"


def build_engine(args: argparse.Namespace) -> Any:
    """Build a discovery engine for the deterministic (data-only) path.

    Lazily imports the ``starboard`` server package so that importing this CLI
    module stays dep-light and SDK-free. Enforces ``data_only=True`` and
    ``llm_client=None``. Tests patch this function to inject a fake engine.

    Raises:
        AuthError: when the workspace client / config cannot be constructed.
    """
    try:
        from starboard.bootstrap import (
            AsyncDatabricksClient,
            AsyncSQLExecutor,
            DiscoveryEngine,
            EngineConfig,
            get_config,
        )
    except Exception as exc:  # noqa: BLE001 - missing server package / extra
        raise AuthError(
            "the discovery engine is unavailable — install the server package "
            'and extra: pip install "starboard[discovery]". '
            f"(import failed: {exc})"
        ) from exc

    try:
        config = get_config()
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
    return DiscoveryEngine(
        sql_executor=sql_executor,
        llm_client=None,  # no LLM: analysis/synthesis are skipped
        config=engine_config,
    )


def serialize_result(result: Any) -> dict[str, Any]:
    """Serialize an ``EngineResult`` into a compact, JSON-able data-only report."""
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


def _cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    engine = build_engine(args)
    result = asyncio.run(engine.run())
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
        help="Restrict discovery to these domains/packs (default: all active).",
    )
    p_run.add_argument("--lookback-days", type=int, default=30)
    p_run.add_argument("--max-parallelism", type=int, default=4)
    p_run.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
