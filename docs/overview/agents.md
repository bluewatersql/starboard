# Agent Catalog

Starboard AI Agent uses **8 domain-specialized agents**, each with dedicated tools, prompts, and Databricks expertise. An Intent Router automatically dispatches user requests to the appropriate agent.

---

## How Routing Works

When you send a message, the **Intent Router** classifies your request using a hybrid approach:

1. **Pattern matching** — Fast keyword and regex matching for common patterns
2. **LLM classification** — For ambiguous requests, an LLM call determines the best agent

The router considers confidence scores and can trigger **agent handoffs** when a question spans multiple domains (e.g., a job analysis that reveals a cluster sizing issue).

---

## Agent Overview

### Query Agent

**Domain:** SQL query optimization and analysis

**When to use:** You have a slow SQL query, want to understand a query plan, or need optimization recommendations.

**Key tools:** `resolve_query`, `analyze_query_plan`, `get_query_runtime_metrics`, `discover_tables`

**Example questions:**
- "Why is this SELECT query taking 45 minutes?"
- "Analyze the explain plan for statement ID 01abc..."
- "How can I optimize this join between two large tables?"

[Full documentation →](../agents/domain/query.md)

---

### Job Agent

**Domain:** Databricks job performance and debugging

**When to use:** A job is failing, running slowly, or you want to optimize job configurations.

**Key tools:** `resolve_job`, `get_job_config`, `analyze_job_history`, `get_run_output`, `get_task_logs`, `get_source_code`, `analyze_code_quality`

**Example questions:**
- "Why did job 12345 fail last night?"
- "Show me the performance trend for my nightly ETL job"
- "What's causing the task dependency bottleneck in this workflow?"

[Full documentation →](../agents/domain/job.md)

---

### UC Agent (Unity Catalog)

**Domain:** Metadata, lineage, governance, and storage optimization

**When to use:** You need to explore catalog assets, trace data lineage, audit access patterns, or optimize storage.

**Key tools:** `list_uc_assets`, `get_table_metadata`, `get_table_lineage`, `get_table_grants`, `analyze_table_schema`, `get_table_history`, `analyze_access_patterns`, `analyze_storage_optimization`, `analyze_policy_coverage`

**Example questions:**
- "Show me all tables in the sales catalog"
- "What's the lineage for the revenue_summary table?"
- "Which tables have no access policies configured?"
- "How much storage could we save by optimizing this table?"

[Full documentation →](../agents/domain/uc.md)

---

### Cluster Agent

**Domain:** Compute cluster configuration, health, and optimization

**When to use:** You want to right-size clusters, diagnose cluster issues, or understand resource utilization.

**Key tools:** `list_clusters`, `get_cluster_config`, `get_cluster_health`, `get_cluster_metrics`, `get_cluster_events`, `get_spark_logs`

**Example questions:**
- "Is my interactive cluster right-sized for its workload?"
- "Show me cluster utilization for the last 7 days"
- "Why does this cluster keep restarting?"

[Full documentation →](../agents/domain/cluster.md)

---

### Analytics Agent (FinOps)

**Domain:** Cost analysis, billing, chargeback, and budget forecasting

**When to use:** You need cost breakdowns, want to generate chargeback reports, or identify spending optimization opportunities.

**Key tools:** FinOps-specific analysis and reporting tools

**Example questions:**
- "What's our Databricks spend for the last quarter?"
- "Generate a chargeback report by team"
- "Which workloads are the most expensive?"
- "Forecast our costs for next month"

[Full documentation →](../agents/domain/analytics.md)

---

### Warehouse Agent

**Domain:** SQL warehouse portfolio management and optimization

**When to use:** You want to optimize warehouse configurations, analyze usage patterns, or generate warehouse-level chargeback reports.

**Key tools:** `get_warehouse_portfolio`, `get_warehouse_fingerprint`, `get_warehouse_health`, `configure_warehouse_slo`, `analyze_warehouse_topology`, `get_warehouse_user_activity`, `generate_warehouse_chargeback`, `generate_portfolio_chargeback`

**Example questions:**
- "Show me our SQL warehouse portfolio"
- "Which warehouses are over-provisioned?"
- "Generate a chargeback report for the data warehouse"
- "What SLO should I set for the reporting warehouse?"

[Full documentation →](../agents/domain/warehouse.md)

---

### Discovery Agent

**Domain:** Workspace-wide health assessment and resource inventory

**When to use:** You want a holistic view of your Databricks workspace, need to assess overall health, or want to inventory resources.

**Key tools:** Discovery-specific scanning and assessment tools

**Example questions:**
- "Run a health assessment on this workspace"
- "What resources exist in this workspace?"
- "Are there any misconfigured resources?"

[Full documentation →](../agents/domain/discovery.md)

---

### Diagnostic Agent

**Domain:** Cross-domain troubleshooting and root cause analysis

**When to use:** You have a complex issue that might span multiple domains, need root cause analysis, or want debugging assistance.

**Key tools:** Cross-domain diagnostic and debugging tools

**Example questions:**
- "My pipeline is slow and I don't know why"
- "Help me troubleshoot this intermittent failure"
- "What's the root cause of these timeout errors?"

[Full documentation →](../agents/domain/diagnostic.md)

---

## Agent Capabilities Matrix

| Capability | Query | Job | UC | Cluster | Analytics | Warehouse | Discovery | Diagnostic |
|-----------|:-----:|:---:|:--:|:-------:|:---------:|:---------:|:---------:|:----------:|
| Read Databricks APIs | x | x | x | x | x | x | x | x |
| SQL Analysis | x | | | | | x | | |
| Cost Analysis | | | | | x | x | | |
| Lineage Tracing | | | x | | | | | |
| Log Analysis | | x | | | | | | x |
| Health Scoring | | | | x | | x | x | |
| Cross-Agent Handoff | x | x | x | x | x | x | x | x |

---

## Cross-Agent Scenarios

Complex questions often involve multiple agents working together:

| Scenario | Agents Involved |
|----------|----------------|
| Debug a failing job → discover cluster is undersized | Job → Cluster |
| Optimize a query → trace lineage to find source tables | Query → UC |
| Cost analysis → identify expensive warehouses → right-size | Analytics → Warehouse |
| Workspace assessment → find ungoverned tables → audit access | Discovery → UC |
| Pipeline debugging → check job, query, and cluster health | Diagnostic → Job → Query → Cluster |
