# Workflow: Job Debugging

This guide walks through an end-to-end workflow for investigating a Databricks job
that is failing or running slower than expected. You will learn what information to
provide, how the Job agent investigates, and how to interpret the debugging output.

---

## When to Use This Workflow

- A Databricks job is failing with errors.
- A job that used to be fast is now slow.
- You want to understand task dependencies and identify bottlenecks.
- You need to review the source code or notebooks attached to a job.
- You want recommendations for job configuration improvements.

---

## What the Job Agent Can Do

The Job Expert agent has access to the following tools:

| Tool | Purpose |
|------|---------|
| `resolve_job` | Look up job metadata from a job ID or name. |
| `get_job_config` | Retrieve job settings, tasks, schedules, and cluster policies. |
| `analyze_job_history` | Review past runs -- durations, success/failure rates, trends. |
| `get_run_output` | Get output and logs from a specific run. |
| `get_task_logs` | Get logs for a specific task within a multi-task job. |
| `get_source_code` | Fetch the notebook or script source code attached to a task. |
| `analyze_code_quality` | Run static analysis on source code for anti-patterns. |
| `get_cluster_config` | Check the cluster configuration used by the job. |
| `get_spark_logs` | Retrieve Spark driver/executor logs for deeper analysis. |
| `get_cluster_metrics` | Get compute metrics for serverless jobs via system tables. |
| `get_table_metadata` | Check tables referenced by the job. |
| `discover_tables` | Extract table references from job source code. |

---

## Step 1: Start the Conversation

### Scenario A: Job is failing

Provide the job ID and describe the failure:

**Web UI:**
```
Job 12345 failed in the last 3 runs. What is going wrong?
```

**CLI:**
```bash
starboard --goal "Job 12345 has been failing. Investigate the root cause."
```

### Scenario B: Job is slow

```
Job 12345 used to complete in 20 minutes but now takes over an hour.
What changed?
```

### Scenario C: Investigate a specific run

```
Analyze run 67890 of job 12345. The run failed at the transform_data task.
```

### Scenario D: Review job code

Upload the notebook or script for review:

**CLI:**
```bash
starboard --input-file notebooks/etl_pipeline.py \
          --goal "Review this ETL pipeline code for anti-patterns and performance issues"
```

!!! tip "Include as much context as possible"
    The more details you provide up front, the faster the agent can zero in on the
    issue. Mention specific task names, error messages, time ranges, or behavioral
    changes.

---

## Step 2: What the Agent Does

The Job Expert follows a systematic investigation pattern:

### Phase 1: Job Resolution

```
-> Resolve Job
-> Get Job Config
```

The agent retrieves the job's metadata including:

- Job name and ID.
- Task definitions (notebook paths, JAR tasks, Python scripts).
- Task dependencies (DAG structure).
- Schedule and trigger configuration.
- Cluster configuration (dedicated or shared, instance types, autoscaling).
- Retry policies and timeout settings.

### Phase 2: Run History Analysis

```
-> Analyze Job History
```

The agent reviews the last N runs to identify:

- **Success/failure rate** -- Is this a new problem or a recurring pattern?
- **Duration trends** -- Is the job getting progressively slower?
- **Failure patterns** -- Do failures correlate with time of day, data volume,
  or specific tasks?
- **Resource utilization** -- Are runs hitting memory or CPU limits?

### Phase 3: Failure Investigation (if applicable)

```
-> Get Run Output
-> Get Task Logs
```

For failing jobs, the agent retrieves:

- The run output including error messages and stack traces.
- Task-level logs for the specific task that failed.
- The Spark driver log for cluster-level errors (OOM, connectivity, etc.).

### Phase 4: Source Code Review

```
-> Get Source Code
-> Analyze Code Quality
```

The agent fetches and reviews the source code attached to the failing or slow task:

- **Anti-pattern detection** -- `SELECT *`, unbounded collects, missing partition
  pruning, Python UDFs where Spark SQL would suffice.
- **Data skew indicators** -- Joins on skewed keys, unbalanced partitions.
- **Resource waste** -- Unnecessary caching, redundant computations, over-broad
  imports.

### Phase 5: Cluster Analysis

```
-> Get Cluster Config
-> Get Spark Logs (or Get Cluster Metrics for serverless)
```

The agent checks whether the cluster configuration matches the workload:

- **Instance types** -- Are instances appropriate for the workload
  (compute-optimized vs. memory-optimized)?
- **Autoscaling** -- Is the min/max worker range appropriate?
- **Spark configuration** -- Are there suboptimal Spark settings?
- **Serverless** -- For serverless jobs, the agent uses system tables for metrics.

---

## Step 3: Understanding the Report

The Job Expert produces an **Advisor Report** with the following sections:

### Summary

A concise overview of the job, its current state, and the root cause (for failures)
or primary bottleneck (for slow jobs).

### Root Cause (for failures)

A clear explanation of why the job is failing, including:

- The specific error and where it occurs.
- The underlying cause (data issue, configuration problem, code bug, resource
  exhaustion).
- Whether the issue is new or has been present in multiple runs.

### Findings

Each finding follows the standard structure:

- **Title** -- Short description of the issue.
- **Impact** -- Severity (Critical, High, Medium, Low).
- **Effort** -- Remediation difficulty (Quick Win, Moderate, Significant).
- **Description** -- Detailed explanation.
- **Recommendation** -- Specific fix with code examples where applicable.

### Common Finding Types

#### Configuration Issues

> **Autoscaling Range Too Narrow**
>
> Impact: High | Effort: Quick Win
>
> The job is configured with min_workers=2, max_workers=4 but processing 500GB
> of data. The cluster hits maximum capacity and tasks queue, extending the
> total runtime by 3x.
>
> **Recommendation:** Increase max_workers to 16 or use a larger instance type
> (e.g., i3.2xlarge for I/O-heavy workloads).

#### Code Anti-Patterns

> **Unbounded `.collect()` on Large DataFrame**
>
> Impact: Critical | Effort: Moderate
>
> Line 45 of `transform_data.py` calls `.collect()` on a DataFrame with 50M
> rows, pulling all data to the driver and causing OOM (OutOfMemoryError).
>
> **Recommendation:** Replace with `.limit(1000).collect()` for sampling, or
> refactor to use Spark-native operations:
> ```python
> # Before (OOM risk)
> all_rows = df.collect()
> for row in all_rows:
>     process(row)
>
> # After (distributed)
> df.foreach(process)
> ```

#### Data Issues

> **Input Table Growth Exceeds Cluster Capacity**
>
> Impact: High | Effort: Moderate
>
> The `raw_events` input table has grown from 100GB to 800GB over 90 days.
> The job's cluster was sized for the original data volume and is now spilling
> 200GB to disk per run.
>
> **Recommendation:** Either increase cluster memory or add partition pruning
> to the read query to limit the data scanned per run.

### Task Dependency Analysis

For multi-task jobs, the agent maps the task DAG and identifies:

- **Critical path** -- The longest chain of dependent tasks that determines total
  runtime.
- **Bottleneck tasks** -- Tasks with disproportionately long durations.
- **Parallelism opportunities** -- Tasks that could run in parallel but are
  unnecessarily sequential.

---

## Step 4: Follow Up

After the initial report, common follow-up paths include:

### For Failures

```
Show me the full stack trace for the last failed run.
```

```
Is this the same error that caused failures last week?
```

```
What would happen if I increased driver memory to 32GB?
```

### For Slow Jobs

```
Which task is the bottleneck in the DAG?
```

```
Analyze the Spark logs for task transform_data to check for data skew.
```

```
What cluster configuration would you recommend for this workload?
```

### Cross-Domain Investigation

```
Analyze the tables this job reads from for partition efficiency.
```
This hands off to the UC Expert for deeper table analysis.

```
What is the cluster utilization for the past week?
```
This hands off to the Cluster Expert for fleet-level analysis.

---

## Example Conversation

---

**You:**
> Job 54321 has been failing for the last 3 runs. The error mentions
> OutOfMemoryError. What is going on?

**Job Expert** (thinking for 18s):
> *-> Resolve Job*
> *-> Get Job Config*
> *-> Analyze Job History*
> *-> Get Run Output*
> *-> Get Task Logs*
> *-> Get Source Code*
> *-> Get Cluster Config*

**Job Expert:**
> ## Job Failure Analysis: ETL Daily Pipeline (Job 54321)
>
> ### Summary
> Job "ETL Daily Pipeline" has failed 3 consecutive times with
> `java.lang.OutOfMemoryError: Java heap space` in the `aggregate_metrics`
> task. The root cause is a combination of data growth and an unbounded
> collect operation.
>
> ### Root Cause
> The `aggregate_metrics` notebook (line 78) calls `.toPandas()` on a
> DataFrame containing 120M rows. This attempts to load the entire dataset
> into driver memory (16GB), which is insufficient.
>
> The job succeeded until February 25 because the dataset was under 40M
> rows. A bulk data load on February 24 tripled the row count.
>
> ### Findings
>
> **1. Unbounded `.toPandas()` on Large Dataset (Impact: Critical)**
> Line 78: `pdf = spark_df.toPandas()` attempts to materialize 120M rows
> (estimated 18GB) into the 16GB driver.
>
> Recommendation: Use Spark-native aggregation or limit the conversion:
> ```python
> # Option 1: Aggregate in Spark first
> result = spark_df.groupBy("date", "region").agg(
>     F.sum("revenue").alias("total_revenue"),
>     F.count("*").alias("order_count")
> ).toPandas()  # Now only ~10K rows
>
> # Option 2: Use Arrow-based conversion with batching
> for batch in spark_df.toLocalIterator():
>     process_batch(batch)
> ```
>
> **2. Driver Memory Undersized (Impact: High)**
> Driver is configured with 16GB but workload requires at least 24GB
> even after optimization.
>
> Recommendation: Increase driver memory to 32GB as a safety margin:
> ```json
> { "driver_node_type_id": "r5.2xlarge" }
> ```
>
> **3. No Retry Policy on Critical Task (Impact: Medium)**
> The `aggregate_metrics` task has no retry configuration. Adding retries
> with increased memory would provide resilience.

**What would you like to do next?**

1. See the full code for `aggregate_metrics` with annotations -- **Continue**
2. Analyze the input tables for data growth patterns -- **Expert** (UC)
3. Review the cluster configuration in detail -- **Expert** (Cluster)

---

## Tips

!!! tip "Mention the error message"
    If you know the error (OutOfMemoryError, TimeoutException,
    FileNotFoundException), include it in your question. This helps the agent
    focus the investigation immediately.

!!! tip "Specify the task name for multi-task jobs"
    Multi-task jobs can have dozens of tasks. If you know which task is failing
    or slow, mention it: "The `transform_data` task in job 12345 is the bottleneck."

!!! tip "Use diagnostic mode for cross-cutting issues"
    If a job failure involves cluster problems, data issues, and code bugs
    simultaneously, use diagnostic mode for unrestricted tool access:
    ```bash
    starboard --mode diagnostic \
              --goal "Job 12345 fails intermittently -- sometimes OOM, sometimes timeout"
    ```

!!! note "Standard vs. serverless jobs"
    The agent automatically detects whether a job runs on a standard cluster or
    serverless compute. For standard clusters, it uses Spark logs. For serverless
    jobs, it queries system tables for compute metrics. No special configuration
    is needed.
