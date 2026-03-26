"""Typed accessors for OpenAI SDK streaming objects.

Centralizes hasattr/getattr checks into a single module so that if the SDK
changes its internal structure, only this file needs updating.
"""

from __future__ import annotations

from typing import Any


def get_delta_content(delta: Any) -> str | None:
    """Extract content from a streaming delta, or None."""
    return getattr(delta, "content", None) or None


def get_delta_tool_calls(delta: Any) -> list[Any] | None:
    """Extract tool calls from a streaming delta, or None."""
    calls = getattr(delta, "tool_calls", None)
    return calls if calls else None


def get_tool_call_id(tc_delta: Any) -> str | None:
    """Extract tool call ID from a delta."""
    return getattr(tc_delta, "id", None) or None


def get_tool_call_function_name(tc_delta: Any) -> str | None:
    """Extract function name from a tool call delta."""
    fn = getattr(tc_delta, "function", None)
    if fn is None:
        return None
    return getattr(fn, "name", None) or None


def get_tool_call_function_args(tc_delta: Any) -> str | None:
    """Extract function arguments from a tool call delta."""
    fn = getattr(tc_delta, "function", None)
    if fn is None:
        return None
    return getattr(fn, "arguments", None) or None


def get_chunk_usage(chunk: Any) -> Any | None:
    """Extract usage from a chunk, or None."""
    return getattr(chunk, "usage", None) or None
