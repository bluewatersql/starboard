"""MLflow discovery query pack.\n\nCovers experiment health, run patterns, user activity, and lifecycle."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

_QUERIES = [
    SystemQuery(
        query_id="P-MLF01", name="Experiment Activity Overview",
        description=(
            "Experiment inventory with run counts, timestamps, and daily "
            "run volume within the lookback window. Consolidates former "
            "P-MLF03 (daily run volume by workspace) into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt),
experiment_info AS (
  SELECT workspace_id, experiment_id, name AS experiment_name,
    create_time, update_time, delete_time
  FROM system.mlflow.experiments_latest
),
run_stats AS (
  SELECT experiment_id, workspace_id,
    COUNT(*) AS run_count,
    COUNT_IF(status = 'FINISHED') AS finished_runs,
    COUNT_IF(status = 'FAILED') AS failed_runs,
    MIN(start_time) AS first_run, MAX(start_time) AS last_run
  FROM system.mlflow.runs_latest, cutoff
  WHERE start_time >= cutoff.dt
  GROUP BY experiment_id, workspace_id
)
SELECT e.workspace_id, e.experiment_id, e.experiment_name,
  e.create_time, e.update_time, e.delete_time,
  COALESCE(rs.run_count, 0) AS run_count,
  COALESCE(rs.finished_runs, 0) AS finished_runs,
  COALESCE(rs.failed_runs, 0) AS failed_runs,
  rs.first_run, rs.last_run
FROM experiment_info e
LEFT JOIN run_stats rs USING (workspace_id, experiment_id)
ORDER BY e.update_time DESC
LIMIT {result_limit}""",
        required_tables=("system.mlflow.experiments_latest", "system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Experiment inventory with run counts and health metrics", output_hint="Experiments ranked by last update with run stats"),
    ),
    SystemQuery(
        query_id="P-MLF02", name="Active vs Soft-Deleted Experiments",
        description="Active vs soft-deleted experiment summary",
        sql_template="""\
SELECT IF(delete_time IS NULL, 'ACTIVE', 'SOFT_DELETED') AS experiment_state,
  COUNT(*) AS num_experiments
FROM system.mlflow.experiments_latest
GROUP BY IF(delete_time IS NULL, 'ACTIVE', 'SOFT_DELETED')""",
        required_tables=("system.mlflow.experiments_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.GOVERNANCE,
        metadata=QueryMetadata(summary="Active vs soft-deleted experiment summary", output_hint="Experiment state counts"),
    ),
    SystemQuery(
        query_id="P-MLF04", name="Experiment Reliability and Noise",
        description=(
            "Top experiments by run count with success ratio. Includes "
            "an is_noisy flag for experiments with 50+ runs and <90% success. "
            "Consolidates former P-MLF05 into one query."
        ),
        sql_template="""\
WITH latest_experiments AS (
  SELECT experiment_id, name AS experiment_name FROM system.mlflow.experiments_latest
)
SELECT le.experiment_name, r.experiment_id,
  ROUND(AVG(IF(r.status = 'FINISHED', 1.0, 0.0)), 4) AS success_ratio,
  COUNT(*) AS run_count,
  IF(COUNT(*) >= 50 AND AVG(IF(r.status = 'FINISHED', 1.0, 0.0)) < 0.9, true, false) AS is_noisy
FROM system.mlflow.runs_latest r
LEFT JOIN latest_experiments le USING (experiment_id)
WHERE r.status IS NOT NULL
GROUP BY le.experiment_name, r.experiment_id
ORDER BY run_count DESC
LIMIT 100""",
        required_tables=("system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Top experiments by run count with success ratio and noise flag", output_hint="Experiments ranked by run count with noisy flag"),
    ),
    SystemQuery(
        query_id="P-MLF06", name="Long-Running Runs",
        description="Longest-running experiment runs",
        sql_template="""\
WITH latest_experiments AS (
  SELECT experiment_id, name AS experiment_name FROM system.mlflow.experiments_latest
)
SELECT le.experiment_name, r.experiment_id, r.run_id, r.run_name, r.status,
  TIMESTAMPDIFF(MINUTE, r.start_time, r.end_time) AS run_length_minutes
FROM system.mlflow.runs_latest r
LEFT JOIN latest_experiments le USING (experiment_id)
WHERE r.end_time IS NOT NULL
ORDER BY run_length_minutes DESC
LIMIT {result_limit}""",
        required_tables=("system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.DEEP_DIVE, category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(summary="Longest-running experiment runs", output_hint="Runs ranked by duration"),
    ),
    SystemQuery(
        query_id="P-MLF07", name="Top Users by Run Volume",
        description="Most active users by run volume and avg duration",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT created_by, COUNT(*) AS num_runs,
  ROUND(AVG(TIMESTAMPDIFF(MINUTE, start_time, end_time)), 2) AS avg_run_minutes
FROM system.mlflow.runs_latest, cutoff
WHERE start_time >= cutoff.dt AND end_time IS NOT NULL
GROUP BY created_by
ORDER BY num_runs DESC
LIMIT {result_limit}""",
        required_tables=("system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.DEEP_DIVE, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Most active users by run volume and avg duration", output_hint="Users ranked by run count"),
    ),
    SystemQuery(
        query_id="P-MLF08", name="Experiment Usage Trend",
        description="Per-experiment daily run trend",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt),
latest_experiments AS (
  SELECT experiment_id, name AS experiment_name FROM system.mlflow.experiments_latest
)
SELECT le.experiment_name, r.experiment_id, DATE(r.start_time) AS run_date,
  COUNT(*) AS runs_started, COUNT_IF(r.status = 'FINISHED') AS finished_runs
FROM system.mlflow.runs_latest r, cutoff
LEFT JOIN latest_experiments le USING (experiment_id)
WHERE r.start_time >= cutoff.dt
GROUP BY le.experiment_name, r.experiment_id, DATE(r.start_time)
ORDER BY run_date DESC, experiment_name
LIMIT {result_limit}""",
        required_tables=("system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.DEEP_DIVE, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Per-experiment daily run trend", output_hint="Daily run trend per experiment"),
    ),
]

MLFLOW_PACK = QueryPack(
    pack_id="mlflow", domain="mlflow", name="MLflow",
    description="MLflow experiment and model lifecycle health",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"AI_RUNTIME", "FEATURE_ENGINEERING", "MODEL_SERVING"}),
)
