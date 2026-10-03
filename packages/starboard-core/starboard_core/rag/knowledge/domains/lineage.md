---
domain: lineage
system_tables:
- system.access.column_lineage
- system.access.table_lineage
---

# Reference: lineage

> Curated Databricks system-table knowledge for the `lineage` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.access.column_lineage
System table in the `lineage` domain. See query packs for vetted SQL over this table.

### system.access.table_lineage
System table in the `lineage` domain. See query packs for vetted SQL over this table.

## Nuance

_No curated nuance entries for this domain yet._

## Codebook

### system.access.table_lineage.entity_type
DOC_TYPE: codebook
CODE_KEY: system.access.table_lineage.entity_type (also system.access.column_lineage.entity_type)
SUMMARY: Originating entity type for a lineage event (what produced the data movement/transformation).
VALUES:
- NOTEBOOK
- JOB
- PIPELINE
- DASHBOARD_V3
- DBSQL_DASHBOARD
- DBSQL_QUERY
- NULL
SQL_HINT: When a user asks "lineage from jobs", filter entity_type='JOB'. For warehouse-only lineage (SQL), filter entity_type='DBSQL_QUERY' or entity_run_id/statement_id is not null.

### system.access.table_lineage.source_type
DOC_TYPE: codebook
CODE_KEY: system.access.table_lineage.source_type
SUMMARY: Source object type (table/path/view/etc).
VALUES:
- TABLE
- PATH
- VIEW
- MATERIALIZED_VIEW
- METRIC_VIEW
- STREAMING_TABLE
SQL_HINT: When source_type='PATH', use source_path for attribution; when 'TABLE' use source_table_full_name.

### system.access.table_lineage.target_type
DOC_TYPE: codebook
CODE_KEY: system.access.table_lineage.target_type
SUMMARY: Target object type (table/path/view/etc).
VALUES:
- TABLE
- PATH
- VIEW
- MATERIALIZED_VIEW
- METRIC_VIEW
- STREAMING_TABLE
SQL_HINT: When target_type='STREAMING_TABLE', expect pipeline-related contexts more frequently; join with Lakeflow pipeline update tables when available.

### system.access.column_lineage.entity_type
DOC_TYPE: codebook
CODE_KEY: system.access.column_lineage.entity_type
SUMMARY: Entity type that produced the column lineage event.
VALUES:
- NOTEBOOK
- JOB
- PIPELINE
- DASHBOARD_V3
- DBSQL_DASHBOARD
- DBSQL_QUERY
- NULL
SQL_HINT: Same semantics as table_lineage.entity_type; prefer statement_id joins for DBSQL_QUERY and job_run_id joins for JOB.

### system.access.column_lineage.source_type
DOC_TYPE: codebook
CODE_KEY: system.access.column_lineage.source_type
SUMMARY: Source object type for column lineage.
VALUES:
- TABLE
- PATH
- VIEW
- MATERIALIZED_VIEW
- METRIC_VIEW
- STREAMING_TABLE
SQL_HINT: Use source_column_name only when source_type is TABLE/VIEW/MATERIALIZED_VIEW/METRIC_VIEW/STREAMING_TABLE.

### system.access.column_lineage.target_type
DOC_TYPE: codebook
CODE_KEY: system.access.column_lineage.target_type
SUMMARY: Target object type for column lineage.
VALUES:
- TABLE
- PATH
- VIEW
- MATERIALIZED_VIEW
- METRIC_VIEW
- STREAMING_TABLE
SQL_HINT: Use target_column_name only when target_type is TABLE/VIEW/MATERIALIZED_VIEW/METRIC_VIEW/STREAMING_TABLE.

### system.access.table_lineage.source_type
DOC_TYPE: codebook
CODE_KEY: system.access.table_lineage.source_type / target_type (also system.access.column_lineage.source_type / target_type)
SUMMARY: The kind of object or source involved in lineage (table vs view vs path vs streaming).
VALUES:
- TABLE
- PATH
- VIEW
- MATERIALIZED_VIEW
- METRIC_VIEW
- STREAMING_TABLE
SQL_HINT: If source_type='PATH', expect source_table_full_name may be null and use source_path. If target_type='VIEW', joins to UC tables may not apply; treat as logical output.

### system.access.table_lineage.entity_type
DOC_TYPE: codebook
CODE_KEY: system.access.(table_lineage|column_lineage).entity_type
SUMMARY: Originating entity kind that produced the lineage transaction.
VALUES:
- NOTEBOOK
- JOB
- PIPELINE
- DASHBOARD_V3
- DBSQL_DASHBOARD
- DBSQL_QUERY
- NULL
SQL_HINT: For DBSQL_QUERY, entity_run_id often corresponds to statement_id; join to system.query.history when present.

### system.access.table_lineage.source_type
DOC_TYPE: codebook
CODE_KEY: system.access.(table_lineage|column_lineage).(source_type|target_type)
SUMMARY: Dataset type for lineage endpoints.
VALUES:
- TABLE
- PATH
- VIEW
- MATERIALIZED_VIEW
- METRIC_VIEW
- STREAMING_TABLE
SQL_HINT: PATH indicates file/path reads/writes outside registered UC tables; treat as higher governance risk.

### system.access.table_lineage.source_type
DOC_TYPE: codebook
CODE_KEY: system.access.table_lineage.source_type | target_type (and similarly in column_lineage)
SUMMARY: Type of the source/target in lineage edges.
VALUES:
- TABLE
- PATH
- VIEW
- MATERIALIZED_VIEW
- METRIC_VIEW
- STREAMING_TABLE
SQL_HINT: Prefer TABLE/STREAMING_TABLE for governance joins (catalog/schema/table). Treat PATH edges as “unmanaged” reads/writes and use source_path/target_path for storage attribution.

## Facets

### system.access.table_lineage.entity_type
NOTEBOOK,JOB,PIPELINE,DASHBOARD_V3,DBSQL_DASHBOARD,DBSQL_QUERY,NULL

### system.access.table_lineage.source_type
TABLE,PATH,VIEW,MATERIALIZED_VIEW,METRIC_VIEW,STREAMING_TABLE

### system.access.table_lineage.target_type
TABLE,PATH,VIEW,MATERIALIZED_VIEW,METRIC_VIEW,STREAMING_TABLE

### system.access.column_lineage.entity_type
NOTEBOOK,JOB,PIPELINE,DASHBOARD_V3,DBSQL_DASHBOARD,DBSQL_QUERY,NULL

### system.access.column_lineage.source_type
TABLE,PATH,VIEW,MATERIALIZED_VIEW,METRIC_VIEW,STREAMING_TABLE

### system.access.column_lineage.target_type
TABLE,PATH,VIEW,MATERIALIZED_VIEW,METRIC_VIEW,STREAMING_TABLE

### system.access.table_lineage.source_type
TABLE,PATH,VIEW,MATERIALIZED_VIEW,METRIC_VIEW,STREAMING_TABLE

### system.access.table_lineage.entity_type
NOTEBOOK,JOB,PIPELINE,DASHBOARD_V3,DBSQL_DASHBOARD,DBSQL_QUERY,NULL

### system.access.table_lineage.source_type
TABLE,PATH,VIEW,MATERIALIZED_VIEW,METRIC_VIEW,STREAMING_TABLE

### system.access.table_lineage.source_type
TABLE,PATH,VIEW,MATERIALIZED_VIEW,METRIC_VIEW,STREAMING_TABLE
