---
domain: storage_optimization
system_tables:
- system.storage.predictive_optimization_operations_history
---

# Reference: storage_optimization

> Curated Databricks system-table knowledge for the `storage_optimization` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.storage.predictive_optimization_operations_history
System table in the `storage_optimization` domain. See query packs for vetted SQL over this table.

## Nuance

_No curated nuance entries for this domain yet._

## Codebook

### system.storage.predictive_optimization_operations_history.operation_type
DOC_TYPE: codebook
CODE_KEY: system.storage.predictive_optimization_operations_history.operation_type
SUMMARY: Optimization operation performed by predictive optimization.
VALUES:
- COMPACTION
- VACUUM
SQL_HINT: Use operation_type to split cost/impact (VACUUM may not reduce file counts the same way COMPACTION does).

### system.storage.predictive_optimization_operations_history.operation_status
DOC_TYPE: codebook
CODE_KEY: system.storage.predictive_optimization_operations_history.operation_status
SUMMARY: Status for predictive optimization operation.
VALUES:
- SUCCESSFUL
- FAILED: INTERNAL_ERROR
SQL_HINT: Track failure counts by catalog/schema to detect systemic issues (permissions, metastore instability, platform incidents).

### system.storage.predictive_optimization_operations_history.usage_unit
DOC_TYPE: codebook
CODE_KEY: system.storage.predictive_optimization_operations_history.usage_unit
SUMMARY: Unit used to bill the optimization operation.
VALUES:
- DBU
- NULL
SQL_HINT: Always group by usage_unit before summing usage_quantity; treat NULL as unknown (older rows / partial ingestion).

### system.storage.predictive_optimization_operations_history.operation_type
DOC_TYPE: codebook
CODE_KEY: system.storage.predictive_optimization_operations_history.operation_type
SUMMARY: Which optimization action ran.
VALUES:
- COMPACTION
- VACUUM
SQL_HINT: COMPACTION impacts file counts/read performance; VACUUM impacts retention and storage. Separate metrics by operation_type; never compare usage_quantity across operation_type without normalizing units.

### system.storage.predictive_optimization_operations_history.operation_status
DOC_TYPE: codebook
CODE_KEY: system.storage.predictive_optimization_operations_history.operation_status
SUMMARY: Final status of the predictive optimization operation.
VALUES:
- SUCCESSFUL
- FAILED: INTERNAL_ERROR
SQL_HINT: For failure dashboards, filter operation_status LIKE 'FAILED%' and group by catalog/schema/table to detect systemic issues.

## Facets

### system.storage.predictive_optimization_operations_history.operation_type
COMPACTION,VACUUM

### system.storage.predictive_optimization_operations_history.operation_status
SUCCESSFUL,FAILED: INTERNAL_ERROR

### system.storage.predictive_optimization_operations_history.usage_unit
DBU,NULL

### system.storage.predictive_optimization_operations_history.operation_type
COMPACTION,VACUUM

### system.storage.predictive_optimization_operations_history.operation_status
SUCCESSFUL,FAILED: INTERNAL_ERROR
