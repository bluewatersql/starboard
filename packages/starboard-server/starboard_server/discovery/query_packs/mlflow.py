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
        query_id="P-MLF01", name="Experiments with Run Counts",
        description="All experiments with run counts and timestamps",
        sql_template="""\
SELECT e.workspace_id, e.experiment_id, e.name AS experiment_name, e.create_time, e.update_time,
  e.delete_time, COUNT(r.run_id) AS run_count
FROM system.mlflow.experiments_latest e
LEFT JOIN system.mlflow.runs_latest r USING (experiment_id)
GROUP BY e.workspace_id, e.experiment_id, e.name, e.create_time, e.update_time, e.delete_time
ORDER BY e.update_time DESC
LIMIT {result_limit}""",
        required_tables=("system.mlflow.experiments_latest", "system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="All experiments with run counts and timestamps", output_hint="Experiments ranked by last update"),
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
        query_id="P-MLF03", name="Runs by Workspace and Day",
        description="Daily run volume by workspace",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT workspace_id, DATE(start_time) AS run_date, COUNT(*) AS runs_started,
  COUNT_IF(status = 'FINISHED') AS finished_runs, COUNT_IF(status = 'FAILED') AS failed_runs
FROM system.mlflow.runs_latest, cutoff
WHERE start_time >= cutoff.dt
GROUP BY workspace_id, DATE(start_time)
ORDER BY run_date DESC, workspace_id
LIMIT {result_limit}""",
        required_tables=("system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Daily run volume by workspace", output_hint="Daily run counts"),
    ),
    SystemQuery(
        query_id="P-MLF04", name="Experiment Reliability (Success Ratio)",
        description="Top experiments by run count with success ratio",
        sql_template="""\
WITH latest_experiments AS (
  SELECT experiment_id, name AS experiment_name FROM system.mlflow.experiments_latest
)
SELECT le.experiment_name, r.experiment_id,
  ROUND(AVG(IF(r.status = 'FINISHED', 1.0, 0.0)), 4) AS success_ratio, COUNT(*) AS run_count
FROM system.mlflow.runs_latest r
LEFT JOIN latest_experiments le USING (experiment_id)
WHERE r.status IS NOT NULL
GROUP BY le.experiment_name, r.experiment_id
ORDER BY run_count DESC
LIMIT 100""",
        required_tables=("system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Top experiments by run count with success ratio", output_hint="Experiments ranked by run count"),
    ),
    SystemQuery(
        query_id="P-MLF05", name="Noisy Experiments (Low Success, Many Runs)",
        description="Experiments with 50+ runs and less than 90 pct success",
        sql_template="""\
WITH latest_experiments AS (
  SELECT experiment_id, name AS experiment_name FROM system.mlflow.experiments_latest
)
SELECT le.experiment_name, r.experiment_id,
  ROUND(AVG(IF(r.status = 'FINISHED', 1.0, 0.0)), 4) AS success_ratio, COUNT(*) AS run_count
FROM system.mlflow.runs_latest r
LEFT JOIN latest_experiments le USING (experiment_id)
WHERE r.status IS NOT NULL
GROUP BY le.experiment_name, r.experiment_id
HAVING run_count >= 50 AND AVG(IF(r.status = 'FINISHED', 1.0, 0.0)) < 0.9
ORDER BY success_ratio ASC, run_count DESC
LIMIT {result_limit}""",
        required_tables=("system.mlflow.runs_latest",), domain="mlflow", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(summary="Experiments with 50+ runs and less than 90% success rate", output_hint="Noisy experiments ranked by success ratio"),
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
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
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
