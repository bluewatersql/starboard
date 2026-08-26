# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""SQL warehouse (DBSQL) operational framings query pack.

Encodes the categorical *framings* an expert uses to reason about a SQL
warehouse portfolio, expressed entirely over PUBLIC Databricks system tables:

- **Utilization bands** — Offline / No-utilization / Under-utilized / Optimal /
  Resource-starved, from a utilization ratio (query busy-time vs warehouse
  running-time) derived from ``system.compute.warehouse_events`` +
  ``system.query.history``.
- **Auto-stop efficiency / waste** — warehouse running-time with zero query
  activity (candidate for a tighter auto-stop), from running intervals in
  ``warehouse_events`` left-joined to query starts.
- **Query-load buckets** — 0-10 / 10-100 / 100-1000 / 1000+ queries per
  warehouse-day.
- **Client-app mix** — dashboards / jobs / dbt / notebooks / external BI / SQL
  editor / API-SDK, via a CASE over ``client_application``.
- **Trend windows** — T7 / T28 / T91 query volume and execution-time trend.

All queries use DBU / duration / count metrics only; no dollar computations.
Any cost interpretation layered on top of these DBU figures is a **list-price
estimate** (public ``system.billing`` reflects list price x usage), never a
contract-accurate or discount-adjusted figure.

Column names verified against current Databricks system-table docs (2026-08):
- ``system.compute.warehouse_events``: ``warehouse_id``, ``event_type``
  (STARTING / RUNNING / SCALED_UP / SCALED_DOWN / STOPPING / STOPPED),
  ``cluster_count``, ``event_time``.
- ``system.query.history``: ``compute.warehouse_id``, ``start_time``,
  ``execution_duration_ms``, ``statement_id``, ``executed_by``,
  ``client_application``.
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
#: above it is "Resource-starved".
OPTIMAL_MAX = 0.80


def classify_utilization_band(
    *,
    running_seconds: float | None,
    total_queries: int,
    utilization_ratio: float | None,
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

    Returns:
        One of ``Offline`` / ``No-utilization`` / ``Under-utilized`` /
        ``Optimal`` / ``Resource-starved``.
    """
    if not running_seconds:
        return "Offline"
    if not total_queries or utilization_ratio is None:
        return "No-utilization"
    if utilization_ratio < UNDER_UTILIZED_MAX:
        return "Under-utilized"
    if utilization_ratio <= OPTIMAL_MAX:
        return "Optimal"
    return "Resource-starved"


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
# a public proxy for how hard the warehouse worked while it was up.
W_W01_SQL = """\
WITH events AS (
  SELECT
    warehouse_id,
    event_type,
    event_time,
    LEAD(event_time) OVER (PARTITION BY warehouse_id ORDER BY event_time) AS next_event_time
  FROM system.compute.warehouse_events
  WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
),
running AS (
  SELECT
    warehouse_id,
    SUM(
      CASE
        WHEN event_type IN ('STARTING', 'RUNNING', 'SCALED_UP', 'SCALED_DOWN')
        THEN DATEDIFF(SECOND, event_time, COALESCE(next_event_time, CURRENT_TIMESTAMP()))
        ELSE 0
      END
    ) AS running_seconds
  FROM events
  GROUP BY warehouse_id
),
query_load AS (
  SELECT
    compute.warehouse_id                      AS warehouse_id,
    COUNT(*)                                  AS total_queries,
    ROUND(SUM(execution_duration_ms) / 1000.0, 2) AS busy_seconds
  FROM system.query.history
  WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND compute.warehouse_id IS NOT NULL
  GROUP BY compute.warehouse_id
)
SELECT
  COALESCE(r.warehouse_id, q.warehouse_id)          AS warehouse_id,
  COALESCE(r.running_seconds, 0)                    AS running_seconds,
  COALESCE(q.total_queries, 0)                      AS total_queries,
  ROUND(TRY_DIVIDE(q.busy_seconds, r.running_seconds), 4) AS utilization_ratio,
  CASE
    WHEN COALESCE(r.running_seconds, 0) = 0                   THEN 'Offline'
    WHEN COALESCE(q.total_queries, 0) = 0                     THEN 'No-utilization'
    -- A NULL ratio (e.g. busy_seconds is NULL) never satisfies the < / <=
    -- comparisons below (SQL 3-valued logic), so without this explicit branch
    -- such a row would fall through to 'Resource-starved'. Map it to
    -- 'No-utilization' to match the Python classify_utilization_band labeler.
    WHEN TRY_DIVIDE(q.busy_seconds, r.running_seconds) IS NULL THEN 'No-utilization'
    WHEN TRY_DIVIDE(q.busy_seconds, r.running_seconds) < 0.30 THEN 'Under-utilized'
    WHEN TRY_DIVIDE(q.busy_seconds, r.running_seconds) <= 0.80 THEN 'Optimal'
    ELSE                                                           'Resource-starved'
  END                                               AS utilization_band
FROM running r
FULL OUTER JOIN query_load q ON r.warehouse_id = q.warehouse_id
ORDER BY running_seconds DESC NULLS LAST
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# W-W02 — Auto-stop efficiency / waste (running with no queries)
# ---------------------------------------------------------------------------
W_W02_SQL = """\
WITH running_intervals AS (
  SELECT
    warehouse_id,
    event_time                                                                       AS interval_start,
    LEAD(event_time) OVER (PARTITION BY warehouse_id ORDER BY event_time)            AS interval_end
  FROM system.compute.warehouse_events
  WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND event_type IN ('STARTING', 'RUNNING', 'SCALED_UP', 'SCALED_DOWN')
),
interval_activity AS (
  SELECT
    ri.warehouse_id,
    DATEDIFF(SECOND, ri.interval_start, COALESCE(ri.interval_end, CURRENT_TIMESTAMP())) AS interval_seconds,
    COUNT(qh.statement_id)                                                              AS query_count
  FROM running_intervals ri
  LEFT JOIN system.query.history qh
         ON qh.compute.warehouse_id = ri.warehouse_id
        AND qh.start_time >= ri.interval_start
        AND qh.start_time <  COALESCE(ri.interval_end, CURRENT_TIMESTAMP())
        AND qh.start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY ri.warehouse_id, ri.interval_start, ri.interval_end
)
SELECT
  warehouse_id,
  ROUND(SUM(interval_seconds) / 3600.0, 2)                                          AS running_hours,
  ROUND(SUM(CASE WHEN query_count = 0 THEN interval_seconds ELSE 0 END) / 3600.0, 2) AS idle_running_hours,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN query_count = 0 THEN interval_seconds ELSE 0 END),
      SUM(interval_seconds)
    ) * 100,
    1
  )                                                                                  AS auto_stop_waste_pct
FROM interval_activity
GROUP BY warehouse_id
HAVING running_hours > 0
ORDER BY idle_running_hours DESC
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# W-W03 — Query-load buckets (per warehouse-day)
# ---------------------------------------------------------------------------
W_W03_SQL = """\
WITH daily AS (
  SELECT
    compute.warehouse_id AS warehouse_id,
    DATE(start_time)     AS query_date,
    COUNT(*)             AS query_count
  FROM system.query.history
  WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND compute.warehouse_id IS NOT NULL
  GROUP BY compute.warehouse_id, DATE(start_time)
)
SELECT
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
GROUP BY compute.warehouse_id
ORDER BY queries_t91 DESC
LIMIT {result_limit}
"""


WAREHOUSE_PACK = QueryPack(
    pack_id="warehouse",
    domain="warehouse",
    name="SQL Warehouse Operational Framings",
    description=(
        "Warehouse utilization bands, auto-stop waste, query-load buckets, "
        "client-app mix, and T7/T28/T91 trend windows over public system tables."
    ),
    queries=(
        SystemQuery(
            query_id="W-W01",
            name="Warehouse Utilization Bands",
            description=(
                "Classifies each warehouse into Offline / No-utilization / "
                "Under-utilized / Optimal / Resource-starved from a "
                "running-time vs query-busy-time utilization ratio."
            ),
            sql_template=W_W01_SQL,
            required_tables=(
                "system.compute.warehouse_events",
                "system.query.history",
            ),
            domain="warehouse",
            required=False,  # depends on warehouse_events; degrade gracefully
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Warehouse utilization bands from a running/busy ratio.",
                output_hint="One row per warehouse with ratio and band.",
                tags=("warehouse", "utilization", "rightsizing"),
            ),
        ),
        SystemQuery(
            query_id="W-W02",
            name="Auto-Stop Efficiency / Waste",
            description=(
                "Warehouse running-time spent with zero queries (idle running) "
                "— candidate for a tighter auto-stop setting."
            ),
            sql_template=W_W02_SQL,
            required_tables=(
                "system.compute.warehouse_events",
                "system.query.history",
            ),
            domain="warehouse",
            required=False,  # depends on warehouse_events; degrade gracefully
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Idle running-time and auto-stop waste percentage.",
                output_hint="Per-warehouse running vs idle-running hours.",
                tags=("warehouse", "auto_stop", "waste"),
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
    ),
    gating_products=frozenset({"SQL"}),
)
