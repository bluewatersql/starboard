# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.warehouse`` — pure warehouse analysis CLI (Phase-2 D4).

Thin ``argparse`` wrapper over the kernel's SDK-free warehouse analyzers. Every
invocation emits the stable JSON envelope (:mod:`starboard_x.contract`) and uses
the Phase-0 exit-code contract (``0 ok · 1 auth · 2 not-found · 3 api-error ·
4 arg-error``).

Verbs:
    analyze --history <json> [--warehouse-id ID] [--warehouse-name NAME]
            [--window-days N]

The ``analyze`` verb is I/O-free: it fingerprints a query-history JSON and scores
warehouse health entirely in-process, importing only the pure analyzers (no
``databricks-sdk``). ``--history`` accepts either a bare list of query-record
dicts or an object of the form ``{"records": [...], "warehouse_id": ...,
"warehouse_name": ..., "analysis_window_days": ...}``.
"""

from __future__ import annotations

import argparse
from typing import Any

from starboard_x import _cli
from starboard_x.contract import ArgError, NotFoundError, to_jsonable

_DOMAIN = "warehouse"


def _load_history(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict]:
    """Return ``(records, envelope_defaults)`` parsed from ``--history``."""
    payload = _cli.read_json_file(args.history, flag="--history")

    defaults: dict[str, Any] = {}
    if isinstance(payload, dict):
        records = payload.get("records")
        if records is None:
            raise ArgError(
                "--history object must contain a 'records' list of query records"
            )
        defaults = {
            "warehouse_id": payload.get("warehouse_id"),
            "warehouse_name": payload.get("warehouse_name"),
            "analysis_window_days": payload.get("analysis_window_days"),
        }
    elif isinstance(payload, list):
        records = payload
    else:
        raise ArgError("--history must be a JSON list or an object with 'records'")

    if not isinstance(records, list):
        raise ArgError("--history 'records' must be a list of query-record objects")
    return records, defaults


def _resolve_warehouse_id(
    records: list[dict[str, Any]],
    args: argparse.Namespace,
    defaults: dict,
) -> str:
    """Pick the warehouse to analyze (CLI flag > history default > sole id)."""
    if args.warehouse_id:
        return str(args.warehouse_id)
    if defaults.get("warehouse_id"):
        return str(defaults["warehouse_id"])

    distinct = {
        str(r.get("warehouse_id"))
        for r in records
        if isinstance(r, dict) and r.get("warehouse_id")
    }
    if len(distinct) == 1:
        return distinct.pop()
    if not distinct:
        raise ArgError(
            "no 'warehouse_id' found in records; pass --warehouse-id explicitly"
        )
    raise ArgError(
        "history spans multiple warehouses "
        f"({', '.join(sorted(distinct))}); pass --warehouse-id to select one"
    )


def _cmd_analyze(args: argparse.Namespace) -> dict[str, Any]:
    # Import the pure analyzers lazily so the envelope/arg-error paths never
    # need them and the import stays visibly SDK-free.
    from starboard_core.domain.analyzers.warehouse_analyzer import (
        FingerprintCalculator,
        HealthScorer,
    )

    records, defaults = _load_history(args)
    warehouse_id = _resolve_warehouse_id(records, args, defaults)

    window_days = args.window_days or defaults.get("analysis_window_days") or 7
    warehouse_name = args.warehouse_name or defaults.get("warehouse_name") or ""

    fingerprint = FingerprintCalculator(
        records,
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
        analysis_window_days=int(window_days),
    ).calculate()

    if fingerprint.total_queries == 0:
        raise NotFoundError(
            f"no query records for warehouse '{warehouse_id}' in the provided history"
        )

    health = HealthScorer(fingerprint, slo_config=None).calculate()

    return {
        "warehouse_id": warehouse_id,
        "fingerprint": to_jsonable(fingerprint),
        "health": to_jsonable(health),
    }


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.warehouse",
        description="Pure SQL-warehouse fingerprinting + health scoring (no I/O).",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_analyze = subparsers.add_parser(
        "analyze",
        help="Fingerprint + health-score a warehouse from a query-history JSON.",
    )
    p_analyze.add_argument(
        "--history", required=True, help="Path to a query-history JSON file."
    )
    p_analyze.add_argument(
        "--warehouse-id", default=None, help="Warehouse to analyze (id)."
    )
    p_analyze.add_argument(
        "--warehouse-name", default=None, help="Human-readable warehouse name."
    )
    p_analyze.add_argument(
        "--window-days", type=int, default=None, help="Analysis window in days."
    )
    p_analyze.set_defaults(func=_cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
