# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Query analysis tool metadata schemas."""

RESOLVE_QUERY = {
    "name": "resolve_query",
    "description": (
        "Get SQL text from statement ID or validate raw SQL. First step for query optimization.\n"
        "Returns: SQL text, statement details (if from ID).\n"
        "Cost: ~100 tokens | Prerequisites: None\n"
        "⚡ Parallel-safe: NO - MUST be called exactly ONCE\n"
        "→ Next: discover_tables, analyze_query_plan"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Statement ID (UUID) or raw SQL text - auto-detected",
            }
        },
        "required": ["target"],
    },
}

ANALYZE_QUERY_PLAN = {
    "name": "analyze_query_plan",
    "description": (
        "Generate and analyze EXPLAIN plan for SQL query. Automatically runs EXPLAIN EXTENDED to show execution strategy.\n"
        "Detects: full table scans, expensive joins, shuffle operations, partition pruning opportunities.\n"
        "Returns: EXPLAIN plan text with optimization insights.\n"
        "Cost: ~500 tokens | Prerequisites: SQL text from resolve_query\n"
        "⚡ Parallel-safe: Can call with other tools in ONE turn (executes in parallel)\n"
        "→ Next: analyze_explain_plan, complete | Why critical: Shows actual execution strategy, not just SQL intent"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql_text": {
                "type": "string",
                "description": "SQL query text to generate EXPLAIN plan for (from resolve_query or state)",
            },
            "plan_text": {
                "type": "string",
                "description": "Optional: Pre-generated EXPLAIN plan text (skips generation if provided)",
            },
        },
        "required": ["sql_text"],
    },
}

ANALYZE_EXPLAIN_PLAN = {
    "name": "analyze_explain_plan",
    "description": (
        "Extract key metrics from EXPLAIN plan: table scans, join types, partitions, data volumes.\n"
        "Returns: Structured metrics (scans, joins, partitions, volumes).\n"
        "Cost: ~200 tokens | Prerequisites: EXPLAIN text\n"
        "⚡ Parallel-safe: Yes - can call with other tools in ONE turn\n"
        "→ Next: complete (with optimization recommendations)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "explain_text": {
                "type": "string",
                "description": "EXPLAIN plan output",
            }
        },
        "required": ["explain_text"],
    },
}
