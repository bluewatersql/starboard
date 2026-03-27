name: starboard-uc
description: Explore Unity Catalog assets, lineage, governance, and storage optimization. Use when user mentions tables, catalogs, schemas, lineage, grants, or Unity Catalog.
  Triggers on: table, catalog, schema, lineage, governance, Unity Catalog, UC, access, grants, drift, storage.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path (Agent Tool)

For comprehensive analysis, call the `uc_agent` MCP tool with a natural language message.
The agent runs a full reasoning loop with automatic tool selection and multi-step analysis.

Example:
```
Call MCP tool: uc_agent
Arguments: { "message": "Analyze lineage and access controls for catalog.schema.customer_orders" }
```

## Manual Workflow (Individual Tools)

For targeted analysis or when you need specific data points:

1. **Browse catalog structure** — Call `list_uc_assets` with no required params
   - Returns: Catalogs, schemas, tables, and volumes in the workspace
   - Use when: You need to discover what assets exist before diving deeper

2. **Get table details** — Call `get_table_metadata` with `table_name: catalog.schema.table`
   - Returns: Column definitions, row count, size, format, and properties
   - Use when: You need schema details or basic statistics for a specific table

3. **Check table history** — Call `get_table_history` with `table_name: catalog.schema.table`
   - Returns: Recent Delta operations (writes, merges, optimizes, vacuums)
   - Use when: You need to understand recent changes or operation patterns

4. **Trace lineage** — Call `get_table_lineage` with `table_name: catalog.schema.table`
   - Returns: Upstream sources and downstream consumers
   - Use when: You need to understand data flow or impact of changes

5. **Audit access** — Call `get_table_grants` with `table_name: catalog.schema.table`
   - Returns: Principals and their granted permissions
   - Use when: Reviewing who can access a table or auditing security posture

6. **Analyze schema health** — Call `analyze_table_schema` with `table_name: catalog.schema.table`
   - Returns: Schema patterns, anomalies, and improvement suggestions
   - Use when: Reviewing table design quality or looking for anti-patterns

7. **Check schema drift** — Call `analyze_schema_drift` with `table_name: catalog.schema.table`
   - Returns: Schema changes over time with frequency and impact analysis
   - Use when: Investigating unexpected column changes or tracking evolution

8. **Optimize storage** — Call `analyze_storage_optimization` with `table_name: catalog.schema.table`
   - Returns: Recommendations for Z-ordering, vacuum, compaction, and file sizing
   - Use when: Tables have performance issues or excessive storage costs

9. **Get full fingerprint** — Call `get_table_fingerprint` with `table_name: catalog.schema.table`
   - Returns: Comprehensive table profile combining metadata, health, and usage signals
   - Use when: You need a complete picture of a table in one call

10. **Analyze costs** — Call `analyze_table_costs` with `table_name: catalog.schema.table`
    - Returns: Storage and compute cost attribution for the table
    - Use when: Understanding cost drivers or building chargeback models

## Available MCP Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `list_uc_assets` | List UC assets: catalogs, schemas, tables, volumes | (none) |
| `get_table_metadata` | Get table metadata: columns, row count, size | `table_name` |
| `get_table_history` | Get Delta table history: recent operations | `table_name` |
| `discover_tables` | Extract table references from SQL/code | `source_text` |
| `get_table_lineage` | Get upstream/downstream dependencies | `table_name` |
| `get_enriched_table_metadata` | Get enriched metadata for multiple tables | (none) |
| `get_table_grants` | Get access grants and permissions | `table_name` |
| `analyze_policy_coverage` | Analyze security policy coverage | (none) |
| `analyze_table_schema` | Analyze schema for patterns/anomalies | `table_name` |
| `analyze_schema_drift` | Analyze schema drift over time | `table_name` |
| `generate_schema_diff` | Generate schema diff between versions | `table_name`, `version_from` |
| `analyze_access_patterns` | Analyze table access patterns | `table_name` |
| `analyze_storage_optimization` | Storage optimization recommendations | `table_name` |
| `analyze_query_impact` | Query performance impact for joins | `table_names` |
| `get_table_fingerprint` | Comprehensive table fingerprint | `table_name` |
| `analyze_table_costs` | Storage and compute cost attribution | `table_name` |
| `uc_agent` | Full UC analysis with automatic tool selection | `message` |

## Composite Tools

| Tool | Description | Chains |
|------|-------------|--------|
| `get_table_profile` | Combined metadata and history for a table | `get_table_metadata` -> `get_table_history` |

## Example Prompts

- "Show me the lineage for catalog.production.customer_orders and check who has access"
- "Analyze schema drift on our fact_sales table over the last 30 days"
- "Which tables in the analytics schema need storage optimization? Check vacuum and Z-order status"
- "Run a full governance audit on the finance catalog -- grants, policy coverage, and access patterns"
- "Compare schema versions 12 and 15 for catalog.staging.events and explain what changed"

## Interpreting Results

**Schema Evolution**: Look for frequent column additions/removals (sign of unstable upstream), type changes (potential data quality risk), and nullable columns that were previously required (relaxed constraints).

**Lineage Completeness**: Tables with no upstream lineage may indicate manual loads or external sources. Tables with no downstream consumers may be unused and candidates for deprecation.

**Access Control Audit**: Watch for overly broad grants (e.g., `ALL PRIVILEGES` to large groups), tables with no explicit grants (relying on inherited permissions), and principals with access who have not queried the table recently.

**Storage Optimization**: Key signals include high number of small files (needs compaction), no recent `OPTIMIZE` operations (needs Z-ordering), no recent `VACUUM` (accumulating deleted files), and tables without partition pruning on common filter columns.

**Cost Attribution**: Compare storage cost vs. compute cost to understand whether a table is storage-heavy (large, infrequently queried) or compute-heavy (frequently scanned, joined). High compute cost on small tables often indicates missing statistics or suboptimal join strategies.
