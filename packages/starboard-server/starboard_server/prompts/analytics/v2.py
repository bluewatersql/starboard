"""
Analytics domain prompts - Version 2 (Jinja2).

System prompt for the Databricks FinOps and cost analytics agent.
Migrated from str.format() to Jinja2 templates in Wave 20260329.
"""

from __future__ import annotations

from starboard_server.prompts.jinja_env import render_template

PROMPT_VERSION = "2.0.0"
"""Semantic version for Analytics prompts. Increment on any prompt change:

Changelog:
- 2.0.0: Jinja2 template migration (Wave 20260329)
- 1.0.0: Initial str.format() version
"""


def build_system_prompt(
    goal: str = "",
    mode: str = "online",
) -> str:
    """Build analytics agent system prompt using Jinja2 template.

    Args:
        goal: User's optimization goal.
        mode: Optimization mode (online, offline, etc.).

    Returns:
        Rendered system prompt string.
    """
    return render_template(
        "analytics/system.jinja2",
        goal=goal,
        mode=mode,
    )
