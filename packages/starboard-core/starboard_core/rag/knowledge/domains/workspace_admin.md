---
domain: workspace_admin
system_tables:
- system.access.audit
- system.access.workspaces_latest
---

# Reference: workspace_admin

> Curated Databricks system-table knowledge for the `workspace_admin` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.access.audit
System table in the `workspace_admin` domain. See query packs for vetted SQL over this table.

### system.access.workspaces_latest
System table in the `workspace_admin` domain. See query packs for vetted SQL over this table.

## Nuance

### scope_account_workspace_metastore | rule
DOC_TYPE: rule
TOPIC: scope_account_workspace_metastore
RULE: Always maintain correct scoping keys when joining system tables.
GUIDELINES:
- account_id scopes across accounts.
- workspace_id scopes within an account.
- metastore_id / metastore_name scopes Unity Catalog entities.
- When in doubt, join on the most-specific stable IDs available.
PITFALL: Joining across workspaces without workspace_id can silently inflate counts and costs.
OUTPUT: recommended_join_keys = (account_id, workspace_id, metastore_id, table_id, ...)

### scope_keys_for_joins | rule
DOC_TYPE: rule
TOPIC: scope_keys_for_joins
RULE: Preserve correct scoping keys in joins to avoid silent fan-out and inflated totals.
GUIDELINES:
- Use workspace_id for workspace-scoped tables.
- Use account_id for account-scoped billing tables.
- Use metastore_id for Unity Catalog entities.
- When available, join on the most-specific stable IDs (workspace_id + entity_id).
OUTPUT: join_key_set = (account_id, workspace_id, metastore_id, entity_id)
PITFALL: Joining across workspaces without workspace_id inflates counts/costs.

### late_populated_columns_gaps | pitfalls
DOC_TYPE: pitfalls
TOPIC: late_populated_columns_gaps
PROBLEM: Some columns in system tables are not populated for older rows (feature introduced later).
HANDLING:
- Expect NULLs before feature launch date.
- Use change_time/create_time to bound analysis.
- Document field availability in results.
PITFALL: Treating NULL as "unset" vs "not available" leads to wrong compliance/audit conclusions.
OUTPUT: availability_notes

## Codebook

### system.access.workspaces_latest.status
DOC_TYPE: codebook
CODE_KEY: system.access.workspaces_latest.status
SUMMARY: Workspace lifecycle status. Useful for filtering out deleted/banned/provisioning workspaces from rollups.
VALUES:
- NOT_PROVISIONED
- PROVISIONING
- RUNNING
- FAILED
- BANNED
SQL_HINT: For account-wide aggregations, default to status='RUNNING'. If including others, label them explicitly so counts/costs aren't interpreted as active usage.

### system.access.workspaces_latest.status
DOC_TYPE: codebook
CODE_KEY: system.access.workspaces_latest.status
SUMMARY: Workspace lifecycle status.
VALUES:
- NOT_PROVISIONED
- PROVISIONING
- RUNNING
- FAILED
- BANNED
SQL_HINT: For inventory reports, default to status='RUNNING' unless explicitly auditing failures/banned workspaces.

## Facets

### system.access.workspaces_latest.status
NOT_PROVISIONED,PROVISIONING,RUNNING,FAILED,BANNED

### system.access.workspaces_latest.status
NOT_PROVISIONED,PROVISIONING,RUNNING,FAILED,BANNED
