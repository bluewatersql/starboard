# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared prompt components for domain agents.

This package provides reusable prompt sections that should be used consistently
across all domain agents to ensure aligned behavior and reduce duplication.

Modules:
    handoff_context: Rules for handling agent-to-agent transitions
    response_format: Guidelines for complete tool usage and data listing/table formatting
    tool_execution: Safety guidelines for tool calling and dependencies
    user_input_policy: Rules for when to ask users vs use defaults
"""

from starboard.prompts.shared.handoff_context import (
    ANALYTICS_HANDOFF_EXTENSION,
    CLUSTER_HANDOFF_EXTENSION,
    DIAGNOSTIC_HANDOFF_EXTENSION,
    JOB_HANDOFF_EXTENSION,
    QUERY_HANDOFF_EXTENSION,
    SHARED_HANDOFF_SECTION,
    UC_HANDOFF_EXTENSION,
    WAREHOUSE_HANDOFF_EXTENSION,
    build_handoff_section,
)
from starboard.prompts.shared.response_format import (
    COMPLETE_TOOL_GUIDELINES,
    DATA_LISTING_GUIDELINES,
    NEXT_STEPS_GUIDELINES,
    build_complete_tool_section,
    build_data_listing_section,
    build_next_steps_section,
)
from starboard.prompts.shared.tool_execution import (
    TOOL_EXECUTION_GUIDELINES,
    build_tool_execution_section,
)
from starboard.prompts.shared.user_input_policy import (
    DATE_POLICY,
    PARAMETER_DEFAULTS,
    USER_INPUT_POLICY,
    USER_INPUT_POLICY_SECTION,
    build_user_input_policy_section,
)

__all__ = [
    # Handoff context
    "SHARED_HANDOFF_SECTION",
    "build_handoff_section",
    "QUERY_HANDOFF_EXTENSION",
    "JOB_HANDOFF_EXTENSION",
    "UC_HANDOFF_EXTENSION",
    "CLUSTER_HANDOFF_EXTENSION",
    "DIAGNOSTIC_HANDOFF_EXTENSION",
    "ANALYTICS_HANDOFF_EXTENSION",
    "WAREHOUSE_HANDOFF_EXTENSION",
    # Response format
    "COMPLETE_TOOL_GUIDELINES",
    "DATA_LISTING_GUIDELINES",
    "NEXT_STEPS_GUIDELINES",
    "build_complete_tool_section",
    "build_data_listing_section",
    "build_next_steps_section",
    # Tool execution
    "TOOL_EXECUTION_GUIDELINES",
    "build_tool_execution_section",
    # User input policy
    "DATE_POLICY",
    "PARAMETER_DEFAULTS",
    "USER_INPUT_POLICY",
    "USER_INPUT_POLICY_SECTION",
    "build_user_input_policy_section",
]
