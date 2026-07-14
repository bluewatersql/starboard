# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Warehouse Portfolio Agent tool schemas.

Defines OpenAI function call schemas for warehouse tools.
These schemas describe parameters and return types for LLM tool calling.
"""

from typing import Any

# =============================================================================
# Portfolio Overview Tool
# =============================================================================

GET_WAREHOUSE_PORTFOLIO: dict[str, Any] = {
    "name": "get_warehouse_portfolio",
    "description": (
        "Get portfolio view of all SQL warehouses with health scores, "
        "performance metrics, and summary statistics.\n"
        "Returns: Warehouse list with health scores, cost, query counts, utilization.\n"
        "Use for: Fleet-wide visibility, identify warehouses needing attention.\n"
        "Cost: ~600 tokens | Prerequisites: None\n"
        "⚡ Parallel-safe: Yes - can call with other tools in ONE turn\n"
        "→ Next: get_warehouse_fingerprint (for deep dive), get_warehouse_health (for specific issues)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days (7, 30, or 90)",
                "default": 7,
                "enum": [7, 30, 90],
            },
            "include_inactive": {
                "type": "boolean",
                "description": "Include warehouses with no recent activity",
                "default": False,
            },
        },
        "required": [],
    },
}

# =============================================================================
# Warehouse Fingerprint Tool
# =============================================================================

GET_WAREHOUSE_FINGERPRINT: dict[str, Any] = {
    "name": "get_warehouse_fingerprint",
    "description": (
        "Generate detailed fingerprint for a specific warehouse including "
        "performance percentiles, workload patterns, time distribution, and "
        "query type breakdown.\n"
        "Returns: Detailed performance metrics, user breakdown, query patterns.\n"
        "Use for: Deep analysis of a single warehouse.\n"
        "Cost: ~800 tokens | Prerequisites: warehouse_id\n"
        "⚡ Parallel-safe: Yes - can call for multiple warehouses in ONE turn\n"
        "→ Next: get_warehouse_health (for SLO compliance), evaluate_warehouse_scenario (for optimization)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {
                "type": "string",
                "description": "The warehouse ID to analyze",
            },
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days",
                "default": 7,
                "enum": [7, 30, 90],
            },
        },
        "required": ["warehouse_id"],
    },
}

# =============================================================================
# Health Scoring Tool
# =============================================================================

GET_WAREHOUSE_HEALTH: dict[str, Any] = {
    "name": "get_warehouse_health",
    "description": (
        "Get health score and SLO compliance for a warehouse.\n"
        "Returns: Overall score (0-100), risk factors, SLO compliance, recommendations.\n"
        "Use for: Assess a specific warehouse's health and get actionable suggestions.\n"
        "Cost: ~500 tokens | Prerequisites: warehouse_id\n"
        "⚡ Parallel-safe: Yes - can call for multiple warehouses in ONE turn\n"
        "→ Next: evaluate_warehouse_scenario (if issues found), configure_warehouse_slo (to set targets)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {
                "type": "string",
                "description": "The warehouse ID to analyze",
            },
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days",
                "default": 7,
            },
        },
        "required": ["warehouse_id"],
    },
}

# =============================================================================
# SLO Management Tools
# =============================================================================

GET_WAREHOUSE_SLO: dict[str, Any] = {
    "name": "get_warehouse_slo",
    "description": (
        "Get current SLO configuration for a warehouse.\n"
        "Returns: Configured targets for latency, availability, and queue time.\n"
        "Cost: ~200 tokens | Prerequisites: warehouse_id\n"
        "⚡ Parallel-safe: Yes - can call for multiple warehouses in ONE turn\n"
        "→ Next: configure_warehouse_slo (to update targets)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {
                "type": "string",
                "description": "The warehouse ID",
            },
        },
        "required": ["warehouse_id"],
    },
}

CONFIGURE_WAREHOUSE_SLO: dict[str, Any] = {
    "name": "configure_warehouse_slo",
    "description": (
        "Configure SLO targets for a warehouse.\n"
        "Use preset profiles (interactive, batch_etl, critical_bi) or specify custom targets.\n"
        "SLOs affect health scoring and enable proactive alerting.\n"
        "Cost: ~100 tokens | Prerequisites: warehouse_id\n"
        "⚠️ Side effect: Modifies warehouse SLO configuration\n"
        "→ Next: get_warehouse_health (to verify new SLOs)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {
                "type": "string",
                "description": "The warehouse ID to configure",
            },
            "slo_profile": {
                "type": "string",
                "description": "Preset SLO profile",
                "enum": ["interactive", "batch_etl", "critical_bi"],
            },
            "p95_latency_target_sec": {
                "type": "number",
                "description": "P95 latency target in seconds (overrides profile)",
            },
            "availability_target_pct": {
                "type": "number",
                "description": "Availability target percentage (e.g., 99.9)",
            },
            "queue_time_target_sec": {
                "type": "number",
                "description": "Queue time target in seconds",
            },
        },
        "required": ["warehouse_id"],
    },
}

# =============================================================================
# What-If Analysis Tools
# =============================================================================

EVALUATE_WAREHOUSE_SCENARIO: dict[str, Any] = {
    "name": "evaluate_warehouse_scenario",
    "description": (
        "Evaluate a what-if scenario for warehouse configuration changes.\n"
        "Returns: Predicted cost, latency, and risk impact.\n"
        "Use for: Model effects of changes before implementing them.\n"
        "Cost: ~400 tokens | Prerequisites: warehouse_id\n"
        "⚡ Parallel-safe: Yes - can evaluate multiple scenarios in ONE turn\n"
        "→ Next: compare_warehouse_scenarios (for multiple options), complete (with recommendations)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {
                "type": "string",
                "description": "The warehouse ID to evaluate",
            },
            "scenario_type": {
                "type": "string",
                "description": "Type of change to evaluate",
                "enum": [
                    "serverless_migration",
                    "scale_up",
                    "scale_down",
                    "auto_stop_change",
                ],
            },
            "proposed_config": {
                "type": "object",
                "description": "Proposed configuration changes",
                "properties": {
                    "warehouse_type": {
                        "type": "string",
                        "enum": ["serverless", "standard"],
                    },
                    "min_clusters": {
                        "type": "integer",
                    },
                    "max_clusters": {
                        "type": "integer",
                    },
                    "auto_stop_minutes": {
                        "type": "integer",
                    },
                },
            },
        },
        "required": ["warehouse_id", "scenario_type"],
    },
}

COMPARE_WAREHOUSE_SCENARIOS: dict[str, Any] = {
    "name": "compare_warehouse_scenarios",
    "description": (
        "Compare multiple what-if scenarios side-by-side.\n"
        "Returns: Cost, performance, and risk comparison to help choose the best option.\n"
        "Use for: Deciding between optimization approaches.\n"
        "Cost: ~600 tokens | Prerequisites: warehouse_id\n"
        "⚡ Parallel-safe: No - consolidates multiple scenarios into one call\n"
        "→ Next: complete (with recommendation)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {
                "type": "string",
                "description": "The warehouse ID to evaluate",
            },
            "scenarios": {
                "type": "array",
                "description": "List of scenario configurations to compare",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Scenario name for identification",
                        },
                        "scenario_type": {
                            "type": "string",
                            "enum": [
                                "serverless_migration",
                                "scale_up",
                                "scale_down",
                                "auto_stop_change",
                            ],
                        },
                        "proposed_config": {
                            "type": "object",
                        },
                    },
                },
            },
        },
        "required": ["warehouse_id", "scenarios"],
    },
}

# =============================================================================
# Topology Analysis Tools
# =============================================================================

ANALYZE_WAREHOUSE_TOPOLOGY: dict[str, Any] = {
    "name": "analyze_warehouse_topology",
    "description": (
        "Analyze warehouse fleet topology for optimization opportunities.\n"
        "Returns: Similar/duplicate warehouses, workload clusters, consolidation opportunities.\n"
        "Use for: Fleet optimization, identifying redundant warehouses.\n"
        "Cost: ~800 tokens | Prerequisites: None\n"
        "⚡ Parallel-safe: Yes - can call with other portfolio tools in ONE turn\n"
        "→ Next: detect_warehouse_overlap (for details), complete (with recommendations)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days",
                "default": 7,
                "enum": [7, 30, 90],
            },
        },
        "required": [],
    },
}

DETECT_WAREHOUSE_OVERLAP: dict[str, Any] = {
    "name": "detect_warehouse_overlap",
    "description": (
        "Detect overlapping warehouses with similar workloads.\n"
        "Returns: Similarity scores, shared users, consolidation recommendations.\n"
        "Use for: Identifying candidates for warehouse consolidation.\n"
        "Cost: ~500 tokens | Prerequisites: None (or specific warehouse_ids)\n"
        "⚡ Parallel-safe: Yes - can call with other tools in ONE turn\n"
        "→ Next: get_warehouse_fingerprint (for affected warehouses), complete (with plan)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_ids": {
                "type": "array",
                "description": "Specific warehouse IDs to compare (optional, compares all if omitted)",
                "items": {"type": "string"},
            },
            "similarity_threshold": {
                "type": "number",
                "description": "Minimum similarity score to report (0-1)",
                "default": 0.6,
            },
        },
        "required": [],
    },
}

# =============================================================================
# User Activity & Chargeback Tools
# =============================================================================

GET_WAREHOUSE_USER_ACTIVITY: dict[str, Any] = {
    "name": "get_warehouse_user_activity",
    "description": (
        "Get user activity breakdown for warehouses.\n"
        "Returns: Who is using them, how much, and resource consumption.\n"
        "Use for: Understanding usage patterns, preparing chargeback data.\n"
        "Cost: ~500 tokens | Prerequisites: None (or warehouse_id for specific)\n"
        "⚡ Parallel-safe: Yes - can call with other tools in ONE turn\n"
        "→ Next: generate_warehouse_chargeback (with cost from portfolio)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {
                "type": "string",
                "description": "Specific warehouse ID (optional, omit for all)",
            },
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days",
                "default": 30,
            },
        },
        "required": [],
    },
}

GENERATE_WAREHOUSE_CHARGEBACK: dict[str, Any] = {
    "name": "generate_warehouse_chargeback",
    "description": (
        "Generate cost chargeback report for a specific warehouse.\n"
        "Returns: User cost allocations based on usage share.\n"
        "Use for: Cost attribution, accountability reporting.\n"
        "Cost: ~400 tokens | Prerequisites: warehouse_id, total_cost_usd (get from portfolio)\n"
        "⚡ Parallel-safe: Yes - can generate for multiple warehouses in ONE turn\n"
        "→ IMPORTANT: Get total_cost_usd from get_warehouse_portfolio first!"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "warehouse_id": {
                "type": "string",
                "description": "The warehouse ID to generate chargeback for",
            },
            "total_cost_usd": {
                "type": "number",
                "description": "Total cost to allocate across users",
            },
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days",
                "default": 30,
            },
            "allocation_method": {
                "type": "string",
                "description": "How to allocate costs",
                "enum": ["runtime", "queries", "bytes"],
                "default": "runtime",
            },
        },
        "required": ["warehouse_id", "total_cost_usd"],
    },
}

GENERATE_PORTFOLIO_CHARGEBACK: dict[str, Any] = {
    "name": "generate_portfolio_chargeback",
    "description": (
        "Generate chargeback report across all warehouses.\n"
        "Returns: Aggregated user costs portfolio-wide.\n"
        "Use for: Organization-level cost attribution.\n"
        "Cost: ~800 tokens | Prerequisites: None (auto-fetches costs)\n"
        "⚡ Parallel-safe: No - consolidates all warehouses into one report\n"
        "→ Next: complete (with cost attribution summary)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days",
                "default": 30,
            },
            "allocation_method": {
                "type": "string",
                "description": "How to allocate costs",
                "enum": ["runtime", "queries", "bytes"],
                "default": "runtime",
            },
        },
        "required": [],
    },
}
