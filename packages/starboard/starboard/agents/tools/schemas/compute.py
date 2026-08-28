# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
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

GET_CLUSTER_RIGHTSIZING = {
    "name": "get_cluster_rightsizing",
    "description": (
        "Right-size a cluster: sizing verdict + list-price DBU cost exposure (CRS-06).\n"
        "Returns: Per-cluster sizing_direction (UNDER/OVER/BALANCED), recommended_action,\n"
        "target_cores_per_node, reduction_pct, dbus_per_day, and a labelled list-price\n"
        "DBU $/month estimate + potential monthly savings.\n"
        "All $ figures are LIST-PRICE DBU ESTIMATES (actual billed cost differs under contracted rates).\n"
        "Cost: ~600 tokens | Prerequisites: none (cluster_id optional to scope to one cluster)\n"
        "⚡ Parallel-safe: Can call with other get_* tools in ONE turn\n"
        "→ Signals: over-provisioned downsize candidates ranked by list-price DBU exposure"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cluster_id": {
                "type": "string",
                "description": "Optional cluster ID to scope the verdict to one cluster",
            },
            "lookback_days": {
                "type": "integer",
                "description": "Utilization/billing window in days (clamped to 90)",
                "default": 30,
            },
            "list_price_per_dbu": {
                "type": "number",
                "description": (
                    "Optional list-price $/DBU used for the estimate "
                    "(defaults to a public list-price rate; output is always "
                    "labelled a list-price DBU estimate)"
                ),
            },
        },
        "required": [],
    },
}

GET_WORKLOAD_RIGHTSIZING = {
    "name": "get_workload_rightsizing",
    "description": (
        "Right-size workloads (jobs + pipelines): unified verdict + reliability (CRS-07/08).\n"
        "Returns: Per-workload sizing_direction ranked by priority (UNDERPROVISIONED first),\n"
        "per-job reliability (run count, success rate, runtime p95), and a labelled\n"
        "list-price DBU cost exposure for the underlying compute.\n"
        "All $ figures are LIST-PRICE DBU ESTIMATES (actual billed cost differs under contracted rates).\n"
        "Cost: ~800 tokens | Prerequisites: none (workload_type/workload_id optional to scope)\n"
        "→ Feeds the autonomous cluster right-sizing monitor (report-only DRAFT/WARN)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "workload_type": {
                "type": "string",
                "description": "Optional filter: JOB or PIPELINE",
                "enum": ["JOB", "PIPELINE"],
            },
            "workload_id": {
                "type": "string",
                "description": "Optional workload ID (job_id or pipeline_id) to scope to one workload",
            },
            "lookback_days": {
                "type": "integer",
                "description": "Utilization/reliability window in days (clamped to 90)",
                "default": 30,
            },
            "list_price_per_dbu": {
                "type": "number",
                "description": (
                    "Optional list-price $/DBU for the cost estimate "
                    "(defaults to a public list-price rate; output labelled a "
                    "list-price DBU estimate)"
                ),
            },
        },
        "required": [],
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
