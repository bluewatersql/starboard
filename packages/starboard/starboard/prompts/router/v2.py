# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Router domain prompts - Version 2 (Jinja2).

System prompt for the intent classification and routing agent.
Migrated from str.format() to Jinja2 templates in Wave 20260329.
"""

from __future__ import annotations

from starboard.prompts.jinja_env import render_template

PROMPT_VERSION = "2.0.0"
"""Semantic version for Router prompts. Increment on any prompt change:

Changelog:
- 2.0.0: Jinja2 template migration (Wave 20260329)
- 1.0.0: Initial str.format() version
"""


def build_system_prompt() -> str:
    """Build router agent system prompt using Jinja2 template.

    Returns:
        Rendered system prompt string.
    """
    return render_template("router/system.jinja2")
