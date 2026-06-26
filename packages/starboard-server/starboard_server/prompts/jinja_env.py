# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Jinja2 environment for prompt template rendering.

Provides a singleton Environment configured for prompt templates with
strict variable checking, no HTML escaping, and custom filters.

Usage:
    from starboard_server.prompts.jinja_env import get_jinja_env, render_template

    env = get_jinja_env()
    prompt = render_template("query/system.jinja2", goal="...", token_budget=120000, mode="online")
"""

from __future__ import annotations

import functools
import json
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

PROMPT_TEMPLATE_PACKAGE = "starboard_server.prompts"
PROMPT_TEMPLATE_DIR = "templates"


@functools.lru_cache(maxsize=1)
def get_jinja_env() -> Environment:
    """Return the singleton Jinja2 Environment for prompt templates.

    Configuration:
        - PackageLoader: resolves templates relative to prompts/templates/
        - autoescape=False: prompts are plain text, not HTML
        - undefined=StrictUndefined: missing variables raise immediately
        - keep_trailing_newline=True: preserve template formatting
        - trim_blocks=True, lstrip_blocks=True: clean Jinja control structure whitespace

    Returns:
        Configured Jinja2 Environment instance.
    """
    env = Environment(
        loader=PackageLoader(PROMPT_TEMPLATE_PACKAGE, PROMPT_TEMPLATE_DIR),
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["json_dumps"] = _json_dumps_filter
    env.filters["intcomma"] = _intcomma_filter
    return env


def _json_dumps_filter(value: Any, indent: int = 2) -> str:
    """Jinja2 filter: serialize a value to formatted JSON."""
    return json.dumps(value, indent=indent, default=str)


def _intcomma_filter(value: int) -> str:
    """Jinja2 filter: format an integer with comma separators (e.g., 120,000)."""
    return f"{value:,}"


def render_template(template_name: str, **kwargs: Any) -> str:
    """Render a prompt template by name with the given context variables.

    Args:
        template_name: Path relative to prompts/templates/ (e.g., "query/system.jinja2").
        **kwargs: Template context variables. StrictUndefined will raise
            if any required variable is missing.

    Returns:
        Rendered prompt string.

    Raises:
        jinja2.UndefinedError: If a required template variable is not provided.
        jinja2.TemplateNotFound: If the template file does not exist.
    """
    env = get_jinja_env()
    template = env.get_template(template_name)
    return template.render(**kwargs)
