---
domain: mlflow
system_tables:
- system.mlflow.experiments_latest
- system.mlflow.run_metrics_history
- system.mlflow.runs_latest
---

# Reference: mlflow

> Curated Databricks system-table knowledge for the `mlflow` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.mlflow.experiments_latest
System table in the `mlflow` domain. See query packs for vetted SQL over this table.

### system.mlflow.run_metrics_history
System table in the `mlflow` domain. See query packs for vetted SQL over this table.

### system.mlflow.runs_latest
System table in the `mlflow` domain. See query packs for vetted SQL over this table.

## Nuance

_No curated nuance entries for this domain yet._

## Codebook

### system.mlflow.runs_latest.status
DOC_TYPE: codebook
CODE_KEY: system.mlflow.runs_latest.status
SUMMARY: MLflow run status (from MLflow RunStatus enum).
VALUES:
- SCHEDULED
- RUNNING
- FINISHED
- FAILED
- KILLED
SQL_HINT: For experiment health, group by status; treat KILLED as user/system interruption distinct from FAILED.

## Facets

### system.mlflow.runs_latest.status
SCHEDULED,RUNNING,FINISHED,FAILED,KILLED
