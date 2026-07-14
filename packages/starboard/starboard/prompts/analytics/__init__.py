# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Analytics domain prompts package.

Contains the system prompt for the FinOps/Analytics agent.
"""

from .v1 import ANALYTICS_SYSTEM_PROMPT, PROMPT_VERSION

__all__ = [
    "ANALYTICS_SYSTEM_PROMPT",
    "PROMPT_VERSION",
]
