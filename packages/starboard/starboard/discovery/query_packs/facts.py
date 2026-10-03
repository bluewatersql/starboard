# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Headline-facts query pack (``F-01`` … ``F-11``) for Databricks discovery.

Source queries for the deterministic ``data.facts`` block that
:mod:`starboard_x.discovery._facts` builds from these rows (convergence
contract §1). Always runs (no product gating) so every envelope carries the
same headline numbers, computed one way — hosts quote them verbatim instead of
re-deriving totals from other packs' rows (whose windows include today).

Window rules (exact, server-side ``CURRENT_DATE()``):

- **Trailing 30 full days, excluding today** —
  ``usage_date >= CURRENT_DATE() - 30 AND usage_date < CURRENT_DATE()``.
  The window is fixed at 30 days (independent of ``--lookback-days``) so the
  headline is comparable across runs.
- **Calendar months** — the last full month and the one before it
  (``[TRUNC(CURRENT_DATE(),'MM') - 2 months, TRUNC(CURRENT_DATE(),'MM'))``).
- **Step-change series** (``F-03``) — daily DBU over **37 days**: the 30-day
  window plus the 7 days before it, so the first window day has a full
  trailing-7-day baseline. It is a step-detection input, not a 30-day total:
  never sum its rows as the window total (``F-01`` / ``data.facts.total`` is).
  ``data.facts.step_change`` carries the exact 7-day before/after bounds used.
- **Recent config changes** — warehouse config versions changed in the last 7
  days (``change_time >= CURRENT_DATE() - 7``, today included: a capacity change
  made today is still a disqualifier for "add capacity").

Every quantity is DBU-filtered (``usage_unit = 'DBU'``) except ``F-01``, which
carries ``usage_unit`` in its grain so DBU and DSU are reported separately and
never summed. Every query carries ``workspace_id`` in its grain. Aggregates are
``{result_limit}``-free so totals are never capped; per-workspace top-N lists
rank in SQL (``ROW_NUMBER``) instead of a global ``LIMIT``. Dimension tables
(``system.lakeflow.jobs`` / ``pipelines``, ``system.compute.warehouses``) are
de-duplicated to one row per entity / config version before joining, so a
source that replicates dimension rows cannot fan out a DBU total. Every table
reference carries an explicit alias. DBU metrics only; no dollar computations.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

from starboard.discovery.query_packs.jobs import _FAILURE_STATES_SQL

# Shared full-day window predicate (trailing 30 full days, excluding today).
_WINDOW = (
    "u.usage_date >= DATEADD(DAY, -30, CURRENT_DATE())\n"
    "  AND u.usage_date < CURRENT_DATE()"
)

F_01_SQL = f"""\
-- Window totals by product and usage_unit (DBU and DSU kept apart).
SELECT
  u.workspace_id,
  u.billing_origin_product,
  u.usage_unit,
  DATEADD(DAY, -30, CURRENT_DATE())  AS window_start,
  DATEADD(DAY, -1, CURRENT_DATE())   AS window_end,
  ROUND(SUM(u.usage_quantity), 4)    AS usage_quantity
FROM system.billing.usage u
WHERE {_WINDOW}
GROUP BY u.workspace_id, u.billing_origin_product, u.usage_unit
ORDER BY u.workspace_id, u.usage_unit, u.billing_origin_product
"""

F_02_SQL = """\
-- DBU for the last full calendar month and the prior full month.
SELECT
  u.workspace_id,
  DATE_FORMAT(TRUNC(u.usage_date, 'MM'), 'yyyy-MM')                          AS usage_month,
  DATE_FORMAT(ADD_MONTHS(TRUNC(CURRENT_DATE(), 'MM'), -1), 'yyyy-MM')        AS last_full_month,
  DATE_FORMAT(ADD_MONTHS(TRUNC(CURRENT_DATE(), 'MM'), -2), 'yyyy-MM')        AS prior_full_month,
  ROUND(SUM(u.usage_quantity), 4)                                            AS dbus
FROM system.billing.usage u
WHERE u.usage_unit = 'DBU'
  AND u.usage_date >= ADD_MONTHS(TRUNC(CURRENT_DATE(), 'MM'), -2)
  AND u.usage_date < TRUNC(CURRENT_DATE(), 'MM')
GROUP BY u.workspace_id, DATE_FORMAT(TRUNC(u.usage_date, 'MM'), 'yyyy-MM')
ORDER BY u.workspace_id, usage_month
"""

F_03_SQL = """\
-- Daily DBU over 37 days: the 30-day window plus the 7 days before it (the
-- step-change baseline). Step-detection input only: do NOT sum as a 30-day total.
-- in_window: true for the 30-day facts window, false for the 7-day baseline rows.
SELECT
  u.workspace_id,
  u.usage_date,
  ROUND(SUM(u.usage_quantity), 4) AS dbus,
  u.usage_date >= DATEADD(DAY, -30, CURRENT_DATE()) AS in_window
FROM system.billing.usage u
WHERE u.usage_unit = 'DBU'
  AND u.usage_date >= DATEADD(DAY, -37, CURRENT_DATE())
  AND u.usage_date < CURRENT_DATE()
GROUP BY u.workspace_id, u.usage_date
ORDER BY u.workspace_id, u.usage_date
"""

F_04_SQL = f"""\
-- Top 10 jobs per workspace by DBU in the window (JOBS product, job_id-attributed).
WITH latest_jobs AS (
  SELECT j.workspace_id, j.job_id, j.name
  FROM system.lakeflow.jobs j
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY j.workspace_id, j.job_id ORDER BY j.change_time DESC
  ) = 1
),
job_dbus AS (
  SELECT
    u.workspace_id,
    u.usage_metadata.job_id         AS job_id,
    SUM(u.usage_quantity)           AS dbus
  FROM system.billing.usage u
  WHERE u.usage_unit = 'DBU'
    AND u.billing_origin_product = 'JOBS'
    AND u.usage_metadata.job_id IS NOT NULL
    AND {_WINDOW}
  GROUP BY u.workspace_id, u.usage_metadata.job_id
),
ranked AS (
  SELECT
    jd.workspace_id,
    jd.job_id,
    jd.dbus,
    ROW_NUMBER() OVER (
      PARTITION BY jd.workspace_id ORDER BY jd.dbus DESC, jd.job_id
    ) AS job_rank
  FROM job_dbus jd
)
SELECT
  r.workspace_id,
  r.job_id,
  lj.name               AS job_name,
  ROUND(r.dbus, 4)      AS dbus,
  r.job_rank
FROM ranked r
LEFT JOIN latest_jobs lj
  ON lj.workspace_id = r.workspace_id AND lj.job_id = r.job_id
WHERE r.job_rank <= 10
ORDER BY r.workspace_id, r.job_rank
"""

F_05_SQL = f"""\
-- Top 10 pipelines per workspace by DBU in the window (dlt_pipeline_id-attributed).
WITH latest_pipelines AS (
  SELECT p.workspace_id, p.pipeline_id, p.name
  FROM system.lakeflow.pipelines p
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY p.workspace_id, p.pipeline_id ORDER BY p.change_time DESC
  ) = 1
),
pipeline_dbus AS (
  SELECT
    u.workspace_id,
    u.usage_metadata.dlt_pipeline_id  AS pipeline_id,
    SUM(u.usage_quantity)             AS dbus
  FROM system.billing.usage u
  WHERE u.usage_unit = 'DBU'
    AND u.usage_metadata.dlt_pipeline_id IS NOT NULL
    AND {_WINDOW}
  GROUP BY u.workspace_id, u.usage_metadata.dlt_pipeline_id
),
ranked AS (
  SELECT
    pd.workspace_id,
    pd.pipeline_id,
    pd.dbus,
    ROW_NUMBER() OVER (
      PARTITION BY pd.workspace_id ORDER BY pd.dbus DESC, pd.pipeline_id
    ) AS pipeline_rank
  FROM pipeline_dbus pd
)
SELECT
  r.workspace_id,
  r.pipeline_id,
  lp.name               AS pipeline_name,
  ROUND(r.dbus, 4)      AS dbus,
  r.pipeline_rank
FROM ranked r
LEFT JOIN latest_pipelines lp
  ON lp.workspace_id = r.workspace_id AND lp.pipeline_id = r.pipeline_id
WHERE r.pipeline_rank <= 10
ORDER BY r.workspace_id, r.pipeline_rank
"""

F_06_SQL = f"""\
-- Job-run reliability over runs that FINISHED in the window. Same per-run
-- definition as the vt-job-failures verify template, so the two reconcile:
--   * one row per (workspace_id, job_id, run_id) over ALL its timeline periods
--     (periods ending from 3 days before the window, so a long run is whole);
--   * final state = result_state of the run's LATEST period (MAX_BY over
--     period_end_time) — a repaired run counts once, by its final outcome;
--   * the run is in the window iff its LAST period ended in
--     [window_start, window_end + 1 day) (full days, today excluded). A run that
--     failed in the window but was repaired/finished today is NOT counted yet.
-- Runs with no terminal final state (still in flight) are excluded.
-- Failure = {_FAILURE_STATES_SQL}; CANCELLED is reported separately.
WITH run_summary AS (
  SELECT
    t.workspace_id,
    t.job_id,
    t.run_id,
    MAX_BY(t.result_state, t.period_end_time) AS final_result_state
  FROM system.lakeflow.job_run_timeline t
  WHERE t.period_end_time >= DATEADD(DAY, -33, CURRENT_DATE())
  GROUP BY t.workspace_id, t.job_id, t.run_id
  HAVING MAX(t.period_end_time) >= DATEADD(DAY, -30, CURRENT_DATE())
     AND MAX(t.period_end_time) < CURRENT_DATE()
)
SELECT
  rs.workspace_id,
  DATEADD(DAY, -30, CURRENT_DATE())                                                AS window_start,
  DATEADD(DAY, -1, CURRENT_DATE())                                                 AS window_end,
  COUNT(*)                                                                         AS runs,
  SUM(CASE WHEN rs.final_result_state IN {_FAILURE_STATES_SQL} THEN 1 ELSE 0 END)  AS failed_runs,
  SUM(CASE WHEN rs.final_result_state = 'FAILED' THEN 1 ELSE 0 END)               AS failed_state_runs,
  SUM(CASE WHEN rs.final_result_state = 'ERROR' THEN 1 ELSE 0 END)                AS error_runs,
  SUM(CASE WHEN rs.final_result_state IN ('TIMED_OUT', 'TIMEDOUT') THEN 1 ELSE 0 END) AS timed_out_runs,
  SUM(CASE WHEN rs.final_result_state = 'CANCELLED' THEN 1 ELSE 0 END)            AS cancelled_runs
FROM run_summary rs
WHERE rs.final_result_state IS NOT NULL
GROUP BY rs.workspace_id
ORDER BY rs.workspace_id
"""

F_07_SQL = f"""\
-- Serverless JOBS + DLT DBU by performance_target (performance-mode share).
SELECT
  u.workspace_id,
  u.billing_origin_product,
  COALESCE(u.product_features.performance_target, 'UNSPECIFIED') AS performance_target,
  ROUND(SUM(u.usage_quantity), 4)                                AS dbus
FROM system.billing.usage u
WHERE u.usage_unit = 'DBU'
  AND u.billing_origin_product IN ('JOBS', 'DLT')
  AND u.product_features.is_serverless = TRUE
  AND {_WINDOW}
GROUP BY
  u.workspace_id,
  u.billing_origin_product,
  COALESCE(u.product_features.performance_target, 'UNSPECIFIED')
ORDER BY u.workspace_id, dbus DESC
"""

F_08_SQL = f"""\
-- SQL-warehouse DBU in the window, classic vs serverless.
SELECT
  u.workspace_id,
  COALESCE(u.product_features.is_serverless, FALSE)  AS is_serverless,
  COUNT(DISTINCT u.usage_metadata.warehouse_id)      AS billed_warehouses,
  ROUND(SUM(u.usage_quantity), 4)                    AS dbus
FROM system.billing.usage u
WHERE u.usage_unit = 'DBU'
  AND u.billing_origin_product = 'SQL'
  AND u.usage_metadata.warehouse_id IS NOT NULL
  AND {_WINDOW}
GROUP BY u.workspace_id, COALESCE(u.product_features.is_serverless, FALSE)
ORDER BY u.workspace_id, is_serverless
"""

F_09_SQL = """\
-- Current (non-deleted) warehouse count. Config versions are de-duplicated
-- (SELECT DISTINCT) before picking the latest version per warehouse.
WITH versions AS (
  SELECT DISTINCT
    w.workspace_id,
    w.warehouse_id,
    w.warehouse_type,
    w.change_time,
    w.delete_time
  FROM system.compute.warehouses w
),
latest AS (
  SELECT
    v.workspace_id,
    v.warehouse_id,
    v.warehouse_type,
    v.delete_time,
    ROW_NUMBER() OVER (
      PARTITION BY v.workspace_id, v.warehouse_id
      ORDER BY v.change_time DESC, v.delete_time DESC NULLS LAST
    ) AS version_rank
  FROM versions v
)
SELECT
  l.workspace_id,
  COUNT(*) AS warehouse_count
FROM latest l
WHERE l.version_rank = 1
  AND l.delete_time IS NULL
GROUP BY l.workspace_id
ORDER BY l.workspace_id
"""

F_10_SQL = """\
-- Warehouse config changes in the last 7 days (today included). Versions are
-- de-duplicated (SELECT DISTINCT over scalar columns) before LAG so a replicated
-- version row never reads as a no-op change.
WITH versions AS (
  SELECT DISTINCT
    w.workspace_id,
    w.warehouse_id,
    w.warehouse_name,
    w.warehouse_type,
    w.warehouse_size,
    w.min_clusters,
    w.max_clusters,
    w.auto_stop_minutes,
    w.change_time,
    w.delete_time
  FROM system.compute.warehouses w
),
lagged AS (
  SELECT
    v.*,
    LAG(v.warehouse_type)    OVER wv AS prev_type,
    LAG(v.warehouse_size)    OVER wv AS prev_size,
    LAG(v.min_clusters)      OVER wv AS prev_min_clusters,
    LAG(v.max_clusters)      OVER wv AS prev_max_clusters,
    LAG(v.auto_stop_minutes) OVER wv AS prev_auto_stop_minutes,
    LAG(v.change_time)       OVER wv AS prev_change_time
  FROM versions v
  WINDOW wv AS (PARTITION BY v.workspace_id, v.warehouse_id ORDER BY v.change_time)
),
described AS (
  SELECT
    l.workspace_id,
    l.warehouse_id,
    l.warehouse_name,
    l.change_time,
    CONCAT_WS('; ',
      CASE WHEN l.delete_time IS NOT NULL THEN 'deleted' END,
      CASE WHEN l.warehouse_type IS DISTINCT FROM l.prev_type
           THEN CONCAT('warehouse_type ', COALESCE(l.prev_type, 'null'), ' -> ',
                       COALESCE(l.warehouse_type, 'null')) END,
      CASE WHEN l.warehouse_size IS DISTINCT FROM l.prev_size
           THEN CONCAT('warehouse_size ', COALESCE(l.prev_size, 'null'), ' -> ',
                       COALESCE(l.warehouse_size, 'null')) END,
      CASE WHEN l.min_clusters IS DISTINCT FROM l.prev_min_clusters
           THEN CONCAT('min_clusters ', COALESCE(CAST(l.prev_min_clusters AS STRING), 'null'),
                       ' -> ', COALESCE(CAST(l.min_clusters AS STRING), 'null')) END,
      CASE WHEN l.max_clusters IS DISTINCT FROM l.prev_max_clusters
           THEN CONCAT('max_clusters ', COALESCE(CAST(l.prev_max_clusters AS STRING), 'null'),
                       ' -> ', COALESCE(CAST(l.max_clusters AS STRING), 'null')) END,
      CASE WHEN l.auto_stop_minutes IS DISTINCT FROM l.prev_auto_stop_minutes
           THEN CONCAT('auto_stop_minutes ',
                       COALESCE(CAST(l.prev_auto_stop_minutes AS STRING), 'null'),
                       ' -> ', COALESCE(CAST(l.auto_stop_minutes AS STRING), 'null')) END
    ) AS change
  FROM lagged l
  WHERE l.prev_change_time IS NOT NULL
    AND l.change_time >= DATEADD(DAY, -7, CURRENT_DATE())
)
SELECT
  d.workspace_id,
  d.warehouse_id,
  d.warehouse_name,
  d.change_time,
  d.change
FROM described d
WHERE d.change <> ''
ORDER BY d.change_time DESC, d.workspace_id, d.warehouse_id
LIMIT 200
"""


F_11_SQL = f"""\
-- Top 10 SQL warehouses per workspace by DBU in the window (usage_metadata.warehouse_id).
-- Same full-day window as vt-warehouse-dbu and W-W01 / W-W02 (at the default lookback).
-- Config versions are de-duplicated (SELECT DISTINCT) before picking the latest name.
WITH versions AS (
  SELECT DISTINCT
    w.workspace_id,
    w.warehouse_id,
    w.warehouse_name,
    w.change_time
  FROM system.compute.warehouses w
),
latest_warehouses AS (
  SELECT
    v.workspace_id,
    v.warehouse_id,
    v.warehouse_name,
    ROW_NUMBER() OVER (
      PARTITION BY v.workspace_id, v.warehouse_id ORDER BY v.change_time DESC
    ) AS version_rank
  FROM versions v
),
warehouse_dbus AS (
  SELECT
    u.workspace_id,
    u.usage_metadata.warehouse_id     AS warehouse_id,
    SUM(u.usage_quantity)             AS dbus
  FROM system.billing.usage u
  WHERE u.usage_unit = 'DBU'
    AND u.usage_metadata.warehouse_id IS NOT NULL
    AND {_WINDOW}
  GROUP BY u.workspace_id, u.usage_metadata.warehouse_id
),
ranked AS (
  SELECT
    wd.workspace_id,
    wd.warehouse_id,
    wd.dbus,
    ROW_NUMBER() OVER (
      PARTITION BY wd.workspace_id ORDER BY wd.dbus DESC, wd.warehouse_id
    ) AS warehouse_rank
  FROM warehouse_dbus wd
)
SELECT
  r.workspace_id,
  r.warehouse_id,
  lw.warehouse_name,
  ROUND(r.dbus, 4)      AS dbus,
  r.warehouse_rank
FROM ranked r
LEFT JOIN latest_warehouses lw
  ON lw.workspace_id = r.workspace_id
 AND lw.warehouse_id = r.warehouse_id
 AND lw.version_rank = 1
WHERE r.warehouse_rank <= 10
ORDER BY r.workspace_id, r.warehouse_rank
"""


def _q(
    query_id: str,
    name: str,
    sql: str,
    tables: tuple[str, ...],
    summary: str,
    output_hint: str,
    category: QueryCategory = QueryCategory.BILLING,
) -> SystemQuery:
    return SystemQuery(
        query_id=query_id,
        name=name,
        description=summary,
        sql_template=sql,
        required_tables=tables,
        domain="billing",
        required=False,
        discovery_mode=DiscoveryMode.GENERAL,
        category=category,
        metadata=QueryMetadata(
            summary=summary,
            output_hint=output_hint,
            tags=("facts",),
        ),
    )


_USAGE = ("system.billing.usage",)

FACTS_PACK = QueryPack(
    pack_id="facts",
    # Grouped with billing for any LLM analysis (no separate domain prompt);
    # the facts block itself is built deterministically by the serializer.
    domain="billing",
    name="Headline Facts (full-day windows)",
    description=(
        "Source queries for the deterministic data.facts block: trailing 30 full "
        "days, last vs prior full month, product mix, top jobs/pipelines, step "
        "change, job reliability, performance mode, warehouses, config changes, "
        "top warehouses by DBU"
    ),
    queries=(
        _q(
            "F-01", "Window Totals by Product and Unit", F_01_SQL, _USAGE,
            "Usage over the trailing 30 full days (excludes today) by product and usage_unit",
            "One row per workspace x product x usage_unit; DBU and DSU never summed",
        ),
        _q(
            "F-02", "Last vs Prior Full Month", F_02_SQL, _USAGE,
            "DBU for the last full calendar month and the prior full month",
            "One row per workspace x month; last_full_month / prior_full_month label the months",
        ),
        _q(
            "F-03", "Daily DBU (37 days: 30-day window + 7-day baseline)", F_03_SQL, _USAGE,
            "Daily DBU over 37 days: the 30-day window plus a 7-day pre-window "
            "baseline for step-change detection (not a 30-day total; quote "
            "data.facts.total for that)",
            "One row per workspace x usage_date over 37 days (step-change input; the "
            "first 7 rows precede data.facts.window, in_window=false — never sum as the "
            "window total)",
        ),
        _q(
            "F-04", "Top Jobs by DBU (window)", F_04_SQL,
            ("system.billing.usage", "system.lakeflow.jobs"),
            "Top 10 jobs per workspace by DBU over the trailing 30 full days",
            "job_rank 1..10 per workspace",
        ),
        _q(
            "F-05", "Top Pipelines by DBU (window)", F_05_SQL,
            ("system.billing.usage", "system.lakeflow.pipelines"),
            "Top 10 pipelines per workspace by DBU over the trailing 30 full days",
            "pipeline_rank 1..10 per workspace",
        ),
        _q(
            "F-06", "Job Run Reliability (window)", F_06_SQL,
            ("system.lakeflow.job_run_timeline",),
            "Job runs that finished in the window (one per run, final state of its latest "
            "period), failures (FAILED/ERROR/TIMED_OUT) and cancellations — same per-run "
            "definition as vt-job-failures",
            "One row per workspace: runs, failed_runs (+ failed_state_runs / error_runs / "
            "timed_out_runs), cancelled_runs, window_start / window_end",
            category=QueryCategory.OPTIMIZATION,
        ),
        _q(
            "F-07", "Serverless Performance-Mode Mix (window)", F_07_SQL, _USAGE,
            "Serverless JOBS + DLT DBU by performance_target over the window",
            "One row per workspace x product x performance_target",
            category=QueryCategory.OPTIMIZATION,
        ),
        _q(
            "F-08", "Warehouse DBU Classic vs Serverless (window)", F_08_SQL, _USAGE,
            "SQL-warehouse DBU over the window split classic vs serverless",
            "One row per workspace x is_serverless",
        ),
        _q(
            "F-09", "Current Warehouse Count", F_09_SQL,
            ("system.compute.warehouses",),
            "Count of current (non-deleted) SQL warehouses",
            "One row per workspace: warehouse_count",
            category=QueryCategory.PROFILE,
        ),
        _q(
            "F-10", "Warehouse Config Changes (last 7 days)", F_10_SQL,
            ("system.compute.warehouses",),
            "Warehouse type/size/cluster-bound/auto-stop changes in the last 7 days",
            "One row per changed config version, newest first",
            category=QueryCategory.PROFILE,
        ),
        _q(
            "F-11", "Top Warehouses by DBU (window)", F_11_SQL,
            ("system.billing.usage", "system.compute.warehouses"),
            "Top 10 SQL warehouses per workspace by DBU over the trailing 30 full days",
            "warehouse_rank 1..10 per workspace (usage_metadata.warehouse_id)",
        ),
    ),
)
