# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Source code analysis tool schemas."""

ANALYZE_CODE_QUALITY = {
    "name": "analyze_code_quality",
    "description": (
        "Analyze Spark/PySpark code for anti-patterns: expensive ops, inefficient transformations.\n"
        "⚡ Parallel-safe: Can call with other tools in ONE turn (executes in parallel)\n"
        "Cost: ~800 tokens | Prerequisites: Source code"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source_code": {"type": "string", "description": "Spark/PySpark code"},
            "job_id": {
                "type": "string",
                "description": "Optional job ID to fetch sources from",
            },
            "task_key": {
                "type": "string",
                "description": "Optional task key for context (requires job_id)",
            },
            "language": {
                "type": "string",
                "enum": ["python", "scala", "sql"],
                "description": "Code language",
            },
        },
        "required": [],
    },
}

GET_SOURCE_CODE = {
    "name": "get_source_code",
    "description": (
        "Get source code for job tasks. CRITICAL - always try first.\n"
        "Returns: Full notebook/script code with line numbers.\n"
        "Cost: ~2K tokens | Prerequisites: job_id, task_key from get_job_config\n"
        "⚡ Parallel-safe: Call for multiple task_keys in ONE turn (executes in parallel)\n"
        "→ If successful: analyze_code_quality, discover_tables\n"
        "→ If fails (restricted notebook): report limitation\n"
        "Why critical: Shows anti-patterns explaining Spark UI bottlenecks"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Job ID"},
            "task_key": {
                "type": "string",
                "description": "Task key from get_job_config",
            },
        },
        "required": ["job_id", "task_key"],
    },
}
