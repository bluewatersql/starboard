"""Discovery Agent tool schemas.

Defines OpenAI function call schemas for the 4-phase discovery workflow
and the legacy monolithic tool.
"""

from typing import Any

DISCOVER_ACTIVE_PRODUCTS: dict[str, Any] = {
    "name": "discover_active_products",
    "description": (
        "Phase 1 — Audit the workspace to discover which Databricks products are "
        "active (JOBS, SQL, SERVING, etc.) by querying system.billing.usage.\n"
        "Returns: List of active products, available domains for analysis, and "
        "the number of query packs that will execute.\n"
        "Use FIRST before running queries. Fast (~5-10s).\n"
        "Cost: ~200 tokens | Prerequisites: None"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lookback_days": {
                "type": "integer",
                "description": "Time window for the audit in days",
                "default": 30,
                "enum": [30, 60, 90],
            },
        },
        "required": [],
    },
}

RUN_DISCOVERY_QUERIES: dict[str, Any] = {
    "name": "run_discovery_queries",
    "description": (
        "Phase 2 — Execute discovery SQL query packs against system tables.\n"
        "Runs queries across all domains relevant to the active products "
        "detected in Phase 1. Optionally filter to specific domains.\n"
        "Returns: Per-domain summary of queries executed, rows returned, "
        "and data availability.\n"
        "Must be called AFTER discover_active_products.\n"
        "Cost: ~500-1000 tokens | Duration: 30-120s depending on workspace size"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of specific domains to query. "
                    "If omitted, queries all domains relevant to active products. "
                    "Options: billing, jobs, compute, query_perf, governance, "
                    "ml, migration, apps, lakebase, vector_search, delta_sharing, "
                    "monitoring, serverless_sql, workflow, aibi"
                ),
            },
        },
        "required": [],
    },
}

ANALYZE_DISCOVERY_DOMAIN: dict[str, Any] = {
    "name": "analyze_discovery_domain",
    "description": (
        "Phase 3 — Analyze domains using heuristics and LLM reasoning.\n"
        "Applies deterministic best-practice rules first, then uses the LLM "
        "for deeper analysis. Produces a letter grade (A-F), numeric score, "
        "findings with priority and impact, and actionable recommendations.\n"
        "IMPORTANT: Use the 'domains' parameter to analyze ALL domains in a "
        "single call. The tool handles parallelism and timeouts internally. "
        "Do NOT call this tool multiple times in parallel.\n"
        "Must be called AFTER run_discovery_queries.\n"
        "Cost: ~800-1500 tokens per domain | Duration: 30-120s for all domains"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of domains to analyze. Pass all domains from "
                    "run_discovery_queries 'domains_with_data'. "
                    "Preferred over single 'domain' — handles parallelism "
                    "and timeouts internally."
                ),
            },
            "domain": {
                "type": "string",
                "description": (
                    "Single domain to analyze. Use 'domains' (array) instead "
                    "for batch analysis of all domains in one call."
                ),
            },
        },
        "required": [],
    },
}

SYNTHESIZE_DISCOVERY_REPORT: dict[str, Any] = {
    "name": "synthesize_discovery_report",
    "description": (
        "Phase 4 — Assemble all domain analyses into the final discovery report.\n"
        "Builds report cards, ranks all findings by priority, generates an "
        "executive summary, and writes output files (report.md, report.json, "
        "executive_summary.md, top_priorities.md).\n"
        "Call AFTER analyzing all desired domains.\n"
        "Returns: Executive summary, report cards (domain grades), top findings, "
        "recommended actions, and output file paths.\n"
        "Cost: ~500-800 tokens | Duration: 10-20s"
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

# Legacy monolithic tool — kept for backward compatibility
RUN_WORKSPACE_DISCOVERY: dict[str, Any] = {
    "name": "run_workspace_discovery",
    "description": (
        "Run a comprehensive workspace health assessment by querying Databricks "
        "system tables, applying best-practice heuristics, and producing a graded "
        "report across billing, jobs, compute, query performance, governance, and "
        "product-specific domains.\n"
        "Returns: DiscoveryReport with executive summary, per-domain grades (A-F), "
        "top 10 prioritized findings, and evidence map.\n"
        "Use for: Workspace health checks, platform audits, best-practice assessments.\n"
        "Cost: ~2000-5000 tokens (depends on active products) | Prerequisites: None\n"
        "Note: This is a long-running operation. Results are written to the output "
        "directory and a summary is returned.\n"
        "PREFER the granular phase tools (discover_active_products, run_discovery_queries, "
        "analyze_discovery_domain, synthesize_discovery_report) for better progress "
        "visibility and adaptive reasoning."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lookback_days": {
                "type": "integer",
                "description": "Time window for analysis in days",
                "default": 30,
                "enum": [30, 60, 90],
            },
            "domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Specific domains to analyze (default: all active). "
                    "Options: billing, jobs, compute, query_perf, governance, "
                    "ml, migration, apps, lakebase, vector_search, delta_sharing, "
                    "monitoring, serverless_sql, workflow, aibi"
                ),
            },
            "data_only": {
                "type": "boolean",
                "description": "Skip LLM analysis and return raw query data only",
                "default": False,
            },
        },
        "required": [],
    },
}
