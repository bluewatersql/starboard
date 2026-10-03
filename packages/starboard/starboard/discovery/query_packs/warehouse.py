# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""SQL warehouse (DBSQL) operational framings query pack.

Encodes the categorical *framings* an expert uses to reason about a SQL
warehouse portfolio, expressed entirely over PUBLIC Databricks system tables:

- **Utilization bands** — Offline / No-utilization / Under-utilized / Optimal /
  High-concurrency / Resource-starved / ``Serverless — pay per use``, from a
  utilization ratio (query busy-time vs warehouse running-time) derived from
  ``system.compute.warehouse_events`` + ``system.query.history``. A ratio above the
  Optimal band only measures concurrency; it is labelled Resource-starved only when
  queries measurably queued at capacity (``waiting_at_capacity_duration_ms``), else
  High-concurrency. SERVERLESS warehouses skip the ratio bands entirely (they bill per
  query, not by running time) and receive ``Serverless — pay per use`` unless capacity
  queueing is measured (≥ 10 % of queries waited), in which case they are
  ``Resource-starved``.
- **Auto-stop efficiency / waste** — warehouse running-time with zero query
  activity (candidate for a tighter auto-stop), from running intervals in
  ``warehouse_events`` left-joined to query starts.
- **Query-load buckets** — 0-10 / 10-100 / 100-1000 / 1000+ queries per
  warehouse-day.
- **Client-app mix** — dashboards / jobs / dbt / notebooks / external BI / SQL
  editor / API-SDK, via a CASE over ``client_application``.
- **Trend windows** — T7 / T28 / T91 query volume and execution-time trend.
- **Per-warehouse DBU** — ``system.billing.usage`` rows carry
  ``usage_metadata.warehouse_id``, so W-W01 / W-W02 attach the warehouse's own DBU over
  the lookback (``warehouse_dbus``) and W-W02 derives an *estimated* idle-DBU figure.
- **Workload drivers** — W-W06 names the dashboards / jobs / Genie spaces / notebooks /
  client apps that drive each warehouse's load (count, read bytes, duration).
- **Config + change history** — W-W07 reports each warehouse's current size / cluster
  bounds / auto-stop from ``system.compute.warehouses`` and the config changes (resize,
  cluster-bound, auto-stop) recorded in the lookback.

Windows: ``{lookback_days}`` queries filter ``>= CURRENT_DATE() - lookback_days``, i.e.
``lookback_days`` full days **plus today-to-date** — except W-W01 and W-W02, which are
full-day windows (``< CURRENT_DATE()``, today excluded) so their ``warehouse_dbus``
matches ``vt-warehouse-dbu`` and the ``data.facts`` window (at the default 30-day
lookback). Elsewhere a reconciliation against exactly N full days differs by today's
partial usage — material for a low-activity warehouse with a burst today.

All queries use DBU / duration / count metrics only; no dollar computations.
Any cost interpretation layered on top of these DBU figures is a **list-price
estimate** (public ``system.billing`` reflects list price x usage), never a
contract-accurate or discount-adjusted figure.

Both source tables are account-scoped, so every query carries ``workspace_id`` in its
grain: a ``warehouse_id`` is unique only within a workspace, and without ``workspace_id``
the running/idle totals silently conflate same-named warehouses across workspaces (and a
consumer can't tell which workspace a waste finding belongs to).

Column names verified against current Databricks system-table docs (2026-08):
- ``system.compute.warehouse_events``: ``workspace_id``, ``warehouse_id``, ``event_type``
  (STARTING / RUNNING / SCALED_UP / SCALED_DOWN / STOPPING / STOPPED),
  ``cluster_count``, ``event_time``.
- ``system.query.history``: ``workspace_id``, ``compute.warehouse_id``, ``start_time``,
  ``execution_duration_ms``, ``waiting_at_capacity_duration_ms``, ``statement_id``,
  ``executed_by``,
  ``client_application``, ``read_bytes``, ``total_duration_ms``, ``query_source``
  (STRUCT: ``job_info.job_id``, ``dashboard_id``, ``legacy_dashboard_id``,
  ``genie_space_id``, ``notebook_id``, ``alert_id``, ``sql_query_id``).
- ``system.billing.usage``: ``usage_metadata.warehouse_id``, ``usage_quantity``,
  ``usage_date``.
- ``system.compute.warehouses`` (SCD, one row per config version): ``workspace_id``,
  ``warehouse_id``, ``warehouse_name``, ``warehouse_type``, ``warehouse_size``,
  ``min_clusters``, ``max_clusters``, ``auto_stop_minutes``, ``change_time``,
  ``delete_time``.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

# --- Framing thresholds (shared by the SQL CASE expressions and the pure
# reference classifiers below, so prompts / formatters can narrate the same
# bands the SQL produces). These are generic, defensible thresholds. ---

#: Utilization ratio below this is "Under-utilized".
UNDER_UTILIZED_MAX = 0.30
#: Utilization ratio at/below this (and >= UNDER_UTILIZED_MAX) is "Optimal";
#: above it is "High-concurrency" or "Resource-starved" (see below).
OPTIMAL_MAX = 0.80
#: Above OPTIMAL_MAX, a warehouse is "Resource-starved" only when at least this
#: percentage of its queries waited at capacity (``waiting_at_capacity_duration_ms
#: > 0``); otherwise the high ratio is just concurrency ("High-concurrency").
STARVED_QUEUED_PCT_MIN = 10.0


def classify_utilization_band(
    *,
    running_seconds: float | None,
    total_queries: int,
    utilization_ratio: float | None,
    queued_query_pct: float | None = None,
    warehouse_type: str | None = None,
) -> str:
    """Classify a warehouse into a utilization band.

    Mirrors the CASE in ``W-W01`` so callers can narrate results in the same
    bands the SQL emits.

    Args:
        running_seconds: Seconds the warehouse spent running in the window.
        total_queries: Queries executed on the warehouse in the window.
        utilization_ratio: Query busy-time / running-time (a public proxy for
            warehouse utilization). May exceed 1.0 when concurrent demand
            exceeds a single slot's capacity.
        queued_query_pct: Percentage of the warehouse's queries that waited at
            capacity. ``None`` (unmeasured) is treated as 0 — a high ratio alone
            never proves starvation.
        warehouse_type: The warehouse type (``CLASSIC`` / ``PRO`` / ``SERVERLESS``
            or ``None`` if the dimension is unavailable). SERVERLESS warehouses
            bill per query, not by running time, so the utilization ratio is not
            a meaningful capacity signal and is skipped in favour of a stable
            informational label.

    Returns:
        One of ``Offline`` / ``No-utilization`` / ``Under-utilized`` /
        ``Optimal`` / ``High-concurrency`` / ``Resource-starved`` /
        ``Serverless — pay per use``.
    """
    if not running_seconds:
        return "Offline"
    if not total_queries or utilization_ratio is None:
        return "No-utilization"
    # Serverless warehouses bill per query; the running-time ratio is not a
    # capacity signal for them. Show queueing pressure if measured; otherwise
    # a stable informational label (never "Under-utilized" on a busy fleet).
    if warehouse_type == "SERVERLESS":
        if (queued_query_pct or 0) >= STARVED_QUEUED_PCT_MIN:
            return "Resource-starved"
        return "Serverless — pay per use"
    if utilization_ratio < UNDER_UTILIZED_MAX:
        return "Under-utilized"
    if utilization_ratio <= OPTIMAL_MAX:
        return "Optimal"
    if (queued_query_pct or 0) >= STARVED_QUEUED_PCT_MIN:
        return "Resource-starved"
    return "High-concurrency"


def classify_load_bucket(query_count: int) -> str:
    """Bucket a query count into 0-10 / 10-100 / 100-1000 / 1000+.

    Mirrors the CASE in ``W-W03``.
    """
    if query_count < 10:
        return "0-10"
    if query_count < 100:
        return "10-100"
    if query_count < 1000:
        return "100-1000"
    return "1000+"


def classify_client_app(client_application: str | None) -> str:
    """Classify a ``client_application`` string into a client-app category.

    Mirrors the CASE in ``W-W04``. Matching is case-insensitive substring;
    order matters (first match wins).
    """
    if client_application is None:
        return "Unknown"
    app = client_application.lower()
    if "dashboard" in app:
        return "Dashboards/BI"
    if "dbt" in app:
        return "dbt"
    if "workflow" in app or "job" in app:
        return "Jobs/Workflows"
    if "notebook" in app:
        return "Notebooks"
    if any(k in app for k in ("power bi", "powerbi", "tableau", "looker", "qlik", "fivetran")):
        return "External BI"
    if "sql editor" in app or "query editor" in app:
        return "SQL Editor"
    if any(k in app for k in ("connector", "odbc", "jdbc", "sdk", "api")):
        return "API/SDK"
    return "Other"


# ---------------------------------------------------------------------------
# W-W01 — Warehouse utilization bands
# ---------------------------------------------------------------------------
# running_seconds is derived from warehouse_events state-transition intervals:
# the time from each "on" event (STARTING/RUNNING/SCALED_*) to the next event
# is running time. utilization_ratio = query busy-seconds / running-seconds is
# a public proxy for how hard the warehouse worked while it was up. It sums
# per-query execution time, so above 1.0 it measures concurrency, not starvation:
# the top band is split on measured capacity queueing (queued_query_pct, the share
# of queries with waiting_at_capacity_duration_ms > 0) into Resource-starved vs
# High-concurrency.
W_W01_SQL = """\
-- Full-day window (>= window_start AND < CURRENT_DATE), same as W-W02 and the
-- data.facts window: warehouse_dbus / running_seconds / query load all cover the
-- same N full days, so warehouse_dbus reconciles with vt-warehouse-dbu (today's
-- partial billing rows previously inflated it). Open intervals close at midnight.
WITH events AS (
  SELECT
    workspace_id,
    warehouse_id,
    event_type,
    event_time,
    LEAD(event_time) OVER (PARTITION BY workspace_id, warehouse_id ORDER BY event_time) AS next_event_time
  FROM system.compute.warehouse_events
  WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND event_time <  CURRENT_DATE()
),
running AS (
  SELECT
    workspace_id,
    warehouse_id,
    SUM(
      CASE
        WHEN event_type IN ('STARTING', 'RUNNING', 'SCALED_UP', 'SCALED_DOWN')
        THEN DATEDIFF(SECOND, event_time, COALESCE(next_event_time, CURRENT_DATE()))
        ELSE 0
      END
    ) AS running_seconds
  FROM events
  GROUP BY workspace_id, warehouse_id
),
query_load AS (
  SELECT
    workspace_id                              AS workspace_id,
    compute.warehouse_id                      AS warehouse_id,
    COUNT(*)                                  AS total_queries,
    ROUND(SUM(execution_duration_ms) / 1000.0, 2) AS busy_seconds,
    ROUND(100.0 * COUNT_IF(waiting_at_capacity_duration_ms > 0) / COUNT(*), 2) AS queued_query_pct,
    ROUND(AVG(waiting_at_capacity_duration_ms) / 1000.0, 3) AS avg_capacity_wait_secs
  FROM system.query.history
  WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND start_time <  CURRENT_DATE()
    AND compute.warehouse_id IS NOT NULL
  GROUP BY workspace_id, compute.warehouse_id
),
-- Warehouse type (CLASSIC / PRO / SERVERLESS) per id, so an idle finding can
-- self-qualify: idle time only costs money on classic/pro — serverless
-- auto-suspends. ANY_VALUE + GROUP BY (not a change_time window) keeps this
-- robust across the public dim and the internal mirror dim, where an ordering
-- column may differ; warehouse_type is stable per warehouse. LEFT-joined so an
-- unavailable dimension yields null, not a failure.
wh_dim AS (
  SELECT workspace_id, warehouse_id, ANY_VALUE(warehouse_type) AS warehouse_type
  FROM system.compute.warehouses
  GROUP BY workspace_id, warehouse_id
),
-- Per-warehouse billed DBU over the lookback's full days (usage_metadata.warehouse_id is populated
-- on warehouse usage). Pre-aggregated to one row per (workspace_id, warehouse_id) so the
-- LEFT JOIN cannot fan out. DBU only; any $ view is a list-price estimate.
wh_dbus AS (
  SELECT
    workspace_id,
    usage_metadata.warehouse_id AS warehouse_id,
    ROUND(SUM(usage_quantity), 2) AS warehouse_dbus
  FROM system.billing.usage
  WHERE usage_metadata.warehouse_id IS NOT NULL
    AND usage_unit = 'DBU'
    AND usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND usage_date <  CURRENT_DATE()
  GROUP BY workspace_id, usage_metadata.warehouse_id
)
SELECT
  COALESCE(r.workspace_id, q.workspace_id)          AS workspace_id,
  COALESCE(r.warehouse_id, q.warehouse_id)          AS warehouse_id,
  w.warehouse_type                                  AS warehouse_type,
  d.warehouse_dbus                                  AS warehouse_dbus,
  COALESCE(r.running_seconds, 0)                    AS running_seconds,
  COALESCE(q.total_queries, 0)                      AS total_queries,
  -- utilization_ratio = summed query execution seconds / warehouse running seconds.
  -- Overlapping queries each count, so > 1.0 = average concurrent queries while up
  -- (2.74 ~ 2.7 queries at once), NOT >100% capacity; saturation = queued_query_pct.
  ROUND(TRY_DIVIDE(q.busy_seconds, r.running_seconds), 4) AS utilization_ratio,
  q.queued_query_pct                                AS queued_query_pct,
  q.avg_capacity_wait_secs                          AS avg_capacity_wait_secs,
  CASE
    WHEN COALESCE(r.running_seconds, 0) = 0                   THEN 'Offline'
    WHEN COALESCE(q.total_queries, 0) = 0                     THEN 'No-utilization'
    -- A NULL ratio (e.g. busy_seconds is NULL) never satisfies the < / <=
    -- comparisons below (SQL 3-valued logic), so without this explicit branch
    -- such a row would fall through to the top band. Map it to
    -- 'No-utilization' to match the Python classify_utilization_band labeler.
    WHEN TRY_DIVIDE(q.busy_seconds, r.running_seconds) IS NULL THEN 'No-utilization'
    -- Serverless warehouses bill per query, not by running time; the
    -- utilization ratio is not a meaningful capacity signal. Show queueing
    -- if measured; otherwise a stable informational label (never
    -- 'Under-utilized' on a fleet that processed 394K portal queries/30d).
    WHEN w.warehouse_type = 'SERVERLESS'
         AND COALESCE(q.queued_query_pct, 0) >= 10.0           THEN 'Resource-starved'
    WHEN w.warehouse_type = 'SERVERLESS'                       THEN 'Serverless — pay per use'
    WHEN TRY_DIVIDE(q.busy_seconds, r.running_seconds) < 0.30 THEN 'Under-utilized'
    WHEN TRY_DIVIDE(q.busy_seconds, r.running_seconds) <= 0.80 THEN 'Optimal'
    -- Above Optimal the ratio is concurrency; only measured capacity queueing
    -- makes it starvation (NULL queueing = unmeasured -> not starved).
    WHEN COALESCE(q.queued_query_pct, 0) >= 10.0                THEN 'Resource-starved'
    ELSE                                                           'High-concurrency'
  END                                               AS utilization_band
FROM running r
FULL OUTER JOIN query_load q
  ON r.warehouse_id = q.warehouse_id AND r.workspace_id = q.workspace_id
LEFT JOIN wh_dim w
  ON w.workspace_id = COALESCE(r.workspace_id, q.workspace_id)
 AND w.warehouse_id = COALESCE(r.warehouse_id, q.warehouse_id)
LEFT JOIN wh_dbus d
  ON d.workspace_id = COALESCE(r.workspace_id, q.workspace_id)
 AND d.warehouse_id = COALESCE(r.warehouse_id, q.warehouse_id)
ORDER BY running_seconds DESC NULLS LAST
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# W-W02 — Auto-stop efficiency / waste (running with no queries)
# ---------------------------------------------------------------------------
# An interval runs from each event to the NEXT event of ANY type, and only intervals
# that START on a running-state event count. LEAD must run over ALL events (incl.
# STOPPING / STOPPED): filtering to running states before LEAD would stretch each
# interval across the stopped time to the next start, so every warehouse would show
# ~the whole window as "running" and the idle estimate would be overstated.
W_W02_SQL = """\
-- D9: full-day window (>= window_start AND < CURRENT_DATE) keeps est_idle_dbus
-- stable across multiple runs on the same day. Using the current timestamp for
-- the open-interval ceiling caused a ~4.7x swing (22 / 96 / 103 for the same
-- window) because partial-today billing rows grow throughout the day, and open
-- intervals stretch by however many seconds elapsed since the query ran.
-- Using CURRENT_DATE() as the ceiling closes both open ends at midnight and makes
-- warehouse_dbus / running_seconds both cover the same N full days.
WITH events AS (
  SELECT
    workspace_id,
    warehouse_id,
    event_type,
    event_time,
    LEAD(event_time) OVER (PARTITION BY workspace_id, warehouse_id ORDER BY event_time) AS next_event_time
  FROM system.compute.warehouse_events
  WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND event_time <  CURRENT_DATE()
),
running_intervals AS (
  SELECT
    workspace_id,
    warehouse_id,
    event_time      AS interval_start,
    next_event_time AS interval_end
  FROM events
  WHERE event_type IN ('STARTING', 'RUNNING', 'SCALED_UP', 'SCALED_DOWN')
),
interval_activity AS (
  SELECT
    ri.workspace_id,
    ri.warehouse_id,
    -- Open interval (last event before today has no following event in-window):
    -- COALESCE to CURRENT_DATE() (midnight) so the interval closes at the day
    -- boundary, giving a deterministic running_seconds independent of run time.
    DATEDIFF(SECOND, ri.interval_start, COALESCE(ri.interval_end, CURRENT_DATE())) AS interval_seconds,
    COUNT(qh.statement_id)                                                          AS query_count
  FROM running_intervals ri
  LEFT JOIN system.query.history qh
         ON qh.compute.warehouse_id = ri.warehouse_id
        AND qh.workspace_id = ri.workspace_id
        AND qh.start_time >= ri.interval_start
        AND qh.start_time <  COALESCE(ri.interval_end, CURRENT_DATE())
        AND qh.start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
        AND qh.start_time <  CURRENT_DATE()
  GROUP BY ri.workspace_id, ri.warehouse_id, ri.interval_start, ri.interval_end
),
-- Warehouse type (CLASSIC / PRO / SERVERLESS) per id: idle running hours only
-- cost money on classic/pro — serverless auto-suspends. ANY_VALUE + GROUP BY
-- (not a change_time window) stays robust across the public dim and the internal
-- mirror dim; warehouse_type is stable per warehouse. LEFT-joined so an
-- unavailable dimension yields null, not a failure.
wh_dim AS (
  SELECT workspace_id, warehouse_id, ANY_VALUE(warehouse_type) AS warehouse_type
  FROM system.compute.warehouses
  GROUP BY workspace_id, warehouse_id
),
-- Per-warehouse billed DBU over the lookback (usage_metadata.warehouse_id is populated
-- on warehouse usage). Pre-aggregated to one row per (workspace_id, warehouse_id) so the
-- LEFT JOIN cannot fan out. DBU only; any $ view is a list-price estimate.
wh_dbus AS (
  SELECT
    workspace_id,
    usage_metadata.warehouse_id AS warehouse_id,
    ROUND(SUM(usage_quantity), 2) AS warehouse_dbus
  FROM system.billing.usage
  WHERE usage_metadata.warehouse_id IS NOT NULL
    AND usage_unit = 'DBU'
    AND usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND usage_date <  CURRENT_DATE()
  GROUP BY workspace_id, usage_metadata.warehouse_id
)
SELECT
  ia.workspace_id,
  ia.warehouse_id,
  w.warehouse_type                                                                 AS warehouse_type,
  ROUND(SUM(interval_seconds) / 3600.0, 2)                                          AS running_hours,
  ROUND(SUM(CASE WHEN query_count = 0 THEN interval_seconds ELSE 0 END) / 3600.0, 2) AS idle_running_hours,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN query_count = 0 THEN interval_seconds ELSE 0 END),
      SUM(interval_seconds)
    ) * 100,
    1
  )                                                                                  AS auto_stop_waste_pct,
  -- Billed DBU for this warehouse over the same lookback (one row per warehouse, so
  -- MAX() just carries it through the aggregate).
  MAX(d.warehouse_dbus)                                                              AS warehouse_dbus,
  -- ESTIMATE (list-price DBU, not a measurement): billed DBU apportioned by the idle
  -- share of running time, i.e. warehouse_dbus x idle_seconds / running_seconds, capped
  -- at warehouse_dbus. Assumes DBU accrue roughly uniformly over running time. NULL for
  -- SERVERLESS: serverless auto-suspends and bills per use, so idle running time is not
  -- billed the way classic/pro idle time is and this apportioning would overstate it
  -- (idle_running_hours still shows; tighten auto_stop_minutes on its own merit).
  -- Only for warehouses CONFIRMED to bill idle running time (CLASSIC/PRO): an
  -- unknown type (dim row missing / not carried) is NULL, never an estimate.
  CASE
    WHEN w.warehouse_type IS NULL OR w.warehouse_type NOT IN ('CLASSIC', 'PRO') THEN NULL
    ELSE ROUND(
      LEAST(
        MAX(d.warehouse_dbus),
        TRY_DIVIDE(
          MAX(d.warehouse_dbus) * SUM(CASE WHEN query_count = 0 THEN interval_seconds ELSE 0 END),
          SUM(interval_seconds)
        )
      ),
      2
    )
  END                                                                                AS est_idle_dbus
FROM interval_activity ia
LEFT JOIN wh_dim w
  ON w.workspace_id = ia.workspace_id AND w.warehouse_id = ia.warehouse_id
LEFT JOIN wh_dbus d
  ON d.workspace_id = ia.workspace_id AND d.warehouse_id = ia.warehouse_id
GROUP BY ia.workspace_id, ia.warehouse_id, w.warehouse_type
HAVING running_hours > 0
ORDER BY est_idle_dbus DESC NULLS LAST, idle_running_hours DESC, warehouse_id
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# W-W03 — Query-load buckets (per warehouse-day)
# ---------------------------------------------------------------------------
W_W03_SQL = """\
WITH daily AS (
  SELECT
    workspace_id         AS workspace_id,
    compute.warehouse_id AS warehouse_id,
    DATE(start_time)     AS query_date,
    COUNT(*)             AS query_count
  FROM system.query.history
  WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND compute.warehouse_id IS NOT NULL
  GROUP BY workspace_id, compute.warehouse_id, DATE(start_time)
)
SELECT
  workspace_id,
  warehouse_id,
  query_date,
  query_count,
  CASE
    WHEN query_count < 10   THEN '0-10'
    WHEN query_count < 100  THEN '10-100'
    WHEN query_count < 1000 THEN '100-1000'
    ELSE                         '1000+'
  END AS load_bucket
FROM daily
ORDER BY warehouse_id, query_date DESC
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# W-W04 — Client-app mix
# ---------------------------------------------------------------------------
W_W04_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id AS warehouse_id,
  CASE
    WHEN client_application IS NULL                       THEN 'Unknown'
    WHEN LOWER(client_application) LIKE '%dashboard%'     THEN 'Dashboards/BI'
    WHEN LOWER(client_application) LIKE '%dbt%'           THEN 'dbt'
    WHEN LOWER(client_application) LIKE '%workflow%'
      OR LOWER(client_application) LIKE '%job%'           THEN 'Jobs/Workflows'
    WHEN LOWER(client_application) LIKE '%notebook%'      THEN 'Notebooks'
    WHEN LOWER(client_application) LIKE '%power bi%'
      OR LOWER(client_application) LIKE '%powerbi%'
      OR LOWER(client_application) LIKE '%tableau%'
      OR LOWER(client_application) LIKE '%looker%'
      OR LOWER(client_application) LIKE '%qlik%'
      OR LOWER(client_application) LIKE '%fivetran%'      THEN 'External BI'
    WHEN LOWER(client_application) LIKE '%sql editor%'
      OR LOWER(client_application) LIKE '%query editor%'  THEN 'SQL Editor'
    WHEN LOWER(client_application) LIKE '%connector%'
      OR LOWER(client_application) LIKE '%odbc%'
      OR LOWER(client_application) LIKE '%jdbc%'
      OR LOWER(client_application) LIKE '%sdk%'
      OR LOWER(client_application) LIKE '%api%'            THEN 'API/SDK'
    ELSE                                                       'Other'
  END                                     AS client_app_category,
  COUNT(*)                                AS total_queries,
  COUNT(DISTINCT executed_by)             AS distinct_users,
  ROUND(SUM(execution_duration_ms) / 1000.0, 2) AS total_execution_secs
FROM system.query.history
WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND compute.warehouse_id IS NOT NULL
GROUP BY ALL
ORDER BY warehouse_id, total_queries DESC
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# W-W05 — Trend windows T7 / T28 / T91
# ---------------------------------------------------------------------------
# Fixed trend windows (7 / 28 / 91 days) are the framing itself, so this query
# scopes to the widest (91-day) window rather than the shared {lookback_days}.
W_W05_SQL = """\
WITH bounds AS (
  SELECT
    DATEADD(DAY,  -7, CURRENT_DATE()) AS t7_start,
    DATEADD(DAY, -28, CURRENT_DATE()) AS t28_start,
    DATEADD(DAY, -91, CURRENT_DATE()) AS t91_start
)
SELECT
  workspace_id,
  compute.warehouse_id AS warehouse_id,
  COUNT(*)                                                                              AS queries_t91,
  SUM(CASE WHEN start_time >= b.t28_start THEN 1 ELSE 0 END)                             AS queries_t28,
  SUM(CASE WHEN start_time >= b.t7_start  THEN 1 ELSE 0 END)                             AS queries_t7,
  ROUND(SUM(execution_duration_ms) / 1000.0, 2)                                         AS exec_secs_t91,
  ROUND(SUM(CASE WHEN start_time >= b.t28_start THEN execution_duration_ms ELSE 0 END) / 1000.0, 2) AS exec_secs_t28,
  ROUND(SUM(CASE WHEN start_time >= b.t7_start  THEN execution_duration_ms ELSE 0 END) / 1000.0, 2) AS exec_secs_t7
FROM system.query.history, bounds b
WHERE start_time >= b.t91_start
  AND compute.warehouse_id IS NOT NULL
GROUP BY workspace_id, compute.warehouse_id
ORDER BY queries_t91 DESC
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# W-W06 — Per-warehouse workload drivers (which dashboard / job / app drives the load)
# ---------------------------------------------------------------------------
# W-W04 buckets the client-app mix per warehouse (a category CASE, no entity). W-W06 goes
# one level down: the specific query source (dashboard / job / Genie space / notebook /
# alert / saved query) x client application that drives each warehouse, with count, read
# bytes and total duration, ranked per warehouse and shown as a share of that warehouse's
# duration. Drivers are ranked by execution time (total_exec_secs = total duration minus
# waiting_at_capacity), not total duration: on a queueing warehouse the source that waits
# most can top total duration while reading almost nothing (a victim, not a driver).
# pct_of_warehouse_exec is that share; read_gb_per_query (decimal GB) separates scan-heavy
# drivers from chatty ones. Per-warehouse context on every row: distinct_sources (count of
# distinct sources on the warehouse, before the top-5 cut — 1 on a single-tenant ingestion
# warehouse, where any share threshold fires trivially), material_sources (driver rows with
# >= 5% of the warehouse's execution time — idle saved queries don't count) and
# warehouse_queued_pct (% of the warehouse's queries that waited at capacity, same
# definition as W-W01 queued_query_pct).
# No user identity columns. The scan is bounded to the last 7 days (or the
# lookback if shorter) via max_lookback_days=7, so the executor renders {lookback_days}
# as min(lookback, 7) and the row carries the effective window_days: 30d+ query.history
# aggregations by source timed out live.
W_W06_SQL = """\
WITH agg AS (
  SELECT
    workspace_id,
    compute.warehouse_id AS warehouse_id,
    CASE
      WHEN query_source.job_info.job_id IS NOT NULL                              THEN 'JOB'
      WHEN query_source.dashboard_id IS NOT NULL
        OR query_source.legacy_dashboard_id IS NOT NULL                          THEN 'DASHBOARD'
      WHEN query_source.genie_space_id IS NOT NULL                               THEN 'GENIE_SPACE'
      WHEN query_source.notebook_id IS NOT NULL                                  THEN 'NOTEBOOK'
      WHEN query_source.alert_id IS NOT NULL                                     THEN 'ALERT'
      WHEN query_source.sql_query_id IS NOT NULL                                 THEN 'SQL_QUERY'
      ELSE                                                                            'OTHER'
    END AS source_type,
    COALESCE(
      query_source.job_info.job_id,
      query_source.dashboard_id,
      query_source.legacy_dashboard_id,
      query_source.genie_space_id,
      query_source.notebook_id,
      query_source.alert_id,
      query_source.sql_query_id
    ) AS source_id,
    client_application,
    {lookback_days}                                AS window_days,
    COUNT(*)                                       AS query_count,
    COUNT_IF(waiting_at_capacity_duration_ms > 0)  AS queued_query_count,
    SUM(read_bytes)                                AS total_read_bytes,
    ROUND(SUM(total_duration_ms) / 1000.0, 2)      AS total_duration_secs,
    ROUND(
      SUM(total_duration_ms - COALESCE(waiting_at_capacity_duration_ms, 0)) / 1000.0, 2
    )                                              AS total_exec_secs
  FROM system.query.history
  WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND compute.warehouse_id IS NOT NULL
  GROUP BY ALL
),
ranked AS (
  SELECT
    *,
    SUM(total_duration_secs) OVER w AS warehouse_duration_secs,
    SUM(total_exec_secs)     OVER w AS warehouse_exec_secs,
    SUM(query_count)         OVER w AS warehouse_query_count,
    SUM(queued_query_count)  OVER w AS warehouse_queued_count,
    -- A source is its (type, id); id-less traffic (OTHER) is keyed by client app, so a
    -- single-tenant ingestion warehouse (one connector) counts as 1 source.
    SIZE(COLLECT_SET(
      COALESCE(source_type || ':' || source_id, 'APP:' || COALESCE(client_application, 'unknown'))
    ) OVER w) AS distinct_sources,
    ROW_NUMBER() OVER (
      PARTITION BY workspace_id, warehouse_id ORDER BY total_exec_secs DESC NULLS LAST
    ) AS driver_rank
  FROM agg
  WINDOW w AS (PARTITION BY workspace_id, warehouse_id)
),
shared AS (
  SELECT
    *,
    ROUND(total_exec_secs * 100.0 / NULLIF(warehouse_exec_secs, 0), 1) AS pct_of_warehouse_exec
  FROM ranked
),
ctx AS (
  SELECT
    *,
    -- Driver rows holding >= 5% of the warehouse's execution time: a
    -- warehouse with one connector plus a few idle saved queries reads 1 here even
    -- when distinct_sources is higher.
    COUNT_IF(pct_of_warehouse_exec >= 5) OVER (
      PARTITION BY workspace_id, warehouse_id
    ) AS material_sources
  FROM shared
)
SELECT
  workspace_id,
  warehouse_id,
  driver_rank,
  source_type,
  source_id,
  client_application,
  window_days,
  query_count,
  total_read_bytes,
  total_duration_secs,
  total_exec_secs,
  ROUND(total_read_bytes / 1e9 / NULLIF(query_count, 0), 3)                  AS read_gb_per_query,
  -- Same value under the catalog's canonical OPP-WH-SCAN metric name.
  ROUND(total_read_bytes / 1e9 / NULLIF(query_count, 0), 3)                  AS avg_read_gb_per_query,
  ROUND(total_duration_secs * 100.0 / NULLIF(warehouse_duration_secs, 0), 1) AS pct_of_warehouse_duration,
  pct_of_warehouse_exec,
  distinct_sources,
  material_sources,
  ROUND(warehouse_queued_count * 100.0 / NULLIF(warehouse_query_count, 0), 2) AS warehouse_queued_pct
FROM ctx
-- Top 5 drivers per warehouse and whole warehouses (busiest first), so a 50-row cap
-- covers ~10 warehouses rather than truncating mid-warehouse; the envelope flags
-- limit_reached when more warehouses exist.
WHERE driver_rank <= 5
ORDER BY warehouse_duration_secs DESC NULLS LAST, workspace_id, warehouse_id, driver_rank
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# W-W07 — Warehouse config + change history
# ---------------------------------------------------------------------------
# system.compute.warehouses is slowly-changing: one row per config version keyed by
# change_time. Some sources replicate identical version rows, so versions are
# de-duplicated (SELECT DISTINCT over the scalar columns — tags is a MAP and is not
# selected) before LAG / ROW_NUMBER; otherwise a duplicate would read as a no-op
# "change" and the latest-row pick would be arbitrary. One row per warehouse: the
# current (latest change_time) config, plus counts of size / cluster-bound / auto-stop
# changes in the lookback and the 3 most recent changes as readable strings. Warehouses
# deleted before the window are dropped.
W_W07_SQL = """\
WITH versions AS (
  SELECT DISTINCT
    workspace_id,
    warehouse_id,
    warehouse_name,
    warehouse_type,
    warehouse_size,
    min_clusters,
    max_clusters,
    auto_stop_minutes,
    change_time,
    delete_time
  FROM system.compute.warehouses
),
ordered AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY workspace_id, warehouse_id
      ORDER BY change_time DESC, delete_time DESC NULLS LAST
    ) AS version_rank,
    LAG(warehouse_size)    OVER w AS prev_size,
    LAG(min_clusters)      OVER w AS prev_min_clusters,
    LAG(max_clusters)      OVER w AS prev_max_clusters,
    LAG(auto_stop_minutes) OVER w AS prev_auto_stop_minutes,
    LAG(change_time)       OVER w AS prev_change_time
  FROM versions
  WINDOW w AS (PARTITION BY workspace_id, warehouse_id ORDER BY change_time)
),
changes AS (
  SELECT
    *,
    prev_change_time IS NOT NULL AND change_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS in_window,
    warehouse_size IS DISTINCT FROM prev_size AS size_changed,
    (min_clusters IS DISTINCT FROM prev_min_clusters
      OR max_clusters IS DISTINCT FROM prev_max_clusters) AS clusters_changed,
    auto_stop_minutes IS DISTINCT FROM prev_auto_stop_minutes AS auto_stop_changed
  FROM ordered
)
SELECT
  workspace_id,
  warehouse_id,
  MAX(CASE WHEN version_rank = 1 THEN warehouse_name END)    AS warehouse_name,
  MAX(CASE WHEN version_rank = 1 THEN warehouse_type END)    AS warehouse_type,
  MAX(CASE WHEN version_rank = 1 THEN warehouse_size END)    AS warehouse_size,
  MAX(CASE WHEN version_rank = 1 THEN min_clusters END)      AS min_clusters,
  MAX(CASE WHEN version_rank = 1 THEN max_clusters END)      AS max_clusters,
  MAX(CASE WHEN version_rank = 1 THEN auto_stop_minutes END) AS auto_stop_minutes,
  MAX(CASE WHEN version_rank = 1 THEN delete_time END)       AS delete_time,
  MAX(change_time)                                           AS last_change_time,
  COUNT_IF(in_window AND size_changed)                       AS size_changes_in_window,
  COUNT_IF(in_window AND clusters_changed)                   AS cluster_changes_in_window,
  COUNT_IF(in_window AND auto_stop_changed)                  AS auto_stop_changes_in_window,
  SLICE(
    REVERSE(ARRAY_SORT(COLLECT_LIST(
      CASE WHEN in_window AND (size_changed OR clusters_changed OR auto_stop_changed) THEN
        CONCAT(
          CAST(change_time AS STRING), ' ',
          'size ', COALESCE(prev_size, '?'), '->', COALESCE(warehouse_size, '?'),
          ', clusters ', COALESCE(CAST(prev_min_clusters AS STRING), '?'), '-',
          COALESCE(CAST(prev_max_clusters AS STRING), '?'), '->',
          COALESCE(CAST(min_clusters AS STRING), '?'), '-',
          COALESCE(CAST(max_clusters AS STRING), '?'),
          ', auto_stop ', COALESCE(CAST(prev_auto_stop_minutes AS STRING), '?'), '->',
          COALESCE(CAST(auto_stop_minutes AS STRING), '?')
        )
      END
    ))),
    1, 3
  )                                                          AS recent_changes
FROM changes
GROUP BY workspace_id, warehouse_id
HAVING MAX(CASE WHEN version_rank = 1 THEN delete_time END) IS NULL
    OR MAX(CASE WHEN version_rank = 1 THEN delete_time END) >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
ORDER BY last_change_time DESC NULLS LAST
LIMIT {result_limit}
"""


WAREHOUSE_PACK = QueryPack(
    pack_id="warehouse",
    domain="warehouse",
    name="SQL Warehouse Operational Framings",
    description=(
        "Warehouse utilization bands, auto-stop waste, query-load buckets, "
        "client-app mix, T7/T28/T91 trend windows, per-warehouse DBU and workload "
        "drivers, and warehouse config + change history over public system tables."
    ),
    queries=(
        SystemQuery(
            query_id="W-W01",
            name="Warehouse Utilization Bands",
            description=(
                "Classifies each warehouse into Offline / No-utilization / "
                "Under-utilized / Optimal / High-concurrency / Resource-starved / "
                "'Serverless — pay per use' from a running-time vs query-busy-time "
                "utilization ratio. SERVERLESS warehouses skip the ratio bands "
                "(billing is per-query, not per running second) and receive "
                "'Serverless — pay per use' unless capacity queueing is measured "
                "(queued_query_pct >= 10), in which case they are 'Resource-starved'. "
                "For classic/pro: above Optimal the ratio measures concurrency; "
                "Resource-starved additionally requires measured capacity queueing. "
                "utilization_ratio = summed query execution seconds / warehouse "
                "running seconds; overlapping queries each count, so a value > 1.0 "
                "is the average number of concurrently executing queries while the "
                "warehouse was up (e.g. 2.74 ~ 2.7 queries at once) — NOT more than "
                "100% of capacity. Capacity saturation is queued_query_pct / "
                "avg_capacity_wait_secs, not the ratio. "
                "Full-day window (today excluded, like W-W02): warehouse_dbus is "
                "the warehouse's DBU over the lookback's full days and reconciles "
                "with vt-warehouse-dbu / data.facts.top_warehouses."
            ),
            sql_template=W_W01_SQL,
            required_tables=(
                "system.compute.warehouse_events",
                "system.query.history",
                "system.compute.warehouses",  # LEFT-joined for warehouse_type
                "system.billing.usage",  # LEFT-joined for per-warehouse warehouse_dbus
            ),
            domain="warehouse",
            required=False,  # depends on warehouse_events; degrade gracefully
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Warehouse utilization bands from a running/busy ratio.",
                output_hint=(
                    "One row per warehouse with ratio, queued_query_pct, "
                    "avg_capacity_wait_secs and band. utilization_ratio > 1 = "
                    "average concurrent queries, not over-capacity. Window = "
                    "lookback full days (today excluded)."
                ),
                tags=("warehouse", "utilization", "rightsizing"),
            ),
        ),
        SystemQuery(
            query_id="W-W02",
            name="Auto-Stop Efficiency / Waste",
            description=(
                "Warehouse running-time spent with zero queries (idle running) "
                "— candidate for a tighter auto-stop setting. Also carries the "
                "warehouse's billed DBU (warehouse_dbus) and an estimated idle-DBU "
                "figure (est_idle_dbus, a list-price DBU estimate capped at "
                "warehouse_dbus; NULL for SERVERLESS warehouses, which auto-suspend "
                "and do not bill idle time the way classic/pro do). "
                "Uses a full-day window (>= window_start AND < CURRENT_DATE) so "
                "est_idle_dbus is deterministic across multiple runs on the same day."
            ),
            sql_template=W_W02_SQL,
            required_tables=(
                "system.compute.warehouse_events",
                "system.query.history",
                "system.compute.warehouses",  # LEFT-joined for warehouse_type
                "system.billing.usage",  # LEFT-joined for per-warehouse warehouse_dbus
            ),
            domain="warehouse",
            required=False,  # depends on warehouse_events; degrade gracefully
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Idle running-time, auto-stop waste percentage, and per-warehouse DBU.",
                output_hint=(
                    "Per (workspace_id, warehouse_id): running vs idle-running hours, "
                    "warehouse_dbus, and est_idle_dbus (estimate; NULL on SERVERLESS). "
                    "Window = N full days before today (excludes today's partial data)."
                ),
                tags=("warehouse", "auto_stop", "waste", "dbu"),
            ),
        ),
        SystemQuery(
            query_id="W-W03",
            name="Query-Load Buckets",
            description=(
                "Per warehouse-day query volume bucketed 0-10 / 10-100 / "
                "100-1000 / 1000+."
            ),
            sql_template=W_W03_SQL,
            required_tables=("system.query.history",),
            domain="warehouse",
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Query-load buckets per warehouse-day.",
                output_hint="Per warehouse-day count and load bucket.",
                tags=("warehouse", "load", "concurrency"),
            ),
        ),
        SystemQuery(
            query_id="W-W04",
            name="Client-App Mix",
            description=(
                "Query volume by client-application category (dashboards, "
                "jobs, dbt, notebooks, external BI, SQL editor, API/SDK)."
            ),
            sql_template=W_W04_SQL,
            required_tables=("system.query.history",),
            domain="warehouse",
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Client-application mix per warehouse.",
                output_hint="Per warehouse x app-category query counts.",
                tags=("warehouse", "client_app", "workload_mix"),
            ),
        ),
        SystemQuery(
            query_id="W-W05",
            name="Trend Windows T7/T28/T91",
            description=(
                "Query volume and execution-time trend across the 7-, 28-, and "
                "91-day windows for each warehouse."
            ),
            sql_template=W_W05_SQL,
            required_tables=("system.query.history",),
            domain="warehouse",
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="T7/T28/T91 query-volume and exec-time trend.",
                output_hint="Per-warehouse counts and exec-secs per window.",
                tags=("warehouse", "trend", "t7_t28_t91"),
            ),
        ),
        SystemQuery(
            query_id="W-W06",
            name="Warehouse Workload Drivers",
            description=(
                "Per warehouse, the top query sources (dashboard / job / Genie space / "
                "notebook / alert / saved query) and client applications by execution "
                "time (total duration minus capacity wait), with query count, read bytes, "
                "GB read per query, and per-warehouse distinct_sources / "
                "material_sources / warehouse_queued_pct. Bounded to the last 7 days "
                "(window_days carries the effective window)."
            ),
            sql_template=W_W06_SQL,
            required_tables=("system.query.history",),
            domain="warehouse",
            max_lookback_days=7,  # bounded scan; 30d+ by-source aggregation timed out
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Top workload drivers (source + client app) per warehouse.",
                output_hint=(
                    "Per warehouse: ranked source_type/source_id x client_application "
                    "with query_count, total_read_bytes, read_gb_per_query (= avg_read_gb_per_query), "
                    "total_duration_secs / total_exec_secs and their shares "
                    "(pct_of_warehouse_duration / pct_of_warehouse_exec); per-warehouse "
                    "distinct_sources, material_sources (>= 5% of exec time) and "
                    "warehouse_queued_pct on every row; "
                    "window_days = effective window (<= 7)."
                ),
                tags=("warehouse", "workload_drivers", "query_source"),
            ),
        ),
        SystemQuery(
            query_id="W-W07",
            name="Warehouse Config & Change History",
            description=(
                "Current configuration per warehouse (type, size, min/max clusters, "
                "auto-stop minutes) and the size / cluster-bound / auto-stop changes "
                "recorded in the lookback, with the 3 most recent changes."
            ),
            sql_template=W_W07_SQL,
            required_tables=("system.compute.warehouses",),
            domain="warehouse",
            required=False,  # config dim may be unavailable; degrade gracefully
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Current warehouse config and recent size/cluster/auto-stop changes.",
                output_hint=(
                    "One row per (workspace_id, warehouse_id): current warehouse_size, "
                    "min/max_clusters, auto_stop_minutes, last_change_time, change "
                    "counts in the window, and recent_changes (latest first)."
                ),
                tags=("warehouse", "config", "change_history", "rightsizing"),
            ),
        ),
    ),
    gating_products=frozenset({"SQL"}),
)
