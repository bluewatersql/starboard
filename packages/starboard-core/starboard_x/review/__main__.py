# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.review`` — pure Workload Review CLI (Phase-3 D1b).

Thin ``argparse`` wrapper over the kernel's deterministic Workload Review engine.
Every invocation emits the stable JSON envelope (:mod:`starboard_x.contract`) and
uses the Phase-0 exit-code contract (``0 ok · 1 auth · 2 not-found · 3 api-error
· 4 arg-error``).

Verbs:
    score --rows <json> [--domains jobs,sql,warehouse] [--workspace NAME]

The ``score`` verb is I/O-free: it loads query-pack rows from ``--rows`` and
scores them against the seed :class:`~starboard_core.domain.rules.registry.RuleRegistry`
entirely in-process, importing only the pure kernel engine (no ``databricks-sdk``).

``--rows`` accepts either:
    * a bare object mapping ``query_id`` → list of row objects, e.g.
      ``{"W-W02": [{"warehouse_id": "wh1", "auto_stop_waste_pct": 80.0}]}``, or
    * an object of the form ``{"rows_by_query_id": {...}, "failed_query_ids":
      [...], "workspace": "..."}`` for full control over degradation signals.
"""

from __future__ import annotations

import argparse
from typing import Any

from starboard_x import _cli
from starboard_x.contract import ArgError

_DOMAIN = "review"


def _parse_domains(raw: str | None) -> list[str]:
    """Split a comma-separated ``--domains`` value into a clean list."""
    from starboard_core.domain.rules.evaluator import DEFAULT_DOMAINS

    if not raw:
        return list(DEFAULT_DOMAINS)
    domains = [d.strip() for d in raw.split(",") if d.strip()]
    if not domains:
        raise ArgError("--domains was empty after parsing; omit it or pass names")
    return domains


def _load_rows(
    args: argparse.Namespace,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], str | None]:
    """Return ``(rows_by_query_id, failed_query_ids, workspace)`` from ``--rows``."""
    payload = _cli.read_json_file(args.rows, flag="--rows")

    if not isinstance(payload, dict):
        raise ArgError("--rows must be a JSON object keyed by query_id")

    if "rows_by_query_id" in payload:
        rows = payload.get("rows_by_query_id")
        failed = payload.get("failed_query_ids", [])
        workspace = payload.get("workspace")
    else:
        rows, failed, workspace = payload, [], None

    if not isinstance(rows, dict):
        raise ArgError("'rows_by_query_id' must be an object keyed by query_id")
    if not isinstance(failed, list):
        raise ArgError("'failed_query_ids' must be a list of query_id strings")

    normalized: dict[str, list[dict[str, Any]]] = {}
    for query_id, query_rows in rows.items():
        if not isinstance(query_rows, list):
            raise ArgError(f"rows for query_id '{query_id}' must be a list")
        normalized[str(query_id)] = [r for r in query_rows if isinstance(r, dict)]

    ws = str(workspace) if workspace is not None else args.workspace
    return normalized, [str(q) for q in failed], ws


def _cmd_score(args: argparse.Namespace) -> dict[str, Any]:
    # Import the pure engine lazily so the envelope/arg-error paths never need
    # it and the import stays visibly SDK-free.
    from starboard_core.domain.rules.evaluator import build_review
    from starboard_core.domain.rules.registry import RuleRegistry

    domains = _parse_domains(args.domains)
    rows_by_query_id, failed_query_ids, workspace = _load_rows(args)

    registry = RuleRegistry.from_seed()
    review = build_review(
        registry=registry,
        domains=domains,
        rows_by_query_id=rows_by_query_id,
        failed_query_ids=failed_query_ids,
        workspace=workspace,
    )
    return review.model_dump(mode="json")


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.review",
        description="Pure Workload Review scoring over query-pack rows (no I/O).",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_score = subparsers.add_parser(
        "score",
        help="Score query-pack rows against the seed rules → ranked findings.",
    )
    p_score.add_argument(
        "--rows",
        required=True,
        help="Path to a JSON file of query-pack rows keyed by query_id.",
    )
    p_score.add_argument(
        "--domains",
        default=None,
        help="Comma-separated review domains (default: jobs,sql,warehouse).",
    )
    p_score.add_argument(
        "--workspace",
        default=None,
        help="Workspace identifier to record in the review envelope.",
    )
    p_score.set_defaults(func=_cmd_score)

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
