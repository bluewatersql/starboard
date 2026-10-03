# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Billing and resource consumption query pack for Databricks discovery.

DBU consumption attribution, trends, growth detection, and chargeback.
Always runs (no product gating). All queries use DBU metrics only;
no dollar/cost computations.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

# DBU-only (D7): system.billing.usage also carries non-DBU units (e.g. DSU for
# Lakebase storage) in the same usage_quantity column. Every *dbus alias in this
# pack filters usage_unit = 'DBU' so a DSU quantity is never summed into a DBU
# figure; C-B01 also emits usage_unit so the unit is explicit on every row.
C_B01_SQL = """\
SELECT
  u.workspace_id,
  u.billing_origin_product,
  u.sku_name,
  u.usage_unit,
  u.product_features.is_serverless                AS is_serverless,
  u.identity_metadata.run_as                      AS run_as,
  CASE
    WHEN u.identity_metadata.run_as LIKE '%@%' THEN 'Human User'
    WHEN u.identity_metadata.run_as IS NULL    THEN 'Unattributed'
    ELSE                                            'Service Principal'
  END                                             AS user_type,
  COUNT(DISTINCT u.usage_metadata.job_id)         AS distinct_jobs,
  COUNT(DISTINCT u.usage_metadata.job_run_id)     AS distinct_runs,
  ROUND(SUM(u.usage_quantity), 2)                 AS dbus_consumed
FROM system.billing.usage u
WHERE u.usage_unit = 'DBU'
  AND u.usage_date BETWEEN DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
                       AND CURRENT_DATE()
GROUP BY ALL
ORDER BY dbus_consumed DESC
LIMIT {result_limit}
"""

C_B02_SQL = """\
-- Monthly SKU trend. month_is_partial flags months at the edges of the lookback
-- window that may be clipped (first month: window may start mid-month; current
-- month: today may be mid-month). Do not compare a partial month directly against
-- a full month as a MoM trend — the partial month will always look lower (W21).
SELECT
  DATE_TRUNC('MONTH', u.usage_date)  AS year_month,
  u.workspace_id,
  u.billing_origin_product,
  u.sku_name,
  u.product_features.is_serverless   AS is_serverless,
  ROUND(SUM(u.usage_quantity), 2)    AS dbus,
  (DATE_TRUNC('MONTH', u.usage_date)
     = DATE_TRUNC('MONTH', DATEADD(DAY, -{lookback_days}, CURRENT_DATE()))
   OR DATE_TRUNC('MONTH', u.usage_date)
     = DATE_TRUNC('MONTH', CURRENT_DATE()))  AS month_is_partial
FROM system.billing.usage u
WHERE u.usage_unit = 'DBU'
  AND u.usage_date BETWEEN DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
                       AND CURRENT_DATE()
GROUP BY ALL
ORDER BY year_month DESC, dbus DESC
LIMIT {result_limit}
"""

C_B03_SQL = """\
WITH date_bounds AS (
  -- Materialise the four boundary dates once so Spark doesn't recompute
  -- CURRENT_DATE() per row inside the CASE expressions.
  SELECT
    DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS lookback_start,
    DATEADD(DAY, -15, CURRENT_DATE())              AS prior_start,   -- d-15
    DATEADD(DAY,  -8, CURRENT_DATE())              AS boundary,      -- d-8
    DATEADD(DAY,  -1, CURRENT_DATE())              AS last_end       -- d-1
),
job_dbus AS (
  SELECT
    t1.workspace_id,
    t1.sku_name,
    t1.usage_metadata.job_id        AS job_id,
    t1.identity_metadata.run_as     AS run_as,
    t1.usage_quantity               AS dbus,
    t1.usage_end_time
  FROM system.billing.usage t1, date_bounds d
  WHERE t1.billing_origin_product = 'JOBS'
    AND t1.usage_unit = 'DBU'
    AND t1.usage_date BETWEEN d.lookback_start AND CURRENT_DATE()
),
most_recent_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                             ORDER BY change_time DESC) = 1
)
SELECT
  t2.name,
  t1.workspace_id,
  t1.job_id,
  t1.sku_name,
  t1.run_as,
  ROUND(SUM(CASE WHEN t1.usage_end_time BETWEEN d.boundary  AND d.last_end   THEN dbus ELSE 0 END), 2) AS last7_dbus,
  ROUND(SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary THEN dbus ELSE 0 END), 2) AS prior7_dbus,
  ROUND(
    SUM(CASE WHEN t1.usage_end_time BETWEEN d.boundary   AND d.last_end   THEN dbus ELSE 0 END)
    - SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary THEN dbus ELSE 0 END),
    2
  )                                                                                                     AS wow_dbu_growth,
  -- wow_growth_pct is NULL when the prior-week DBU is below 1 DBU: a near-zero
  -- denominator produces exploding percentages (e.g. 133,507% when prior = 0.00
  -- DBU) that are arithmetically correct but operationally meaningless (W24).
  ROUND(
    CASE
      WHEN SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary
                    THEN dbus ELSE 0 END) < 1
      THEN NULL
      ELSE TRY_DIVIDE(
        SUM(CASE WHEN t1.usage_end_time BETWEEN d.boundary   AND d.last_end   THEN dbus ELSE 0 END)
        - SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary THEN dbus ELSE 0 END),
        SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary   THEN dbus ELSE 0 END)
      ) * 100
    END,
    1
  )                                                                                                     AS wow_growth_pct
FROM job_dbus t1
CROSS JOIN date_bounds d
LEFT JOIN most_recent_jobs t2 USING (workspace_id, job_id)
GROUP BY ALL
ORDER BY wow_dbu_growth DESC
LIMIT {result_limit}
"""

C_B04_SQL = """\
-- Daily DBU trend over the lookback window, plus step-change detection.
-- Step: for each calendar day find avg(7-day window before) vs avg(7-day window after);
-- report the day with the largest positive lift (step_dbu_lift). Then, for that day,
-- show the top JOBS by per-job lift (avg daily DBU after minus avg daily DBU before).
-- Evidence: spend doubled on 2026-09-14 (16K→34.7K DBU/day; Silver job 455→5,443 DBU/day).
-- DBU-only (usage_unit = 'DBU'); workspace_id in grain; LIMIT {result_limit} (W30).
WITH date_bounds AS (
  SELECT
    DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS win_start,
    DATEADD(DAY, -1, CURRENT_DATE())               AS win_end
),
daily AS (
  SELECT
    u.workspace_id,
    u.billing_origin_product,
    u.usage_date,
    ROUND(SUM(u.usage_quantity), 2)                AS daily_dbus
  FROM system.billing.usage u, date_bounds d
  WHERE u.usage_unit = 'DBU'
    AND u.usage_date BETWEEN d.win_start AND d.win_end
  GROUP BY u.workspace_id, u.billing_origin_product, u.usage_date
),
workspace_daily AS (
  SELECT workspace_id, usage_date,
    ROUND(SUM(daily_dbus), 2)                      AS total_daily_dbus
  FROM daily
  GROUP BY workspace_id, usage_date
),
rolling AS (
  SELECT
    workspace_id,
    usage_date,
    total_daily_dbus,
    ROUND(AVG(total_daily_dbus) OVER (
      PARTITION BY workspace_id ORDER BY usage_date
      ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ), 2)                                          AS avg_7d_before,
    ROUND(AVG(total_daily_dbus) OVER (
      PARTITION BY workspace_id ORDER BY usage_date
      ROWS BETWEEN CURRENT ROW AND 6 FOLLOWING
    ), 2)                                          AS avg_7d_after
  FROM workspace_daily
),
step AS (
  SELECT
    workspace_id,
    usage_date                                     AS step_date,
    avg_7d_before,
    avg_7d_after,
    ROUND(avg_7d_after - avg_7d_before, 2)         AS dbu_lift
  FROM rolling
  WHERE avg_7d_before IS NOT NULL AND avg_7d_after IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY workspace_id ORDER BY dbu_lift DESC
  ) = 1
),
job_impact AS (
  SELECT
    u.workspace_id,
    s.step_date,
    s.dbu_lift                                     AS step_dbu_lift,
    u.usage_metadata.job_id                        AS job_id,
    ROUND(
      SUM(CASE WHEN u.usage_date BETWEEN DATEADD(DAY, -7, s.step_date)
                                     AND DATEADD(DAY, -1, s.step_date)
               THEN u.usage_quantity ELSE 0 END) / 7.0, 2
    )                                              AS avg_daily_dbu_before,
    ROUND(
      SUM(CASE WHEN u.usage_date BETWEEN s.step_date
                                     AND DATEADD(DAY,  6, s.step_date)
               THEN u.usage_quantity ELSE 0 END) / 7.0, 2
    )                                              AS avg_daily_dbu_after
  FROM system.billing.usage u
  JOIN step s ON u.workspace_id = s.workspace_id
  WHERE u.billing_origin_product = 'JOBS'
    AND u.usage_unit = 'DBU'
    AND u.usage_metadata.job_id IS NOT NULL
    AND u.usage_date BETWEEN DATEADD(DAY, -7, s.step_date)
                         AND DATEADD(DAY,  6, s.step_date)
  GROUP BY u.workspace_id, s.step_date, s.dbu_lift, u.usage_metadata.job_id
),
-- Per-job step (D12): the workspace step_date is where the SUM of jobs moved
-- most, but each contributing job can have its own change point — and its own
-- shape (one job steps on a day while another ramped up over a week before it).
-- For each contributing job: a zero-filled daily series over the window, its own
-- largest trailing-7d lift date (full 7-day windows on both sides), and a
-- ramp-vs-step label from how many days sit mid-transition.
contrib AS (
  SELECT workspace_id, job_id
  FROM job_impact
  WHERE avg_daily_dbu_after > avg_daily_dbu_before
),
calendar AS (
  SELECT EXPLODE(SEQUENCE(d.win_start, d.win_end)) AS usage_date
  FROM date_bounds d
),
job_usage AS (
  SELECT
    u.workspace_id,
    u.usage_metadata.job_id                        AS job_id,
    u.usage_date,
    SUM(u.usage_quantity)                          AS dbus
  FROM system.billing.usage u, date_bounds d
  WHERE u.billing_origin_product = 'JOBS'
    AND u.usage_unit = 'DBU'
    AND u.usage_metadata.job_id IS NOT NULL
    AND u.usage_date BETWEEN d.win_start AND d.win_end
  GROUP BY u.workspace_id, u.usage_metadata.job_id, u.usage_date
),
job_daily AS (
  SELECT c.workspace_id, c.job_id, cal.usage_date,
    COALESCE(ju.dbus, 0)                           AS daily_dbus
  FROM contrib c
  CROSS JOIN calendar cal
  LEFT JOIN job_usage ju
    ON ju.workspace_id = c.workspace_id
   AND ju.job_id = c.job_id
   AND ju.usage_date = cal.usage_date
),
job_rolling AS (
  SELECT
    workspace_id,
    job_id,
    usage_date,
    AVG(daily_dbus) OVER w_before                  AS avg_before,
    COUNT(*)        OVER w_before                  AS n_before,
    AVG(daily_dbus) OVER w_after                   AS avg_after,
    COUNT(*)        OVER w_after                   AS n_after
  FROM job_daily
  WINDOW
    w_before AS (PARTITION BY workspace_id, job_id ORDER BY usage_date
                 ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING),
    w_after  AS (PARTITION BY workspace_id, job_id ORDER BY usage_date
                 ROWS BETWEEN CURRENT ROW AND 6 FOLLOWING)
),
job_step AS (
  SELECT workspace_id, job_id,
    usage_date                                     AS job_step_date,
    avg_before,
    avg_after - avg_before                         AS lift
  FROM job_rolling
  WHERE n_before = 7 AND n_after = 7
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY workspace_id, job_id ORDER BY avg_after - avg_before DESC, usage_date
  ) = 1
),
job_shape AS (
  -- transition_days = days within [job_step_date-7, job_step_date+6] whose DBU
  -- sits between 25% and 75% of the way from the before-level to the after-level.
  -- A step jumps straight across (0–1 such days); a ramp lingers mid-way.
  SELECT
    s.workspace_id,
    s.job_id,
    s.job_step_date,
    ROUND(s.lift, 2)                               AS job_step_dbu_lift,
    COUNT_IF(jd.daily_dbus > s.avg_before + 0.25 * s.lift
             AND jd.daily_dbus < s.avg_before + 0.75 * s.lift) AS job_transition_days
  FROM job_step s
  JOIN job_daily jd
    ON jd.workspace_id = s.workspace_id
   AND jd.job_id = s.job_id
   AND jd.usage_date BETWEEN DATEADD(DAY, -7, s.job_step_date)
                         AND DATEADD(DAY,  6, s.job_step_date)
  WHERE s.lift > 0
  GROUP BY s.workspace_id, s.job_id, s.job_step_date, s.lift
)
SELECT
  ji.workspace_id,
  ji.step_date,
  ji.step_dbu_lift,
  ji.job_id,
  ji.avg_daily_dbu_before,
  ji.avg_daily_dbu_after,
  ROUND(ji.avg_daily_dbu_after - ji.avg_daily_dbu_before, 2) AS job_dbu_lift,
  js.job_step_date,
  js.job_step_dbu_lift,
  js.job_transition_days,
  CASE
    WHEN js.job_step_date IS NULL   THEN NULL
    WHEN js.job_transition_days > 3 THEN 'RAMP'
    ELSE                                 'STEP'
  END                                              AS job_change_shape
FROM job_impact ji
LEFT JOIN job_shape js
  ON js.workspace_id = ji.workspace_id AND js.job_id = ji.job_id
WHERE ji.avg_daily_dbu_after > ji.avg_daily_dbu_before
ORDER BY ji.workspace_id, job_dbu_lift DESC
LIMIT {result_limit}
"""

BILLING_PACK = QueryPack(
    pack_id="billing",
    domain="billing",
    name="Resource Consumption & Attribution",
    description="DBU consumption attribution, trends, growth detection, chargeback",
    queries=(
        SystemQuery(
            query_id="C-B01",
            name="DBU Consumption by Workspace x Product x Identity",
            description=(
                "DBU attribution by product, run_as identity, and user type. "
                "DBU-only (usage_unit = 'DBU', carried on every row): non-DBU units "
                "such as Lakebase DSU are excluded, never summed into dbus_consumed"
            ),
            sql_template=C_B01_SQL,
            required_tables=("system.billing.usage",),
            domain="billing",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="DBU consumption by workspace, product, and identity",
                output_hint=(
                    "dbus_consumed is DBU only (usage_unit column = 'DBU'); DSU and "
                    "other non-DBU quantities are excluded — read them from a "
                    "unit-carrying query (e.g. SVA-02), never add them to DBU"
                ),
            ),
        ),
        SystemQuery(
            query_id="C-B02",
            name="Monthly SKU Trend",
            description=(
                "DBU by month, workspace, product, and SKU over a 90-day lookback "
                "(usage_unit = 'DBU' only; non-DBU units such as DSU excluded). "
                "month_is_partial=TRUE flags the first and current calendar months, "
                "which may be clipped by the lookback window start or today; do not "
                "compare partial months directly against full months as a MoM trend (W21)."
            ),
            sql_template=C_B02_SQL,
            required_tables=("system.billing.usage",),
            domain="billing",
            lookback_override=90,

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Monthly SKU trend analysis (90-day lookback; month_is_partial flags edge months)",
                output_hint="Filter month_is_partial=FALSE for full-month MoM comparisons",
            ),
        ),
        SystemQuery(
            query_id="C-B03",
            name="Week-over-Week DBU Growth by Job",
            description=(
                "Job-level WoW DBU growth over a fixed 14-day window: last-7 days (d-7 to d-1) "
                "vs prior-7 days (d-14 to d-8). wow_growth_pct is NULL when the prior-week DBU "
                "is below 1 DBU to suppress exploding percentages on near-zero denominators (W24)."
            ),
            sql_template=C_B03_SQL,
            required_tables=("system.billing.usage", "system.lakeflow.jobs"),
            domain="billing",
            lookback_override=14,

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Week-over-week DBU growth by job (14-day window; last-7 vs prior-7)",
                output_hint=(
                    "wow_growth_pct NULL = prior-week DBU < 1 (new or idle job); "
                    "sort by wow_dbu_growth for absolute impact"
                ),
            ),
        ),
        SystemQuery(
            query_id="C-B04",
            name="Daily DBU Trend and Step Change",
            description=(
                "Daily DBU trend over the lookback window with step-change detection: "
                "finds the single day with the largest trailing-7d average lift "
                "(avg of 7 days after minus avg of 7 days before), then shows the top "
                "JOBS contributing to that step — avg daily DBU in the 7-day window "
                "before vs after the step date. Per contributing job it also gives "
                "the job's OWN change point (job_step_date = that job's largest "
                "trailing-7d lift, full 7-day windows), job_step_dbu_lift, and "
                "job_change_shape: STEP (jumped within ~a day) or RAMP (more than 3 "
                "days mid-transition, i.e. the lift spread over days). Do not "
                "attribute the workspace step_date to every job — a job can have "
                "ramped from an earlier date. Useful for diagnosing sudden spend "
                "spikes (e.g. a new job, a runaway task). workspace_id in grain; "
                "DBU-only (usage_unit = 'DBU')."
            ),
            sql_template=C_B04_SQL,
            required_tables=("system.billing.usage",),
            domain="billing",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Daily DBU trend and largest step-change day with per-job before/after",
                output_hint=(
                    "step_date / step_dbu_lift = WORKSPACE-level avg-7d lift; "
                    "job_dbu_lift = the job's contribution measured around that "
                    "workspace date; job_step_date / job_change_shape = the job's own "
                    "change point and whether it was a STEP or a RAMP — quote these "
                    "per job, not the workspace step_date"
                ),
            ),
        ),
    ),
    gating_products=frozenset(),
)
