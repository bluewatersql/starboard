"""Streaming response handling for OpenAI API calls.

Extracts the streaming iteration logic, chunk buffering, and tool call
accumulation from the main client into reusable async generator functions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import (
    APIError,
    APITimeoutError,
    RateLimitError,
)

from starboard_server.adapters.llm.openai.sdk_types import (
    get_chunk_usage,
    get_delta_content,
    get_delta_tool_calls,
    get_tool_call_function_args,
    get_tool_call_function_name,
    get_tool_call_id,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


async def iter_text_stream(
    stream: Any,
    collect_token_usage: Any,
    normalize_usage: Any,
) -> AsyncIterator[tuple[str, int, int, int]]:
    """Iterate over a text streaming response, yielding content chunks.

    Yields tuples of (content, input_tokens, output_tokens, chunk_count)
    where token counts are updated from usage data in the final chunk.

    Args:
        stream: The async stream from OpenAI API
        collect_token_usage: Callback to collect token usage
        normalize_usage: Function to normalize usage data

    Yields:
        Content string chunks as they arrive
    """
    chunk_count = 0

    async for chunk in stream:
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta
            if delta.content:
                chunk_count += 1
                yield delta.content

        # Collect usage if available (usually in the last chunk)
        usage = get_chunk_usage(chunk)
        if usage:
            collect_token_usage(usage)
            normalize_usage(usage)


async def iter_json_stream(
    stream: Any,
    collect_token_usage: Any,
) -> AsyncIterator[tuple[str, Any]]:
    """Iterate over a JSON streaming response, yielding content chunks.

    Yields tuples of (content_chunk, usage_or_none).

    Args:
        stream: The async stream from OpenAI API
        collect_token_usage: Callback to collect token usage

    Yields:
        Content string chunks as they arrive
    """
    async for chunk in stream:
        usage = None
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content, None

        usage = get_chunk_usage(chunk)
        if usage:
            collect_token_usage(usage)
            yield "", usage


async def iter_tool_call_stream(
    stream: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Iterate over a streaming tool-call response with smart buffering.

    Text tokens are yielded immediately for real-time display.
    Tool calls are buffered until complete, then yielded as full calls.

    Args:
        stream: The async stream from OpenAI API

    Yields:
        Streaming event dicts with type, content, tool_calls, or usage
    """
    tool_calls_buffer: dict[int, dict[str, Any]] = {}
    finish_reason = None
    total_tokens_estimate = 0

    async for chunk in stream:
        if not chunk.choices or len(chunk.choices) == 0:
            continue

        delta = chunk.choices[0].delta
        finish_reason = chunk.choices[0].finish_reason or finish_reason

        # Handle content deltas (thinking/reasoning text)
        content = get_delta_content(delta)
        if content:
            total_tokens_estimate += 1
            yield {
                "type": "content_delta",
                "content": content,
                "finish_reason": finish_reason,
            }

        # Handle tool call deltas (buffered until complete)
        tool_calls = get_delta_tool_calls(delta)
        if tool_calls:
            for tc_delta in tool_calls:
                idx = tc_delta.index

                if idx not in tool_calls_buffer:
                    tool_calls_buffer[idx] = {
                        "id": "",
                        "type": "function",
                        "name": "",
                        "arguments": "",
                    }

                tc_id = get_tool_call_id(tc_delta)
                if tc_id:
                    tool_calls_buffer[idx]["id"] = tc_id
                tc_name = get_tool_call_function_name(tc_delta)
                if tc_name:
                    tool_calls_buffer[idx]["name"] = tc_name
                tc_args = get_tool_call_function_args(tc_delta)
                if tc_args:
                    tool_calls_buffer[idx]["arguments"] += tc_args

    # Stream complete - yield buffered tool calls if any
    if tool_calls_buffer:
        sorted_calls = [
            {
                "id": call["id"],
                "name": call["name"],
                "arguments": call["arguments"],
            }
            for _, call in sorted(tool_calls_buffer.items())
        ]
        yield {
            "type": "tool_calls_delta",
            "tool_calls": sorted_calls,
            "finish_reason": finish_reason,
        }

    # Yield usage/finish metadata
    yield {
        "type": "_stream_meta",
        "finish_reason": finish_reason,
        "total_tokens_estimate": total_tokens_estimate,
        "tool_calls_buffer": tool_calls_buffer,
    }


def build_streaming_usage(
    stream: Any,
    messages: list[dict[str, Any]],
    total_tokens_estimate: int,
    collect_token_usage: Any,
) -> dict[str, int]:
    """Build usage data from stream, falling back to estimates.

    Args:
        stream: The completed stream object
        messages: Original messages for estimation
        total_tokens_estimate: Rough token estimate from chunk counting
        collect_token_usage: Callback to collect token usage

    Returns:
        Usage data dict with prompt_tokens, completion_tokens, total_tokens
    """
    usage = get_chunk_usage(stream)
    if usage:
        usage_data = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }
        collect_token_usage(usage)
    else:
        prompt_tokens = (
            sum(len(str(m.get("content", "")).split()) for m in messages) * 1.3
        )
        usage_data = {
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": total_tokens_estimate,
            "total_tokens": int(prompt_tokens) + total_tokens_estimate,
        }
    return usage_data


def yield_error_event(error: Exception) -> dict[str, Any]:
    """Create an error event dict from an exception.

    Args:
        error: The exception

    Returns:
        Error event dict for streaming
    """
    if isinstance(error, RateLimitError):
        return {
            "type": "error",
            "error_type": "RateLimitError",
            "error_message": str(error),
        }
    elif isinstance(error, APITimeoutError):
        return {
            "type": "error",
            "error_type": "APITimeoutError",
            "error_message": str(error),
        }
    elif isinstance(error, APIError):
        return {
            "type": "error",
            "error_type": "APIError",
            "error_message": str(error),
        }
    elif isinstance(
        error, (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout)
    ):
        return {
            "type": "error",
            "error_type": type(error).__name__,
            "error_message": f"Network error: {str(error)}. The connection was interrupted - this may be due to timeout or network issues.",
            "recoverable": True,
        }
    else:
        return {
            "type": "error",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
