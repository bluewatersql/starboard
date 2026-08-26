"""Discovery domain helper — self-describing catalog of domains and commands.

Maps the ``starboard-discovery`` skill. This is *data-only*: it summarizes the
verbs the CLI exposes and never invokes the heavy discovery engine or the SDK.
"""
from __future__ import annotations

from typing import Any

# Canonical catalog of domains -> commands with short descriptions. Kept in sync
# with the registered subparsers by ``tests/test_cli_contract.py``.
DOMAIN_CATALOG: list[dict[str, Any]] = [
    {
        "name": "job",
        "description": "Databricks Jobs: definitions and run history.",
        "commands": ["fetch", "runs", "list"],
    },
    {
        "name": "query",
        "description": "SQL query history and slow-query analysis.",
        "commands": ["fetch", "history", "slow"],
    },
    {
        "name": "warehouse",
        "description": "SQL warehouses: config, listing, and metrics.",
        "commands": ["fetch", "list", "metrics"],
    },
    {
        "name": "uc",
        "description": "Unity Catalog metadata: catalogs, schemas, tables, lineage.",
        "commands": ["catalogs", "schemas", "tables", "table", "lineage"],
    },
    {
        "name": "cluster",
        "description": "Clusters: config, listing, events, and Spark context.",
        "commands": ["fetch", "list", "events", "spark-context"],
    },
    {
        "name": "finops",
        "description": "Cost and usage: billable usage, budgets, log delivery.",
        "commands": ["usage", "budgets", "log-delivery"],
    },
    {
        "name": "diagnostic",
        "description": "Observability: workspace config, node types, run state.",
        "commands": [
            "workspace",
            "node-types",
            "spark-versions",
            "run-state",
            "cluster-log",
        ],
    },
    {
        "name": "analyze",
        "description": "Combined multi-domain workload snapshot.",
        "commands": ["snapshot"],
    },
    {
        "name": "discovery",
        "description": "Self-describing catalog of domains and commands.",
        "commands": ["list"],
    },
]


def register(subparsers) -> None:
    p = subparsers.add_parser("discovery", help="Discover available domains/commands")
    sp = p.add_subparsers(dest="command", required=True)

    list_cmd = sp.add_parser("list", help="List available domains and their commands")
    list_cmd.set_defaults(func=cmd_list)


def cmd_list(args) -> dict[str, Any]:  # noqa: ARG001 - args unused (data-only)
    return {
        "domains": DOMAIN_CATALOG,
        "count": len(DOMAIN_CATALOG),
    }
