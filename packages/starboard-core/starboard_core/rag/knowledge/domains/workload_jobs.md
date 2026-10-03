---
domain: workload_jobs
system_tables:
- system.lakeflow.job_run_timeline
- system.lakeflow.job_task_run_timeline
- system.lakeflow.job_tasks
- system.lakeflow.jobs
- system.query.history
---

# Reference: workload_jobs

> Curated Databricks system-table knowledge for the `workload_jobs` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.lakeflow.job_run_timeline
System table in the `workload_jobs` domain. See query packs for vetted SQL over this table.

### system.lakeflow.job_task_run_timeline
System table in the `workload_jobs` domain. See query packs for vetted SQL over this table.

### system.lakeflow.job_tasks
System table in the `workload_jobs` domain. See query packs for vetted SQL over this table.

### system.lakeflow.jobs
System table in the `workload_jobs` domain. See query packs for vetted SQL over this table.

### system.query.history
System table in the `workload_jobs` domain. See query packs for vetted SQL over this table.

## Nuance

### tags_normalization_attribution | recipe
DOC_TYPE: recipe
TOPIC: tags_normalization_attribution
GOAL: Use tags for cost allocation and reporting reliably.
STEPS:
1) Extract tags (MAP) and normalize keys and values:
   - lower(trim(key)), lower(trim(value))
   - map known aliases ("team", "owner", "cost_center") -> canonical_key
2) Apply precedence rules:
   - resource tags > job tags > workspace defaults
3) Fill missing tags with 'unknown' bucket to preserve totals.
OUTPUT: canonical_tags_map
PITFALL: Key casing and alias drift causes fragmented grouping (Team vs team vs TEAM).

### tags_normalization_attribution | template_sql
DOC_TYPE: template_sql
TOPIC: tags_normalization_attribution
TEMPLATE:
-- Normalize MAP tags into canonical (key,value) rows
WITH raw AS (
  SELECT {{resource_id}} AS resource_id, tags
  FROM {{source_table}}
), exploded AS (
  SELECT resource_id, lower(trim(k)) AS raw_key, lower(trim(v)) AS raw_value
  FROM raw
  LATERAL VIEW explode(tags) t AS k, v
)
SELECT
  resource_id,
  CASE
    WHEN raw_key IN ('team','owner_team','org_team') THEN 'team'
    WHEN raw_key IN ('cost_center','costcentre','cc') THEN 'cost_center'
    ELSE raw_key
  END AS canonical_key,
  raw_value AS canonical_value
FROM exploded;
NOTES:
- Join canonical tags back to cost/usage after normalization.
- Extend alias mapping over time as needed.

### job_run_lifecycle_status | rule
DOC_TYPE: rule
TOPIC: job_run_lifecycle_status
RULE: Job runs in system.lakeflow.job_run_timeline have multiple states. Distinguish lifecycle_state for accurate cost and success rate analysis.
KEY STATES:
- TERMINATED: run completed (check result_state for SUCCESS/FAILED)
- RUNNING: currently executing
- PENDING: queued but not started
- SKIPPED: skipped due to schedule or dependency
GUIDELINES:
- Filter to lifecycle_state = 'TERMINATED' for historical success rate analysis.
- Check result_state = 'SUCCESS' for successful runs only.
- Duration calculations require both start_time and end_time (only valid for TERMINATED).
PITFALL: Including RUNNING/PENDING runs in success rate calculations produces invalid metrics.
OUTPUT: valid_job_run_metrics

### scd2_current_state_queries | template_sql
DOC_TYPE: template_sql
TOPIC: scd2_current_state_queries
GOAL: Get current state from SCD2 system tables (e.g., lakeflow.jobs).
TEMPLATE:
WITH ranked AS (
  SELECT *,
         row_number() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) AS rn
  FROM system.lakeflow.jobs
)
SELECT *
FROM ranked
WHERE rn = 1;
PITFALL:
- Forgetting to use change_time ordering yields duplicate job configurations.
- Include delete_time logic if you only want active resources.

## Codebook

### system.lakeflow.job_run_timeline.trigger_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.trigger_type
SUMMARY: What triggered the job run (schedule/continuous/file/onetime).
VALUES:
- CONTINUOUS
- CRON
- FILE_ARRIVAL
- ONETIME
- ONETIME_RETRY
SQL_HINT: Use trigger_type to segment reliability/latency (CRON vs FILE_ARRIVAL). For retries, ONETIME_RETRY often implies upstream transient failure or rate limiting.

### system.lakeflow.job_run_timeline.result_state
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.result_state
SUMMARY: Outcome classification for a job/task run.
VALUES:
- SUCCEEDED
- FAILED
- SKIPPED
- CANCELLED
- TIMED_OUT
- ERROR
- BLOCKED
- NULL (only for intermediate hourly slices of long runs; final slice carries the result)
SQL_HINT: For run-level outcome counts, filter to the terminal slice: result_state IS NOT NULL (or pick the max(period_end_time) per run_id).

### system.lakeflow.job_run_timeline.run_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.run_type
SUMMARY: Shape of a run (standard job run vs submitted run vs notebook workflow run).
VALUES:
- JOB_RUN
- SUBMIT_RUN
- WORKFLOW_RUN
SQL_HINT: For operational dashboards, JOB_RUN is the common baseline. WORKFLOW_RUN may appear only in job_run_timeline and can be missing from other jobs tables; treat as a special class when joining dimensions.

### system.lakeflow.job_run_timeline.termination_code + termination_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.termination_code + termination_type
SUMMARY: Termination codes/types vary and evolve; treat as drilldown facets and build fallbacks when fields are NULL (older rows).
PATTERNS/EXAMPLES (non-exhaustive):
- termination_type='SUCCESS' AND termination_code IS NULL
- termination_type='CLIENT_ERROR' AND termination_code LIKE 'COMMAND_EXECUTION_ERROR%'
- termination_type='SERVICE_ERROR' AND termination_code LIKE 'INTERNAL_ERROR%'
SQL_HINT: If termination_code is missing (older data), derive status from result_state; otherwise use termination_type as primary and termination_code as detailed reason.

### system.lakeflow.job_run_timeline.termination_code
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.termination_code
SUMMARY: Root termination reason used for triage (quota limits, cluster failures, auth, etc.).
VALUES:
- SUCCESS
- CANCELLED
- SKIPPED
- DRIVER_ERROR
- CLUSTER_ERROR
- REPOSITORY_CHECKOUT_FAILED
- INVALID_CLUSTER_REQUEST
- WORKSPACE_RUN_LIMIT_EXCEEDED
- FEATURE_DISABLED
- CLUSTER_REQUEST_LIMIT_EXCEEDED
- STORAGE_ACCESS_ERROR
- RUN_EXECUTION_ERROR
- UNAUTHORIZED_ERROR
- LIBRARY_INSTALLATION_ERROR
- MAX_CONCURRENT_RUNS_EXCEEDED
- MAX_SPARK_CONTEXTS_EXCEEDED
- RESOURCE_NOT_FOUND
- INVALID_RUN_CONFIGURATION
- CLOUD_FAILURE
- MAX_JOB_QUEUE_SIZE_EXCEEDED
SQL_HINT: For reliability dashboards, group by termination_code and surface top-N. Distinguish user cancel vs platform cancel: termination_code=CANCELLED can mean platform cancellation (exceeded max duration, etc.) while result_state=CANCELLED reflects the run’s outcome state.

### system.lakeflow.job_run_timeline.trigger_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.trigger_type
SUMMARY: What triggered the job run.
VALUES:
- CONTINUOUS
- CRON
- FILE_ARRIVAL
- ONETIME
- ONETIME_RETRY
SQL_HINT: For reliability analysis, group failures by trigger_type; CRON/FILE_ARRIVAL often correlate with bursty concurrency and queue time.

### system.lakeflow.job_run_timeline.run_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.run_type
SUMMARY: Job run category.
VALUES:
- JOB_RUN
- SUBMIT_RUN
- WORKFLOW_RUN
SQL_HINT: WORKFLOW_RUN indicates orchestration-style runs (multi-task). SUBMIT_RUN tends to be ad hoc; consider separating in reporting.

### system.lakeflow.job_run_timeline.result_state
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.result_state (also in system.lakeflow.job_task_run_timeline.result_state)
SUMMARY: Outcome state for job runs and task runs. Important for filtering "failed" vs "blocked" vs "intermediate" slices.
VALUES:
- SUCCEEDED
- FAILED
- SKIPPED
- CANCELLED
- TIMED_OUT
- ERROR
- BLOCKED
- NULL
SQL_HINT: When aggregating outcomes, treat result_state=NULL as an intermediate slice for a long-running run (only the final slice has the terminal result_state).

### system.lakeflow.job_run_timeline.termination_code
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.job_run_timeline.termination_code (also in system.lakeflow.job_task_run_timeline.termination_code)
SUMMARY: Termination reason category. Useful to separate user-cancel, platform limits, infra faults, storage/security errors.
VALUES:
- SUCCESS
- CANCELLED
- SKIPPED
- DRIVER_ERROR
- CLUSTER_ERROR
- REPOSITORY_CHECKOUT_FAILED
- INVALID_CLUSTER_REQUEST
- WORKSPACE_RUN_LIMIT_EXCEEDED
- FEATURE_DISABLED
- CLUSTER_REQUEST_LIMIT_EXCEEDED
- MAX_CONCURRENT_RUNS_EXCEEDED
- MAX_JOB_QUEUE_SIZE_EXCEEDED
- MAX_JOB_QUEUE_TIME_EXCEEDED
- MAXIMUM_NUMBER_OF_RUNS_REACHED
- MAXIMUM_CONCURRENT_RUNS_REACHED
- TASK_FAILED
- TRANSIENT_FAILURE
- SERVICE_FAULT
- COMPLIANCE_SECURITY_PROFILE_DTL_MISSING
- COMPLIANCE_SECURITY_PROFILE_IS_MISSING
- COMPLIANCE_SECURITY_PROFILE_INTERNAL_ERROR
- USER_ERROR
- INVALID_CLIENT_CONFIGURATION
- EXECUTION_TIMEOUT
- EXECUTION_FAILURE
- UNEXPECTED_FAILURE
- RATE_LIMITED
- STORAGE_ACCESS_ERROR
SQL_HINT: For operational triage, GROUP BY termination_code first, then drill into error fields/logs. For capacity issues, look for *_LIMIT_EXCEEDED and MAX_*_REACHED codes; for repo issues, REPOSITORY_CHECKOUT_FAILED.

## Facets

### system.lakeflow.job_run_timeline.trigger_type
CONTINUOUS,CRON,FILE_ARRIVAL,ONETIME,ONETIME_RETRY

### system.lakeflow.job_run_timeline.result_state
SUCCEEDED,FAILED,SKIPPED,CANCELLED,TIMED_OUT,ERROR,BLOCKED,NULL

### system.lakeflow.job_run_timeline.run_type
JOB_RUN,SUBMIT_RUN,WORKFLOW_RUN

### system.lakeflow.job_run_timeline.termination_code + termination_type
termination_type='SUCCESS' AND termination_code IS NULL,termination_type='CLIENT_ERROR' AND termination_code LIKE 'COMMAND_EXECUTION_ERROR%',termination_type='SERVICE_ERROR' AND termination_code LIKE 'INTERNAL_ERROR%'

### system.lakeflow.job_run_timeline.termination_code
SUCCESS,CANCELLED,SKIPPED,DRIVER_ERROR,CLUSTER_ERROR,REPOSITORY_CHECKOUT_FAILED,INVALID_CLUSTER_REQUEST,WORKSPACE_RUN_LIMIT_EXCEEDED,FEATURE_DISABLED,CLUSTER_REQUEST_LIMIT_EXCEEDED,STORAGE_ACCESS_ERROR,RUN_EXECUTION_ERROR,UNAUTHORIZED_ERROR,LIBRARY_INSTALLATION_ERROR,MAX_CONCURRENT_RUNS_EXCEEDED,MAX_SPARK_CONTEXTS_EXCEEDED,RESOURCE_NOT_FOUND,INVALID_RUN_CONFIGURATION,CLOUD_FAILURE,MAX_JOB_QUEUE_SIZE_EXCEEDED

### system.lakeflow.job_run_timeline.trigger_type
CONTINUOUS,CRON,FILE_ARRIVAL,ONETIME,ONETIME_RETRY

### system.lakeflow.job_run_timeline.run_type
JOB_RUN,SUBMIT_RUN,WORKFLOW_RUN

### system.lakeflow.job_run_timeline.result_state
SUCCEEDED,FAILED,SKIPPED,CANCELLED,TIMED_OUT,ERROR,BLOCKED,NULL

### system.lakeflow.job_run_timeline.termination_code
SUCCESS,CANCELLED,SKIPPED,DRIVER_ERROR,CLUSTER_ERROR,REPOSITORY_CHECKOUT_FAILED,INVALID_CLUSTER_REQUEST,WORKSPACE_RUN_LIMIT_EXCEEDED,FEATURE_DISABLED,CLUSTER_REQUEST_LIMIT_EXCEEDED,MAX_CONCURRENT_RUNS_EXCEEDED,MAX_JOB_QUEUE_SIZE_EXCEEDED,MAX_JOB_QUEUE_TIME_EXCEEDED,MAXIMUM_NUMBER_OF_RUNS_REACHED,MAXIMUM_CONCURRENT_RUNS_REACHED,TASK_FAILED,TRANSIENT_FAILURE,SERVICE_FAULT,COMPLIANCE_SECURITY_PROFILE_DTL_MISSING,COMPLIANCE_SECURITY_PROFILE_IS_MISSING,COMPLIANCE_SECURITY_PROFILE_INTERNAL_ERROR,USER_ERROR,INVALID_CLIENT_CONFIGURATION,EXECUTION_TIMEOUT,EXECUTION_FAILURE,UNEXPECTED_FAILURE,RATE_LIMITED,STORAGE_ACCESS_ERROR
