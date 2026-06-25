# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Tool bridge mapping MCP tool calls to ToolRegistry execution.

Generates MCP tool definitions from ``ALL_TOOL_METADATA``, injects an
optional ``workspace_id`` parameter, and orchestrates the full execution
pipeline: rate-limit → validate → resolve → auth → circuit-breaker → execute
→ format → sanitize.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

PHASE_A_TOOLS: frozenset[str] = frozenset(
    {
        "resolve_query",
        "resolve_job",
        "get_table_metadata",
        "get_warehouse_portfolio",
        "analyze_query_plan",
        "get_job_config",
        "list_uc_assets",
        "list_clusters",
        "get_query_runtime_metrics",
        "get_cluster_health",
        "get_warehouse_health",
    }
)

PHASE_B_TOOLS: frozenset[str] = PHASE_A_TOOLS | frozenset({
    # Job deep analysis
    "analyze_job_history", "get_run_output", "get_task_logs",
    "get_source_code", "analyze_code_quality",
    # UC deep analysis
    "get_table_lineage", "get_table_history", "analyze_table_schema",
    "analyze_storage_optimization", "get_table_fingerprint",
    "analyze_table_costs", "get_table_grants", "analyze_access_patterns",
    "analyze_schema_drift", "analyze_query_impact", "generate_schema_diff",
    "analyze_policy_coverage", "get_enriched_table_metadata",
    # Cluster deep analysis
    "get_cluster_config", "get_cluster_events", "get_cluster_metrics",
    "get_spark_logs",
    # Warehouse deep analysis
    "get_warehouse_fingerprint", "configure_warehouse_slo",
    "analyze_warehouse_topology", "get_warehouse_user_activity",
    "generate_warehouse_chargeback", "generate_portfolio_chargeback",
    # Discovery
    "discover_active_products", "run_discovery_queries",
    "analyze_discovery_domain", "start_discovery_analysis",
    "get_discovery_analysis_progress", "synthesize_discovery_report",
    # Analytics
    "build_analytics_context", "build_sql_query",
    "validate_sql_query", "execute_sql_query",
    # Cross-domain
    "discover_tables", "explore_artifact",
    "analyze_explain_plan",
})

SAFE_MODE_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "explore_artifact",
        "analyze_code_quality",
    }
)

# Internal tools that should never be exposed via MCP.
_INTERNAL_TOOLS: frozenset[str] = frozenset(
    {
        "request_user_input",
        "complete",
        "resolve_user_intent",
        "run_workspace_discovery",
    }
)


def tool_metadata_to_mcp_schema(meta: dict[str, Any]) -> dict[str, Any]:
    """Convert a tool metadata dict to an MCP-compatible tool definition.

    Adds an optional ``workspace_id`` property to the input schema so callers
    can override the default workspace on a per-call basis.

    Args:
        meta: Entry from ``ALL_TOOL_METADATA`` (keys: name, description, parameters).

    Returns:
        Dict with ``name``, ``description``, and ``inputSchema`` suitable for
        MCP ``list_tools`` responses.
    """
    params = copy.deepcopy(meta["parameters"])

    # Inject optional workspace_id parameter
    props = params.setdefault("properties", {})
    props["workspace_id"] = {
        "type": "string",
        "description": "Workspace ID override (uses default if omitted)",
    }
    # workspace_id must NOT be in required
    if "workspace_id" in params.get("required", []):
        params["required"] = [r for r in params["required"] if r != "workspace_id"]

    return {
        "name": meta["name"],
        "description": meta["description"],
        "inputSchema": params,
    }


def resolve_allowed_tools(
    *,
    safe_mode: bool = False,
    tool_scope: Literal["phase_a", "phase_b", "full"] = "phase_a",
) -> frozenset[str]:
    """Resolve the set of allowed tool names for a given mode and scope.

    Args:
        safe_mode: When ``True``, only offline-safe tools are returned.
        tool_scope: Tool scope level.

    Returns:
        Immutable set of allowed tool names.
    """
    if safe_mode:
        return SAFE_MODE_ALLOWED_TOOLS
    if tool_scope == "full":
        return frozenset(ALL_TOOL_METADATA.keys()) - _INTERNAL_TOOLS
    if tool_scope == "phase_b":
        return PHASE_B_TOOLS
    return PHASE_A_TOOLS


def get_mcp_tools(
    *,
    safe_mode: bool = False,
    tool_scope: Literal["phase_a", "phase_b", "full"] = "phase_a",
) -> list[dict[str, Any]]:
    """Return MCP tool definitions for the current mode.

    Args:
        safe_mode: When ``True``, only offline-safe tools are returned.
        tool_scope: Tool scope level (``"phase_a"``, ``"phase_b"``, or ``"full"``).

    Returns:
        List of MCP tool schema dicts.
    """
    allowed = resolve_allowed_tools(safe_mode=safe_mode, tool_scope=tool_scope)
    tools: list[dict[str, Any]] = []
    for name in sorted(allowed):
        meta = ALL_TOOL_METADATA.get(name)
        if meta is not None:
            tools.append(tool_metadata_to_mcp_schema(meta))
    return tools
