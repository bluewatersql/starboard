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
        "BATCH MODE (preferred): Pass all domains from run_discovery_queries "
        "'domains_with_data' via the 'domains' parameter. The server runs "
        "all domain analyses in parallel internally.\n"
        "Must be called AFTER run_discovery_queries.\n"
        "Cost: ~800-1500 tokens per domain | Duration: 5-7 min for full batch"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Single domain to analyze (e.g. 'billing', 'jobs', 'compute')."
                ),
            },
            "domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Batch mode (preferred) — analyze all domains in one call. "
                    "Pass the 'domains_with_data' list from run_discovery_queries."
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

START_DISCOVERY_ANALYSIS: dict[str, Any] = {
    "name": "start_discovery_analysis",
    "description": (
        "Phase 3 (async) — Start background domain analysis and return "
        "immediately.\n"
        "Launches LLM-powered analysis for all domains in parallel on the "
        "server. Returns in under 1 second with status 'started'.\n"
        "After calling this, poll get_discovery_analysis_progress every "
        "30-60 seconds until status is 'completed', then call "
        "synthesize_discovery_report.\n"
        "Must be called AFTER run_discovery_queries.\n"
        "Cost: ~800-1500 tokens per domain (background) | Duration: <1s"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Domains to analyze. Defaults to all domains with data "
                    "from run_discovery_queries."
                ),
            },
        },
        "required": [],
    },
}

GET_DISCOVERY_ANALYSIS_PROGRESS: dict[str, Any] = {
    "name": "get_discovery_analysis_progress",
    "description": (
        "Check progress of background domain analysis started by "
        "start_discovery_analysis.\n"
        "Returns instantly with current progress: how many domains are "
        "complete, which are remaining, and elapsed time.\n"
        "When status is 'completed', the response includes all domain "
        "results and you should call synthesize_discovery_report.\n"
        "When status is 'running', call again in 30-60 seconds.\n"
        "Cost: 0 tokens | Duration: <1s"
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
