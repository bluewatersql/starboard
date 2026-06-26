# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Prompt factory functions for domain agents.

This module provides factory functions that build formatted prompts
for each domain agent with appropriate context (mode, goal, token budget).

Uses Jinja2 templates (v2) for prompt rendering. Legacy str.format()
imports retained for backward compatibility.
"""

from collections.abc import Callable

from starboard_core.domain.models.llm import OptimizationMode

from starboard_server.prompts.analytics.v2 import (
    build_system_prompt as _analytics_build,
)
from starboard_server.prompts.base import AgentDomain
from starboard_server.prompts.cluster.v2 import (
    build_system_prompt as _cluster_build,
)
from starboard_server.prompts.diagnostic.v2 import (
    build_system_prompt as _diagnostic_build,
)
from starboard_server.prompts.discovery.v3 import (
    build_system_prompt as _discovery_build,
)
from starboard_server.prompts.job.v2 import build_system_prompt as _job_build
from starboard_server.prompts.query.v2 import (
    build_system_prompt as _query_build,
)
from starboard_server.prompts.router.v2 import (
    build_system_prompt as _router_build,
)
from starboard_server.prompts.uc.v2 import build_system_prompt as _uc_build
from starboard_server.prompts.warehouse.v2 import (
    build_system_prompt as _warehouse_build,
)


def get_system_prompt(
    domain: AgentDomain,
    goal: str = "",
    token_budget: int = 120_000,
    mode: str = "online",
) -> str:
    """
    Get system prompt for a domain agent.

    Args:
        domain: Agent domain (router, query, job, uc, cluster, diagnostic, analytics, warehouse)
        goal: User's goal or task description
        token_budget: Available token budget for the agent
        mode: Optimization mode (online, diagnostic, batch, etc.)

    Returns:
        Formatted system prompt string

    Raises:
        ValueError: If domain is not recognized

    Example:
        >>> prompt = get_system_prompt(
        ...     domain="query",
        ...     goal="Optimize slow SELECT query",
        ...     token_budget=100_000,
        ...     mode="online"
        ... )
        >>> "SQL query optimization expert" in prompt
        True
    """
    builders = {
        "router": lambda: _router_build(),
        "query": lambda: _query_build(
            goal=goal or "Optimize SQL query performance",
            token_budget=token_budget,
            mode=mode,
        ),
        "job": lambda: _job_build(
            goal=goal or "Optimize Databricks job performance",
            token_budget=token_budget,
            mode=mode,
        ),
        "uc": lambda: _uc_build(
            goal=goal or "Analyze Unity Catalog assets, governance, and optimization",
            token_budget=token_budget,
            mode=mode,
        ),
        "cluster": lambda: _cluster_build(
            goal=goal or "Optimize cluster configuration",
            token_budget=token_budget,
            mode=mode,
        ),
        "diagnostic": lambda: _diagnostic_build(
            goal=goal or "Diagnose and troubleshoot performance issues",
            token_budget=token_budget,
            mode=mode,
            available_artifacts=format_available_artifacts(None),
        ),
        "analytics": lambda: _analytics_build(
            goal=goal or "Analyze costs and provide FinOps recommendations",
            mode=mode,
        ),
        "warehouse": lambda: _warehouse_build(
            goal=goal or "Optimize SQL warehouse portfolio",
            token_budget=token_budget,
            mode=mode,
        ),
        "discovery": lambda: _discovery_build(
            goal=goal or "Run a comprehensive workspace health assessment",
            token_budget=token_budget,
            mode=mode,
        ),
    }

    if domain not in builders:
        raise ValueError(
            "Unknown domain: "
            + domain
            + ". Must be one of: "
            + str(list(builders.keys()))
        )

    return builders[domain]()


def build_router_prompt(
    mode: OptimizationMode,  # noqa: ARG001
    goal: str,  # noqa: ARG001
    budget_remaining: int,  # noqa: ARG001
    context: dict | None = None,  # noqa: ARG001
) -> str:
    """
    Build router agent system prompt.

    Router prompt is static (no formatting), but this function
    maintains the consistent signature for AgentConfig.system_prompt_builder.

    Args:
        mode: Optimization mode (ignored for router)
        goal: User goal (ignored for router)
        budget_remaining: Token budget (ignored for router)
        context: Optional context dict (ignored for router)

    Returns:
        Static router system prompt
    """
    return _router_build()


def build_query_prompt(
    mode: OptimizationMode,
    goal: str,
    budget_remaining: int,
    context: dict | None = None,  # noqa: ARG001
) -> str:
    """
    Build query agent system prompt.

    Args:
        mode: Optimization mode
        goal: User's optimization goal
        budget_remaining: Remaining token budget
        context: Optional context dict (unused by query agent)

    Returns:
        Formatted query agent system prompt
    """
    return _query_build(
        goal=goal or "Optimize SQL query performance",
        token_budget=budget_remaining,
        mode=mode.value if isinstance(mode, OptimizationMode) else mode,
    )


def build_job_prompt(
    mode: OptimizationMode,
    goal: str,
    budget_remaining: int,
    context: dict | None = None,  # noqa: ARG001
) -> str:
    """
    Build job agent system prompt.

    Args:
        mode: Optimization mode
        goal: User's optimization goal
        budget_remaining: Remaining token budget
        context: Optional context dict (unused by job agent)

    Returns:
        Formatted job agent system prompt
    """
    return _job_build(
        goal=goal or "Optimize Databricks job performance",
        token_budget=budget_remaining,
        mode=mode.value if isinstance(mode, OptimizationMode) else mode,
    )


def build_uc_prompt(
    mode: OptimizationMode,
    goal: str,
    budget_remaining: int,
    context: dict | None = None,  # noqa: ARG001
) -> str:
    """
    Build Unity Catalog (UC) agent system prompt.

    The UC agent replaces the deprecated "table" agent with extended
    capabilities for data governance, lineage analysis, schema intelligence,
    access control, and storage optimization.

    Args:
        mode: Optimization mode
        goal: User's optimization goal
        budget_remaining: Remaining token budget
        context: Optional context dict (unused by UC agent)

    Returns:
        Formatted UC agent system prompt
    """
    return _uc_build(
        goal=goal or "Analyze Unity Catalog assets, governance, and optimization",
        token_budget=budget_remaining,
        mode=mode.value if isinstance(mode, OptimizationMode) else mode,
    )


def build_cluster_prompt(
    mode: OptimizationMode,
    goal: str,
    budget_remaining: int,
    context: dict | None = None,  # noqa: ARG001
) -> str:
    """
    Build cluster agent system prompt.

    Args:
        mode: Optimization mode
        goal: User's optimization goal
        budget_remaining: Remaining token budget
        context: Optional context dict (unused by cluster agent)

    Returns:
        Formatted cluster agent system prompt
    """
    return _cluster_build(
        goal=goal or "Optimize cluster configuration",
        token_budget=budget_remaining,
        mode=mode.value if isinstance(mode, OptimizationMode) else mode,
    )


def format_available_artifacts(artifacts: list[dict] | None) -> str:
    """
    Format available artifacts for prompt display.

    Args:
        artifacts: List of artifact metadata dicts from context

    Returns:
        Formatted string for prompt, or default message if no artifacts
    """
    if not artifacts:
        return "No large artifacts uploaded."

    lines = []
    for artifact in artifacts:
        filename = artifact.get("filename", "unknown")
        detected_type = artifact.get("detected_type", "unknown")
        size_bytes = artifact.get("size_bytes", 0)
        attachment_id = artifact.get("attachment_id", "")

        lines.append(
            "- **"
            + filename
            + "** ("
            + detected_type
            + ", "
            + str(size_bytes)
            + " bytes)\n  - attachment_id: `"
            + attachment_id
            + "`"
        )
    return "\n".join(lines)


def build_diagnostic_prompt(
    mode: OptimizationMode,
    goal: str,
    budget_remaining: int,
    context: dict | None = None,
) -> str:
    """
    Build diagnostic agent system prompt.

    Args:
        mode: Optimization mode
        goal: User's optimization goal
        budget_remaining: Remaining token budget
        context: Optional context dict containing available_artifacts

    Returns:
        Formatted diagnostic agent system prompt
    """
    # Extract and format available artifacts from context
    available_artifacts = context.get("available_artifacts") if context else None
    formatted_artifacts = format_available_artifacts(available_artifacts)

    return _diagnostic_build(
        goal=goal or "Diagnose and troubleshoot performance issues",
        token_budget=budget_remaining,
        mode=mode.value if isinstance(mode, OptimizationMode) else mode,
        available_artifacts=formatted_artifacts,
    )


def build_analytics_prompt(
    mode: OptimizationMode,
    goal: str,
    budget_remaining: int,  # noqa: ARG001
    context: dict | None = None,  # noqa: ARG001
) -> str:
    """
    Build analytics agent system prompt.

    Args:
        mode: Optimization mode
        goal: User's optimization goal
        budget_remaining: Remaining token budget (not used by analytics prompt)
        context: Optional context dict (unused by analytics agent)

    Returns:
        Formatted analytics agent system prompt
    """
    return _analytics_build(
        goal=goal or "Analyze costs and provide FinOps recommendations",
        mode=mode.value if isinstance(mode, OptimizationMode) else mode,
    )


def build_warehouse_prompt(
    mode: OptimizationMode,
    goal: str,
    budget_remaining: int,
    context: dict | None = None,  # noqa: ARG001
) -> str:
    """
    Build warehouse portfolio agent system prompt.

    Args:
        mode: Optimization mode
        goal: User's optimization goal
        budget_remaining: Remaining token budget
        context: Optional context dict (unused by warehouse agent)

    Returns:
        Formatted warehouse agent system prompt
    """
    return _warehouse_build(
        goal=goal or "Optimize SQL warehouse portfolio",
        token_budget=budget_remaining,
        mode=mode.value if isinstance(mode, OptimizationMode) else mode,
    )


def build_discovery_prompt(
    mode: OptimizationMode,
    goal: str,
    budget_remaining: int,
    context: dict | None = None,  # noqa: ARG001
) -> str:
    """Build discovery agent system prompt.

    Args:
        mode: Optimization mode.
        goal: User's goal for workspace discovery.
        budget_remaining: Remaining token budget.
        context: Optional context dict (unused by discovery agent).

    Returns:
        Formatted discovery agent system prompt.
    """
    return _discovery_build(
        goal=goal or "Run a comprehensive workspace health assessment",
        token_budget=budget_remaining,
        mode=mode.value if isinstance(mode, OptimizationMode) else mode,
    )


def get_prompt_builder_for_domain(
    domain: AgentDomain,
) -> Callable[[OptimizationMode, str, int, dict | None], str]:
    """
    Get prompt builder function for a domain.

    Returns a callable that can be passed to AgentConfig.system_prompt_builder.
    The callable signature matches: (mode, goal, budget_remaining, context=None) -> str

    Args:
        domain: Agent domain

    Returns:
        Prompt builder function for the domain

    Raises:
        ValueError: If domain is not recognized

    Example:
        >>> builder = get_prompt_builder_for_domain("query")
        >>> prompt = builder(OptimizationMode.ONLINE, "Optimize query", 100000, None)
        >>> "SQL query optimization" in prompt
        True
        >>>
        >>> # Use with AgentConfig
        >>> config = AgentConfig(
        ...     system_prompt_builder=get_prompt_builder_for_domain("query")
        ... )
    """
    builders: dict[
        AgentDomain, Callable[[OptimizationMode, str, int, dict | None], str]
    ] = {
        "router": build_router_prompt,
        "query": build_query_prompt,
        "job": build_job_prompt,
        "uc": build_uc_prompt,
        "cluster": build_cluster_prompt,
        "diagnostic": build_diagnostic_prompt,
        "analytics": build_analytics_prompt,
        "warehouse": build_warehouse_prompt,
        "discovery": build_discovery_prompt,
    }

    if domain not in builders:
        raise ValueError(
            "Unknown domain: "
            + domain
            + ". Must be one of: "
            + str(list(builders.keys()))
        )

    return builders[domain]
