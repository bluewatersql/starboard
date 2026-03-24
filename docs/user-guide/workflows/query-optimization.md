# Workflow: Query Optimization

This guide walks through an end-to-end workflow for optimizing a slow SQL query
using the Starboard AI agent. You will learn what to ask, how the Query agent
investigates, and how to interpret the recommendations.

---

## When to Use This Workflow

- A SQL query is running slower than expected.
- You want to optimize a query before deploying it to production.
- You need to understand an execution plan and identify bottlenecks.
- You want recommendations for indexing, partitioning, or rewriting.

---

## What the Query Agent Can Do

The Query Expert agent has access to the following tools:

| Tool | Purpose |
|------|---------|
| `resolve_query` | Retrieve SQL text from a Databricks statement ID. |
| `analyze_query_plan` | Run EXPLAIN and analyze the execution plan. |
| `get_query_runtime_metrics` | Fetch actual execution metrics (duration, rows, spill). |
| `get_table_metadata` | Retrieve table schemas, partitions, and statistics. |
| `discover_tables` | Extract table references from SQL. |
| `get_table_history` | Check recent table operations (compaction, OPTIMIZE, etc.). |

---

## Step 1: Start the Conversation

### Option A: You have a statement ID

If you have a Databricks query statement ID (e.g., from the Query History UI), use
it directly:

**Web UI:**
```
Why is query 01ef-abc123-def456 running slowly?
```

**CLI:**
```bash
starboard --goal "Analyze and optimize query with statement ID 01ef-abc123-def456"
```

The agent will resolve the statement ID to retrieve the full SQL text, execution
plan, and runtime metrics automatically.

### Option B: You have raw SQL

Paste or upload the SQL directly:

**Web UI:**
```
Optimize this query:

SELECT
    o.order_id,
    o.order_date,
    c.customer_name,
    p.product_name,
    oi.quantity,
    oi.unit_price
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
WHERE o.order_date > '2024-01-01'
  AND c.region = 'US'
ORDER BY o.order_date DESC
```

**CLI (from file):**
```bash
starboard --input-file queries/slow_report.sql \
          --goal "Optimize this SQL query for better performance"
```

### Option C: You want offline analysis

If you do not want the agent to run queries against Databricks:

**Web UI:** Toggle the **Offline Mode** switch before submitting.

**CLI:**
```bash
starboard --mode offline \
          --input-file queries/slow_report.sql \
          --goal "Review this query for anti-patterns and suggest improvements"
```

In offline mode the agent can still analyze query structure, detect anti-patterns, and
suggest rewrites -- it just cannot run EXPLAIN or fetch live metrics.

---

## Step 2: What the Agent Does

Once you submit your request, the Query Expert follows a systematic investigation:

### Phase 1: Query Resolution

The agent starts by resolving your query:

```
-> Resolve Query
```

- If you provided a statement ID, the tool fetches the SQL text and classification
  (SELECT, DML, DDL).
- If you provided raw SQL, the agent parses it directly.

### Phase 2: Table Discovery

```
-> Discover Tables
-> Get Table Metadata (for each table)
```

The agent identifies all tables referenced in the query and fetches their metadata:
schema definitions, partition columns, table statistics (row counts, data size), and
storage format (Delta, Parquet, etc.).

### Phase 3: Execution Plan Analysis

```
-> Analyze Query Plan
```

The agent runs `EXPLAIN` on your query (in online mode) and analyzes the execution
plan for:

- **Full table scans** on large tables.
- **Cartesian products** or missing join predicates.
- **Data skew** in joins or aggregations.
- **Spill to disk** from insufficient memory.
- **Inefficient sort/shuffle operations**.

### Phase 4: Runtime Metrics (if available)

```
-> Get Query Runtime Metrics
```

If the query has been executed previously, the agent retrieves actual runtime data:
wall-clock duration, rows scanned, bytes read, spill metrics, and stage-level
breakdown.

### Phase 5: Table History Check

```
-> Get Table History
```

The agent checks whether tables have been recently optimized, compacted, or vacuumed.
Stale statistics or un-compacted Delta tables are common causes of poor performance.

---

## Step 3: Understanding the Report

The agent produces an **Advisor Report** with several sections:

### Summary

A brief overview of the query, its current performance characteristics, and the
overall assessment (e.g., "This query performs a full scan on a 500GB table due to
missing partition pruning").

### Findings

Each finding includes:

- **Title** -- A short description of the issue (e.g., "Full Table Scan on `orders`").
- **Impact** -- Severity indicator (Critical, High, Medium, Low).
- **Effort** -- Implementation difficulty (Quick Win, Moderate, Significant).
- **Description** -- Detailed explanation of why this is a problem.
- **Recommendation** -- Specific, actionable fix.

Example finding:

> **Full Table Scan on `orders` (500GB)**
>
> Impact: High | Effort: Quick Win
>
> The query filters on `order_date > '2024-01-01'` but the `orders` table is
> partitioned by `order_year` and `order_month`. The predicate does not align
> with partition columns, causing a full scan of all 500GB.
>
> **Recommendation:** Rewrite the WHERE clause to use partition columns:
> ```sql
> WHERE order_year >= 2024
>   AND order_date > '2024-01-01'
> ```

### Optimized Query

When applicable, the agent provides a fully rewritten version of your query with
all recommended changes applied, ready to test.

### Implementation Plan

A prioritized list of changes ordered by impact and effort:

1. **Quick wins** -- changes you can apply immediately (predicate pushdown,
   partition pruning).
2. **Medium-term** -- changes requiring DDL or data reorganization (adding Z-ORDER,
   changing partition scheme).
3. **Long-term** -- architectural changes (materialized views, pre-aggregation
   tables).

---

## Step 4: Follow Up

After the report, the agent suggests next steps. Common options include:

- **"Run the optimized query and compare performance"** -- The agent will execute
  both versions and show a side-by-side comparison.
- **"Analyze table partitioning strategy"** -- Hand off to the UC Expert for deeper
  table analysis.
- **"Check if other queries hit the same tables"** -- Identify related queries that
  would benefit from the same optimizations.

You can also ask your own follow-up questions:

```
What if I add a Z-ORDER on (customer_id, order_date)?
```

```
Show me the execution plan for the optimized version.
```

```
Are there any other queries that scan the orders table inefficiently?
```

---

## Example Conversation

Below is a representative conversation showing the full workflow:

---

**You:**
> Why is query 01ef-abc123 running slowly? It used to take 30 seconds but now takes
> 5 minutes.

**Query Expert** (thinking for 12s):
> *-> Resolve Query*
> *-> Discover Tables*
> *-> Get Table Metadata (orders, customers, order_items, products)*
> *-> Analyze Query Plan*
> *-> Get Query Runtime Metrics*
> *-> Get Table History*

**Query Expert:**
> ## Query Performance Analysis
>
> ### Summary
> The query joins 4 tables (orders, customers, order_items, products) and filters
> on `order_date` and `region`. Performance degraded from 30s to 5m due to two
> compounding factors.
>
> ### Findings
>
> **1. Missing Partition Pruning on `orders` (Impact: Critical)**
> The `orders` table is partitioned by `order_year` but the predicate
> `order_date > '2024-01-01'` does not reference the partition column,
> causing a full scan of 1.2TB across all partitions.
>
> **2. Stale Table Statistics (Impact: High)**
> The `orders` table has not been ANALYZED since 2025-11-15. The table has
> grown from 200M to 800M rows since then. The optimizer is using outdated
> cardinality estimates, leading to a suboptimal join strategy (broadcast
> instead of sort-merge).
>
> **3. Unnecessary SELECT columns (Impact: Medium)**
> The query selects 6 columns but downstream processing only uses 3. Removing
> unused columns reduces shuffle data by ~40%.
>
> ### Optimized Query
> ```sql
> SELECT o.order_id, o.order_date, c.customer_name
> FROM orders o
> JOIN customers c ON o.customer_id = c.customer_id
> WHERE o.order_year >= 2024
>   AND o.order_date > '2024-01-01'
>   AND c.region = 'US'
> ORDER BY o.order_date DESC
> ```
>
> ### Recommended Actions
> 1. (Quick Win) Add `order_year >= 2024` predicate for partition pruning.
> 2. (Quick Win) Run `ANALYZE TABLE orders COMPUTE STATISTICS`.
> 3. (Moderate) Remove unused columns from SELECT.

**What would you like to do next?**

1. Run the optimized query and compare performance -- **Continue**
2. Analyze the `orders` table partitioning in depth -- **Expert** (UC)
3. Check for other slow queries hitting these tables -- **Continue**

---

## Tips

!!! tip "Include context about the performance change"
    If a query recently got slower, mention it: "This query used to take 30 seconds
    but now takes 5 minutes." The agent will specifically investigate what changed
    (data growth, stale stats, schema drift).

!!! tip "Provide the statement ID when possible"
    Statement IDs give the agent access to actual runtime metrics, which produce
    more precise recommendations than static SQL analysis alone.

!!! tip "Use offline mode for pre-deployment review"
    Before deploying new queries to production, run them through offline analysis to
    catch anti-patterns early:
    ```bash
    starboard --mode offline --input-file new_query.sql \
              --goal "Review this query before we deploy it to production"
    ```
