# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Discovery domain prompts - Version 3 (Jinja2).

System prompt for the workspace discovery agent.
Migrated from str.format() to Jinja2 templates in Wave 20260329.
"""

from __future__ import annotations

from starboard.prompts.jinja_env import render_template

PROMPT_VERSION = "3.0.0"
"""Semantic version for Discovery prompts. Increment on any prompt change:

Changelog:
- 3.0.0: Jinja2 template migration (Wave 20260329)
- 2.0.0: Previous str.format() version
"""


def build_system_prompt(
    goal: str = "",
    token_budget: int = 120_000,
    mode: str = "online",
) -> str:
    """Build discovery agent system prompt using Jinja2 template.

    Args:
        goal: User's goal for workspace discovery.
        token_budget: Available token budget for the agent.
        mode: Optimization mode (online, offline, etc.).

    Returns:
        Rendered system prompt string.
    """
    return render_template(
        "discovery/system.jinja2",
        goal=goal,
        token_budget=token_budget,
        mode=mode,
    )
