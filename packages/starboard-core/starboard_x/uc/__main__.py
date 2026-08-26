# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.uc`` — pure Unity Catalog analysis CLI (Phase-2 D4).

Thin ``argparse`` wrapper over the kernel's SDK-free UC analyzers. Every
invocation emits the stable JSON envelope (:mod:`starboard_x.contract`) and uses
the Phase-0 exit-code contract (``0 ok · 1 auth · 2 not-found · 3 api-error ·
4 arg-error``).

Verbs:
    analyze --input <json>

The ``analyze`` verb is I/O-free: it inspects a table's schema entirely
in-process, importing only the pure analyzers (no ``databricks-sdk``).
``--input`` is a JSON object of the form::

    {
      "table_name": "catalog.schema.table",   # optional (enables classification)
      "columns": [
        {"name": "id", "data_type": "BIGINT", "position": 0, "nullable": false},
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
from typing import Any

from starboard_x import _cli
from starboard_x.contract import ArgError, to_jsonable

_DOMAIN = "uc"


def _parse_columns(raw_columns: Any) -> list:
    """Build ``ColumnInfo`` objects from the input's ``columns`` list."""
    from starboard_core.domain.models.uc import ColumnInfo

    if not isinstance(raw_columns, list) or not raw_columns:
        raise ArgError("--input must contain a non-empty 'columns' list")

    columns = []
    for idx, col in enumerate(raw_columns):
        if not isinstance(col, dict):
            raise ArgError(f"columns[{idx}] must be an object")
        name = col.get("name")
        data_type = col.get("data_type") or col.get("type")
        if not name or not data_type:
            raise ArgError(
                f"columns[{idx}] requires 'name' and 'data_type' (got {col!r})"
            )
        columns.append(
            ColumnInfo(
                name=str(name),
                data_type=str(data_type),
                position=int(col.get("position", idx)),
                nullable=bool(col.get("nullable", True)),
                comment=col.get("comment"),
                is_partition=bool(col.get("is_partition", False)),
                is_clustering=bool(col.get("is_clustering", False)),
            )
        )
    return columns


def _cmd_analyze(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.domain.analyzers.uc_analyzer import UCAnalyzer

    payload = _cli.read_json_file(args.input, flag="--input")
    if not isinstance(payload, dict):
        raise ArgError("--input must be a JSON object with a 'columns' list")

    columns = _parse_columns(payload.get("columns"))
    table_name = payload.get("table_name") or payload.get("full_name")

    anomalies = UCAnalyzer.detect_schema_anomalies(columns)
    semantic = UCAnalyzer.detect_semantic_patterns(columns)
    schema_health = UCAnalyzer.calculate_schema_health(
        column_count=len(columns),
        anomaly_count=len(anomalies),
        has_partitioning=any(c.is_partition for c in columns),
        has_clustering=any(c.is_clustering for c in columns),
        stats_age_days=payload.get("stats_age_days"),
    )

    result: dict[str, Any] = {
        "table_name": table_name,
        "column_count": len(columns),
        "anomalies": to_jsonable(anomalies),
        "semantic_patterns": semantic,
        "schema_health": schema_health,
    }

    if table_name:
        table_type, tt_conf = UCAnalyzer.classify_table_type_heuristic(
            table_name, columns
        )
        layer, layer_conf = UCAnalyzer.classify_data_layer_heuristic(table_name)
        result["classification"] = {
            "table_type": table_type,
            "table_type_confidence": tt_conf,
            "data_layer": layer,
            "data_layer_confidence": layer_conf,
        }

    return result


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.uc",
        description="Pure Unity Catalog schema analysis (anomalies + health, no I/O).",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_analyze = subparsers.add_parser(
        "analyze", help="Analyze a table's schema from a columns JSON."
    )
    p_analyze.add_argument(
        "--input", required=True, help="Path to a table-schema JSON file."
    )
    p_analyze.set_defaults(func=_cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
