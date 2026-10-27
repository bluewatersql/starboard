---
domain: security_access
system_tables:
- system.access.assistant_events
- system.access.audit
- system.access.clean_room_events
- system.access.inbound_network
- system.access.outbound_network
---

# Reference: security_access

> Curated Databricks system-table knowledge for the `security_access` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.access.assistant_events
System table in the `security_access` domain. See query packs for vetted SQL over this table.

### system.access.audit
System table in the `security_access` domain. See query packs for vetted SQL over this table.

### system.access.clean_room_events
System table in the `security_access` domain. See query packs for vetted SQL over this table.

### system.access.inbound_network
System table in the `security_access` domain. See query packs for vetted SQL over this table.

### system.access.outbound_network
System table in the `security_access` domain. See query packs for vetted SQL over this table.

## Nuance

_No curated nuance entries for this domain yet._

## Codebook

### system.access.audit.audit_level
DOC_TYPE: codebook
CODE_KEY: system.access.audit.audit_level
SUMMARY: Scope of the audit event (account vs workspace).
VALUES:
- ACCOUNT_LEVEL
- WORKSPACE_LEVEL
SQL_HINT: When mixing account + workspace audit logs, filter audit_level explicitly; workspace_id=0 commonly indicates ACCOUNT_LEVEL events.

### system.access.workspaces_latest.status
DOC_TYPE: codebook
CODE_KEY: system.access.workspaces_latest.status
SUMMARY: Workspace lifecycle state.
VALUES:
- NOT_PROVISIONED
- PROVISIONING
- RUNNING
- FAILED
- BANNED
SQL_HINT: Use status='RUNNING' for active inventory; exclude FAILED/BANNED when calculating coverage.

### system.access.audit.service_name + system.access.audit.action_name
DOC_TYPE: codebook
CODE_KEY: system.access.audit.service_name + system.access.audit.action_name
SUMMARY: Service/action are large and evolving; treat as drilldown facets and allow prefix/contains matching.
PATTERNS/EXAMPLES (non-exhaustive):
- service_name='workspace' AND action_name LIKE 'clusters/%'
- service_name='unityCatalog' AND action_name LIKE 'grants/%'
- service_name='sql' AND action_name LIKE 'warehouses/%'
- service_name='jobs' AND action_name LIKE 'runs/%'
SQL_HINT: Start with service_name equality + action_name LIKE 'prefix/%' instead of enumerating all actions; group by service_name then top action_name.

### system.access.audit.audit_level
DOC_TYPE: codebook
CODE_KEY: system.access.audit.audit_level
SUMMARY: Indicates whether an audit event was captured at account-level or workspace-level.
VALUES:
- ACCOUNT_LEVEL
- WORKSPACE_LEVEL
SQL_HINT: Always filter audit_level when answering compliance questions; account-level events may have workspace_id=0 and should not be joined to workspace-scoped tables without guarding logic.

### system.access.audit.audit_level
DOC_TYPE: codebook
CODE_KEY: system.access.audit.audit_level
SUMMARY: Whether an audit event is emitted at account or workspace scope.
VALUES:
- ACCOUNT_LEVEL
- WORKSPACE_LEVEL
SQL_HINT: If you are investigating org-wide admin changes, start with audit_level='ACCOUNT_LEVEL'. For workspace operational actions, use audit_level='WORKSPACE_LEVEL' and filter workspace_id.

### system.access.audit.audit_level
DOC_TYPE: codebook
CODE_KEY: system.access.audit.audit_level
SUMMARY: Scope of audit event.
VALUES:
- ACCOUNT_LEVEL
- WORKSPACE_LEVEL
SQL_HINT: Use audit_level to separate account admin actions from in-workspace user actions.

## Facets

### system.access.audit.audit_level
ACCOUNT_LEVEL,WORKSPACE_LEVEL

### system.access.workspaces_latest.status
NOT_PROVISIONED,PROVISIONING,RUNNING,FAILED,BANNED

### system.access.audit.service_name + system.access.audit.action_name
service_name='workspace' AND action_name LIKE 'clusters/%',service_name='unityCatalog' AND action_name LIKE 'grants/%',service_name='sql' AND action_name LIKE 'warehouses/%',service_name='jobs' AND action_name LIKE 'runs/%'

### system.access.audit.audit_level
ACCOUNT_LEVEL,WORKSPACE_LEVEL

### system.access.audit.audit_level
ACCOUNT_LEVEL,WORKSPACE_LEVEL

### system.access.audit.audit_level
ACCOUNT_LEVEL,WORKSPACE_LEVEL
