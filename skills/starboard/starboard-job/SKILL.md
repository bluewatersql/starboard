name: starboard-job
description: Analyze Databricks job configuration, run history, failures, and performance. Use when user mentions jobs, runs, workflows, DAGs, or job IDs.
  Triggers on: job, run, failure, task, workflow, DAG, schedule, notebook job, job_id.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path (Agent Tool)

For comprehensive analysis, call the `job_agent` MCP tool with a natural language message.
The agent runs a full reasoning loop with automatic tool selection and multi-step analysis.

Example:
```
Call MCP tool: job_agent
Arguments: { "message": "Analyze job 12345 — it failed 3 times this week and I need to understand why" }
```

## Manual Workflow (Individual Tools)

For targeted analysis or when you need specific data points:

1. **Resolve the job** — Call `resolve_job` with `target: "<job_id or run_id>"`
   - Returns: Job metadata, current status, recent run summary, creator, schedule
   - Use when: You have a job ID or run ID and need basic job information

2. **Get full configuration** — Call `get_job_config` with `job_id: "<id>"`
   - Returns: Complete job definition including tasks, clusters, libraries, parameters, schedule, notifications
   - Use when: You need to review the job setup for misconfiguration or optimization opportunities

3. **Analyze run history** — Call `analyze_job_history` with `job_id: "<id>"`
   - Returns: Run duration trends, success/failure rates, P50/P95 durations, failure patterns over time
   - Use when: You need to identify performance regressions or recurring failure patterns

4. **Get run output** — Call `get_run_output` with `run_id: "<id>"`
   - Returns: Task results, output logs, error messages, and exit codes for a specific run
   - Use when: A specific run failed and you need to see what happened

5. **Get task logs** — Call `get_task_logs` with `run_id: "<id>"`, `task_key: "<key>"`
   - Returns: Detailed logs (stdout/stderr) for a specific task within a multi-task job
   - Use when: You need to drill into a specific failing task in a DAG/workflow

6. **Get source code** — Call `get_source_code` with `job_id: "<id>"`, `task_key: "<key>"`
   - Returns: Notebook or script source code for a task
   - Use when: You need to review the code a task executes for anti-patterns or bugs

7. **Analyze code quality** — Call `analyze_code_quality` (pass source code context)
   - Returns: Anti-pattern detection, Spark best practice violations, performance issues in code
   - Use when: You have source code and want to identify Spark/PySpark anti-patterns

8. **Check cluster configuration** — Call `get_cluster_config` with `cluster_id: "<id>"`
   - Returns: Cluster spec, instance types, autoscaling config, Spark conf, libraries
   - Use when: Job performance may be affected by its cluster sizing or configuration

## Available MCP Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `resolve_job` | Get job info from job_id or run_id | `target` |
| `get_job_config` | Get full job configuration and task definitions | `job_id` |
| `analyze_job_history` | Analyze run history, trends, and failure patterns | `job_id` |
| `get_run_output` | Get output and logs for a specific job run | `run_id` |
| `get_task_logs` | Get detailed logs for a specific task in a run | `run_id`, `task_key` |
| `get_source_code` | Get source code for a job task | `job_id`, `task_key` |
| `analyze_code_quality` | Analyze Spark/PySpark code for anti-patterns | (source code context) |
| `get_cluster_config` | Get cluster configuration for the job's compute | `cluster_id` |
| `job_agent` | Full job analysis with automatic tool selection | `message` |

## Composite Tools

| Tool | Description | Chains |
|------|-------------|--------|
| `get_job_summary` | Quick job overview with config and status | `resolve_job` -> `get_job_config` -> latest run status |

## Example Prompts

- "Job 12345 has been failing every night at 2am for the past week. What's going wrong?"
- "Analyze the performance history of job 67890 — it used to run in 30 minutes but now takes over 2 hours"
- "Review the configuration and source code of job 11111 and suggest optimizations for cost and performance"
- "Show me the task dependency graph for job 54321 and identify which tasks are bottlenecks"
- "Get the error logs from the latest failed run of job 98765 and help me debug the root cause"

## Interpreting Results

When analyzing job results, focus on these key indicators:

- **Failure patterns**: Look for recurring failures at the same time, same task, or same error. Common root causes include upstream data delays, credential expiration, resource contention, and OOM errors.
- **Retry configuration**: Check if retries are configured. Jobs without retries fail permanently on transient errors. Too many retries mask persistent issues and waste compute.
- **Cluster sizing**: Compare cluster configuration against workload needs. Over-provisioned clusters waste cost; under-provisioned clusters cause spills, OOM, and slow shuffles. Look at the job's Spark event logs for executor utilization.
- **Task dependency bottlenecks**: In multi-task workflows, identify the critical path. A single slow task can block all downstream tasks. Look for tasks with high duration variance — they indicate instability.
- **Code quality anti-patterns**: Common Spark anti-patterns include: collecting large datasets to driver (`collect()` on big data), Python UDFs instead of native Spark functions, excessive repartitioning, missing cache/persist for reused DataFrames, and cartesian joins.
- **Schedule alignment**: Check if the job schedule conflicts with other heavy workloads or if upstream dependencies complete before this job starts.
- **Duration trends**: A steadily increasing duration usually indicates growing data volume without corresponding cluster scaling or code optimization. Sudden jumps often point to schema changes, data quality issues, or infrastructure problems.
