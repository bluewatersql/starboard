# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""OpenAI LLM client and utilities."""

from starboard.adapters.llm.openai.client import OpenAIProvider
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

__all__ = ["OpenAIProvider"]
