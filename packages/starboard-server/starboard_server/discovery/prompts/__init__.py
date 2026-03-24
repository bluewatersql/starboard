"""Discovery prompts — domain analysis prompt templates.

Versioned prompt templates for LLM-driven workspace health analysis.
"""

from starboard_server.discovery.prompts.domain_analysis import (
    DOMAIN_PROMPT_TEMPLATES,
    PromptBuilder,
)
from starboard_server.discovery.prompts.v1 import PROMPT_METADATA, PROMPT_VERSION

__all__ = [
    "DOMAIN_PROMPT_TEMPLATES",
    "PROMPT_METADATA",
    "PROMPT_VERSION",
    "PromptBuilder",
]
