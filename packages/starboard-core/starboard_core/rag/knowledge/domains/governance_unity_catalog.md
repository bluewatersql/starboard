---
domain: governance_unity_catalog
system_tables:
- system.access.column_lineage
- system.access.table_lineage
- system.information_schema.catalogs
- system.information_schema.columns
- system.information_schema.schemata
- system.information_schema.tables
- system.storage.predictive_optimization_operations_history
---

# Reference: governance_unity_catalog

> Curated Databricks system-table knowledge for the `governance_unity_catalog` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.access.column_lineage
System table in the `governance_unity_catalog` domain. See query packs for vetted SQL over this table.

### system.access.table_lineage
System table in the `governance_unity_catalog` domain. See query packs for vetted SQL over this table.

### system.information_schema.catalogs
System table in the `governance_unity_catalog` domain. See query packs for vetted SQL over this table.

### system.information_schema.columns
System table in the `governance_unity_catalog` domain. See query packs for vetted SQL over this table.

### system.information_schema.schemata
System table in the `governance_unity_catalog` domain. See query packs for vetted SQL over this table.

### system.information_schema.tables
System table in the `governance_unity_catalog` domain. See query packs for vetted SQL over this table.

### system.storage.predictive_optimization_operations_history
System table in the `governance_unity_catalog` domain. See query packs for vetted SQL over this table.

## Nuance

### uc_table_identity_rename_safe | rule
DOC_TYPE: rule
TOPIC: uc_table_identity_rename_safe
RULE: Prefer stable identifiers (table_id) over names for long-term tracking.
WHY:
- table_name/catalog/schema can change (rename/move).
- table_id remains stable across renames.
OUTPUT: stable_table_key = (metastore_id, table_id)
PITFALL: Using only 3-part name breaks longitudinal analysis after refactors.

### predictive_optimization_metrics | concept
DOC_TYPE: concept
TOPIC: predictive_optimization_metrics
SUMMARY: Predictive Optimization is a Unity Catalog feature that automatically optimizes tables. Tracking which tables have it enabled and their optimization impact requires joining system.information_schema.tables with system.compute.table_storage_metrics.
KEY METRICS:
- predictive_optimization_enabled (boolean in table properties)
- Files optimized, bytes optimized
- Cost impact (calculate based on optimization operations)
GUIDELINES:
- Filter to tables where predictive_optimization_enabled = true.
- Join to billing usage using table_id if available to estimate cost savings.
PITFALL: Not all table metadata sources include predictive optimization status; may need to query table properties directly.
OUTPUT: optimization_impact_report

## Codebook

_No curated codebook entries for this domain yet._

## Facets

_No categorical facets for this domain yet._
