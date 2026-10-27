# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Job domain prompts - Version 2 (Jinja2).

System prompt for the Databricks job optimization agent.
Migrated from str.format() to Jinja2 templates in Wave 20260329.
"""

from __future__ import annotations

from starboard.prompts.jinja_env import render_template

PROMPT_VERSION = "2.0.0"
"""Semantic version for Job prompts. Increment on any prompt change:

Changelog:
- 2.0.0: Jinja2 template migration (Wave 20260329)
- 1.0.0: Previous str.format() version
"""


def build_system_prompt(
    goal: str = "",
    token_budget: int = 120_000,
    mode: str = "online",
) -> str:
    """Build job agent system prompt using Jinja2 template.

    Args:
        goal: User's optimization goal.
        token_budget: Available token budget for the agent.
        mode: Optimization mode (online, offline, etc.).

    Returns:
        Rendered system prompt string.
    """
    return render_template(
        "job/system.jinja2",
        goal=goal,
        token_budget=token_budget,
        mode=mode,
    )
