---
domain: workload_pipelines
system_tables:
- system.lakeflow.pipeline_update_timeline
- system.lakeflow.pipelines
---

# Reference: workload_pipelines

> Curated Databricks system-table knowledge for the `workload_pipelines` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.lakeflow.pipeline_update_timeline
System table in the `workload_pipelines` domain. See query packs for vetted SQL over this table.

### system.lakeflow.pipelines
System table in the `workload_pipelines` domain. See query packs for vetted SQL over this table.

## Nuance

### dlt_event_type_semantics | rule
DOC_TYPE: rule
TOPIC: dlt_event_type_semantics
RULE: Delta Live Tables event logs (system.lakeflow.pipeline_events) contain multiple event_type values. Filter by appropriate event_type for your analysis.
COMMON EVENT TYPES:
- 'update_progress': pipeline execution status and progress
- 'flow_progress': dataset-level processing progress
- 'user_action': user-initiated actions (start, stop)
- 'flow_definition': dataset definitions and schemas
GUIDELINES:
- Use event_type = 'update_progress' for pipeline run analysis.
- Join to system.lakeflow.pipelines on pipeline_id for pipeline metadata.
- Filter by timestamp for date ranges.
PITFALL: Not filtering event_type produces duplicate/irrelevant events and breaks aggregations.
OUTPUT: relevant_dlt_events

## Codebook

### system.lakeflow.pipeline_update_timeline.update_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipeline_update_timeline.update_type
SUMMARY: Type of pipeline update execution.
VALUES:
- UPDATE
- FULL_REFRESH
- RESET
SQL_HINT: When users say 'full refresh', filter update_type='FULL_REFRESH' and analyze durations/costs separately from incremental UPDATE.

### system.lakeflow.pipeline_update_timeline.result_state
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipeline_update_timeline.result_state
SUMMARY: Outcome of a pipeline update.
VALUES:
- SUCCESS
- FAILED
- CANCELED
- TIMEDOUT
- SKIPPED
- BLOCKED
- INTERNAL_ERROR
SQL_HINT: Use INTERNAL_ERROR to flag platform-side failures; pair with request_id to identify retries.

### system.lakeflow.pipeline_update_timeline.trigger_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipeline_update_timeline.trigger_type
SUMMARY: What triggered the pipeline update.
VALUES:
- MANUAL
- SCHEDULE
- JOB_TASK
- CONTINUOUS
SQL_HINT: If trigger_type='JOB_TASK', use trigger_details.job_task.* to join back to the job that triggered the pipeline.

### system.lakeflow.pipelines.settings.edition
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipelines.settings.edition
SUMMARY: Pipeline edition (commercial tier) when present.
VALUES:
- CORE
- PRO
- ADVANCED
- NULL
SQL_HINT: If edition is NULL for older rows, infer tier via billing usage.product_features.dlt_tier when available.

### system.lakeflow.pipelines.settings.channel
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipelines.settings.channel
SUMMARY: Release channel for pipeline.
VALUES:
- CURRENT
- PREVIEW
- NULL
SQL_HINT: When diagnosing regressions, split by channel to isolate PREVIEW behavior; treat NULL as 'unknown/older'.

### system.lakeflow.pipelines.settings.serverless
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipelines.settings.serverless
SUMMARY: Whether the pipeline is configured for serverless execution.
VALUES:
- true
- false
SQL_HINT: User prompts like 'serverless pipeline' map to settings.serverless=true; for billing, corroborate with usage.product_features.is_serverless where applicable.

### system.lakeflow.pipelines.pipeline_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipelines.pipeline_type
SUMMARY: What kind of Lakeflow pipeline this is (ETL vs MV vs streaming table vs ingestion).
VALUES:
- ETL_PIPELINE
- MATERIALIZED_VIEW
- STREAMING_TABLE
- INGESTION_PIPELINE
- INGESTION_GATEWAY
SQL_HINT: Pipeline behavior/latency expectations differ: STREAMING_TABLE is continuous-ish, MATERIALIZED_VIEW is refresh-driven; use pipeline_type to choose SLA dashboards and cost attribution logic.

### system.lakeflow.pipeline_update_timeline.result_state
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipeline_update_timeline.result_state
SUMMARY: Outcome state for pipeline updates.
VALUES:
- COMPLETED
- FAILED
- CANCELED
SQL_HINT: For reliability reporting, compute success_rate = COMPLETED / (COMPLETED+FAILED+CANCELED) over a date window. For incident triage, filter FAILED then join to trigger context (request_id, trigger_type/details).

### system.lakeflow.pipeline_update_timeline.update_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipeline_update_timeline.update_type
SUMMARY: Why the pipeline update happened.
VALUES:
- API_CALL
- RETRY_ON_FAILURE
- SERVICE_UPGRADE
- SCHEMA_CHANGE
- JOB_TASK
- USER_ACTION
- DBSQL_REQUEST
- SETTINGS_CHANGE
- SCHEMA_EXPLORATION
- INFRASTRUCTURE_MAINTENANCE
- START_RESOURCES
SQL_HINT: In incident reviews, separate USER_ACTION/SETTINGS_CHANGE/SCHEMA_CHANGE from INFRASTRUCTURE_MAINTENANCE/SERVICE_UPGRADE to reduce false attribution.

### system.lakeflow.pipeline_update_timeline.trigger_details.job_task.performance_target
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipeline_update_timeline.trigger_details.job_task.performance_target
SUMMARY: Performance mode for serverless pipeline updates triggered by job tasks.
VALUES:
- PERFORMANCE_OPTIMIZED
- STANDARD
SQL_HINT: Only populated for serverless pipeline updates. When users ask for “performance optimized pipelines”, filter performance_target='PERFORMANCE_OPTIMIZED' and join to pipeline_id to attribute owners/tags.

### system.lakeflow.pipelines.pipeline_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipelines.pipeline_type
SUMMARY: Pipeline family classification.
VALUES:
- dlt
- lakeflow
SQL_HINT: Use pipeline_type to separate classic DLT vs newer Lakeflow pipeline families before comparing KPIs (latency, success rate, cost attribution).

### system.lakeflow.pipeline_update_timeline.result_state
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipeline_update_timeline.result_state
SUMMARY: Outcome of the pipeline update.
VALUES:
- COMPLETED
- FAILED
- CANCELED
SQL_HINT: Pair FAILED with update_type to separate user-caused config/schema failures from infrastructure/maintenance-driven failures.

### system.lakeflow.pipeline_update_timeline.trigger_type
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipeline_update_timeline.trigger_type
SUMMARY: Trigger category for pipeline updates.
VALUES:
- job_task
SQL_HINT: If trigger_type='job_task', use trigger_details.job_task.* to join back to jobs/job_task_run_timeline for upstream attribution.

### system.lakeflow.pipelines.settings
DOC_TYPE: codebook
CODE_KEY: system.lakeflow.pipelines.settings.<keys>
SUMMARY: Keys inside pipelines.settings (struct) that describe runtime/feature configuration for a pipeline.
KEYS:
- photon
- development
- continuous
- serverless
- edition
- channel
SQL_HINT: Treat settings as config facets; for fleet analysis, explode the struct into columns (or use dot access) and group by these keys. Combine with update_type=SETTINGS_CHANGE to measure configuration churn.

## Facets

### system.lakeflow.pipeline_update_timeline.update_type
UPDATE,FULL_REFRESH,RESET

### system.lakeflow.pipeline_update_timeline.result_state
SUCCESS,FAILED,CANCELED,TIMEDOUT,SKIPPED,BLOCKED,INTERNAL_ERROR

### system.lakeflow.pipeline_update_timeline.trigger_type
MANUAL,SCHEDULE,JOB_TASK,CONTINUOUS

### system.lakeflow.pipelines.settings.edition
CORE,PRO,ADVANCED,NULL

### system.lakeflow.pipelines.settings.channel
CURRENT,PREVIEW,NULL

### system.lakeflow.pipelines.settings.serverless
true,false

### system.lakeflow.pipelines.pipeline_type
ETL_PIPELINE,MATERIALIZED_VIEW,STREAMING_TABLE,INGESTION_PIPELINE,INGESTION_GATEWAY

### system.lakeflow.pipeline_update_timeline.result_state
COMPLETED,FAILED,CANCELED

### system.lakeflow.pipeline_update_timeline.update_type
API_CALL,RETRY_ON_FAILURE,SERVICE_UPGRADE,SCHEMA_CHANGE,JOB_TASK,USER_ACTION,DBSQL_REQUEST,SETTINGS_CHANGE,SCHEMA_EXPLORATION,INFRASTRUCTURE_MAINTENANCE,START_RESOURCES

### system.lakeflow.pipeline_update_timeline.trigger_details.job_task.performance_target
PERFORMANCE_OPTIMIZED,STANDARD

### system.lakeflow.pipelines.pipeline_type
dlt,lakeflow

### system.lakeflow.pipeline_update_timeline.result_state
COMPLETED,FAILED,CANCELED

### system.lakeflow.pipeline_update_timeline.trigger_type
job_task

### system.lakeflow.pipelines.settings
photon,development,continuous,serverless,edition,channel
