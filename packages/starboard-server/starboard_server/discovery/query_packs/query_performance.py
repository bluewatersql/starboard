"""Query performance analysis pack."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery

C_Q01_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id AS warehouse_id,
  executed_by,
  statement_type,
  DATE(start_time) AS query_date,
  COUNT(*) AS total_queries,
  ROUND(AVG(total_duration_ms / 1000.0), 2) AS avg_total_secs,
  ROUND(PERCENTILE(total_duration_ms / 1000.0, 0.50), 2) AS p50_total_secs,
  ROUND(PERCENTILE(total_duration_ms / 1000.0, 0.95), 2) AS p95_total_secs,
  ROUND(PERCENTILE(total_duration_ms / 1000.0, 0.99), 2) AS p99_total_secs,
  ROUND(AVG(execution_duration_ms / 1000.0), 2) AS avg_execution_secs,
  ROUND(AVG(compilation_duration_ms / 1000.0), 2) AS avg_compilation_secs,
  SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed_queries,
  SUM(CASE WHEN from_result_cache = 'true' THEN 1 ELSE 0 END) AS cache_hits,
  ROUND(SUM(read_bytes) / (1024.0 * 1024 * 1024), 2) AS total_read_gb
FROM system.query.history
WHERE start_time >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
  AND compute.warehouse_id IS NOT NULL
GROUP BY workspace_id, compute.warehouse_id, executed_by, statement_type, DATE(start_time)
ORDER BY total_queries DESC
"""

C_Q02_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id AS warehouse_id,
  statement_id,
  executed_by,
  statement_type,
  DATE(start_time) AS query_date,
  ROUND(total_duration_ms / 1000.0, 2) AS total_secs,
  ROUND(execution_duration_ms / 1000.0, 2) AS execution_secs,
  ROUND(compilation_duration_ms / 1000.0, 2) AS compilation_secs,
  ROUND(spilled_local_bytes / (1024.0 * 1024 * 1024), 2) AS spill_gb,
  ROUND(shuffle_read_bytes / (1024.0 * 1024 * 1024), 2) AS shuffle_gb,
  read_io_cache_percent AS cache_hit_pct,
  ROUND(total_task_duration_ms / NULLIF(execution_duration_ms, 0), 2) AS task_to_exec_ratio,
  ROUND(read_bytes / (1024.0 * 1024 * 1024), 2) AS read_gb,
  read_partitions,
  pruned_files,
  ROUND(pruned_files * 1.0 / NULLIF(read_files, 0), 2) AS pruning_ratio,
  ROUND(compilation_duration_ms * 1.0 / NULLIF(total_duration_ms, 0) * 100, 1) AS compilation_pct,
  from_result_cache,
  (CASE WHEN spilled_local_bytes > 1073741824 THEN 1 ELSE 0 END
   + CASE WHEN shuffle_read_bytes > 10737418240 THEN 1 ELSE 0 END
   + CASE WHEN compilation_duration_ms > 5000 THEN 1 ELSE 0 END
   + CASE WHEN total_task_duration_ms / NULLIF(execution_duration_ms, 0) > 10 THEN 1 ELSE 0 END
   + CASE WHEN read_io_cache_percent < 30 AND read_bytes > 1073741824 THEN 1 ELSE 0 END
   + CASE WHEN total_duration_ms > 300000 THEN 1 ELSE 0 END) AS optimization_score
FROM system.query.history
WHERE start_time >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
  AND compute.warehouse_id IS NOT NULL
  AND execution_status = 'FINISHED'
  AND (
    spilled_local_bytes > 0 OR shuffle_read_bytes > 1073741824
    OR compilation_duration_ms > 5000 OR total_duration_ms > 300000
    OR read_io_cache_percent < 30
  )
ORDER BY optimization_score DESC, total_duration_ms DESC
LIMIT 200
"""

C_Q03_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id AS warehouse_id,
  MD5(statement_text) AS statement_text_hash,
  COUNT(*) AS execution_count,
  COUNT(DISTINCT executed_by) AS distinct_users,
  ROUND(AVG(total_duration_ms / 1000.0), 2) AS avg_total_secs,
  ROUND(SUM(total_duration_ms / 1000.0), 2) AS total_compute_secs,
  SUM(CASE WHEN from_result_cache = 'true' THEN 1 ELSE 0 END) AS cache_hits,
  ROUND(SUM(CASE WHEN from_result_cache = 'true' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS cache_hit_pct,
  ROUND(SUM(read_bytes) / (1024.0 * 1024 * 1024), 2) AS total_read_gb,
  MIN(start_time) AS first_seen,
  MAX(start_time) AS last_seen
FROM system.query.history
WHERE start_time >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
  AND compute.warehouse_id IS NOT NULL
  AND execution_status = 'FINISHED'
GROUP BY workspace_id, compute.warehouse_id, MD5(statement_text)
HAVING COUNT(*) >= 5
ORDER BY execution_count DESC
LIMIT 200
"""

C_Q04_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id AS warehouse_id,
  execution_status,
  error_message,
  COUNT(*) AS occurrences,
  COUNT(DISTINCT executed_by) AS affected_users,
  MIN(start_time) AS first_occurrence,
  MAX(start_time) AS last_occurrence,
  ROUND(AVG(total_duration_ms / 1000.0), 2) AS avg_duration_secs
FROM system.query.history
WHERE start_time >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
  AND compute.warehouse_id IS NOT NULL
  AND execution_status != 'FINISHED'
GROUP BY workspace_id, compute.warehouse_id, execution_status, error_message
HAVING COUNT(*) >= 3
ORDER BY occurrences DESC
LIMIT 100
"""

C_Q05_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id AS warehouse_id,
  DATE(start_time) AS query_date,
  HOUR(start_time) AS query_hour,
  COUNT(*) AS concurrent_queries,
  ROUND(AVG(total_duration_ms / 1000.0), 2) AS avg_total_secs,
  ROUND(AVG((waiting_at_capacity_duration_ms + waiting_for_compute_duration_ms) / 1000.0), 2) AS avg_queue_secs,
  SUM(CASE WHEN (waiting_at_capacity_duration_ms + waiting_for_compute_duration_ms) > 30000 THEN 1 ELSE 0 END) AS queries_queued_30s_plus,
  ROUND(MAX(total_duration_ms / 1000.0), 2) AS max_total_secs
FROM system.query.history
WHERE start_time >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
  AND compute.warehouse_id IS NOT NULL
GROUP BY workspace_id, compute.warehouse_id, DATE(start_time), HOUR(start_time)
HAVING COUNT(*) >= 10
ORDER BY concurrent_queries DESC
LIMIT 200
"""

QUERY_PERF_PACK = QueryPack(
    pack_id="query_perf",
    domain="query_performance",
    name="Query Performance Analysis",
    description="Query profiling, optimization candidates, caching, concurrency, errors",
    queries=(
        SystemQuery(
            query_id="C-Q01",
            name="Comprehensive Query Performance Profile",
            description="Aggregated query metrics by warehouse, user, statement type, and date",
            sql_template=C_Q01_SQL,
            required_tables=("system.query.history",),
            domain="query_performance",
        ),
        SystemQuery(
            query_id="C-Q02",
            name="Multi-Signal Optimization Candidates",
            description="Queries with spill, shuffle, compilation, or long runtimes",
            sql_template=C_Q02_SQL,
            required_tables=("system.query.history",),
            domain="query_performance",
            lookback_override=7,
        ),
        SystemQuery(
            query_id="C-Q03",
            name="Repeated Queries and Caching Opportunity",
            description="High-frequency query hashes with cache hit metrics",
            sql_template=C_Q03_SQL,
            required_tables=("system.query.history",),
            domain="query_performance",
        ),
        SystemQuery(
            query_id="C-Q04",
            name="Warehouse Failure Error Patterns",
            description="Non-FINISHED query error patterns by warehouse",
            sql_template=C_Q04_SQL,
            required_tables=("system.query.history",),
            domain="query_performance",
        ),
        SystemQuery(
            query_id="C-Q05",
            name="Warehouse Concurrency Peaks",
            description="Hourly concurrency and queue metrics by warehouse",
            sql_template=C_Q05_SQL,
            required_tables=("system.query.history",),
            domain="query_performance",
        ),
    ),
    gating_products=frozenset({"SQL"}),
)
