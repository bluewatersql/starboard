---
domain: query
system_tables:
- system.compute.warehouse_events
- system.query.history
---

# Reference: query

> Curated Databricks system-table knowledge for the `query` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.compute.warehouse_events
System table in the `query` domain. See query packs for vetted SQL over this table.

### system.query.history
System table in the `query` domain. See query packs for vetted SQL over this table.

## Nuance

### shared_warehouse_attribution_by_query | concept
DOC_TYPE: concept
TOPIC: shared_warehouse_attribution_by_query
SUMMARY: Shared warehouses run many users/teams concurrently; warehouse-level costs need allocation. Query-level attribution uses query history (who ran what, when) to distribute spend.
BEST PRACTICE:
- Use query duration, bytes read, or other metrics as a weight.
- Preserve time windows to align with billing intervals.
PITFALL: Counting queries equally can bias attribution toward chatty workloads.

### query_to_billing_usage_linking | recipe
DOC_TYPE: recipe
TOPIC: query_to_billing_usage_linking
GOAL: Attribute billing usage to queries (or query cohorts) for cost/performance analysis.
INPUTS (typical):
- system.query.history (statement_id, warehouse_id, start_time, end_time, executed_by)
- system.billing.usage (sku, usage_start_time, usage_quantity)
- system.compute.warehouses / warehouse_events (warehouse type)
STRATEGY:
1) Filter query history to window.
2) Filter usage to window + relevant SKU family.
3) Join on warehouse_id where valid; for serverless, join via time windows and/or query cohorts.
4) Allocate usage to queries using weights (duration/bytes/rows).
PITFALL: Expecting a perfect 1:1 join key between billing rows and statement_id; allocation is often required.

### query_to_billing_allocation | recipe
DOC_TYPE: recipe
TOPIC: query_to_billing_allocation
GOAL: Attribute billing usage/cost to queries (or query cohorts) when no direct 1:1 key exists.
INPUTS (typical):
- system.query.history (statement_id, warehouse_id, executed_by, start_time, end_time)
- system.billing.usage (usage_start_time/usage_date, sku_name, usage_quantity)
- prices (list_prices/account_prices)
STEPS:
1) Filter queries to window; keep executed_by + warehouse_id.
2) Filter usage to same window + relevant SKU family.
3) Compute weights per query (duration_ms is default).
4) Allocate usage_quantity (or cost) proportionally by weight within a cohort (warehouse_id + time bucket).
OUTPUT: allocated_cost_by_executed_by (and optionally by tags)
PITFALL: Expecting perfect joins between statement_id and billing rows; allocation is often required.

### query_to_billing_allocation | template_sql
DOC_TYPE: template_sql
TOPIC: query_to_billing_allocation
GRAIN: hour
PARAMS:
- {{start_ts}}, {{end_ts}}
TEMPLATE:
WITH q AS (
  SELECT
    warehouse_id,
    executed_by,
    statement_id,
    start_time,
    end_time,
    date_trunc('hour', start_time) AS hr,
    (unix_millis(end_time) - unix_millis(start_time)) AS duration_ms
  FROM system.query.history
  WHERE start_time >= {{start_ts}} AND start_time < {{end_ts}}
    AND execution_status = 'FINISHED'
), q_weights AS (
  SELECT
    warehouse_id,
    hr,
    executed_by,
    statement_id,
    duration_ms,
    SUM(duration_ms) OVER (PARTITION BY warehouse_id, hr) AS total_ms
  FROM q
), u AS (
  SELECT
    usage_metadata.warehouse_id AS warehouse_id,
    date_trunc('hour', usage_start_time) AS hr,
    sku_name,
    usage_unit,
    usage_quantity,
    usage_start_time
  FROM system.billing.usage
  WHERE usage_start_time >= {{start_ts}} AND usage_start_time < {{end_ts}}
), priced AS (
  SELECT
    u.*,
    p.list_price,
    (u.usage_quantity * p.list_price) AS estimated_cost
  FROM u
  JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name
   AND u.usage_start_time >= p.pricing_start_time
   AND u.usage_start_time < COALESCE(p.pricing_end_time, CURRENT_TIMESTAMP)
)
SELECT
  qw.executed_by,
  priced.sku_name,
  priced.usage_unit,
  SUM( priced.usage_quantity * (qw.duration_ms / NULLIF(qw.total_ms, 0)) ) AS allocated_usage_quantity,
  SUM( priced.estimated_cost * (qw.duration_ms / NULLIF(qw.total_ms, 0)) ) AS allocated_cost
FROM priced
JOIN q_weights qw
  ON priced.warehouse_id = qw.warehouse_id
 AND priced.hr = qw.hr
GROUP BY qw.executed_by, priced.sku_name, priced.usage_unit
LIMIT 1000;
NOTES:
- Resource IDs are in usage_metadata column (usage_metadata.warehouse_id, usage_metadata.cluster_id, etc.)
- If usage_metadata.warehouse_id is unreliable for serverless, cohort by time bucket only (less precise).
- Replace duration_ms with better weights if available (bytes/rows/cpu time).

### query_history_execution_status | rule
DOC_TYPE: rule
TOPIC: query_history_execution_status
RULE: Always filter query history by execution_status when calculating costs, performance metrics, or attribution.
GUIDELINES:
- Use execution_status = 'FINISHED' for cost allocation and performance analysis.
- Include 'FAILED' only when analyzing error rates or debugging.
- Exclude 'RUNNING' and 'PENDING' from historical cost analysis.
- Duration calculations are only meaningful for FINISHED/FAILED queries.
PITFALL: Including all statuses inflates query counts and produces invalid duration metrics. RUNNING queries have end_time = NULL which breaks duration calculations.
OUTPUT: valid_query_metrics = true

### query_profile_metrics_spill | concept
DOC_TYPE: concept
TOPIC: query_profile_metrics_spill
SUMMARY: Query profile metrics reveal performance bottlenecks. Spill to disk is a critical indicator of insufficient memory.
KEY METRICS:
- spill_to_disk_bytes: bytes written to disk due to memory pressure
- total_bytes_read: input data size
- execution_time_ms: total execution time
GUIDELINES:
- High spill_to_disk_bytes (>10% of total_bytes_read) indicates undersized warehouse.
- Join with system.query.history to identify problematic queries.
- Recommend warehouse size increases for chronic spillers.
PITFALL: Analyzing only duration without checking spill metrics misses root cause of slow queries.
OUTPUT: performance_bottleneck_diagnosis

### sql_query_generation_policy_split | concept
DOC_TYPE: concept
TOPIC: sql_query_generation_policy_split
SUMMARY: Split SQL generation instructions into (A) static 'always-on' policy and (B) retrieved playbooks. Always-on policy includes: never invent tables/columns, fully-qualified names, type-safe operations, date filters, LIMIT safety, return only SQL. Retrieved playbooks include: join routing, domain context tables, friendly display columns, pricing temporal joins, SCD2 current-row templates, field canonicalization maps, and cross-domain grain/unit alignment templates.
WHY: Retrieval can miss; invariants must not depend on RAG. Conversely, join paths and templates benefit from being maintained centrally and evolving with metadata.
OUTPUT: recommended_policy_layering = (static_invariants, rag_playbooks)

### domain_context_inclusion | rule
DOC_TYPE: rule
TOPIC: domain_context_inclusion
RULE: When answering cost/usage/performance questions, include at least one relevant resource/domain context table (warehouse, cluster, job, pipeline, etc.). Do not return only billing/cost tables without resource identity context.
GUIDELINES:
- Prefer joining usage to the most specific domain table that provides stable IDs + friendly names.
- Preserve scoping keys (workspace_id/account_id) when available.
OUTPUT: query_has_resource_context = true
PITFALL: Billing-only outputs are hard to interpret and often fail chargeback/showback needs.

### friendly_display_columns | rule
DOC_TYPE: rule
TOPIC: friendly_display_columns
RULE: Include user-friendly metadata columns (names/labels) when available (e.g., job_name, pipeline_name, cluster_name, warehouse_name, executed_by).
GUIDELINES:
- Prefer selecting both stable IDs and friendly names.
- If friendly names are in a domain table, join to it rather than omitting.
OUTPUT: includes_friendly_columns = true
PITFALL: ID-only outputs are not actionable for operators and hinder UX.

### date_window_guardrail | rule
DOC_TYPE: rule
TOPIC: date_window_guardrail
RULE: Always include an explicit date/time filter for system tables with time columns (usage_date, usage_start_time, start_time, event_time, change_time, etc.). Prefer the most relevant time column for the table.
DEFAULT:
- If user provides no window, use last 30 days.
- If question is clearly about 'today'/'yesterday', use CURRENT_DATE-based boundaries.
OUTPUT: has_time_filter = true
PITFALL: Unbounded queries are expensive and misleading (mixing historical schema variants and price changes).

### cross_domain_grain_unit_alignment | rule
DOC_TYPE: rule
TOPIC: cross_domain_grain_unit_alignment
RULE: For cross-domain queries (e.g., queries + billing, jobs + billing, warehouses + query history), enforce consistent grain and unit semantics.
GUIDELINES:
- Choose a primary grain: day or hour (prefer the most granular grain available when consistency is hard).
- Do not sum usage_quantity across mixed usage_unit; group by usage_unit or convert explicitly.
- Keep USD cost computed at the same grain as usage rows (or aggregate after pricing join).
OUTPUT: chosen_grain = (hour|day)
PITFALL: Mixing grains (hourly query data with daily usage without alignment) silently distorts attribution.

### scd2_current_row_selection | rule
DOC_TYPE: rule
TOPIC: scd2_current_row_selection
RULE: For SCD2 system tables (history of resource configuration), select the current row version using row_number() ordering by the change/effective time and QUALIFY/WHERE rn=1.
GUIDELINES:
- Partition by stable business keys (workspace_id + entity_id).
- Order by change_time DESC (or equivalent).
- Optionally filter deleted entities by delete_time IS NULL (if the question is about active resources).
OUTPUT: is_current_snapshot = true
PITFALL: Without SCD2 collapse, results duplicate resources and inflate counts/cost attribution joins.

### scd2_current_row_selection | template_sql
DOC_TYPE: template_sql
TOPIC: scd2_current_row_selection
GOAL: Collapse SCD2 tables to the latest row per entity.
PARAMS:
- {{source_table}}
- {{partition_keys_csv}} (e.g., workspace_id, job_id)
- {{order_col}} (e.g., change_time)
- {{active_only_predicate}} (optional; e.g., delete_time IS NULL)
TEMPLATE:
WITH ranked AS (
  SELECT *,
         row_number() OVER (PARTITION BY {{partition_keys_csv}} ORDER BY {{order_col}} DESC) AS rn
  FROM {{source_table}}
)
SELECT *
FROM ranked
WHERE rn = 1
{{#if active_only_predicate}}AND ({{active_only_predicate}}){{/if}};
NOTES:
- Prefer QUALIFY rn = 1 when supported in your SQL dialect.
- Ensure order_col is the true SCD2 change/effective timestamp for that table.

### sql_query_safety_limit | rule
DOC_TYPE: rule
TOPIC: sql_query_safety_limit
RULE: Add LIMIT 1000 to generated SQL for safety unless the user explicitly requests full extraction or aggregation-only output where LIMIT would change meaning.
GUIDELINES:
- Prefer applying LIMIT at the outermost SELECT.
- For aggregated summaries, LIMIT is still acceptable but usually not necessary; keep it if uncertain.
OUTPUT: has_limit = true
PITFALL: Missing LIMIT can accidentally scan huge partitions and return massive result sets.

### field_canonicalization_maps | concept
DOC_TYPE: concept
TOPIC: field_canonicalization_maps
SUMMARY: Maintain canonical field naming via retrieval-time alias maps so SQL generation uses actual metadata column names (e.g., user says 'sku' but column is 'sku_name'). Store alias_map per table/domain and apply during SQL synthesis.
PATTERN:
- alias_key: user-facing or common synonym
- canonical_column: true column name in metadata
- scope: table-qualified or domain-wide
OUTPUT: alias_resolution_strategy = (table_scoped_first, domain_fallback)
PITFALL: Hard-coding a few examples doesn't scale; alias drift causes wrong SQL.

### field_canonicalization_maps | rule
DOC_TYPE: rule
TOPIC: field_canonicalization_maps
RULE: Resolve user-specified field aliases to canonical metadata columns before writing SQL. If alias is ambiguous across selected tables, prefer:
1) exact match in the selected table
2) domain-specific alias map
3) require explicit qualification (table.column) in query generation context
OUTPUT: canonical_columns_only = true
PITFALL: Using the alias as a column name produces invalid SQL or (worse) matches a different column with similar meaning.

### field_canonicalization_maps | recipe
DOC_TYPE: recipe
TOPIC: field_canonicalization_maps
GOAL: Define a scalable alias map record format to drive SQL generation.
RECORD SHAPE (encoded as text for RAG):
ALIAS_MAP:
- alias=sku -> canonical=sku_name scope=system.billing.usage
- alias=deleted_time -> canonical=delete_time scope=domain:workload_jobs
- alias=cluster -> canonical=cluster_id scope=system.compute.clusters
RULES:
- Prefer table-scoped mappings when possible.
- Keep canonical columns in sync with metadata refresh.
OUTPUT: alias_map_usage_instructions
PITFALL: Domain-wide aliases can clash; always attempt table-scope first.

### timestamp_timezone_handling | rule
DOC_TYPE: rule
TOPIC: timestamp_timezone_handling
RULE: System tables use UTC timestamps. When filtering or comparing timestamps, ensure consistency.
GUIDELINES:
- All system table timestamps (usage_start_time, start_time, event_time, etc.) are in UTC.
- When users specify dates without timezone, treat as UTC unless context suggests otherwise.
- Use CURRENT_TIMESTAMP for 'now' comparisons, CURRENT_DATE for date boundaries.
- Document timezone assumptions in query comments.
PITFALL: Mixing local time assumptions with UTC system timestamps causes off-by-hours errors in time window queries.
OUTPUT: timezone_consistent = true

### partition_pruning_best_practices | rule
DOC_TYPE: rule
TOPIC: partition_pruning_best_practices
RULE: System tables are partitioned by date/timestamp columns. Always filter on partition columns for performance.
KEY PARTITION COLUMNS:
- system.billing.usage: usage_date (preferred) or usage_start_time
- system.query.history: start_time
- system.lakeflow.job_run_timeline: start_time
- system.lakeflow.pipeline_events: timestamp
GUIDELINES:
- Include partition column filter in WHERE clause, not just in JOIN conditions.
- Use >= and < (half-open interval) for timestamp ranges.
- Avoid functions on partition columns (e.g., DATE(start_time)) as they break pruning.
PITFALL: Queries without partition filters scan entire table history and are extremely expensive.
OUTPUT: partition_pruning_enabled = true

## Codebook

### system.query.history.execution_status
DOC_TYPE: codebook
CODE_KEY: system.query.history.execution_status
SUMMARY: Terminal status of the statement execution.
VALUES:
- FINISHED
- FAILED
- CANCELED
SQL_HINT: For performance analytics, default to execution_status='FINISHED'. For reliability, compute failure_rate using (FAILED + CANCELED) / total. When investigating CANCELED, also group by executed_by and client_application to find automation cancel patterns.

### system.query.history.compute.type
DOC_TYPE: codebook
CODE_KEY: system.query.history.compute.type
SUMMARY: Compute type used to run the statement.
VALUES:
- WAREHOUSE
- SERVERLESS_COMPUTE
SQL_HINT: If the user asks “serverless queries”, filter compute.type='SERVERLESS_COMPUTE' (not warehouse inventory). If the user asks “serverless warehouses”, filter system.compute.warehouses.warehouse_type='SERVERLESS' (inventory).

### system.query.history.client_application
DOC_TYPE: codebook
CODE_KEY: system.query.history.client_application
SUMMARY: Client application name is non-exhaustive and ecosystem-driven (BI tools, Databricks UI, connectors).
PATTERNS/EXAMPLES (non-exhaustive):
- Databricks SQL
- Tableau
- Power BI
- JDBC
- ODBC
- dbt
SQL_HINT: Group by client_application to spot noisy clients; normalize case and strip versions if present.

### system.query.history.statement_type
DOC_TYPE: codebook
CODE_KEY: system.query.history.statement_type
SUMMARY: Statement types are numerous; treat as facet for grouping and use LIKE for families (e.g., 'CREATE', 'ALTER').
PATTERNS/EXAMPLES (non-exhaustive):
- SELECT
- INSERT
- UPDATE
- DELETE
- MERGE
- CREATE
- ALTER
- DROP
- COPY
SQL_HINT: When measuring read-heavy workload, focus on statement_type IN ('SELECT') or use statement_text parsing for mixed statements.

### system.query.history.execution_status
DOC_TYPE: codebook
CODE_KEY: system.query.history.execution_status
SUMMARY: Terminal state for statement execution.
VALUES:
- FINISHED
- FAILED
- CANCELED
SQL_HINT: For performance analytics, filter execution_status='FINISHED' before computing latency percentiles; keep FAILED for reliability analysis.

## Facets

### system.query.history.execution_status
FINISHED,FAILED,CANCELED

### system.query.history.compute.type
WAREHOUSE,SERVERLESS_COMPUTE

### system.query.history.client_application
Databricks SQL,Tableau,Power BI,JDBC,ODBC,dbt

### system.query.history.statement_type
SELECT,INSERT,UPDATE,DELETE,MERGE,CREATE,ALTER,DROP,COPY

### system.query.history.execution_status
FINISHED,FAILED,CANCELED
