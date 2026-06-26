# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
LLM response dataclasses for reasoning agent.

This module provides immutable dataclasses for representing LLM responses,
including tool calls and token usage. These structures match OpenAI's API
response format while remaining provider-agnostic.

These types were originally in agents/output/llm_responses.py and were moved
here to fix the layer violation (adapter importing from agents layer).
The original module re-exports from here for backward compatibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.serialization import json_loads

logger = get_logger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    """
    Token usage information from LLM call.

    Attributes:
        prompt_tokens: Number of tokens in the prompt
        completion_tokens: Number of tokens in the completion
        total_tokens: Total tokens used (prompt + completion)

    Example:
        >>> usage = TokenUsage(
        ...     prompt_tokens=1500,
        ...     completion_tokens=300,
        ...     total_tokens=1800,
        ... )
        >>> print(f"Cost: ${usage.estimate_cost(0.01, 0.03):.4f}")
        Cost: $0.0240
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        """Validate token counts."""
        if self.prompt_tokens < 0:
            raise ValueError(f"prompt_tokens must be >= 0, got {self.prompt_tokens}")

        if self.completion_tokens < 0:
            raise ValueError(
                f"completion_tokens must be >= 0, got {self.completion_tokens}"
            )

        if self.total_tokens < 0:
            raise ValueError(f"total_tokens must be >= 0, got {self.total_tokens}")

        # Verify total equals sum (with small tolerance for rounding)
        expected_total = self.prompt_tokens + self.completion_tokens
        if abs(self.total_tokens - expected_total) > 1:
            logger.warning(
                f"Total tokens ({self.total_tokens}) doesn't match "
                f"sum ({expected_total}). Using provided total."
            )

    def estimate_cost(
        self, input_cost_per_million: float, output_cost_per_million: float
    ) -> float:
        """
        Estimate cost in USD based on token pricing.

        Args:
            input_cost_per_million: Cost per million input tokens
            output_cost_per_million: Cost per million output tokens

        Returns:
            Estimated cost in USD

        Example:
            >>> usage = TokenUsage(1500, 300, 1800)
            >>> usage.estimate_cost(0.15, 0.60)  # gpt-4o-mini pricing
            0.00024
        """
        input_cost = (self.prompt_tokens / 1_000_000) * input_cost_per_million
        output_cost = (self.completion_tokens / 1_000_000) * output_cost_per_million
        return input_cost + output_cost


@dataclass(frozen=True)
class ToolCall:
    """
    Single tool call from LLM.

    Represents a request from the LLM to execute a tool/function. The LLM
    provides the tool name and arguments in JSON format.

    Attributes:
        id: Unique identifier for this tool call (from LLM)
        name: Name of the tool to call
        arguments: JSON string of arguments (must be parsed)

    Example:
        >>> tool_call = ToolCall(
        ...     id="call_abc123",
        ...     name="resolve_query",
        ...     arguments='{"statement_id": "abc123"}',
        ... )
        >>> args = tool_call.parse_arguments()
        >>> print(args["statement_id"])
        abc123
    """

    id: str
    name: str
    arguments: str  # JSON string

    def __post_init__(self) -> None:
        """Validate tool call."""
        if not self.id:
            raise ValueError("Tool call id cannot be empty")

        if not self.name:
            raise ValueError("Tool call name cannot be empty")

        # Normalize empty/missing arguments to valid empty JSON object.
        # LLMs legitimately send empty arguments for tools with only
        # optional parameters.
        if not self.arguments or self.arguments.strip() == "":
            object.__setattr__(self, "arguments", "{}")

        # Verify arguments is valid JSON
        try:
            json_loads(self.arguments)
        except json.JSONDecodeError as e:
            raise ValueError(f"Tool call arguments must be valid JSON: {e}") from e

    def parse_arguments(self) -> dict[str, Any]:
        """
        Parse arguments from JSON string to dictionary.

        Also handles nested JSON strings (workaround for some LLM providers
        that serialize nested objects as JSON strings instead of objects).

        Returns:
            Dictionary of parsed arguments

        Raises:
            ValueError: If arguments is not valid JSON

        Example:
            >>> tool_call = ToolCall(
            ...     id="call_123",
            ...     name="search",
            ...     arguments='{"query": "test"}',
            ... )
            >>> args = tool_call.parse_arguments()
            >>> args["query"]
            'test'
        """
        try:
            args = json_loads(self.arguments)

            # Workaround: Some LLMs (Claude/Databricks) serialize nested objects as JSON strings
            for key, value in args.items():
                if isinstance(value, str) and value.strip().startswith("{"):
                    try:
                        args[key] = json_loads(value)
                        logger.debug(
                            f"Parsed nested JSON string for parameter: {key}",
                            extra={"tool_call_id": self.id, "tool_name": self.name},
                        )
                    except json.JSONDecodeError:
                        pass

            return args
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse tool call arguments: {e}",
                extra={"tool_call_id": self.id, "tool_name": self.name},
            )
            raise ValueError(f"Invalid JSON in tool call arguments: {e}") from e


@dataclass(frozen=True)
class LLMResponse:
    """
    Unified response from LLM call.

    Represents a complete response from an LLM API call, which may include
    text content, tool calls, or both.

    Attributes:
        content: Optional text response from LLM
        tool_calls: Tuple of tool calls (empty if none)
        usage: Token usage information
        finish_reason: Reason the LLM stopped generating
        model: Model that generated the response
    """

    content: str | None
    tool_calls: tuple[ToolCall, ...]
    usage: TokenUsage
    finish_reason: str
    model: str

    def __post_init__(self) -> None:
        """Validate response."""
        if not self.content and not self.tool_calls:
            logger.warning(
                "LLMResponse has neither content nor tool_calls. "
                f"Finish reason: {self.finish_reason}"
            )

        valid_reasons = {
            "stop",
            "length",
            "tool_calls",
            "content_filter",
            "function_call",
        }
        if self.finish_reason not in valid_reasons:
            logger.warning(
                f"Unexpected finish_reason: {self.finish_reason}. "
                f"Expected one of: {valid_reasons}"
            )

    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0

    def has_content(self) -> bool:
        """Check if response contains text content."""
        return self.content is not None and self.content.strip() != ""

    def to_dict(self) -> dict[str, Any]:
        """Convert response to dictionary."""
        return {
            "content": self.content,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ],
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
            },
            "finish_reason": self.finish_reason,
            "model": self.model,
        }


@dataclass(frozen=True)
class ToolResult:
    """
    Result from executing a tool.

    Attributes:
        tool_call_id: ID of the tool call this result corresponds to
        tool_name: Name of the tool that was executed
        content: String representation of the result
        error: Optional error message if tool execution failed
        raw_result: Optional original result dict
    """

    tool_call_id: str
    tool_name: str
    content: str
    error: str | None = None
    raw_result: dict | None = None

    def __post_init__(self) -> None:
        """Validate tool result."""
        if not self.tool_call_id:
            logger.debug(
                f"ToolResult for {self.tool_name} has empty tool_call_id "
                "(will be set by caller)"
            )

        if not self.tool_name:
            raise ValueError("tool_name cannot be empty")

        if not self.content and not self.error:
            logger.warning("ToolResult for {self.tool_name} has no content or error")

    def is_error(self) -> bool:
        """Check if tool execution resulted in an error."""
        return self.error is not None

    def to_message_dict(self) -> dict[str, str]:
        """Convert to message dictionary for LLM conversation."""
        content = self.content
        if self.error:
            content = f"Error: {self.error}"

        if not content or content.strip() == "":
            content = "(empty result)"

        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.tool_name,
            "content": content,
        }
