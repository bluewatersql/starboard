---
domain: finops_billing
system_tables:
- system.billing.account_prices
- system.billing.cloud_infra_cost
- system.billing.list_prices
- system.billing.usage
- system.serving.endpoint_usage
---

# Reference: finops_billing

> Curated Databricks system-table knowledge for the `finops_billing` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.billing.account_prices
System table in the `finops_billing` domain. See query packs for vetted SQL over this table.

### system.billing.cloud_infra_cost
System table in the `finops_billing` domain. See query packs for vetted SQL over this table.

### system.billing.list_prices
System table in the `finops_billing` domain. See query packs for vetted SQL over this table.

### system.billing.usage
System table in the `finops_billing` domain. See query packs for vetted SQL over this table.

### system.serving.endpoint_usage
System table in the `finops_billing` domain. See query packs for vetted SQL over this table.

## Nuance

### allocate_serverless_cost_shared_warehouse | recipe
DOC_TYPE: recipe
TOPIC: allocate_serverless_cost_shared_warehouse
WAREHOUSE_TYPE: serverless
ATTRIBUTION_MODEL: proportional_by_query
GOAL: Allocate serverless warehouse cost to teams/users/tags when the underlying compute is shared.
INPUTS (typical):
- system.billing.usage (usage_quantity, usage_unit, sku)
- system.query.history (executed_by, statement_id, start_time, end_time)
- system.compute.warehouse_events or warehouses (warehouse_id, serverless/standard hints)
STEPS:
1) Filter usage to serverless SQL SKU(s) for date range.
2) Compute per-query share metric (e.g., query_duration_ms or query_cost_weight).
3) Allocate usage_quantity proportionally across queries.
4) Map queries to owners/tags and roll up.
OUTPUT: allocated_cost_by_owner_tag
PITFALL: If you allocate only by warehouse_id for serverless, you'll mis-attribute shared spend.

### allocate_serverless_cost_shared_warehouse | template_sql
DOC_TYPE: template_sql
TOPIC: allocate_serverless_cost_shared_warehouse
WAREHOUSE_TYPE: serverless
PARAMS:
- {{start_ts}}, {{end_ts}}
- {{serverless_sql_sku_prefix}} (optional)
TEMPLATE:
WITH usage AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_start_time >= {{start_ts}} AND usage_start_time < {{end_ts}}
    AND sku LIKE {{serverless_sql_sku_prefix}}
), q AS (
  SELECT statement_id, executed_by, start_time, end_time,
         (unix_millis(end_time) - unix_millis(start_time)) AS query_duration_ms
  FROM system.query.history
  WHERE start_time >= {{start_ts}} AND start_time < {{end_ts}}
    AND execution_status = 'FINISHED'
), q_totals AS (
  SELECT SUM(query_duration_ms) AS total_query_ms FROM q
)
SELECT
  q.executed_by,
  u.sku,
  u.usage_unit,
  u.usage_quantity,
  q.query_duration_ms,
  (q.query_duration_ms / NULLIF(q_totals.total_query_ms, 0)) AS share,
  u.usage_quantity * (q.query_duration_ms / NULLIF(q_totals.total_query_ms, 0)) AS allocated_usage_quantity
FROM usage u
CROSS JOIN q_totals
JOIN q ON 1=1;
NOTES:
- This is a proportional allocation template; replace share metric (duration) with a better weight if available.
- Join in tags/owners after allocation (e.g., via executed_by mapping).

### pricing_effective_window_join | rule
DOC_TYPE: rule
TOPIC: pricing_effective_window_join
TIME_VALIDITY: range_join_required
RULE: When joining billing usage to prices, join by SKU and enforce the price effective window. Handle NULL pricing_end_time correctly (means price is still active).
JOIN CONDITION (canonical):
For date-grain usage:
- u.sku_name = p.sku_name
- u.usage_date BETWEEN p.price_start_time AND COALESCE(p.price_end_time, CURRENT_DATE)
For timestamp-grain usage:
- u.sku_name = p.sku_name
- u.usage_start_time >= p.pricing_start_time
- u.usage_start_time < COALESCE(p.pricing_end_time, CURRENT_TIMESTAMP)
OUTPUT: correct_unit_price_per_usage_row
PITFALL: Using (p.pricing_end_time IS NULL OR ...) pattern is verbose; COALESCE is cleaner. Missing this logic causes active prices to be excluded from joins.

### pricing_effective_window_join | template_sql
DOC_TYPE: template_sql
TOPIC: pricing_effective_window_join
GRAIN: day
PARAMS:
- {{start_date}}, {{end_date}}
TEMPLATE:
WITH u AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_date >= {{start_date}} AND usage_date < {{end_date}}
), p AS (
  SELECT *
  FROM system.billing.list_prices
)
SELECT
  u.*, p.pricing_unit, p.list_price,
  (u.usage_quantity * p.list_price) AS estimated_cost
FROM u
JOIN p
  ON u.sku_name = p.sku_name
 AND u.usage_date BETWEEN p.price_start_time AND COALESCE(p.price_end_time, CURRENT_DATE);
NOTES:
- COALESCE handles NULL price_end_time (active prices) correctly.
- Use account_prices when you need negotiated pricing; same pattern applies.
- Always keep date filter on usage_date for partition pruning.

### pricing_effective_window_join | template_sql
DOC_TYPE: template_sql
TOPIC: pricing_effective_window_join
GRAIN: timestamp
PARAMS:
- {{start_ts}}, {{end_ts}}
TEMPLATE:
WITH u AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_start_time >= {{start_ts}} AND usage_start_time < {{end_ts}}
), p AS (
  SELECT *
  FROM system.billing.list_prices
)
SELECT
  u.*, p.pricing_unit, p.list_price,
  (u.usage_quantity * p.list_price) AS estimated_cost
FROM u
JOIN p
  ON u.sku_name = p.sku_name
 AND u.usage_start_time >= p.pricing_start_time
 AND u.usage_start_time < COALESCE(p.pricing_end_time, CURRENT_TIMESTAMP);
NOTES:
- COALESCE ensures active prices (NULL end time) match correctly.
- Keep time bounds aligned to your reporting window for consistent totals.

### sku_normalization_similarity | concept
DOC_TYPE: concept
TOPIC: sku_normalization_similarity
GOAL: Make SKU-based similarity searches reliable by normalizing SKUs into canonical tokens.
NORMALIZATION:
- lower(sku)
- replace non-alphanumerics with '_'
- split into tokens
- map known aliases to canonical families (e.g., serverless_sql, sql_warehouse, jobs_compute)
INDEXING STRATEGY:
- Store sku_family (scalar) + sku_norm (scalar string) on usage/price-related docs and templates.
- Include "SKU_TOKENS:" line in text for lexical + embedding reinforcement.
PITFALL: Embeddings can blur similar SKUs; keep exact normalized token fields for matching/filters.

### sku_name_vs_sku_column | rule
DOC_TYPE: rule
TOPIC: sku_name_vs_sku_column
RULE: In system.billing tables, the SKU identifier column name varies by table. Always use the correct column name for joins.
GUIDELINES:
- system.billing.usage: use sku_name
- system.billing.list_prices: use sku_name
- system.billing.account_prices: use sku_name (verify in your metadata)
- Some older examples may reference just 'sku' - verify actual schema
JOIN PATTERN:
  u.sku_name = p.sku_name
PITFALL: Using 'sku' when column is 'sku_name' causes query failures or wrong results if both columns exist.
OUTPUT: correct_sku_column_name

### usage_unit_quantity_semantics | rule
DOC_TYPE: rule
TOPIC: usage_unit_quantity_semantics
RULE: Always interpret usage_quantity in the context of usage_unit and SKU.
GUIDELINES:
- usage_unit defines the measurement (e.g., DBU-hours, compute-units).
- Do not compare usage_quantity across different usage_unit values without conversion.
- Cost = usage_quantity * unit_price (after correct effective-window pricing join).
PITFALL: Aggregating usage_quantity across mixed usage_unit values produces meaningless totals.
OUTPUT: normalized_usage (optional), estimated_cost

### usage_metadata_null_handling | rule
DOC_TYPE: rule
TOPIC: usage_metadata_null_handling
RULE: The usage_metadata column in system.billing.usage often has NULL values for resource ID fields (usage_metadata.warehouse_id, usage_metadata.cluster_id, usage_metadata.job_id, usage_metadata.dlt_pipeline_id, usage_metadata.notebook_id, usage_metadata.endpoint_id). Always use LEFT JOIN or handle NULLs explicitly.
GUIDELINES:
- Use LEFT JOIN when joining usage to resource tables to preserve unattributed usage.
- Group unattributed costs into 'unknown' or 'unallocated' buckets.
- Calculate % of costs successfully attributed vs unattributed.
- Document attribution coverage in results.
PITFALL: Using INNER JOIN silently drops unattributed costs from totals, making reports incomplete.
OUTPUT: attribution_coverage_pct

### usage_metadata_null_handling | template_sql
DOC_TYPE: template_sql
TOPIC: usage_metadata_null_handling
GOAL: Calculate costs with attribution coverage reporting.
PARAMS:
- {{start_date}}, {{end_date}}
TEMPLATE:
WITH u AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_date >= {{start_date}} AND usage_date < {{end_date}}
), priced AS (
  SELECT
    u.*,
    p.list_price,
    (u.usage_quantity * p.list_price) AS estimated_cost
  FROM u
  JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name
   AND u.usage_date BETWEEN p.price_start_time AND COALESCE(p.price_end_time, CURRENT_DATE)
)
SELECT
  COALESCE(w.warehouse_id, 'unattributed') AS warehouse_id,
  COALESCE(w.name, 'Unknown') AS warehouse_name,
  SUM(priced.estimated_cost) AS estimated_cost,
  SUM(CASE WHEN w.warehouse_id IS NULL THEN priced.estimated_cost ELSE 0 END) AS unattributed_cost,
  100.0 - (SUM(CASE WHEN w.warehouse_id IS NULL THEN priced.estimated_cost ELSE 0 END) / NULLIF(SUM(priced.estimated_cost), 0) * 100) AS attribution_coverage_pct
FROM priced
LEFT JOIN system.compute.warehouses w
  ON priced.usage_metadata.warehouse_id = w.warehouse_id
GROUP BY COALESCE(w.warehouse_id, 'unattributed'), COALESCE(w.name, 'Unknown')
ORDER BY estimated_cost DESC
LIMIT 1000;
NOTES:
- Reports both attributed and unattributed costs.
- Use COALESCE to create explicit 'unknown' buckets.
- Resource IDs are in usage_metadata column (usage_metadata.warehouse_id, usage_metadata.cluster_id, etc.)

### cloud_infra_cost_vs_list_price | concept
DOC_TYPE: concept
TOPIC: cloud_infra_cost_vs_list_price
SUMMARY: Databricks cost analysis may involve multiple layers:
- usage/list_prices/account_prices estimate platform consumption cost
- cloud_infra_cost reflects underlying cloud infrastructure costs
They answer different questions (chargeback vs true infra cost).
GUIDELINE:
- Use list/account prices for chargeback consistency.
- Use cloud_infra_cost for infra optimization and variance analysis.
PITFALL: Summing both together double-counts.

### cost_allocation_tag_precedence | rule
DOC_TYPE: rule
TOPIC: cost_allocation_tag_precedence
RULE: When multiple tag sources exist, apply consistent precedence rules for cost allocation.
PRECEDENCE (highest to lowest):
1. Resource-specific tags (warehouse tags, cluster tags, job tags)
2. Workspace default tags
3. Account default tags
4. 'untagged' fallback bucket
GUIDELINES:
- Extract tags from usage metadata first.
- If NULL, join to resource tables (warehouses, jobs, clusters) for their tags.
- If still NULL, use workspace/account defaults.
- Always preserve 'untagged' bucket to maintain cost totals.
PITFALL: Inconsistent tag precedence causes allocation discrepancies across reports.
OUTPUT: canonical_tag_per_usage_row

### domain_join_routing_finops_usage | recipe
DOC_TYPE: recipe
TOPIC: domain_join_routing_finops_usage
GOAL: Choose the right domain context table(s) when starting from billing usage.
HEURISTICS:
- If the question is about SQL warehouses: join to system.compute.warehouses using usage_metadata.warehouse_id (warehouse_name, warehouse_size, warehouse_type if available) and/or system.compute.warehouse_events.
- If about clusters/jobs compute: join to system.compute.clusters using usage_metadata.cluster_id (cluster_name) and/or lakeflow/jobs tables using usage_metadata.job_id when present in usage_metadata.
- If about users/chargeback: include executed_by (from query history) or owner fields from jobs/pipelines.
OUTPUT: chosen_context_domain = (compute_warehouses|compute_clusters|workload_jobs|workload_pipelines|query)
PITFALL: Using the wrong context table yields missing friendly names and incorrect attribution joins. Resource IDs are in the usage_metadata column.

### domain_join_routing_finops_usage | template_sql
DOC_TYPE: template_sql
TOPIC: domain_join_routing_finops_usage
USE_CASE: SQL warehouse cost/usage with warehouse context + friendly names
PARAMS:
- {{start_date}}, {{end_date}}
TEMPLATE:
WITH usage AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_date >= {{start_date}} AND usage_date < {{end_date}}
), priced AS (
  SELECT
    u.*,
    p.list_price,
    (u.usage_quantity * p.list_price) AS estimated_cost
  FROM usage u
  JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name
   AND u.usage_date BETWEEN p.price_start_time AND COALESCE(p.price_end_time, CURRENT_DATE)
)
SELECT
  w.warehouse_id,
  w.name AS warehouse_name,
  w.warehouse_size,
  w.warehouse_type,
  priced.sku_name,
  priced.usage_unit,
  SUM(priced.usage_quantity) AS usage_quantity,
  SUM(priced.estimated_cost) AS estimated_cost
FROM priced
JOIN system.compute.warehouses w
  ON priced.usage_metadata.warehouse_id = w.warehouse_id
GROUP BY
  w.warehouse_id, w.name, w.warehouse_size, w.warehouse_type,
  priced.sku_name, priced.usage_unit
LIMIT 1000;
NOTES:
- Resource IDs are in the usage_metadata column (usage_metadata.warehouse_id, usage_metadata.cluster_id, etc.)
- Adjust join keys to include workspace_id if present in your metadata.
- If usage_metadata.warehouse_id is not present for serverless, use query-level allocation playbooks instead.

### user_cost_attribution | concept
DOC_TYPE: concept
TOPIC: user_cost_attribution
GOAL: Attribute costs to individual users for chargeback and accountability.
IDENTITY SOURCES (precedence order):
1. identity_metadata.run_as - Most reliable for workload execution identity (structured column in system.billing.usage)
2. usage_metadata.run_as - Fallback for older records (structured column in system.billing.usage)
3. executed_by (from query.history for SQL warehouses) - Query-level attribution
4. created_by / owned_by (from resource tables) - Resource ownership
5. 'system' or 'unknown' - Unattributed/system workloads
KEY INSIGHT: Different compute types store user identity in different locations. identity_metadata and usage_metadata are structured columns in system.billing.usage. Always use COALESCE with proper precedence to maximize attribution coverage.
OUTPUT: user_identity, attribution_source, attribution_confidence
PITFALL: Using only one identity source causes incomplete attribution and under-reports user costs.

### user_cost_attribution | rule
DOC_TYPE: rule
TOPIC: user_cost_attribution
RULE: Extract user identity from multiple sources using COALESCE to maximize attribution coverage.
IDENTITY EXTRACTION PATTERN:
COALESCE(
  identity_metadata.run_as,     -- Primary: workload execution identity (structured column)
  usage_metadata.run_as,         -- Fallback: usage owner (structured column)
  'system'                       -- Default: system/unattributed
) AS user_name
WHERE TO APPLY:
- system.billing.usage: Always use this pattern for user attribution (identity_metadata and usage_metadata are structured columns)
- Join to query.history for SQL warehouse queries (executed_by)
- Join to jobs/pipelines for resource-level owner (created_by/run_as)
OUTPUT: complete_user_attribution
PITFALL: Using only identity_metadata.run_as excludes workloads without identity metadata (pre-2023 data, certain compute types). Resource IDs are in usage_metadata column (usage_metadata.warehouse_id, usage_metadata.cluster_id, usage_metadata.job_id, etc.).

### user_cost_attribution | template_sql
DOC_TYPE: template_sql
TOPIC: user_cost_attribution
USE_CASE: Complete user cost chargeback across ALL compute types
PARAMS:
- {{start_date}}, {{end_date}}
- {{min_cost}} (default: 0.0)
- {{workspace_id}} (optional)
TEMPLATE:
WITH user_costs AS (
  SELECT
    COALESCE(
      identity_metadata.run_as,
      usage_metadata.run_as,
      'system'
    ) AS user_name,
    COALESCE(billing_origin_product, 'OTHER') AS resource_type,
    u.usage_quantity * lp.pricing.default AS cost
  FROM system.billing.usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
    AND u.cloud = lp.cloud
    AND u.usage_date >= lp.price_start_time
    AND u.usage_date < COALESCE(lp.price_end_time, CURRENT_DATE + INTERVAL 1 DAY)
  WHERE u.usage_date >= {{start_date}}
    AND u.usage_date < {{end_date}}
    {{#if workspace_id}}AND u.workspace_id = {{workspace_id}}{{/if}}
),
user_totals AS (
  SELECT
    user_name,
    SUM(cost) AS total_cost,
    SUM(CASE WHEN resource_type IN ('JOBS', 'JOBS_SERVERLESS') THEN cost ELSE 0 END) AS jobs_cost,
    SUM(CASE WHEN resource_type IN ('SQL', 'SERVERLESS_SQL') THEN cost ELSE 0 END) AS warehouse_cost,
    SUM(CASE WHEN resource_type = 'ALL_PURPOSE' THEN cost ELSE 0 END) AS cluster_cost,
    SUM(CASE WHEN resource_type = 'DLT' THEN cost ELSE 0 END) AS pipeline_cost,
    SUM(CASE WHEN resource_type = 'MODEL_SERVING' THEN cost ELSE 0 END) AS serving_cost
  FROM user_costs
  GROUP BY user_name
),
grand_total AS (
  SELECT SUM(total_cost) AS grand_total FROM user_totals
)
SELECT
  user_name,
  ROUND(total_cost, 2) AS total_cost,
  ROUND(jobs_cost, 2) AS jobs_cost,
  ROUND(warehouse_cost, 2) AS warehouse_cost,
  ROUND(cluster_cost, 2) AS cluster_cost,
  ROUND(pipeline_cost, 2) AS pipeline_cost,
  ROUND(serving_cost, 2) AS serving_cost,
  ROUND((total_cost / NULLIF(gt.grand_total, 0)) * 100, 2) AS percent_of_total
FROM user_totals
CROSS JOIN grand_total gt
WHERE total_cost >= {{min_cost}}
ORDER BY total_cost DESC
LIMIT 1000;
NOTES:
- Uses LEFT JOIN for pricing to preserve unpriced usage
- Breaks down by resource type for detailed chargeback
- Reports percent of total for context

### resource_name_enrichment | concept
DOC_TYPE: concept
TOPIC: resource_name_enrichment
GOAL: Enrich billing data with human-readable resource names, owners, and metadata for actionable cost reports.
ENRICHMENT SOURCES:
- Jobs: system.lakeflow.jobs (job_name, created_by, run_as, tags) - join on usage_metadata.job_id
- Warehouses: system.compute.warehouses (warehouse_name, warehouse_size, warehouse_type, created_by) - join on usage_metadata.warehouse_id
- Clusters: system.compute.clusters (cluster_name, cluster_source, owned_by, driver_node_type) - join on usage_metadata.cluster_id
- Pipelines: system.lakeflow.pipelines (pipeline_name, creator_user_name, target) - join on usage_metadata.dlt_pipeline_id
KEY PATTERN: Use LEFT JOIN to preserve unattributed costs, then COALESCE to create 'Unknown' buckets. Resource IDs are in usage_metadata column.
RELATED RULES: See friendly_display_columns for column selection guidance.
OUTPUT: enriched_cost_with_names_and_owners
PITFALL: Using INNER JOIN silently drops costs for deleted/missing resources, making reports incomplete.

### resource_name_enrichment | rule
DOC_TYPE: rule
TOPIC: resource_name_enrichment
RULE: When enriching billing usage with resource names, use LEFT JOIN to latest resource metadata (SCD2 collapsed) to preserve costs for deleted/missing resources.
STEPS:
1. Create CTE with latest resource metadata (ROW_NUMBER...ORDER BY change_time DESC WHERE rn=1)
2. LEFT JOIN usage to latest metadata on usage_metadata.resource_id (e.g., usage_metadata.job_id = j.job_id)
3. Use COALESCE for names: COALESCE(resource.name, usage.usage_metadata.resource_id, 'Unknown')
4. Calculate attribution coverage: % costs with successful enrichment
RELATED PATTERNS: See usage_metadata_null_handling for NULL handling guidance. Resource IDs are in usage_metadata column.
OUTPUT: enriched_usage_with_coverage_metrics
PITFALL: INNER JOIN drops costs for deleted resources (warehouses/jobs removed after usage occurred), COALESCE prevents NULL propagation in GROUP BY.

### resource_name_enrichment | template_sql
DOC_TYPE: template_sql
TOPIC: resource_name_enrichment
USE_CASE: Job costs with job names, owners, and tags
PARAMS:
- {{start_date}}, {{end_date}}
- {{workspace_id}} (optional)
TEMPLATE:
WITH usage AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_date >= {{start_date}}
    AND usage_date < {{end_date}}
    AND billing_origin_product IN ('JOBS', 'JOBS_SERVERLESS')
    {{#if workspace_id}}AND workspace_id = {{workspace_id}}{{/if}}
),
priced AS (
  SELECT
    u.*,
    (u.usage_quantity * lp.pricing.default) AS cost
  FROM usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
    AND u.cloud = lp.cloud
    AND u.usage_date >= lp.price_start_time
    AND u.usage_date < COALESCE(lp.price_end_time, CURRENT_DATE + INTERVAL 1 DAY)
),
jobs_latest AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY workspace_id, job_id
      ORDER BY change_time DESC
    ) AS rn
  FROM system.lakeflow.jobs
)
SELECT
  COALESCE(CAST(p.usage_metadata.job_id AS STRING), 'unknown') AS job_id,
  COALESCE(j.name, 'Unknown Job') AS job_name,
  COALESCE(j.run_as, j.created_by, 'unknown') AS job_owner,
  j.tags,
  p.billing_origin_product,
  SUM(p.usage_quantity) AS total_usage_quantity,
  SUM(p.cost) AS total_cost,
  COUNT(DISTINCT p.usage_date) AS days_active,
  SUM(CASE WHEN j.job_id IS NULL THEN p.cost ELSE 0 END) AS unattributed_cost
FROM priced p
LEFT JOIN jobs_latest j
  ON p.usage_metadata.job_id = j.job_id
  AND p.workspace_id = j.workspace_id
  AND j.rn = 1
GROUP BY
  COALESCE(CAST(p.usage_metadata.job_id AS STRING), 'unknown'),
  COALESCE(j.name, 'Unknown Job'),
  COALESCE(j.run_as, j.created_by, 'unknown'),
  j.tags,
  p.billing_origin_product
ORDER BY total_cost DESC
LIMIT 1000;
NOTES:
- LEFT JOIN preserves costs for deleted jobs
- SCD2 collapse via ROW_NUMBER ensures one row per job
- Reports unattributed costs (no matching job metadata)
- Includes tags for downstream tag-based attribution

### resource_name_enrichment | template_sql
DOC_TYPE: template_sql
TOPIC: resource_name_enrichment
USE_CASE: SQL warehouse costs with names, size, type, and owner
PARAMS:
- {{start_date}}, {{end_date}}
- {{workspace_id}} (optional)
TEMPLATE:
WITH usage AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_date >= {{start_date}}
    AND usage_date < {{end_date}}
    AND billing_origin_product IN ('SQL', 'SERVERLESS_SQL')
    {{#if workspace_id}}AND workspace_id = {{workspace_id}}{{/if}}
),
priced AS (
  SELECT
    u.*,
    (u.usage_quantity * lp.pricing.default) AS cost
  FROM usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
    AND u.cloud = lp.cloud
    AND u.usage_date >= lp.price_start_time
    AND u.usage_date < COALESCE(lp.price_end_time, CURRENT_DATE + INTERVAL 1 DAY)
),
warehouses_latest AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY workspace_id, warehouse_id
      ORDER BY change_time DESC
    ) AS rn
  FROM system.compute.warehouses
)
SELECT
  COALESCE(p.usage_metadata.warehouse_id, 'unknown') AS warehouse_id,
  COALESCE(w.name, 'Unknown Warehouse') AS warehouse_name,
  COALESCE(w.warehouse_size, 'unknown') AS warehouse_size,
  COALESCE(w.warehouse_type, 'unknown') AS warehouse_type,
  COALESCE(w.created_by, 'unknown') AS warehouse_owner,
  w.enable_serverless_compute,
  p.billing_origin_product,
  SUM(p.usage_quantity) AS total_usage_quantity,
  SUM(p.cost) AS total_cost,
  COUNT(DISTINCT p.usage_date) AS days_active,
  SUM(CASE WHEN w.warehouse_id IS NULL THEN p.cost ELSE 0 END) AS unattributed_cost,
  ROUND((SUM(CASE WHEN w.warehouse_id IS NULL THEN p.cost ELSE 0 END) / NULLIF(SUM(p.cost), 0)) * 100, 2) AS unattributed_pct
FROM priced p
LEFT JOIN warehouses_latest w
  ON p.usage_metadata.warehouse_id = w.warehouse_id
  AND p.workspace_id = w.workspace_id
  AND w.rn = 1
GROUP BY
  COALESCE(p.usage_metadata.warehouse_id, 'unknown'),
  COALESCE(w.name, 'Unknown Warehouse'),
  COALESCE(w.warehouse_size, 'unknown'),
  COALESCE(w.warehouse_type, 'unknown'),
  COALESCE(w.created_by, 'unknown'),
  w.enable_serverless_compute,
  p.billing_origin_product
ORDER BY total_cost DESC
LIMIT 1000;
NOTES:
- Includes warehouse configuration (size, type, serverless) for optimization insights
- Reports attribution coverage with unattributed_cost and unattributed_pct
- Distinguishes serverless vs standard for allocation strategy

### resource_name_enrichment | template_sql
DOC_TYPE: template_sql
TOPIC: resource_name_enrichment
USE_CASE: All-purpose cluster costs with names, source, and owner
PARAMS:
- {{start_date}}, {{end_date}}
- {{workspace_id}} (optional)
TEMPLATE:
WITH usage AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_date >= {{start_date}}
    AND usage_date < {{end_date}}
    AND billing_origin_product = 'ALL_PURPOSE'
    {{#if workspace_id}}AND workspace_id = {{workspace_id}}{{/if}}
),
priced AS (
  SELECT
    u.*,
    (u.usage_quantity * lp.pricing.default) AS cost
  FROM usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
    AND u.cloud = lp.cloud
    AND u.usage_date >= lp.price_start_time
    AND u.usage_date < COALESCE(lp.price_end_time, CURRENT_DATE + INTERVAL 1 DAY)
),
clusters_latest AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY workspace_id, cluster_id
      ORDER BY change_time DESC
    ) AS rn
  FROM system.compute.clusters
)
SELECT
  COALESCE(p.usage_metadata.cluster_id, 'unknown') AS cluster_id,
  COALESCE(c.cluster_name, 'Unknown Cluster') AS cluster_name,
  COALESCE(c.cluster_source, 'INTERACTIVE') AS cluster_source,
  COALESCE(c.owned_by, c.creator_user_name, 'unknown') AS cluster_owner,
  c.driver_node_type,
  c.autotermination_minutes,
  SUM(p.usage_quantity) AS total_usage_quantity,
  SUM(p.cost) AS total_cost,
  COUNT(DISTINCT p.usage_date) AS days_active,
  SUM(CASE WHEN c.cluster_id IS NULL THEN p.cost ELSE 0 END) AS unattributed_cost
FROM priced p
LEFT JOIN clusters_latest c
  ON p.usage_metadata.cluster_id = c.cluster_id
  AND p.workspace_id = c.workspace_id
  AND c.rn = 1
GROUP BY
  COALESCE(p.usage_metadata.cluster_id, 'unknown'),
  COALESCE(c.cluster_name, 'Unknown Cluster'),
  COALESCE(c.cluster_source, 'INTERACTIVE'),
  COALESCE(c.owned_by, c.creator_user_name, 'unknown'),
  c.driver_node_type,
  c.autotermination_minutes
ORDER BY total_cost DESC
LIMIT 1000;
NOTES:
- cluster_source helps distinguish job clusters from interactive
- Includes autotermination_minutes for idle resource detection
- Reports unattributed costs for deleted clusters

### multi_resource_top_contributors | concept
DOC_TYPE: concept
TOPIC: multi_resource_top_contributors
GOAL: Identify top N cost contributors across ALL compute types (jobs, warehouses, clusters, pipelines) with unified resource enrichment.
KEY INSIGHT: "Who is spending the most" questions require unified ranking across resource types with names, owners, and resource metadata. Cannot answer with single-resource queries.
PATTERN:
1. Aggregate costs by resource_type + resource_id (from usage_metadata column)
2. Enrich with names from all resource tables (LEFT JOIN to jobs/warehouses/clusters/pipelines using usage_metadata.job_id, usage_metadata.warehouse_id, usage_metadata.cluster_id, usage_metadata.dlt_pipeline_id)
3. Rank by total_cost across all types
4. Return top N with percent of total
OUTPUT: unified_top_n_cost_report
PITFALL: Separate queries per resource type prevent cross-resource ranking and inflate cost totals if summed incorrectly. Resource IDs are in usage_metadata column.

### multi_resource_top_contributors | template_sql
DOC_TYPE: template_sql
TOPIC: multi_resource_top_contributors
USE_CASE: Top N cost contributors across ALL resource types with names and owners
PARAMS:
- {{start_date}}, {{end_date}}
- {{workspace_id}} (optional)
- {{limit}} (default: 50)
- {{min_cost}} (default: 1.0)
TEMPLATE:
WITH usage AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_date >= {{start_date}}
    AND usage_date < {{end_date}}
    {{#if workspace_id}}AND workspace_id = {{workspace_id}}{{/if}}
),
priced AS (
  SELECT
    u.*,
    (u.usage_quantity * lp.pricing.default) AS cost
  FROM usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
    AND u.cloud = lp.cloud
    AND u.usage_date >= lp.price_start_time
    AND u.usage_date < COALESCE(lp.price_end_time, CURRENT_DATE + INTERVAL 1 DAY)
),
resource_costs AS (
  SELECT
    COALESCE(billing_origin_product, 'OTHER') AS resource_type,
    CASE
      WHEN billing_origin_product IN ('JOBS', 'JOBS_SERVERLESS') THEN CAST(usage_metadata.job_id AS STRING)
      WHEN billing_origin_product IN ('SQL', 'SERVERLESS_SQL') THEN usage_metadata.warehouse_id
      WHEN billing_origin_product = 'ALL_PURPOSE' THEN usage_metadata.cluster_id
      WHEN billing_origin_product = 'DLT' THEN usage_metadata.dlt_pipeline_id
      WHEN billing_origin_product = 'MODEL_SERVING' THEN usage_metadata.endpoint_id
      ELSE COALESCE(usage_metadata.cluster_id, usage_metadata.warehouse_id, 'unknown')
    END AS resource_id,
    SUM(usage_quantity) AS total_usage_quantity,
    SUM(cost) AS total_cost
  FROM priced
  GROUP BY 1, 2
  HAVING total_cost >= {{min_cost}}
),
jobs_latest AS (
  SELECT job_id, workspace_id, name AS job_name, COALESCE(run_as, created_by, 'unknown') AS owner,
    ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) AS rn
  FROM system.lakeflow.jobs
),
warehouses_latest AS (
  SELECT warehouse_id, workspace_id, name AS warehouse_name, COALESCE(created_by, 'unknown') AS owner,
    ROW_NUMBER() OVER (PARTITION BY workspace_id, warehouse_id ORDER BY change_time DESC) AS rn
  FROM system.compute.warehouses
),
clusters_latest AS (
  SELECT cluster_id, workspace_id, cluster_name, COALESCE(owned_by, creator_user_name, 'unknown') AS owner,
    ROW_NUMBER() OVER (PARTITION BY workspace_id, cluster_id ORDER BY change_time DESC) AS rn
  FROM system.compute.clusters
),
enriched AS (
  SELECT
    rc.resource_type,
    rc.resource_id,
    COALESCE(
      j.job_name,
      w.warehouse_name,
      c.cluster_name,
      rc.resource_id
    ) AS resource_name,
    COALESCE(j.owner, w.owner, c.owner, 'unknown') AS resource_owner,
    rc.total_usage_quantity,
    rc.total_cost
  FROM resource_costs rc
  LEFT JOIN jobs_latest j
    ON rc.resource_type IN ('JOBS', 'JOBS_SERVERLESS')
    AND rc.resource_id = CAST(j.job_id AS STRING)
    AND j.rn = 1
  LEFT JOIN warehouses_latest w
    ON rc.resource_type IN ('SQL', 'SERVERLESS_SQL')
    AND rc.resource_id = w.warehouse_id
    AND w.rn = 1
  LEFT JOIN clusters_latest c
    ON rc.resource_type = 'ALL_PURPOSE'
    AND rc.resource_id = c.cluster_id
    AND c.rn = 1
  WHERE rc.resource_id IS NOT NULL AND rc.resource_id != 'unknown'
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (ORDER BY total_cost DESC) AS cost_rank,
    SUM(total_cost) OVER () AS grand_total
  FROM enriched
)
SELECT
  cost_rank,
  resource_type,
  resource_id,
  resource_name,
  resource_owner,
  ROUND(total_usage_quantity, 2) AS total_usage_quantity,
  ROUND(total_cost, 2) AS total_cost,
  ROUND((total_cost / NULLIF(grand_total, 0)) * 100, 2) AS percent_of_total
FROM ranked
WHERE cost_rank <= {{limit}}
ORDER BY cost_rank;
NOTES:
- Unified query across all compute types
- Enriches with names and owners from all resource tables
- Reports top N with percent of total for context
- Essential for 'who is spending the most' questions

### tag_based_cost_attribution | template_sql
DOC_TYPE: template_sql
TOPIC: tag_based_cost_attribution
USE_CASE: Cost allocation by tag (team/cost_center/environment) with resource type breakdown
PARAMS:
- {{start_date}}, {{end_date}}
- {{tag_key}} (e.g., 'team', 'cost_center', 'environment')
- {{workspace_id}} (optional)
- {{tag_value_filter}} (optional: filter to specific tag value)
- {{min_cost}} (default: 1.0)
TEMPLATE:
WITH usage AS (
  SELECT *
  FROM system.billing.usage
  WHERE usage_date >= {{start_date}}
    AND usage_date < {{end_date}}
    {{#if workspace_id}}AND workspace_id = {{workspace_id}}{{/if}}
),
tagged_costs AS (
  SELECT
    LOWER(TRIM(COALESCE(custom_tags['{{tag_key}}'], 'untagged'))) AS tag_value,
    COALESCE(billing_origin_product, 'OTHER') AS resource_type,
    CASE
      WHEN billing_origin_product IN ('JOBS', 'JOBS_SERVERLESS') THEN CAST(usage_metadata.job_id AS STRING)
      WHEN billing_origin_product IN ('SQL', 'SERVERLESS_SQL') THEN usage_metadata.warehouse_id
      WHEN billing_origin_product = 'ALL_PURPOSE' THEN usage_metadata.cluster_id
      WHEN billing_origin_product = 'DLT' THEN usage_metadata.dlt_pipeline_id
      ELSE COALESCE(usage_metadata.cluster_id, usage_metadata.warehouse_id, 'unknown')
    END AS resource_id,
    u.usage_quantity,
    u.usage_quantity * lp.pricing.default AS cost
  FROM usage u
  LEFT JOIN system.billing.list_prices lp
    ON u.sku_name = lp.sku_name
    AND u.cloud = lp.cloud
    AND u.usage_date >= lp.price_start_time
    AND u.usage_date < COALESCE(lp.price_end_time, CURRENT_DATE + INTERVAL 1 DAY)
  {{#if tag_value_filter}}
  WHERE LOWER(TRIM(COALESCE(custom_tags['{{tag_key}}'], 'untagged'))) = LOWER('{{tag_value_filter}}')
  {{/if}}
),
aggregated AS (
  SELECT
    tag_value,
    resource_type,
    COUNT(DISTINCT resource_id) AS resource_count,
    SUM(usage_quantity) AS total_usage_quantity,
    SUM(cost) AS total_cost
  FROM tagged_costs
  GROUP BY tag_value, resource_type
),
grand_total AS (
  SELECT
    SUM(total_cost) AS grand_total,
    SUM(CASE WHEN tag_value = 'untagged' THEN total_cost ELSE 0 END) AS untagged_total
  FROM aggregated
)
SELECT
  a.tag_value,
  a.resource_type,
  a.resource_count,
  ROUND(a.total_usage_quantity, 2) AS total_usage_quantity,
  ROUND(a.total_cost, 2) AS total_cost,
  ROUND((a.total_cost / NULLIF(gt.grand_total, 0)) * 100, 2) AS percent_of_total,
  ROUND((gt.untagged_total / NULLIF(gt.grand_total, 0)) * 100, 2) AS untagged_pct
FROM aggregated a
CROSS JOIN grand_total gt
WHERE a.total_cost >= {{min_cost}}
ORDER BY a.total_cost DESC
LIMIT 1000;
NOTES:
- Resource IDs are in usage_metadata column (usage_metadata.job_id, usage_metadata.warehouse_id, usage_metadata.cluster_id, etc.)
- Handles NULL tags with 'untagged' fallback (see cost_allocation_tag_precedence rule)
- Breaks down by resource_type for detailed allocation
- Reports tagging coverage (untagged_pct)
- Normalizes tag values (lowercase, trim) per tags_normalization_attribution recipe

### attribution_coverage_reporting | rule
DOC_TYPE: rule
TOPIC: attribution_coverage_reporting
RULE: Always report attribution coverage (% costs successfully attributed) alongside cost breakdowns.
METRICS TO INCLUDE:
- total_cost: Grand total from billing
- attributed_cost: Costs successfully linked to resources/users/tags
- unattributed_cost: Costs without attribution (NULL joins)
- attribution_coverage_pct: (attributed_cost / total_cost) * 100
WHY:
- Helps users understand data quality and completeness
- Identifies gaps in tagging or resource metadata
- Prevents misinterpretation of incomplete attribution as 'no cost'
PATTERN:
SUM(CASE WHEN resource_id IS NOT NULL THEN cost ELSE 0 END) AS attributed_cost,
SUM(CASE WHEN resource_id IS NULL THEN cost ELSE 0 END) AS unattributed_cost,
ROUND((SUM(CASE WHEN resource_id IS NOT NULL THEN cost ELSE 0 END) / NULLIF(SUM(cost), 0)) * 100, 2) AS attribution_coverage_pct
RELATED PATTERNS: See usage_metadata_null_handling for LEFT JOIN patterns. Resource IDs are in usage_metadata column (usage_metadata.warehouse_id, usage_metadata.cluster_id, usage_metadata.job_id, etc.).
OUTPUT: attribution_quality_metrics
PITFALL: Not reporting coverage makes users think unattributed costs don't exist.

## Codebook

### system.billing.usage.billing_origin_product
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.billing_origin_product
SUMMARY: Databricks product that originated the usage record. Useful to split shared SKUs (serverless jobs SKU can include multiple originating products).
VALUES:
- JOBS
- DLT
- SQL
- ALL_PURPOSE
- MODEL_SERVING
- INTERACTIVE
- DEFAULT_STORAGE
- VECTOR_SEARCH
- LAKEHOUSE_MONITORING
- PREDICTIVE_OPTIMIZATION
- ONLINE_TABLES
- FOUNDATION_MODEL_TRAINING
- AGENT_EVALUATION
- FINE_GRAINED_ACCESS_CONTROL
- BASE_ENVIRONMENTS
- DATA_CLASSIFICATION
- DATA_QUALITY_MONITORING
- AI_GATEWAY
- AI_RUNTIME
- NETWORKING
- APPS
- DATABASE
- AI_FUNCTIONS
- AGENT_BRICKS
- CLEAN_ROOM
- LAKEFLOW_CONNECT
SQL_HINT: When users ask for “serverless spend”, prefer filtering by billing_origin_product + product_features.is_serverless rather than SKU name alone.

### system.billing.usage.usage_type
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.usage_type
SUMMARY: Billing usage type classification; choose aggregation and units accordingly.
VALUES:
- COMPUTE_TIME
- STORAGE_SPACE
- NETWORK_BYTE
- NETWORK_HOUR
- API_OPERATION
- TOKEN
- GPU_TIME
- ANSWER
SQL_HINT: Never SUM(usage_quantity) across mixed usage_type (or mixed usage_unit). Partition by usage_type first.

### system.billing.usage.record_type
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.record_type
SUMMARY: Correction mechanism. Retractions negate originals (negative usage_quantity); restatements contain corrected values.
VALUES:
- ORIGINAL
- RETRACTION
- RESTATEMENT
SQL_HINT: For “true totals”, SUM(usage_quantity) across all record_type; do NOT filter to ORIGINAL unless you explicitly want pre-correction numbers.

### system.billing.usage.usage_metadata.storage_api_type
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.usage_metadata.storage_api_type
SUMMARY: Tier classification for default storage operations.
VALUES:
- TIER_1 (PUT, COPY, POST, LIST)
- TIER_2 (other operations)
SQL_HINT: Use this only when billing_origin_product=DEFAULT_STORAGE (otherwise often NULL).

### system.billing.usage.product_features.jobs_tier
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.jobs_tier
SUMMARY: Jobs tier feature hint.
VALUES:
- LIGHT
- CLASSIC
- null
SQL_HINT: Use jobs_tier to split costs within JOBS where available; otherwise fall back to SKU + compute type.

### system.billing.usage.product_features.sql_tier
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.sql_tier
SUMMARY: SQL tier feature hint.
VALUES:
- CLASSIC
- PRO
- null
SQL_HINT: Combine with usage_metadata.warehouse_id to attribute spend to a warehouse (standard) vs allocate (serverless).

### system.billing.usage.product_features.dlt_tier
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.dlt_tier
SUMMARY: Lakeflow Spark Declarative Pipelines tier.
VALUES:
- CORE
- PRO
- ADVANCED
- null
SQL_HINT: If users ask “DLT spend by tier”, filter billing_origin_product=DLT and group by dlt_tier.

### system.billing.usage.product_features.serving_type
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.serving_type
SUMMARY: Model serving usage subtype.
VALUES:
- MODEL
- GPU_MODEL
- FOUNDATION_MODEL
- FEATURE
- null
SQL_HINT: Use serving_type for cost attribution across endpoint categories when billing_origin_product=MODEL_SERVING.

### system.billing.usage.product_features.offering_type
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.offering_type
SUMMARY: Offering type for certain serving workloads.
VALUES:
- BATCH_INFERENCE
- null

### system.billing.usage.product_features.performance_target
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.performance_target
SUMMARY: Performance mode for serverless job or pipeline.
VALUES:
- PERFORMANCE_OPTIMIZED
- STANDARD
- null
SQL_HINT: Only meaningful for serverless workloads; classic compute typically yields null here.

### system.billing.usage.product_features.networking.connectivity_type
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.networking.connectivity_type
SUMMARY: Serverless networking connectivity type.
VALUES:
- PUBLIC_IP
- PRIVATE_IP
SQL_HINT: Use to split serverless networking spend when billing_origin_product=NETWORKING.

### system.billing.usage.product_features.agent_bricks.problem_type
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.agent_bricks.problem_type
SUMMARY: Agent Bricks problem type.
VALUES:
- AGENT_BRICKS_KNOWLEDGE_ASSISTANT
- null

### system.billing.usage.product_features.agent_bricks.workload_type
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.product_features.agent_bricks.workload_type
SUMMARY: Agent Bricks workload type.
VALUES:
- AGENT_BRICKS_REAL_TIME_INFERENCE
- null

### system.billing.usage.usage_metadata
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.usage_metadata.<keys>
SUMMARY: Keys in usage_metadata (all strings) that help attribute billing usage back to resource model objects.
COMMON_KEYS:
- cluster_id (classic compute)
- job_id, job_run_id, job_name (jobs compute / serverless jobs)
- warehouse_id (SQL workloads)
- notebook_id, notebook_path (serverless notebooks)
- dlt_pipeline_id, dlt_update_id, dlt_maintenance_id (pipelines + related features)
- endpoint_id, endpoint_name (model serving + vector search endpoints)
- metastore_id, uc_table_catalog, uc_table_schema, uc_table_name (UC-linked usage)
- app_id, app_name (Databricks Apps)
SQL_HINT: If billing_origin_product=SQL or product_features.sql_tier is set, warehouse_id is often your primary attribution key; for shared/serverless patterns, allocate by query history.

### system.billing.usage.cloud
DOC_TYPE: codebook
CODE_KEY: system.billing.usage.cloud
SUMMARY: Cloud provider associated with usage/pricing rows.
VALUES:
- AWS
- AZURE
- GCP
SQL_HINT: If you join usage to prices, always join on sku_name AND cloud (and currency_code where relevant).

### system.lakeflow.job_run_timeline.trigger_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.trigger_type
SUMMARY: What triggered a job run. Useful for spend allocation and operational/cost correlation (e.g., continuous jobs tend to be always-on).
VALUES:
- CONTINUOUS
- CRON
- FILE_ARRIVAL
- ONETIME
- ONETIME_RETRY
SQL_HINT: For cost attribution, join/allocate by job_id/job_run_id when available; otherwise use trigger_type to separate always-on (CONTINUOUS) patterns from batch (CRON/ONETIME).

### system.lakeflow.job_run_timeline.run_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.run_type
SUMMARY: Structural category of a job execution. Useful for cost attribution caveats and allocation strategies.
VALUES:
- JOB_RUN
- SUBMIT_RUN
- WORKFLOW_RUN
SQL_HINT: Prefer direct attribution via usage_metadata.job_id/job_run_id where available; treat WORKFLOW_RUN carefully (may not have 1:1 usage attribution in all cases).

## Facets

### system.billing.usage.billing_origin_product
JOBS,DLT,SQL,ALL_PURPOSE,MODEL_SERVING,INTERACTIVE,DEFAULT_STORAGE,VECTOR_SEARCH,LAKEHOUSE_MONITORING,PREDICTIVE_OPTIMIZATION,ONLINE_TABLES,FOUNDATION_MODEL_TRAINING,AGENT_EVALUATION,FINE_GRAINED_ACCESS_CONTROL,BASE_ENVIRONMENTS,DATA_CLASSIFICATION,DATA_QUALITY_MONITORING,AI_GATEWAY,AI_RUNTIME,NETWORKING,APPS,DATABASE,AI_FUNCTIONS,AGENT_BRICKS,CLEAN_ROOM,LAKEFLOW_CONNECT

### system.billing.usage.usage_type
COMPUTE_TIME,STORAGE_SPACE,NETWORK_BYTE,NETWORK_HOUR,API_OPERATION,TOKEN,GPU_TIME,ANSWER

### system.billing.usage.record_type
ORIGINAL,RETRACTION,RESTATEMENT

### system.billing.usage.usage_metadata.storage_api_type
TIER_1,TIER_2

### system.billing.usage.product_features.jobs_tier
LIGHT,CLASSIC,null

### system.billing.usage.product_features.sql_tier
CLASSIC,PRO,null

### system.billing.usage.product_features.dlt_tier
CORE,PRO,ADVANCED,null

### system.billing.usage.product_features.serving_type
MODEL,GPU_MODEL,FOUNDATION_MODEL,FEATURE,null

### system.billing.usage.product_features.offering_type
BATCH_INFERENCE,null

### system.billing.usage.product_features.performance_target
PERFORMANCE_OPTIMIZED,STANDARD,null

### system.billing.usage.product_features.networking.connectivity_type
PUBLIC_IP,PRIVATE_IP

### system.billing.usage.product_features.agent_bricks.problem_type
AGENT_BRICKS_KNOWLEDGE_ASSISTANT,null

### system.billing.usage.product_features.agent_bricks.workload_type
AGENT_BRICKS_REAL_TIME_INFERENCE,null

### system.billing.usage.usage_metadata
cluster_id,job_id,job_run_id,job_name,warehouse_id,notebook_id,notebook_path,dlt_pipeline_id,dlt_update_id,dlt_maintenance_id,endpoint_id,endpoint_name,metastore_id,uc_table_catalog,uc_table_schema,uc_table_name,app_id,app_name

### system.billing.usage.cloud
AWS,AZURE,GCP

### system.lakeflow.job_run_timeline.trigger_type
CONTINUOUS,CRON,FILE_ARRIVAL,ONETIME,ONETIME_RETRY

### system.lakeflow.job_run_timeline.run_type
JOB_RUN,SUBMIT_RUN,WORKFLOW_RUN
