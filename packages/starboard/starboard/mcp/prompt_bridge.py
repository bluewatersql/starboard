# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Prompt bridge: exposes domain agent system prompts as MCP prompts.

Each domain agent has a corresponding MCP prompt that surfaces the
agent's system prompt with optional ``goal`` and ``workspace_id``
parameters.  This lets MCP clients discover available agent
capabilities and preview prompt behaviour before calling the agent tool.
"""

from __future__ import annotations

from typing import Any

from starboard.mcp.agent_bridge import AGENT_DOMAINS
from starboard.prompts.base import AgentDomain

# Prompt metadata for list_prompts responses.
# Each entry maps directly to a FastMCP ``@prompt()`` registration.
_PROMPT_DESCRIPTIONS: dict[str, str] = {
    "query_agent_prompt": ("Preview the SQL query optimization agent's system prompt"),
    "job_agent_prompt": ("Preview the Databricks job analysis agent's system prompt"),
    "uc_agent_prompt": ("Preview the Unity Catalog governance agent's system prompt"),
    "cluster_agent_prompt": ("Preview the cluster configuration agent's system prompt"),
    "analytics_agent_prompt": (
        "Preview the FinOps cost analysis agent's system prompt"
    ),
    "warehouse_agent_prompt": (
        "Preview the SQL warehouse portfolio agent's system prompt"
    ),
    "diagnostic_agent_prompt": (
        "Preview the troubleshooting and diagnostics agent's system prompt"
    ),
    "discovery_agent_prompt": ("Preview the workspace discovery agent's system prompt"),
}

# Metadata list for iteration during registration.
PROMPT_METADATA: list[dict[str, Any]] = [
    {
        "name": f"{domain}_agent_prompt",
        "description": _PROMPT_DESCRIPTIONS[f"{domain}_agent_prompt"],
        "domain": domain,
    }
    for domain in AGENT_DOMAINS
]


def build_prompt_messages(
    domain: AgentDomain,
    *,
    goal: str = "",
    workspace_id: str = "",
) -> list[dict[str, str]]:
    """Build MCP prompt messages for a domain agent.

    Loads the domain's system prompt from the prompt factories and
    returns it as MCP ``Message`` dicts that clients can display or
    use as context.

    Args:
        domain: Agent domain (``query``, ``job``, etc.).
        goal: Optional user goal to interpolate into the prompt.
        workspace_id: Optional workspace context for the prompt.

    Returns:
        List of message dicts with ``role`` and ``content`` keys.
    """
    from starboard.prompts.factories import get_system_prompt

    system_prompt = get_system_prompt(
        domain=domain,
        goal=goal or "General analysis and optimization",
        token_budget=120_000,
        mode="online",
    )

    messages: list[dict[str, str]] = [
        {
            "role": "user",
            "content": (
                f"You are the Starboard {domain} agent"
                + (f" for workspace {workspace_id}" if workspace_id else "")
                + (f".\nGoal: {goal}" if goal else ".")
                + "\n\nBelow is your system prompt:\n\n"
                + system_prompt
            ),
        },
    ]
    return messages
