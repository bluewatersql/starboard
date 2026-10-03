# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Streaming helpers for OpenAI API calls.

Provides usage accounting and error-event mapping shared by the streaming
methods on :class:`~starboard.adapters.llm.openai.client.OpenAIProvider`.

The per-chunk streaming loops live inline in ``client.py`` (they own the SDK
iteration); reasoning-model delta content is flattened to text via
:func:`starboard.adapters.llm.openai.sdk_types.get_delta_content` at those call
sites.
"""

from __future__ import annotations

from typing import Any

import httpx
from openai import (
    APIError,
    APITimeoutError,
    RateLimitError,
)

from starboard.adapters.llm.openai.sdk_types import get_chunk_usage
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


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
