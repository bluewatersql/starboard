---
domain: compute_warehouses
system_tables:
- system.compute.warehouse_events
- system.compute.warehouses
- system.query.history
---

# Reference: compute_warehouses

> Curated Databricks system-table knowledge for the `compute_warehouses` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.compute.warehouse_events
System table in the `compute_warehouses` domain. See query packs for vetted SQL over this table.

### system.compute.warehouses
System table in the `compute_warehouses` domain. See query packs for vetted SQL over this table.

### system.query.history
System table in the `compute_warehouses` domain. See query packs for vetted SQL over this table.

## Nuance

### serverless_vs_standard_sql_warehouses | concept
DOC_TYPE: concept
TOPIC: serverless_vs_standard_sql_warehouses
WAREHOUSE_TYPE: both
SUMMARY: Distinguish serverless vs standard SQL warehouses when interpreting telemetry and billing. Serverless is platform-managed (elastic compute) and can change how usage/cost attribution works compared to a dedicated warehouse. Standard warehouses have clearer warehouse identity and capacity configuration. Always confirm warehouse_type before choosing attribution logic.
KEY DIFFERENCES:
- Identity: standard has stable warehouse_id and config; serverless may have shared/pooled infrastructure.
- Cost attribution: serverless often requires allocation across workloads/users/queries.
- Telemetry joins: serverless may require using query-level or event-level joins rather than warehouse-level rollups.
CHECKS:
- Determine if warehouse is serverless vs standard before aggregating costs.
- Prefer query-level joins for serverless attribution.

### serverless_vs_standard_sql_warehouses | rule
DOC_TYPE: rule
TOPIC: serverless_vs_standard_sql_warehouses
RULE: Choose attribution and joins based on warehouse_type.
IF serverless:
- Use query-level or request-level attribution (e.g., query history + billing usage).
- Avoid assuming 1:1 mapping of warehouse_id to spend.
IF standard:
- Warehouse-level aggregation is usually valid.
- Allocate costs using warehouse_id and time windows.
OUTPUT: recommended_join_strategy = (query_level | warehouse_level)
PITFALL: Mixing serverless and standard into one rollup without tagging warehouse_type produces misleading per-warehouse cost and utilization metrics.

### warehouse_id_stability_issues | concept
DOC_TYPE: concept
TOPIC: warehouse_id_stability_issues
SUMMARY: The usage_metadata.warehouse_id field in system.billing.usage can be NULL or missing for certain configurations (especially serverless). This breaks simple warehouse-level attribution.
HANDLING:
- Check for NULL usage_metadata.warehouse_id before assuming warehouse-level joins will work.
- For serverless, fall back to query-level allocation using system.query.history.
- Document when attribution is approximate due to missing warehouse_id.
PITFALL: Assuming usage_metadata.warehouse_id is always present causes inner joins to silently drop unattributed costs.
OUTPUT: attribution_reliability = (high|medium|low)

## Codebook

### system.compute.warehouses.warehouse_type
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouses.warehouse_type
SUMMARY: SQL warehouse type. Drives attribution logic (dedicated vs shared/serverless) and which joins are reliable.
VALUES:
- CLASSIC
- PRO
- SERVERLESS
SQL_HINT: If users ask for "serverless warehouse" analysis, filter warehouse_type='SERVERLESS' (from system.compute.warehouses) and avoid assuming 1:1 warehouse_id -> cost without validating billing origin + serverless flags.

### system.compute.warehouses.warehouse_channel
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouses.warehouse_channel
SUMMARY: Release channel for SQL warehouse.
VALUES:
- CURRENT
- PREVIEW
SQL_HINT: When diagnosing regressions, segment by warehouse_channel (PREVIEW may include new engine/runtime behavior).

### system.compute.warehouses.warehouse_size
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouses.warehouse_size
SUMMARY: SQL warehouse size tier.
VALUES:
- 2X_SMALL
- X_SMALL
- SMALL
- MEDIUM
- LARGE
- X_LARGE
- 2X_LARGE
- 3X_LARGE
- 4X_LARGE
- 5X_LARGE
SQL_HINT: If the user asks for "X-LARGE" or "largest" warehouses, filter warehouse_size IN ('X_LARGE','2X_LARGE','3X_LARGE','4X_LARGE','5X_LARGE'). Pair with utilization metrics (events/query history) to justify resizing.

### system.compute.warehouse_events.event_type
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouse_events.event_type
SUMMARY: Warehouse lifecycle/scale event type.
VALUES:
- SCALED_UP
- SCALED_DOWN
- STOPPING
- RUNNING
- STARTING
- STOPPED
SQL_HINT: To measure scaling volatility, count SCALED_UP/SCALED_DOWN per day. For availability windows, use STARTING->RUNNING and STOPPING->STOPPED transitions.

### system.compute.warehouses.warehouse_type
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouses.warehouse_type
SUMMARY: SQL warehouse type classification.
VALUES:
- CLASSIC
- PRO
- SERVERLESS
SQL_HINT: When users ask for “serverless warehouses”, filter system.compute.warehouses.warehouse_type='SERVERLESS' (resource dimension) and only then join/query workload/cost tables at matching grain.

### system.compute.warehouses.warehouse_size
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouses.warehouse_size
SUMMARY: SQL warehouse size enumeration (cluster size).
VALUES:
- 2X_SMALL
- X_SMALL
- SMALL
- MEDIUM
- LARGE
- X_LARGE
- 2X_LARGE
- 3X_LARGE
- 4X_LARGE
- 5X_LARGE
SQL_HINT: When users ask for “X-LARGE warehouses”, filter warehouse_size='X_LARGE'. Treat this as a dimension filter (warehouse inventory) and then join to query/workload/cost by warehouse_id + time.

### system.compute.warehouses.warehouse_channel
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouses.warehouse_channel
SUMMARY: SQL warehouse release channel.
VALUES:
- CURRENT
- PREVIEW
SQL_HINT: Use warehouse_channel to separate preview-feature risk/perf investigations vs steady-state production.

### system.compute.warehouse_events.event_type
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouse_events.event_type
SUMMARY: Warehouse lifecycle / scaling events.
VALUES:
- SCALED_UP
- SCALED_DOWN
- STOPPING
- RUNNING
- STARTING
- STOPPED
SQL_HINT: Use event_type + event_time to explain capacity changes (queueing, bursts, auto-stop behavior) around a performance/cost incident window.

### system.compute.warehouse_events.event_type
DOC_TYPE: codebook
CODE_KEY: system.compute.warehouse_events.event_type
SUMMARY: Warehouse lifecycle + autoscaling events.
VALUES:
- SCALED_UP
- SCALED_DOWN
- STOPPING
- RUNNING
- STARTING
- STOPPED
SQL_HINT: For reliability analysis, compute durations between STARTING->RUNNING and RUNNING->STOPPED; for capacity, track cluster_count over time around SCALED_UP/DOWN.

## Facets

### system.compute.warehouses.warehouse_type
CLASSIC,PRO,SERVERLESS

### system.compute.warehouses.warehouse_channel
CURRENT,PREVIEW

### system.compute.warehouses.warehouse_size
2X_SMALL,X_SMALL,SMALL,MEDIUM,LARGE,X_LARGE,2X_LARGE,3X_LARGE,4X_LARGE,5X_LARGE

### system.compute.warehouse_events.event_type
SCALED_UP,SCALED_DOWN,STOPPING,RUNNING,STARTING,STOPPED

### system.compute.warehouses.warehouse_type
CLASSIC,PRO,SERVERLESS

### system.compute.warehouses.warehouse_size
2X_SMALL,X_SMALL,SMALL,MEDIUM,LARGE,X_LARGE,2X_LARGE,3X_LARGE,4X_LARGE,5X_LARGE

### system.compute.warehouses.warehouse_channel
CURRENT,PREVIEW

### system.compute.warehouse_events.event_type
SCALED_UP,SCALED_DOWN,STOPPING,RUNNING,STARTING,STOPPED

### system.compute.warehouse_events.event_type
SCALED_UP,SCALED_DOWN,STOPPING,RUNNING,STARTING,STOPPED
