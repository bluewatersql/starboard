# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Diagnostic domain prompts - Version 2 (Jinja2).

Artifact-first, evidence-based troubleshooting prompt for the Diagnostic Agent.
Migrated from str.format() to Jinja2 templates in Wave 20260329.
"""

from __future__ import annotations

from starboard_server.prompts.jinja_env import render_template

PROMPT_VERSION = "2.0.0"
"""Semantic version for Diagnostic prompts. Increment on any prompt change:

Changelog:
- 2.0.0: Jinja2 template migration (Wave 20260329)
- 1.2.0: Previous str.format() version
"""


def build_system_prompt(
    goal: str = "",
    token_budget: int = 120_000,
    mode: str = "online",
    available_artifacts: str = "No large artifacts uploaded.",
) -> str:
    """Build diagnostic agent system prompt using Jinja2 template.

    Args:
        goal: User's optimization goal.
        token_budget: Available token budget for the agent.
        mode: Optimization mode (online, offline, etc.).
        available_artifacts: Formatted string of available artifacts.

    Returns:
        Rendered system prompt string.
    """
    return render_template(
        "diagnostic/system.jinja2",
        goal=goal,
        token_budget=token_budget,
        mode=mode,
        available_artifacts=available_artifacts,
    )
