name: starboard-query
description: Analyze SQL query performance, execution plans, and optimization for Databricks. Use when user mentions SQL queries, slow queries, execution plans, or statement IDs.
  Triggers on: SQL, query, slow query, execution plan, statement_id, optimize query, query plan, DBSQL.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path (Agent Tool)

For comprehensive analysis, call the `query_agent` MCP tool with a natural language message.
The agent runs a full reasoning loop with automatic tool selection and multi-step analysis.

Example:
```
Call MCP tool: query_agent
Arguments: { "message": "Analyze the performance of statement 01ef-abcd-1234 and suggest optimizations" }
```

## Manual Workflow (Individual Tools)

For targeted analysis or when you need specific data points:

1. **Resolve the query** — Call `resolve_query` with `target: "<statement_id or SQL text>"`
   - Returns: SQL text, statement metadata, warehouse ID, execution status
   - Use when: You have a statement ID and need the SQL text, or want to validate raw SQL

2. **Discover referenced tables** — Call `discover_tables` with `source_text: "<SQL text>"`
   - Returns: List of table references extracted from the SQL
   - Use when: You need to understand which tables a query touches before deeper analysis

3. **Analyze the execution plan** — Call `analyze_query_plan` with `sql_text: "<SQL text>"`
   - Returns: EXPLAIN plan with annotated stages, shuffle operations, and scan types
   - Use when: You need to understand how the query engine executes the query

4. **Extract plan metrics** — Call `analyze_explain_plan` with `explain_text: "<EXPLAIN output>"`
   - Returns: Parsed metrics including scan types, join strategies, shuffle sizes, and partition pruning
   - Use when: You have raw EXPLAIN output and need structured metrics extracted

5. **Get runtime metrics** — Call `get_query_runtime_metrics` with `statement_id: "<id>"`
   - Returns: Execution duration, bytes read/written, rows processed, spill metrics, peak memory
   - Use when: You need actual execution performance data (not just the plan)

6. **Check table metadata** — Call `get_table_metadata` with `table_name: "<catalog.schema.table>"`
   - Returns: Table schema, partitioning, statistics, storage format, row count
   - Use when: Stale statistics or partitioning issues may be affecting query performance

## Available MCP Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `resolve_query` | Get SQL text from statement ID or validate raw SQL | `target` |
| `analyze_query_plan` | Generate and analyze EXPLAIN plan | `sql_text` |
| `analyze_explain_plan` | Extract structured metrics from EXPLAIN plan text | `explain_text` |
| `get_query_runtime_metrics` | Get detailed execution metrics for a completed query | `statement_id` |
| `get_table_metadata` | Get table schema, stats, and storage info | `table_name` |
| `discover_tables` | Extract table references from SQL text | `source_text` |
| `query_agent` | Full query analysis with automatic tool selection | `message` |

## Composite Tools

| Tool | Description | Chains |
|------|-------------|--------|
| `get_query_analysis` | End-to-end query analysis | `resolve_query` -> `get_query_runtime_metrics` -> `analyze_query_plan` |

## Example Prompts

- "Why is statement 01ef-abcd-1234-5678 running slowly? It used to finish in 2 minutes but now takes 20."
- "Analyze this SQL and suggest optimizations: SELECT * FROM catalog.schema.orders JOIN catalog.schema.customers ON orders.customer_id = customers.id WHERE order_date > '2025-01-01'"
- "Show me the execution plan for my query and identify any full table scans or missing partition pruning"
- "Get the runtime metrics for statement 01ef-9876-fedc and check if there's data skew or spill to disk"

## Interpreting Results

When analyzing query results, focus on these key indicators:

- **Join order**: Verify the optimizer places the smaller table on the build side of hash joins. Suboptimal join order causes excessive memory use and spill.
- **Partition pruning**: Check that partition filters are pushed down to the scan. If the plan shows a full scan on a partitioned table, the WHERE clause may not align with the partition column.
- **Filter pushdown**: Filters should appear at the scan level, not after a shuffle. Late filtering means unnecessary data movement.
- **Statistics freshness**: Stale or missing table statistics cause the optimizer to make poor join and scan decisions. Check `get_table_metadata` for last ANALYZE timestamp.
- **Spill to disk**: Any spill indicates insufficient memory for the operation. Look at `spill_to_disk_bytes` in runtime metrics — even small spills degrade performance significantly.
- **Data skew**: Uneven partition sizes or skewed join keys cause some tasks to run much longer than others. Look for max task duration significantly exceeding median task duration.
- **Shuffle size**: Large shuffles between stages indicate potential for repartitioning optimization or broadcast join conversion for small tables.
