"""Tool schemas for RAG-based discovery (Analytics Agent).

NOTE: Legacy schemas removed (Dec 25, 2025):
- DISCOVER_SYSTEM_TABLES (replaced by SEARCH_SYSTEM_TABLES)
- GET_TABLE_SUMMARY (deprecated, no replacement)

All RAG tools now use multi-collection store with domain filtering.
"""

BUILD_ANALYTICS_CONTEXT = {
    "name": "build_analytics_context",
    "description": (
        "Build analytics RAG context for SQL generation.\n"
        "Always retrieves Tables + Nuance collections.\n"
        "Optionally retrieves Codebook, Facets, and Learnings.\n"
        "Filters by rag_resource_domain (Databricks resource-model domains).\n"
        "\n"
        "RETURNS:\n"
        "  • context_handle: Opaque string handle (format: 'ctx_xxxxxxxxxxxx')\n"
        "    - Pass this handle to build_sql_query WITHOUT modification\n"
        "    - Handle is valid for 1 hour (automatically cached server-side)\n"
        "  • summary: Metadata about what was found\n"
        "    - tables_found: Count of relevant tables\n"
        "    - nuances_found: Count of best practices/patterns\n"
        "    - codebook_found: Count of field definitions\n"
        "    - facets_found: Count of value enumerations\n"
        "    - learnings_found: Count of past successful patterns\n"
        "    - domains_searched: List of domains searched\n"
        "\n"
        "IMPORTANT:\n"
        "• The full RAG context is cached server-side (NOT returned to save tokens)\n"
        "• Use the context_handle in build_sql_query to access the full context\n"
        "• If build_sql_query returns low confidence, call this tool again with:\n"
        "  - Additional rag_resource_domains\n"
        "  - Additional collections (include_codebook, include_facets, etc.)\n"
        "\n"
        "Cost: Low (150 tokens for handle + summary) | Previously: 12K tokens for full context\n"
        "→ Next: Pass context_handle to build_sql_query"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_query": {
                "type": "string",
                "description": "User's natural language query",
            },
            "rag_resource_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional resource-model domains (e.g., ['finops_billing', 'compute_warehouses'])"
                ),
            },
            "include_tables": {
                "type": "boolean",
                "default": True,
                "description": "Include tables entries",
            },
            "include_nuance": {
                "type": "boolean",
                "default": True,
                "description": "Include nuance entries",
            },
            "include_codebook": {
                "type": "boolean",
                "default": False,
                "description": "Include codebook entries",
            },
            "include_facets": {
                "type": "boolean",
                "default": False,
                "description": "Include facet entries",
            },
            "include_learnings": {
                "type": "boolean",
                "default": False,
                "description": "Include reflexion learnings (filtered by agent_domain)",
            },
            "agent_domain": {
                "type": "string",
                "default": "analytics",
                "description": "Agent domain for learnings filtering",
            },
            "n_tables": {"type": "integer", "default": 10},
            "n_nuances": {"type": "integer", "default": 5},
            "n_codebook": {"type": "integer", "default": 5},
            "n_facets": {"type": "integer", "default": 10},
            "n_learnings": {"type": "integer", "default": 5},
        },
        "required": ["user_query"],
        "additionalProperties": False,
    },
}
