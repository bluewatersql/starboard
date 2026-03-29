"""
Visualization prompts - Version 2 (Jinja2).

LLM-driven chart recommendation prompts.
Migrated from str.format() to Jinja2 templates in Wave 20260329.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from starboard_server.prompts.jinja_env import render_template

# Re-export FEW_SHOT_EXAMPLES from v1 (these are data structures, not templates)
from starboard_server.prompts.visualization.v1 import FEW_SHOT_EXAMPLES  # noqa: F401

PROMPT_VERSION = "2.0.0"
"""Semantic version for visualization prompts. Increment on any prompt change:

Changelog:
- 2.0.0: Jinja2 template migration (Wave 20260329)
- 1.0.0: Initial str.format() version
"""


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def build_visualization_prompt(
    query_metadata: dict[str, Any], data_profile: dict[str, Any]
) -> list[dict[str, str]]:
    """Build a complete LLM prompt for chart recommendation using Jinja2.

    Args:
        query_metadata: Query catalog metadata including name, description,
            recommended_chart_types, and goals.
        data_profile: Statistical summary of the data.

    Returns:
        List of message dicts with role and content keys.
    """
    goals = query_metadata.get("goals", [])
    goals_str = ", ".join(goals) if goals else "No specific goals"

    recommended = query_metadata.get("recommended_chart_types", [])
    recommended_str = ", ".join(recommended) if recommended else "No specific recommendation"

    data_profile_json = json.dumps(data_profile, indent=2, cls=DateTimeEncoder)

    system_content = render_template("visualization/system.jinja2")
    user_content = render_template(
        "visualization/user_content.jinja2",
        query_name=query_metadata.get("name", "Unknown Query"),
        query_description=query_metadata.get("description", "No description"),
        goals_str=goals_str,
        recommended_str=recommended_str,
        data_profile_json=data_profile_json,
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
