---
domain: compute_clusters
system_tables:
- system.compute.clusters
- system.compute.node_timeline
- system.compute.node_types
---

# Reference: compute_clusters

> Curated Databricks system-table knowledge for the `compute_clusters` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.compute.clusters
System table in the `compute_clusters` domain. See query packs for vetted SQL over this table.

### system.compute.node_timeline
System table in the `compute_clusters` domain. See query packs for vetted SQL over this table.

### system.compute.node_types
System table in the `compute_clusters` domain. See query packs for vetted SQL over this table.

## Nuance

### cluster_source_attribution | rule
DOC_TYPE: rule
TOPIC: cluster_source_attribution
RULE: Always identify cluster source to correctly attribute costs and understand workload type.
SOURCES:
- JOB: cluster created by a job (check cluster_source or usage_metadata.job_id)
- PIPELINE: cluster created by Delta Live Tables pipeline (usage_metadata.dlt_pipeline_id)
- INTERACTIVE: user-created cluster for notebooks (usage_metadata.notebook_id)
- SQL_WAREHOUSE: not technically a cluster but separate compute type (usage_metadata.warehouse_id)
GUIDELINES:
- Join system.compute.clusters to system.lakeflow.jobs using usage_metadata.cluster_id or usage_metadata.job_id when available.
- For DLT pipelines, join to system.lakeflow.pipelines using usage_metadata.dlt_pipeline_id.
- Use cluster_source column when available to avoid complex joins.
PITFALL: Treating all clusters as equivalent misattributes automated workload costs to general compute buckets. Resource IDs are in the usage_metadata column.
OUTPUT: workload_type_attribution

## Codebook

### system.compute.clusters.cluster_source
DOC_TYPE: codebook
CODE_KEY: system.compute.clusters.cluster_source
SUMMARY: Where/why a cluster was created (critical for governance + attribution).
VALUES:
- UI
- API
- JOB
- PIPELINE
- PIPELINE_MAINTENANCE
SQL_HINT: Prefer cluster_source='JOB'/'PIPELINE' for workload compute inventories; treat UI/API as interactive/all-purpose unless proven otherwise.

### system.compute.clusters.data_security_mode
DOC_TYPE: codebook
CODE_KEY: system.compute.clusters.data_security_mode
SUMMARY: Governance / isolation mode for compute.
VALUES:
- NONE
- LEGACY_TABLE_ACL
- LEGACY_PASSTHROUGH
- LEGACY_SINGLE_USER
- SINGLE_USER
- USER_ISOLATION
SQL_HINT: Segment workloads by data_security_mode when diagnosing permission issues, UC compatibility, and performance overhead from isolation/credential passthrough.

### clusters.runtime_engine
DOC_TYPE: codebook
CODE_KEY: clusters.runtime_engine
SUMMARY: Execution engine selection for clusters.
VALUES:
- STANDARD
- PHOTON
SQL_HINT: When users say "Photon on/off", this is the facet. For performance triage, compare PHOTON vs STANDARD cohorts controlling for node_type + DBR.

### system.compute.clusters.gcp_attributes.availability
DOC_TYPE: codebook
CODE_KEY: system.compute.clusters.gcp_attributes.availability
SUMMARY: GCP compute availability class.
VALUES:
- ON_DEMAND_GCP
- PREEMPTIBLE_GCP
SQL_HINT: Use PREEMPTIBLE_GCP cohorting when analyzing churny executors / task retries; correlate with node_timeline interruptions and job failures.

## Facets

### system.compute.clusters.cluster_source
UI,API,JOB,PIPELINE,PIPELINE_MAINTENANCE

### system.compute.clusters.data_security_mode
NONE,LEGACY_TABLE_ACL,LEGACY_PASSTHROUGH,LEGACY_SINGLE_USER,SINGLE_USER,USER_ISOLATION

### clusters.runtime_engine
STANDARD,PHOTON

### system.compute.clusters.gcp_attributes.availability
ON_DEMAND_GCP,PREEMPTIBLE_GCP
