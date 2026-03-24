# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Message building helpers for domain agent state updates.

This module provides functions to add assistant and tool messages
to the agent state during the reasoning loop.

Responsibilities:
- Build assistant messages with tool call metadata
- Build tool result messages with special complete-tool handling
- Extract final output from complete tool results

Does NOT:
- Execute reasoning or tools (that's ReasoningEngine/ToolExecutor)
- Emit events (that's EventStreamer)
- Determine reasoning flow (that's reasoning_loop)
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from starboard_server.agents.state.agent_state import AgentState, Message
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.serialization import json_dumps, json_loads

logger = get_logger(__name__)


def add_assistant_message(state: AgentState, reasoning_result: Any) -> AgentState:
    """
    Add assistant message to state from reasoning result.

    Args:
        state: Current agent state
        reasoning_result: ReasoningStep with thinking content and tool calls

    Returns:
        New AgentState with assistant message added
    """
    # Build metadata with tool calls if present
    metadata: dict[str, Any] | None = None
    if reasoning_result.tool_calls:
        metadata = {
            "tool_calls": [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": (tc.get("arguments") or "").strip() or "{}",
                    },
                }
                for tc in reasoning_result.tool_calls
            ]
        }

    return state.add_message(
        Message(
            role="assistant",
            content=reasoning_result.thinking_content or "",
            metadata=metadata,  # type: ignore[arg-type]
        )
    )


def add_tool_message(state: AgentState, tool_result: Any) -> AgentState:
    """
    Add tool result message to state.

    Handles special cases:
    - Complete tool: extracts final_output from raw_result or parsed JSON
    - Normal tools: extracts content attribute
    - Failed tools: uses error message

    Args:
        state: Current agent state
        tool_result: ToolExecutionResult with success status and result

    Returns:
        New AgentState with tool message added
    """
    # Update working memory
    new_memory = state.working_memory.add_tool_used(tool_result.tool_call.name)
    state = dataclasses.replace(state, working_memory=new_memory)

    # Extract content
    if tool_result.success and tool_result.result:
        # Special handling for complete tool
        if tool_result.tool_call.name == "complete":
            # Use raw_result if available (preserved from tool registry)
            # This avoids issues with truncated content not being valid JSON
            raw_result = getattr(tool_result.result, "raw_result", None)
            if raw_result and isinstance(raw_result, dict):
                final_output = raw_result
                state = dataclasses.replace(state, final_output=final_output)
                content = getattr(tool_result.result, "content", "") or json_dumps(
                    final_output
                )

                # Log visualization chart_config for debugging
                viz = final_output.get("visualization")
                if viz and isinstance(viz, dict):
                    chart_config = viz.get("chart_config")
                    logger.debug(
                        "complete_tool_visualization_captured",
                        has_visualization=True,
                        has_chart_config=chart_config is not None,
                        chart_config_type=type(chart_config).__name__
                        if chart_config
                        else None,
                        chart_config_keys=list(chart_config.keys())
                        if isinstance(chart_config, dict)
                        else [],
                        chart_config_preview=str(chart_config)[:500]
                        if chart_config
                        else None,
                    )

                logger.debug(
                    "complete_tool_result_stored",
                    has_summary="summary" in final_output,
                    has_report_type="report_type" in final_output,
                    has_visualization="visualization" in final_output,
                    used_raw_result=True,
                )
            else:
                # Fallback: try to parse content as JSON string
                content = getattr(tool_result.result, "content", "") or ""
                try:
                    final_output = json_loads(content)
                    state = dataclasses.replace(state, final_output=final_output)
                    logger.debug(
                        "complete_tool_result_stored",
                        has_summary="summary" in final_output,
                        has_report_type="report_type" in final_output,
                        used_raw_result=False,
                    )
                except json.JSONDecodeError:
                    logger.warning(
                        "complete_tool_output_not_json",
                        content_preview=content[:200] if content else "(empty)",
                    )
        else:
            # Normal tools return object with content attribute
            content = getattr(tool_result.result, "content", "") or ""
    else:
        content = tool_result.error or "Tool failed"

    # Add tool message
    return state.add_message(
        Message(
            role="tool",
            content=content,
            name=tool_result.tool_call.name,
            tool_call_id=tool_result.tool_call.id,
        )
    )
