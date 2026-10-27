# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tool schemas for Analytics SQL Generation (Agentic RAG Workflow).

Analytics SQL follows an agentic RAG pattern where the agent controls the workflow:
1. RAG Discovery: Agent calls build_analytics_context (tables+nuances always; codebook/facets/learnings as needed)
2. SQL Generation: Agent calls build_sql_query with accumulated RAG context
3. SQL Validation: Agent calls validate_sql_query (syntax + EXPLAIN validation)
4. SQL Execution: Agent calls execute_sql_query with validated SQL

This implements a multi-step workflow for SQL generation and execution.
"""

BUILD_SQL_QUERY = {
    "name": "build_sql_query",
    "description": (
        "Generate SQL query from user request using cached RAG context.\n"
        "Uses LLM to build SQL based on context retrieved via build_analytics_context.\n"
        "\n"
        "IMPORTANT: Pass the context_handle string exactly as returned by build_analytics_context.\n"
        "Do NOT modify, inspect, or alter the handle. It's an opaque reference to cached context.\n"
        "\n"
        "The SQL generator will:\n"
        "  • Access full RAG context server-side (tables, nuances, codebook, etc.)\n"
        "  • Generate SQL from the user query and context\n"
        "  • Return SQL + confidence score + missing context (if any)\n"
        "  • Provide feedback for reflexion loop (what's missing)\n"
        "\n"
        "WHEN TO USE:\n"
        "• After calling build_analytics_context (which returns context_handle)\n"
        "• Before validation and execution\n"
        "\n"
        "RETURNS:\n"
        "  • sql: Generated SQL query\n"
        "  • confidence: Confidence score (0.0-1.0, aim for >0.7)\n"
        "  • missing_context: List of missing context types (e.g., ['warehouse_names', 'join_keys'])\n"
        "  • reasoning: LLM explanation of SQL generation and confidence\n"
        "\n"
        "REFLEXION LOOP (if confidence < 0.7):\n"
        "Use missing_context feedback to refine RAG search:\n"
        "  → Call build_analytics_context again with additional domains/collections\n"
        "  → Call build_sql_query with new context_handle\n"
        "  → Repeat until confidence >= 0.7 (max 3 attempts)\n"
        "\n"
        "Cost: Low (80 tokens for handle) | Prerequisites: context_handle from build_analytics_context\n"
        "→ Next: Call validate_sql_query to validate generated SQL\n"
        "\n"
        "Example workflow:\n"
        "1. build_analytics_context(...) → {context_handle: 'ctx_abc123', summary: {...}}\n"
        "2. build_sql_query(user_query='...', context_handle='ctx_abc123') → {sql: '...', confidence: 0.9}\n"
        "3. validate_sql_query(sql='SELECT...')\n"
        "4. execute_sql_query(sql='SELECT...')"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_query": {
                "type": "string",
                "description": "User's original natural language query",
            },
            "context_handle": {
                "type": "string",
                "description": (
                    "Context handle from build_analytics_context (format: 'ctx_xxxxxxxxxxxx').\n"
                    "Pass this EXACTLY as returned. Do NOT modify or inspect.\n"
                    "The full RAG context is retrieved server-side using this handle."
                ),
            },
            "previous_errors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Previous validation errors from reflexion loop (optional)",
            },
        },
        "required": ["user_query", "context_handle"],
    },
}

VALIDATE_SQL_QUERY = {
    "name": "validate_sql_query",
    "description": (
        "Validate SQL query using two-gate validation.\n"
        "For generate SQL with a high confidence, set runtime_validation to False."
        "to skip EXPLAIN validation."
        "This is a tradeoff between speed and confidence."
        "If you are not sure about the SQL, set runtime_validation to True."
        "This will perform EXPLAIN validation and return a more accurate result."
        "However, it will be slower."
        "If you are sure about the SQL, set runtime_validation to False."
        "This will skip EXPLAIN validation and return a faster result."
        "\n"
        "VALIDATION GATES:\n"
        "  • Gate 1 (Syntax): SQLglot parsing - checks syntax, read-only, safety\n"
        "  • Gate 2 (Runtime): EXPLAIN plan - verifies columns/tables exist on Databricks\n"
        "\n"
        "WHEN TO USE:\n"
        "• After generating SQL with build_sql_query\n"
        "• Before executing SQL with execute_sql_query\n"
        "• ALWAYS validate before execution (required workflow step)\n"
        "\n"
        "REFLEXION LOOP:\n"
        "If validation fails, the error messages tell you WHY (missing columns, wrong tables, etc.).\n"
        "Use this feedback to:\n"
        "1. Search for additional RAG context if needed (call build_analytics_context with include_codebook/facets/learnings)\n"
        "2. Call build_sql_query again with corrected context\n"
        "3. Retry validation (max 3 attempts recommended)\n"
        "\n"
        "Returns: Validation result with is_valid flag and error details if any\n"
        "Cost: Low (100-200 tokens) | Prerequisites: SQL generated from build_sql_query\n"
        "→ Next: If valid, call execute_sql_query. If invalid, gather more RAG context and rebuild.\n"
        "\n"
        "Example reflexion:\n"
        "1. validate_sql_query(sql='SELECT pricing.cost...') → Error: Column 'pricing.cost' not found\n"
        "2. search_codebook(query='cost fields', table='system.billing.usage') → Find correct field\n"
        "3. build_sql_query(..., codebook=[correct fields]) → Generate corrected SQL\n"
        "4. validate_sql_query(sql='SELECT usage_quantity * list_price...') → Success!"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "SQL query to validate (from build_sql_query)",
            },
            "runtime_validation": {
                "type": "boolean",
                "description": "Whether to perform runtime validation (EXPLAIN)",
                "default": False,
            },
        },
        "required": ["sql"],
    },
}

EXECUTE_SQL_QUERY = {
    "name": "execute_sql_query",
    "description": (
        "Execute validated SQL query on Databricks with full result formatting.\n"
        "\n"
        "PREREQUISITES:\n"
        "• SQL MUST be validated first with validate_sql_query\n"
        "• Only execute queries that passed both validation gates\n"
        "\n"
        "WHEN TO USE:\n"
        "• After validate_sql_query returns is_valid=True\n"
        "• As the final step in the agentic RAG workflow\n"
        "\n"
        "WHAT YOU GET:\n"
        "• formatted_results: LLM-optimized profile with:\n"
        "  - numeric_stats: Aggregations (sum, min, max, mean, percentiles)\n"
        "  - categorical_stats: Top values and distributions\n"
        "  - temporal_stats: Date ranges\n"
        "  - sample_rows: Representative sample (up to 20 rows)\n"
        "  - trend: Time-series trend analysis (if applicable)\n"
        "• visualization: Visualization and chart config recommendations (passed through unchanged)\n"
        "  - data_reference: Reference ID for cached data (passed through unchanged)\n"
        "  - has_visualization: Whether a visualization was generated\n"
        "  - chart_recommendation: Chart type and title (passed through unchanged)\n"
        "  - chart_config: Chart configuration object or null with defined schema\n"
        "• row_count: Number of rows returned\n"
        "• metadata: Execution metadata\n"
        "  - execution_time_ms: Query execution time in milliseconds\n"
        "\n"
        "Cost: Variable (depends on query complexity) | Prerequisites: Validated SQL\n"
        "→ Next: Use formatted_results for your analysis, then call complete\n"
        "\n"
        "Example workflow (complete):\n"
        "1. build_analytics_context (gather RAG context)\n"
        "2. build_sql_query (generate SQL from context)\n"
        "3. validate_sql_query (ensure SQL is safe and correct)\n"
        "4. execute_sql_query (run validated SQL) ← You are here\n"
        "5. Analyze formatted_results (statistics, trends, top contributors)\n"
        "6. complete (provide insights and recommendations to user)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "Validated SQL query to execute (from validate_sql_query)",
            }
        },
        "required": ["sql"],
    },
}
