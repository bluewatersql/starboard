"""Compute resource and infrastructure tool schemas."""

LIST_CLUSTERS = {
    "name": "list_clusters",
    "description": (
        "List compute clusters with recent activity (default: last 30 days).\n"
        "Returns: Cluster list with IDs, names, states, sizes, and summary.\n"
        "Note: Databricks clusters are ephemeral - most job/pipeline clusters will be TERMINATED.\n"
        "Use for: Fleet discovery, identifying clusters for analysis, overview.\n"
        "Cost: ~400 tokens | Prerequisites: None\n"
        "⚡ Parallel-safe: Yes - can call with other tools in ONE turn\n"
        "→ Next: get_cluster_config (for specific cluster), get_cluster_metrics (for utilization)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "window_days": {
                "type": "integer",
                "description": "Only include clusters with activity within this window (days)",
                "default": 30,
                "enum": [7, 14, 30, 60, 90],
            },
            "include_terminated": {
                "type": "boolean",
                "description": "Include terminated clusters (recommended: True for job/pipeline clusters)",
                "default": True,
            },
        },
        "required": [],
    },
}

GET_CLUSTER_CONFIG = {
    "name": "get_cluster_config",
    "description": (
        "Get cluster configuration: node types, autoscaling, Spark config.\n"
        "Cost: ~400 tokens | Prerequisites: cluster_id\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn (executes in parallel)"
    ),
    "parameters": {
        "type": "object",
        "properties": {"cluster_id": {"type": "string", "description": "Cluster ID"}},
        "required": ["cluster_id"],
    },
}

GET_WAREHOUSE_CONFIG = {
    "name": "get_warehouse_config",
    "description": (
        "Get warehouse configuration: size, autoscaling, min/max clusters.\n"
        "Cost: ~400 tokens | Prerequisites: warehouse_id\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn (executes in parallel)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {"type": "string", "description": "Warehouse ID"}
        },
        "required": ["warehouse_id"],
    },
}

GET_SPARK_LOGS = {
    "name": "get_spark_logs",
    "description": (
        "Get Spark UI logs for debugging: job performance, stage metrics, errors, OOMs.\n"
        "Returns: Spark UI analysis (jobs, stages, tasks) with performance metrics.\n"
        "If logs unavailable: Returns 'found: false' with reason - NOT an error.\n"
        "Cost: ~1-2K tokens | Prerequisites: cluster_id (get from analyze_job_history)\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn (executes in parallel)\n\n"
        "**HOW TO GET cluster_id:**\n"
        "→ Call analyze_job_history first - it returns cluster_id in the response\n"
        "→ Use that cluster_id to call this tool\n\n"
        "**LIMITATIONS:**\n"
        "→ Serverless compute: No logs (no cluster logging)\n"
        "→ Logging not configured: Returns {found: false}\n"
        "→ Recently finished jobs: Logs may have ~1-5 min delay"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cluster_id": {
                "type": "string",
                "description": "Cluster ID to fetch Spark logs for (get this from analyze_job_history)",
            },
        },
        "required": ["cluster_id"],
    },
}

GET_CLUSTER_EVENTS = {
    "name": "get_cluster_events",
    "description": (
        "Get cluster lifecycle events: start, terminate, scale, failures.\n"
        "Returns: Event timeline with timestamps.\n"
        "Cost: ~400 tokens | Prerequisites: cluster_id\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn (executes in parallel)\n"
        "→ Identifies: Frequent restarts, spot preemptions, autoscaling issues"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cluster_id": {"type": "string", "description": "Cluster ID"},
        },
        "required": ["cluster_id"],
    },
}

GET_CLUSTER_METRICS = {
    "name": "get_cluster_metrics",
    "description": (
        "Get cluster metrics: CPU, memory, disk, network, GC.\n"
        "Returns: Resource utilization per executor/driver.\n"
        "Cost: ~500 tokens | Prerequisites: cluster_id\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn (executes in parallel)\n"
        "→ Signals: High CPU → increase parallelism | Disk spill → increase memory | Low util → downsize"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cluster_id": {"type": "string", "description": "Cluster ID"},
        },
        "required": ["cluster_id"],
    },
}

GET_WAREHOUSE_METRICS = {
    "name": "get_warehouse_metrics",
    "description": (
        "Get warehouse metrics: query times, queue waits, concurrency, data scanned.\n"
        "Returns: Performance stats (p50, p95, p99).\n"
        "Cost: ~500 tokens | Prerequisites: warehouse_id\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn (executes in parallel)\n"
        "→ Signals: High queue → scale up | Low util → downsize | Large scans → add filters"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {"type": "string", "description": "Warehouse ID"},
        },
        "required": ["warehouse_id"],
    },
}

GET_QUERY_RUNTIME_METRICS = {
    "name": "get_query_runtime_metrics",
    "description": (
        "Get detailed query execution metrics: stage times, rows, shuffles, spills.\n"
        "Returns: Per-stage breakdown, task durations.\n"
        "Cost: ~600 tokens | Prerequisites: statement_id\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn (executes in parallel)\n"
        "→ Signals: Stage bottleneck, shuffle volume, skew (max >> median), spills"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "statement_id": {"type": "string", "description": "Query execution ID"},
        },
        "required": ["statement_id"],
    },
}

GET_CLUSTER_HEALTH = {
    "name": "get_cluster_health",
    "description": (
        "Get health score and risk analysis for a Databricks cluster.\n"
        "Returns: Overall health score (0-100), metric scores by dimension, identified risks, and recommendations.\n"
        "Use for: Cluster health assessment, risk identification, optimization recommendations.\n"
        "Cost: ~500 tokens | Prerequisites: cluster_id\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn (executes in parallel)\n"
        "→ Signals: Over-provisioned, under-provisioned, deprecated runtime, security risks"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cluster_id": {
                "type": "string",
                "description": "Cluster ID to analyze health for",
            },
        },
        "required": ["cluster_id"],
    },
}
