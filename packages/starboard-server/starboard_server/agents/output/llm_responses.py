# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
LLM response dataclasses for reasoning agent.

This module re-exports types from their canonical location in
``adapters.llm.types`` for backward compatibility. All consumers
can continue importing from here without changes.
"""

from starboard_server.adapters.llm.types import (  # noqa: F401
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolResult,
)

__all__ = ["LLMResponse", "TokenUsage", "ToolCall", "ToolResult"]
