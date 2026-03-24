# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Tool bridge mapping MCP tool calls to ToolRegistry execution.

Generates MCP tool definitions from ``ALL_TOOL_METADATA``, injects an
optional ``workspace_id`` parameter, and orchestrates the full execution
pipeline: rate-limit → validate → resolve → auth → circuit-breaker → execute
→ format → sanitize.
"""

from __future__ import annotations

import copy
from typing import Any

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


def get_mcp_tools(*, safe_mode: bool = False) -> list[dict[str, Any]]:
    """Return MCP tool definitions for the current mode.

    Args:
        safe_mode: When ``True``, only offline-safe tools are returned.

    Returns:
        List of MCP tool schema dicts.
    """
    allowed = SAFE_MODE_ALLOWED_TOOLS if safe_mode else PHASE_A_TOOLS
    tools: list[dict[str, Any]] = []
    for name in sorted(allowed):
        meta = ALL_TOOL_METADATA.get(name)
        if meta is not None:
            tools.append(tool_metadata_to_mcp_schema(meta))
    return tools
