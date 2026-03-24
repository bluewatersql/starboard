# Query Map Template Usage Guide -- Deprecated

> Last verified: 2026-03-24

!!! warning "Deprecated"
    The template-based query system documented here has been superseded by the **Analytics Agent's Agentic RAG workflow**. The Analytics agent now uses `build_analytics_context`, `build_sql_query`, `validate_sql_query`, and `execute_sql_query` tools to dynamically generate and execute SQL queries against Databricks system tables.

    The static template catalog (`unified_template_catalog.py`) and renderer (`template_renderer.py`) remain in the codebase for backward compatibility but are no longer the primary query mechanism.

## What Replaced Templates

The Analytics agent (domain: `analytics`) uses an agentic workflow instead of static templates:

1. **`build_analytics_context`** -- Gathers relevant schema metadata and context via RAG
2. **`build_sql_query`** -- Generates SQL from the user query + gathered context
3. **`validate_sql_query`** -- Validates syntax and runs EXPLAIN
4. **`execute_sql_query`** -- Executes the validated SQL and returns results

This approach handles arbitrary cost and usage questions without requiring a pre-built template for each query pattern.

## Where to Learn More

- [Tool Catalog -- Analytics Tools](tools/TOOL_CATALOG.md#analytics-tools) -- Analytics agent tool reference
- [Tool Architecture](TOOL_ARCHITECTURE.md) -- Three-layer tool design
- [API Reference](api/API_REFERENCE.md) -- REST API endpoints

---

**Last Updated**: 2026-03-24
**Status**: Deprecated
