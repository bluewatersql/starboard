name: starboard-diagnostic
description: Troubleshoot Databricks issues with error detection, log analysis, and root cause analysis. Use when user mentions errors, debugging, troubleshooting, or failures.
  Triggers on: error, debug, troubleshoot, failing, broken, root cause, logs, stack trace, exception.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path

Two modes are available. **Direct orchestration** gives you full control and avoids double-LLM cost. **Auto-pilot** delegates everything to the server-side agent.

### Direct Orchestration (Recommended)

1. Fetch MCP resource `starboard://prompts/diagnostic` — this returns the expert system prompt with troubleshooting workflows, cross-domain correlation patterns, and root cause analysis strategies.
2. Follow the returned prompt's guidance to call tools directly based on the user's error or issue.
3. Gather signals from multiple domains (jobs, clusters, queries, tables) and correlate them as the prompt directs.

### Auto-Pilot

Call MCP tool `diagnostic_agent` with:
```json
{ "message": "<the user's original error description or troubleshooting request>" }
```
Wait for the result (the diagnostic agent correlates signals across jobs, clusters, queries, and tables).

If the user did not specify a resource, use: `{ "message": "Run a health check and identify any current issues or anomalies" }`

## Manual Workflow (Individual Tools)

For systematic debugging, gather information from multiple domains before diagnosing.
Cross-reference signals across jobs, clusters, queries, and tables to isolate root cause.

1. **Identify the failure** — Start by resolving the failing resource
   - For job failures: Call `resolve_job` with `target: <job_id or name>` to get job details
   - For query failures: Call `resolve_query` with `target: <statement_id or SQL>` to get query details
   - Returns: Resource identity, status, and recent execution history

2. **Get execution details** — Retrieve logs and output from the failed run
   - Call `get_run_output` with `run_id: <run_id>` for job run output and error messages
   - Call `get_task_logs` with `run_id: <run_id>` for detailed task-level logs and stack traces
   - Call `get_query_runtime_metrics` with `statement_id: <id>` for query execution metrics
   - Returns: Error messages, stack traces, runtime metrics, and execution timeline

3. **Check cluster state at time of failure** — Correlate with infrastructure events
   - Call `get_cluster_events` with `cluster_id: <id>` to find resize, termination, or OOM events
   - Call `get_cluster_metrics` with `cluster_id: <id>` for CPU, memory, and disk at failure time
   - Call `get_spark_logs` with `cluster_id: <id>` for Spark executor and shuffle errors
   - Returns: Infrastructure events, resource utilization, and Spark-level diagnostics

4. **Examine job configuration** — Check for misconfiguration
   - Call `get_job_config` with `job_id: <id>` for cluster spec, retry policy, and task setup
   - Call `get_source_code` with `job_id: <id>` for the notebook or script being executed
   - Call `analyze_code_quality` with `source_code: <code>` for anti-patterns in the code
   - Returns: Configuration details, source code, and quality analysis

5. **Check upstream data** — Verify table health if failure may be data-related
   - Call `get_table_metadata` with `table_name: <name>` for schema and row counts
   - Call `get_table_history` with `table_name: <name>` for recent operations (unexpected writes, schema changes)
   - Call `analyze_schema_drift` with `table_name: <name>` if schema changes are suspected
   - Returns: Table state, recent modifications, and schema evolution

6. **Analyze patterns** — Look for recurring issues
   - Call `analyze_job_history` with `job_id: <id>` for failure trends over time
   - Call `get_cluster_health` with `cluster_id: <id>` for overall cluster risk score
   - Returns: Historical patterns, failure frequency, and systemic risk indicators

## Available MCP Tools

The diagnostic agent has access to ALL Starboard tools. Key tools for troubleshooting:

| Tool | Description | Required Params | Domain |
|------|-------------|-----------------|--------|
| `diagnostic_agent` | Full troubleshooting with cross-domain analysis | `message` | Agent |
| `resolve_job` | Resolve job by ID or name | `target` | Job |
| `get_job_config` | Get job configuration | `job_id` | Job |
| `analyze_job_history` | Analyze job run history and failure patterns | `job_id` | Job |
| `get_run_output` | Get run output and error messages | `run_id` | Job |
| `get_task_logs` | Get detailed task logs and stack traces | `run_id` | Job |
| `get_source_code` | Get notebook/script source code | `job_id` | Job |
| `analyze_code_quality` | Analyze code for anti-patterns | `source_code` | Job |
| `resolve_query` | Resolve query by statement ID | `target` | Query |
| `get_query_runtime_metrics` | Get query execution metrics | `statement_id` | Query |
| `analyze_query_plan` | Analyze query execution plan | `sql_text` | Query |
| `list_clusters` | List all clusters | (none) | Cluster |
| `get_cluster_config` | Get cluster configuration | `cluster_id` | Cluster |
| `get_cluster_health` | Get cluster health score | `cluster_id` | Cluster |
| `get_cluster_metrics` | Get CPU, memory, disk metrics | `cluster_id` | Cluster |
| `get_cluster_events` | Get lifecycle events | `cluster_id` | Cluster |
| `get_spark_logs` | Get Spark UI logs | `cluster_id` | Cluster |
| `get_table_metadata` | Get table metadata | `table_name` | UC |
| `get_table_history` | Get Delta table history | `table_name` | UC |
| `analyze_schema_drift` | Analyze schema drift | `table_name` | UC |
| `analyze_storage_optimization` | Storage optimization recs | `table_name` | UC |

## Example Prompts

- "Job 98765 has been failing intermittently for the past week -- find the root cause and suggest a fix"
- "I'm getting a ClassNotFoundException in my Spark job on cluster 0315-182023-abcde. What's wrong?"
- "Our nightly ETL pipeline timed out last night. Check the job runs, cluster events, and upstream tables for issues"
- "Debug why queries against catalog.prod.transactions are suddenly 10x slower than last week"
- "The Spark executor on cluster 0422-091500-xyz keeps running out of memory. Analyze the workload and recommend fixes"

## Interpreting Results

**Error Pattern Recognition**: Correlate error types with likely causes. `OutOfMemoryError` on executors suggests data skew, insufficient memory, or large broadcast joins. `ClassNotFoundException` indicates missing library dependencies or cluster init script failures. `AnalysisException` points to schema mismatches or missing tables. `TimeoutException` may indicate network issues, long-running queries, or resource contention.

**Cross-Domain Correlation**: The most powerful diagnostic technique is correlating signals across domains. A job failure (job domain) that coincides with a cluster resize event (cluster domain) and a schema change on an upstream table (UC domain) tells a much richer story than any single signal alone. Always check at least two domains when diagnosing non-trivial failures.

**Root Cause vs. Symptom**: Distinguish between root cause and symptoms. An OOM error (symptom) may be caused by data skew in a join (root cause), which itself may be caused by a schema drift that changed a join key from unique to non-unique (deeper root cause). Follow the chain: error message -> execution metrics -> cluster state -> data state -> code quality.

**Remediation Steps**: After identifying root cause, recommend specific fixes ordered by impact and effort. Quick wins include Spark config tuning (shuffle partitions, memory settings), retry policies, and auto-termination settings. Medium-effort fixes include query rewrites, partition strategies, and cluster right-sizing. High-effort fixes include pipeline redesign, schema refactoring, and data model changes.

**Recurring Failures**: When `analyze_job_history` shows repeated failures, look for patterns in timing (same time daily = resource contention or upstream dependency), error type (same error = systemic issue), and cluster (same cluster = infrastructure problem). Intermittent failures with different errors often indicate resource exhaustion under variable load.
