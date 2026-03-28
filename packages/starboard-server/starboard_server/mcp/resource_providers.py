# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""MCP resource providers for catalog, health, and prompt introspection.

Implements ``list_resources`` / ``read_resource`` with resources:

- ``starboard://workspace/info``       — workspace config (no secrets)
- ``starboard://agents/catalog``       — domain agents and their tools
- ``starboard://tools/catalog``        — full tool inventory
- ``starboard://tools/dependencies``   — tool dependency graph
- ``starboard://health``               — server health snapshot
- ``starboard://prompts/{domain}``     — domain agent system prompts (8 domains)
"""

from __future__ import annotations

import time
from typing import Any

from starboard_server.agents.tool_categories import TOOL_CATEGORIES
from starboard_server.agents.tools.registry import ALL_TOOL_METADATA
from starboard_server.mcp.agent_bridge import AGENT_DOMAINS
from starboard_server.mcp.circuit_breaker_registry import MCPCircuitBreakerRegistry
from starboard_server.mcp.config import MCPServerConfig
from starboard_server.mcp.exceptions import ExecutionError
from starboard_server.mcp.tool_bridge import PHASE_A_TOOLS

# Static dependency map for composite/chained tool usage.
TOOL_DEPENDENCIES: dict[str, list[str]] = {
    "analyze_query_plan": ["resolve_query"],
    "get_job_config": ["resolve_job"],
    "get_table_history": ["get_table_metadata"],
    "analyze_job_history": ["resolve_job"],
    "get_run_output": ["resolve_job"],
    "get_task_logs": ["resolve_job"],
    "get_source_code": ["resolve_job"],
}


class StarboardResourceProvider:
    """Serves MCP resources for catalog and health introspection.

    Args:
        config: Server configuration.
        circuit_breakers: Per-workspace circuit breaker registry.
    """

    _DOMAIN_PROMPT_DESCRIPTIONS: dict[str, str] = {
        "query": "SQL query optimization expert guidance — tool ordering, Databricks SQL knowledge, and analysis workflows",
        "job": "Databricks job performance analysis — Spark tuning, cluster sizing, and job optimization workflows",
        "uc": "Unity Catalog governance expert — lineage, access control, schema intelligence, and storage optimization",
        "cluster": "Cluster configuration and optimization — autoscaling, instance types, Spark configs",
        "analytics": "FinOps cost analysis and billing — consumption trends, budget forecasting, chargeback",
        "warehouse": "SQL warehouse portfolio optimization — concurrency, sizing, SLO configuration",
        "diagnostic": "Troubleshooting and root cause analysis — error diagnosis, performance debugging",
        "discovery": "Workspace health assessment — cross-domain analysis, optimization opportunities",
    }

    _RESOURCES: list[dict[str, str]] = [
        {
            "uri": "starboard://workspace/info",
            "name": "Workspace Info",
            "description": "Workspace configuration (no secrets)",
        },
        {
            "uri": "starboard://agents/catalog",
            "name": "Agent Catalog",
            "description": "Available domain agents with capabilities",
        },
        {
            "uri": "starboard://tools/catalog",
            "name": "Tool Catalog",
            "description": "Full tool inventory with schemas",
        },
        {
            "uri": "starboard://tools/dependencies",
            "name": "Tool Dependencies",
            "description": "Tool dependency graph for chaining",
        },
        {
            "uri": "starboard://health",
            "name": "Server Health",
            "description": "Server health, circuit breakers, rate limits",
        },
        *[
            {
                "uri": f"starboard://prompts/{domain}",
                "name": f"{domain.title()} Agent Prompt",
                "description": desc,
            }
            for domain, desc in _DOMAIN_PROMPT_DESCRIPTIONS.items()
            if domain in AGENT_DOMAINS
        ],
    ]

    def __init__(
        self,
        config: MCPServerConfig,
        circuit_breakers: MCPCircuitBreakerRegistry | None = None,
    ) -> None:
        self._config = config
        self._circuit_breakers = circuit_breakers
        self._start_time = time.monotonic()

    def list_resources(self) -> list[dict[str, str]]:
        """Return metadata for all available resources."""
        return list(self._RESOURCES)

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a single resource by URI.

        Args:
            uri: Resource URI (e.g. ``starboard://workspace/info``).

        Returns:
            Resource payload as a dict.

        Raises:
            ExecutionError: If URI is unknown.
        """
        handlers: dict[str, Any] = {
            "starboard://workspace/info": self._workspace_info,
            "starboard://agents/catalog": self._agents_catalog,
            "starboard://tools/catalog": self._tools_catalog,
            "starboard://tools/dependencies": self._tools_dependencies,
            "starboard://health": self._health,
        }
        handler = handlers.get(uri)
        if handler is not None:
            return handler()

        # Dynamic prompt resources: starboard://prompts/{domain}
        if uri.startswith("starboard://prompts/"):
            domain = uri.removeprefix("starboard://prompts/")
            if domain in AGENT_DOMAINS:
                return self._domain_prompt(domain)

        raise ExecutionError(
            f"Unknown resource URI: {uri!r}",
            code="EXEC_UNKNOWN_RESOURCE",
        )

    # ------------------------------------------------------------------
    # Resource handlers
    # ------------------------------------------------------------------

    def _workspace_info(self) -> dict[str, Any]:
        workspaces: dict[str, Any] = {}
        for ws_id, profile in self._config.workspaces.items():
            workspaces[ws_id] = {
                "host": profile.host,
                "warehouse_id": profile.warehouse_id,
                "default_catalog": profile.default_catalog,
            }
        return {
            "default_workspace_id": self._config.default_workspace_id,
            "workspaces": workspaces,
            "server_version": self._config.schema_version,
            "safe_mode": self._config.safe_mode,
        }

    def _agents_catalog(self) -> dict[str, Any]:
        agents: list[dict[str, Any]] = []
        _descriptions: dict[str, str] = {
            "query": "SQL query analysis and optimization",
            "job": "Databricks job performance tuning",
            "uc": "Unity Catalog metadata, lineage, governance",
            "cluster": "Cluster configuration and optimization",
            "analytics": "FinOps cost analysis and billing",
            "warehouse": "SQL warehouse portfolio optimization",
            "diagnostic": "Troubleshooting and root cause analysis",
            "discovery": "Workspace health assessment",
        }
        for domain in sorted(_descriptions):
            tools_config = TOOL_CATEGORIES.get(domain, [])
            if tools_config == "all":
                tool_list = sorted(ALL_TOOL_METADATA.keys())
            elif isinstance(tools_config, list):
                tool_list = sorted(tools_config)
            else:
                tool_list = []
            agents.append(
                {
                    "domain": domain,
                    "description": _descriptions[domain],
                    "tools": tool_list,
                    "mcp_tool_name": f"{domain}_agent",
                }
            )
        return {"agents": agents}

    def _tools_catalog(self) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        for name, meta in sorted(ALL_TOOL_METADATA.items()):
            phase = "A" if name in PHASE_A_TOOLS else "B"
            tools.append(
                {
                    "name": name,
                    "description": meta.get("description", ""),
                    "parameters_schema": meta.get("parameters", {}),
                    "phase": phase,
                }
            )
        return {"tools": tools, "total_count": len(tools)}

    def _tools_dependencies(self) -> dict[str, Any]:
        return {"dependencies": TOOL_DEPENDENCIES}

    def _health(self) -> dict[str, Any]:
        cb_states: dict[str, Any] = {}
        if self._circuit_breakers is not None:
            for ws_id, state in self._circuit_breakers.get_all_states().items():
                cb_states[ws_id] = {"state": state.value}

        uptime = time.monotonic() - self._start_time
        return {
            "status": "healthy",
            "circuit_breakers": cb_states,
            "tools_registered": len(ALL_TOOL_METADATA),
            "uptime_seconds": round(uptime),
        }

    def _domain_prompt(self, domain: str) -> dict[str, Any]:
        """Return the system prompt for a domain agent.

        The prompt contains the full expert guidance: tool ordering,
        Databricks domain knowledge, analysis workflows, error handling
        strategies, and output formatting. Claude can use this to
        orchestrate domain tools directly without a server-side agent.
        """
        from starboard_server.prompts.factories import get_system_prompt

        prompt_text = get_system_prompt(
            domain=domain,
            goal="{goal}",
            token_budget=120_000,
            mode="online",
        )

        tools_config = TOOL_CATEGORIES.get(domain, [])
        if tools_config == "all":
            tool_list = sorted(ALL_TOOL_METADATA.keys())
        elif isinstance(tools_config, list):
            tool_list = sorted(tools_config)
        else:
            tool_list = []

        return {
            "domain": domain,
            "prompt_version": self._get_prompt_version(domain),
            "system_prompt": prompt_text,
            "available_tools": tool_list,
            "usage": (
                "Use this prompt as expert guidance when orchestrating "
                f"Starboard {domain} tools directly. Replace {{goal}} with "
                "the user's actual goal. Call the listed tools in the order "
                "recommended by the prompt."
            ),
        }

    @staticmethod
    def _get_prompt_version(domain: str) -> str:
        """Extract PROMPT_VERSION from a domain's prompt module."""
        _module_map: dict[str, str] = {
            "query": "starboard_server.prompts.query",
            "job": "starboard_server.prompts.job",
            "uc": "starboard_server.prompts.uc",
            "cluster": "starboard_server.prompts.cluster",
            "analytics": "starboard_server.prompts.analytics.v1",
            "warehouse": "starboard_server.prompts.warehouse",
            "diagnostic": "starboard_server.prompts.diagnostic",
            "discovery": "starboard_server.prompts.discovery",
        }
        try:
            import importlib

            mod = importlib.import_module(_module_map[domain])
            return getattr(mod, "PROMPT_VERSION", "1.0.0")
        except (ImportError, KeyError):
            return "1.0.0"
