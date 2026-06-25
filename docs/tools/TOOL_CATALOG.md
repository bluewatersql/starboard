# Starboard AI Agent - Complete Tool Catalog

> Last verified: 2026-03-24

**Total Tools**: 45+
**Domains**: 9 (router, query, job, uc, cluster, analytics, diagnostic, warehouse, discovery)

---

## Table of Contents

1. [Overview](#overview)
2. [Tool Architecture](#tool-architecture)
3. [Router Tools](#router-tools) (3 tools)
4. [Query Tools](#query-tools) (8 tools)
5. [Job Tools](#job-tools) (14 tools)
6. [UC Tools](#uc-tools-unity-catalog) (18 tools)
7. [Cluster Tools](#cluster-tools) (8 tools)
8. [Analytics Tools](#analytics-tools) (6 tools)
9. [Warehouse Tools](#warehouse-tools) (11 tools)
10. [Discovery Tools](#discovery-tools) (6 tools)
11. [Diagnostic Agent](#diagnostic-agent)
12. [Core Tools](#core-tools) (2 tools)
13. [Online vs Offline Tools](#online-vs-offline-tools)
14. [Tool Overlap Matrix](#tool-overlap-matrix)
15. [Tool Sharing Strategy](#tool-sharing-strategy)

---

## Overview

The Starboard AI Agent provides 45+ specialized tools organized by domain. Tools follow a three-layer architecture and are assigned to agents using the **Pragmatic Hybrid (80/20)** strategy defined in `tool_categories.py`.

### Common Interface Pattern

All tools follow this async signature:

```python
async def tool_name(
    param1: str,
    param2: int | None = None,
) -> dict[str, Any]:
    """Tool description."""
    return {"result_key": value}
```

---

## Tool Architecture

```
Tool Interface (Agent-Facing)
    |
Tool Adapter (adapters/*)
    |
Tool Service (services/*)
    |
Tool Domain Logic (domain/*)
    |
External APIs (Databricks, etc.)
```

**Source**: `packages/starboard-server/starboard_server/tools/`

---

## Router Tools

**Domain**: `router`
**Purpose**: Intent classification and routing decisions
**Tool Count**: 3

| Tool | Description |
|------|-------------|
| `resolve_user_intent` | Classify user request into a domain |
| `request_user_input` | Request clarification from the user (pauses and waits) |
| `complete` | Return the routing decision |

---

## Query Tools

**Domain**: `query`
**Purpose**: SQL optimization, query plan analysis, and runtime metrics
**Tool Count**: 8 (including strategic overlap and core tools)

| Tool | Sharing | Description |
|------|---------|-------------|
| `resolve_query` | Exclusive | Get SQL text from statement_id or raw SQL |
| `analyze_query_plan` | Exclusive | Run EXPLAIN and analyze execution plan |
| `get_query_runtime_metrics` | Shared (warehouse) | Get actual execution metrics for a statement |
| `get_table_metadata` | Shared (job, uc) | Need schemas, partitions, stats for optimization |
| `discover_tables` | Shared (job, uc) | Extract table references from SQL |
| `get_table_history` | Shared (uc) | Check recent table operations |

Core tools (`request_user_input`, `complete`) are also available.

---

## Job Tools

**Domain**: `job`
**Purpose**: Databricks job performance analysis, Spark tuning, code quality
**Tool Count**: 14 (including strategic overlap and core tools)

| Tool | Sharing | Description |
|------|---------|-------------|
| `resolve_job` | Exclusive | Get job metadata from job_id or name |
| `get_job_config` | Exclusive | Retrieve job settings and task definitions |
| `analyze_job_history` | Exclusive | Review past runs, failures, durations |
| `get_run_output` | Exclusive | Get run output and logs for diagnostics |
| `get_task_logs` | Exclusive | Get logs for a specific task in a run |
| `get_source_code` | Exclusive | Fetch notebook/script source code |
| `analyze_code_quality` | Exclusive | Static analysis for anti-patterns |
| `get_cluster_config` | Shared (cluster) | Jobs need cluster configuration info |
| `get_spark_logs` | Shared (cluster) | Job analysis needs Spark logs (STANDARD jobs) |
| `get_cluster_metrics` | Shared (cluster) | For SERVERLESS jobs (via system tables) |
| `get_table_metadata` | Shared (query, uc) | Jobs query tables |
| `discover_tables` | Shared (query, uc) | Find tables in job code |

Core tools (`request_user_input`, `complete`) are also available.

---

## UC Tools (Unity Catalog)

**Domain**: `uc`
**Purpose**: Unity Catalog governance, metadata, lineage, schema analysis, storage optimization
**Tool Count**: 18 (including core tools)

### Phase 1 - Core UC Tools

| Tool | Sharing | Description |
|------|---------|-------------|
| `list_uc_assets` | Exclusive | List catalogs, schemas, tables, volumes, functions |
| `get_table_metadata` | Shared (query, job) | Extended table metadata (schema + storage + stats) |
| `get_table_lineage` | Exclusive | Trace upstream/downstream dependencies |
| `get_table_grants` | Exclusive | Access policies and grants |
| `analyze_table_schema` | Exclusive | Schema analysis with anomaly detection |
| `get_table_history` | Shared (query) | Delta version history |
| `analyze_access_patterns` | Exclusive | Query frequency, reader/writer tracking |
| `analyze_schema_drift` | Exclusive | Track schema changes over time |

### Phase 2 - Advanced UC Tools

| Tool | Description |
|------|-------------|
| `analyze_storage_optimization` | Storage optimization recommendations |
| `analyze_query_impact` | Query performance prediction |
| `get_table_fingerprint` | Comprehensive workload profile |
| `analyze_table_costs` | Per-table cost breakdown |
| `generate_schema_diff` | Version-aware schema comparison |
| `analyze_policy_coverage` | Security policy completeness |

### Legacy/Shared

| Tool | Description |
|------|-------------|
| `get_enriched_table_metadata` | Get enriched metadata for multiple tables |
| `discover_tables` | Find related tables in SQL/notebooks |

Core tools (`request_user_input`, `complete`) are also available.

---

## Cluster Tools

**Domain**: `cluster`
**Purpose**: Databricks cluster configuration, health scoring, and metrics
**Tool Count**: 8 (including core tools)

| Tool | Sharing | Description |
|------|---------|-------------|
| `list_clusters` | Exclusive | List all clusters with recent activity |
| `get_cluster_config` | Shared (job) | Get cluster configuration settings |
| `get_cluster_health` | Exclusive | Health scoring and risk analysis |
| `get_cluster_metrics` | Exclusive | CPU, memory, I/O utilization metrics |
| `get_cluster_events` | Exclusive | Review scaling and lifecycle events |
| `get_spark_logs` | Shared (job) | Analyze Spark resource utilization |

Core tools (`request_user_input`, `complete`) are also available.

---

## Analytics Tools

**Domain**: `analytics`
**Purpose**: FinOps cost analysis using Agentic RAG and SQL generation
**Tool Count**: 6 (including core tools)

| Tool | Description |
|------|-------------|
| `build_analytics_context` | Agentic RAG context builder -- gathers relevant schema and metadata |
| `build_sql_query` | Generate SQL from user query + RAG context |
| `validate_sql_query` | Validate SQL syntax and run EXPLAIN |
| `execute_sql_query` | Execute validated SQL and return results |

Core tools (`request_user_input`, `complete`) are also available.

!!! note
    The Analytics agent uses an agentic RAG workflow: first `build_analytics_context` gathers relevant metadata, then `build_sql_query` generates SQL, `validate_sql_query` checks it, and `execute_sql_query` runs it against Databricks system tables.

---

## Warehouse Tools

**Domain**: `warehouse`
**Purpose**: SQL warehouse portfolio optimization, SLO management, chargeback
**Tool Count**: 11 (including shared and core tools)

| Tool | Sharing | Description |
|------|---------|-------------|
| `get_warehouse_portfolio` | Exclusive | List all warehouses with metrics |
| `get_warehouse_fingerprint` | Exclusive | Detailed warehouse analysis profile |
| `get_warehouse_health` | Exclusive | Health scoring and SLO compliance |
| `get_query_runtime_metrics` | Shared (query) | Query metrics for warehouse analysis |
| `configure_warehouse_slo` | Exclusive | Configure SLO targets |
| `analyze_warehouse_topology` | Exclusive | Cross-warehouse analysis |
| `get_warehouse_user_activity` | Exclusive | User activity breakdown |
| `generate_warehouse_chargeback` | Exclusive | Single warehouse chargeback report |
| `generate_portfolio_chargeback` | Exclusive | Portfolio-wide chargeback report |

Core tools (`request_user_input`, `complete`) are also available.

---

## Discovery Tools

**Domain**: `discovery`
**Purpose**: Workspace health assessment using a 4-phase workflow
**Tool Count**: 6 (including core tools)

| Tool | Phase | Description |
|------|-------|-------------|
| `discover_active_products` | 1 - Audit | Discover active Databricks products in the workspace |
| `run_discovery_queries` | 2 - Query | Execute query packs against system tables |
| `start_discovery_analysis` | 3 - Analyze | Start an async domain analysis job |
| `get_discovery_analysis_progress` | 3 - Analyze | Poll progress of an in-flight domain analysis |
| `analyze_discovery_domain` | 3 - Analyze | Analyze a specific domain's health (called per-domain) |
| `synthesize_discovery_report` | 4 - Report | Assemble the final discovery report |

Core tools (`request_user_input`, `complete`) are also available.

!!! tip
    The Discovery agent follows a strict 4-phase workflow: audit active products, run query packs, analyze each domain, then synthesize the final report.

---

## Diagnostic Agent

**Domain**: `diagnostic`
**Configuration**: `"all"` (special marker)

The Diagnostic agent receives **unrestricted access to all tools** across every domain. This enables cross-domain troubleshooting and root cause analysis without tool restrictions.

```python
TOOL_CATEGORIES = {
    "diagnostic": "all",  # Special marker - gets unrestricted access
}
```

---

## Core Tools

Available to **all** agents across every domain:

| Tool | Description |
|------|-------------|
| `request_user_input` | Pause reasoning and request clarification from the user |
| `complete` | Signal that the agent has finished and return the final response |

---

## Online vs Offline Tools

Tools are classified by their dependency on the Databricks API. When `offline_mode=True`, online tools are filtered out.

### ONLINE_TOOLS (require Databricks API)

```
Job:        resolve_job, get_job_config, analyze_job_history, get_run_output,
            get_task_logs, get_source_code
Cluster:    list_clusters, get_cluster_config, get_cluster_health,
            get_cluster_metrics, get_cluster_events, get_spark_logs
Query:      resolve_query, analyze_query_plan, get_query_runtime_metrics
UC:         list_uc_assets, get_table_metadata, get_table_lineage,
            get_table_grants, analyze_table_schema, get_table_history,
            analyze_access_patterns, analyze_schema_drift, discover_tables,
            get_enriched_table_metadata, analyze_storage_optimization,
            analyze_query_impact, get_table_fingerprint, analyze_table_costs,
            generate_schema_diff, analyze_policy_coverage
Discovery:  discover_active_products, run_discovery_queries,
            analyze_discovery_domain, synthesize_discovery_report
Warehouse:  get_warehouse_portfolio, get_warehouse_fingerprint,
            get_warehouse_health, configure_warehouse_slo,
            analyze_warehouse_topology, get_warehouse_user_activity,
            generate_warehouse_chargeback, generate_portfolio_chargeback
Analytics:  build_analytics_context, build_sql_query, validate_sql_query,
            execute_sql_query
```

### OFFLINE_TOOLS (work without Databricks API)

```
complete, request_user_input, explore_artifact,
analyze_code_quality, resolve_user_intent
```

---

## Tool Overlap Matrix

This matrix shows which domains have access to each shared tool. The Diagnostic agent is omitted (it has access to all tools).

| Tool | Domains with Access |
|------|-------------------|
| `get_table_metadata` | query, job, uc |
| `discover_tables` | query, job, uc |
| `get_table_history` | query, uc |
| `get_table_lineage` | uc only |
| `list_uc_assets` | uc only |
| `get_table_grants` | uc only |
| `analyze_table_schema` | uc only |
| `analyze_access_patterns` | uc only |
| `analyze_schema_drift` | uc only |
| `list_clusters` | cluster only |
| `get_cluster_config` | job, cluster |
| `get_cluster_health` | cluster only |
| `get_spark_logs` | job, cluster |
| `get_cluster_metrics` | cluster only |
| `get_cluster_events` | cluster only |
| `get_query_runtime_metrics` | query, warehouse |
| `build_analytics_context` | analytics only |
| `build_sql_query` | analytics only |
| `validate_sql_query` | analytics only |
| `execute_sql_query` | analytics only |
| `get_warehouse_portfolio` | warehouse only |
| `get_warehouse_fingerprint` | warehouse only |
| `get_warehouse_health` | warehouse only |
| `configure_warehouse_slo` | warehouse only |
| `analyze_warehouse_topology` | warehouse only |
| `get_warehouse_user_activity` | warehouse only |
| `generate_warehouse_chargeback` | warehouse only |
| `generate_portfolio_chargeback` | warehouse only |
| `start_discovery_analysis` | discovery only |
| `get_discovery_analysis_progress` | discovery only |
| `request_user_input` | all 9 domains |
| `complete` | all 9 domains |

---

## Tool Sharing Strategy

The tool system uses the **Pragmatic Hybrid (80/20)** approach:

- **80% of operations**: Agents complete independently using strategic tool overlap. For example, the Job agent has `get_cluster_config` because jobs run on clusters and frequently need cluster info.
- **20% of complex operations**: Agents delegate to the domain specialist. For example, complex lineage tracing (`get_table_lineage`) is exclusive to the UC agent.

**Design Principles**:

1. **Core tools shared by all agents** -- `complete` and `request_user_input`
2. **Frequent operations get shared tools** -- the 80% rule
3. **Complex/rare operations delegate to specialists** -- the 20% rule
4. **Domain experts get ALL tools in their domain**
5. **Diagnostic agent gets ALL tools** -- special unrestricted case

**Source**: `packages/starboard-server/starboard_server/agents/tool_categories.py`

---

## Related Documentation

- [Tool Architecture](../TOOL_ARCHITECTURE.md) -- Three-layer architecture details
- [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md) -- Overall system design
- [API Reference](../api/API_REFERENCE.md) -- REST API endpoints

---

**Last Updated**: 2026-03-24
**Version**: 3.0
