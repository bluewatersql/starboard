# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery prompts — domain analysis prompt templates.

Versioned prompt templates for LLM-driven workspace health analysis.
"""

from starboard.discovery.prompts.domain_analysis import (
    DOMAIN_PROMPT_TEMPLATES,
    PromptBuilder,
)
from starboard.discovery.prompts.v1 import PROMPT_METADATA, PROMPT_VERSION

__all__ = [
    "DOMAIN_PROMPT_TEMPLATES",
    "PROMPT_METADATA",
    "PROMPT_VERSION",
    "PromptBuilder",
]
