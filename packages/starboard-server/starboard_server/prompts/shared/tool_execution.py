# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Shared tool execution guidelines for domain agent prompts.

This module provides reusable instructions for proper tool calling behavior
across all domain agents, particularly for handling tool dependencies and
parallel execution.

Prevents issues like:
- Calling dependent tools with placeholder values
- Over-parallelizing tool calls that have data dependencies
- Wasting tokens on tools that will fail due to missing inputs
"""

# =============================================================================
# TOOL EXECUTION GUIDELINES
# =============================================================================

TOOL_EXECUTION_GUIDELINES = """
===============================================================================
TOOL EXECUTION GUIDELINES (CRITICAL)
===============================================================================

**NEVER use placeholder values when calling tools.**

If a tool requires data from another tool's output:
1. Call the data-producing tool FIRST
2. WAIT for its results before calling dependent tools
3. Use the ACTUAL returned data in subsequent calls
"""

# =============================================================================
# BUILDER FUNCTION
# =============================================================================


def build_tool_execution_section() -> str:
    """
    Build the tool execution guidelines section for inclusion in prompts.

    Returns:
        Complete tool execution guidelines string ready to embed in a prompt.

    Example:
        >>> from starboard_server.prompts.shared.tool_execution import (
        ...     build_tool_execution_section
        ... )
        >>> guidelines = build_tool_execution_section()
        >>> "placeholder" in guidelines.lower()
        True
    """
    return TOOL_EXECUTION_GUIDELINES
