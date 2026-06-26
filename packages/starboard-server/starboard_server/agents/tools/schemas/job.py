# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Job analysis and tracking tool schemas."""

RESOLVE_JOB = {
    "name": "resolve_job",
    "description": (
        "Get job info from job_id or run_id. First step for job optimization.\n"
        "Returns: Job details (name, settings, last run status).\n"
        "Cost: ~100 tokens | Prerequisites: None\n"
        "⚡ Parallel-safe: Yes - can call with other tools in ONE turn\n"
        "→ Next: get_job_config"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "job_id or run_id - auto-detected",
            }
        },
        "required": ["target"],
    },
}

GET_JOB_CONFIG = {
    "name": "get_job_config",
    "description": (
        "Get full job configuration: cluster, tasks, Spark configs, libraries.\n"
        "Returns: Settings, task definitions, dependencies.\n"
        "Cost: ~500 tokens | Prerequisites: job_id\n"
        "⚡ Parallel-safe: NO - MUST be called exactly ONCE\n"
        "→ Next: get_source_code (using task_keys)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Databricks job ID"}
        },
        "required": ["job_id"],
    },
}

ANALYZE_JOB_HISTORY = {
    "name": "analyze_job_history",
    "description": (
        "Analyze job run history: failures, performance trends, duration.\n"
        "Returns: Success rate, avg duration, failures, cluster_id for Spark log lookup.\n"
        "Cost: ~600 tokens | Prerequisites: job_id\n"
        "⚡ Parallel-safe: Can call with other tools in ONE turn (executes in parallel)\n"
        "→ Returns cluster_id - use with get_spark_logs for detailed Spark metrics"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Job ID"},
            "lookback_days": {
                "type": "integer",
                "description": "Days of history (default: 7)",
            },
        },
        "required": ["job_id"],
    },
}

GET_RUN_OUTPUT = {
    "name": "get_run_output",
    "description": (
        "Get output and logs for a job run including ALL task-level outputs.\n"
        "Iterates through each task in the run to collect detailed diagnostics.\n"
        "Returns:\n"
        "  - state: Job run state (result_state, state_message)\n"
        "  - tasks[]: Per-task outputs with task_key, run_id, state, error, logs\n"
        "  - summary: Aggregated error messages from failed tasks\n"
        "Use when: Job failed and you need to understand which task failed and WHY.\n"
        "Cost: ~800+ tokens (scales with task count) | Prerequisites: run_id\n"
        "⚡ Parallel-safe: Yes - can call with other tools in ONE turn\n"
        "→ Check tasks[] for per-task errors, logs, and notebook_output"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Databricks job run ID (parent run, not task run)",
            }
        },
        "required": ["run_id"],
    },
}

GET_TASK_LOGS = {
    "name": "get_task_logs",
    "description": (
        "Get logs for a SPECIFIC task within a job run.\n"
        "Use when you know which task failed and need its detailed logs.\n"
        "More efficient than get_run_output when focusing on one task.\n"
        "Returns:\n"
        "  - logs: Task execution logs (Spark driver logs, stdout)\n"
        "  - error: Error message if task failed\n"
        "  - state: Task state (result_state, state_message)\n"
        "  - notebook_output: Notebook result if applicable\n"
        "  - duration: Task execution duration\n"
        "Cost: ~300 tokens | Prerequisites: run_id + task_key\n"
        "⚡ Parallel-safe: Yes - can call with other tools in ONE turn\n"
        "→ Use after get_run_output to drill into a specific failed task"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Databricks job run ID (from get_run_output or job history)",
            },
            "task_key": {
                "type": "string",
                "description": "Task key identifier (from tasks[] in get_run_output)",
            },
        },
        "required": ["run_id", "task_key"],
    },
}
