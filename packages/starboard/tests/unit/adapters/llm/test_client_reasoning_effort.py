# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for reasoning_effort=none injected for GPT-5 models when tools are used."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starboard.adapters.llm.openai.client import OpenAIProvider
from starboard.infra.core.config import EnvConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StopTest(Exception):
    """Sentinel raised inside mocks to abort after capturing call kwargs."""


def _make_config(model: str) -> EnvConfig:
    return EnvConfig(
        llm_provider="openai",
        llm_api_key="test-key",
        llm_model=model,
    )


def _make_provider(model: str) -> OpenAIProvider:
    """Build an OpenAIProvider with a fake AsyncOpenAI client."""
    with patch("starboard.adapters.llm.openai.client.AsyncOpenAI"):
        provider = OpenAIProvider(cfg=_make_config(model))
    # Replace the mock's chat.completions.create with a plain AsyncMock
    provider.async_client = MagicMock()
    provider.async_client.chat.completions.create = AsyncMock()
    return provider


def _minimal_tool_response() -> MagicMock:
    """Minimal mock response that call_with_tools can read without crashing."""
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.total_tokens = 15
    # Extra attributes normalize_usage may inspect
    usage.prompt_tokens_details = None
    usage.completion_tokens_details = None

    message = MagicMock()
    message.content = "ok"
    message.tool_calls = None

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"

    resp = MagicMock()
    resp.usage = usage
    resp.choices = [choice]
    return resp


_DUMMY_TOOL = {
    "type": "function",
    "function": {
        "name": "dummy",
        "description": "A dummy tool",
        "parameters": {"type": "object", "properties": {}},
    },
}


# ---------------------------------------------------------------------------
# call_with_tools — GPT-5 → reasoning_effort must be "none"
# ---------------------------------------------------------------------------

class TestCallWithToolsGpt5:
    @pytest.mark.asyncio
    async def test_gpt5_model_adds_reasoning_effort_none(self) -> None:
        provider = _make_provider("databricks-gpt-5-6-sol")
        provider.async_client.chat.completions.create.return_value = _minimal_tool_response()

        await provider.call_with_tools(
            messages=[{"role": "user", "content": "hello"}],
            tools=[_DUMMY_TOOL],
        )

        call_kwargs = provider.async_client.chat.completions.create.call_args[1]
        assert "tools" in call_kwargs, "tools should be present"
        assert call_kwargs.get("reasoning_effort") == "none", (
            "GPT-5 + tools must send reasoning_effort='none'"
        )

    @pytest.mark.asyncio
    async def test_gpt5_model_variant_gpt5_adds_reasoning_effort_none(self) -> None:
        provider = _make_provider("gpt-5")
        provider.async_client.chat.completions.create.return_value = _minimal_tool_response()

        await provider.call_with_tools(
            messages=[{"role": "user", "content": "hello"}],
            tools=[_DUMMY_TOOL],
        )

        call_kwargs = provider.async_client.chat.completions.create.call_args[1]
        assert call_kwargs.get("reasoning_effort") == "none"


# ---------------------------------------------------------------------------
# call_with_tools — non-GPT-5 → no reasoning_effort
# ---------------------------------------------------------------------------

class TestCallWithToolsNonGpt5:
    @pytest.mark.asyncio
    async def test_non_gpt5_model_no_reasoning_effort(self) -> None:
        provider = _make_provider("databricks-claude-opus-4-8")
        provider.async_client.chat.completions.create.return_value = _minimal_tool_response()

        await provider.call_with_tools(
            messages=[{"role": "user", "content": "hello"}],
            tools=[_DUMMY_TOOL],
        )

        call_kwargs = provider.async_client.chat.completions.create.call_args[1]
        assert "tools" in call_kwargs
        assert "reasoning_effort" not in call_kwargs, (
            "Non-GPT-5 models must NOT receive reasoning_effort"
        )


# ---------------------------------------------------------------------------
# call_with_tools_stream — GPT-5 → reasoning_effort must be "none"
# ---------------------------------------------------------------------------

class TestCallWithToolsStreamGpt5:
    @pytest.mark.asyncio
    async def test_gpt5_stream_adds_reasoning_effort_none(self) -> None:
        provider = _make_provider("databricks-gpt-5-6-sol")

        captured: dict = {}

        async def _capture_and_stop(**kwargs: object) -> None:
            captured.update(kwargs)
            raise _StopTest("captured")

        provider.async_client.chat.completions.create.side_effect = _capture_and_stop

        with pytest.raises(_StopTest):
            async for _ in provider.call_with_tools_stream(
                messages=[{"role": "user", "content": "hello"}],
                tools=[_DUMMY_TOOL],
            ):
                pass

        assert "tools" in captured, "tools should be present"
        assert captured.get("reasoning_effort") == "none", (
            "GPT-5 + tools stream must send reasoning_effort='none'"
        )


# ---------------------------------------------------------------------------
# call_with_tools_stream — non-GPT-5 → no reasoning_effort
# ---------------------------------------------------------------------------

class TestCallWithToolsStreamNonGpt5:
    @pytest.mark.asyncio
    async def test_non_gpt5_stream_no_reasoning_effort(self) -> None:
        provider = _make_provider("databricks-claude-opus-4-8")

        captured: dict = {}

        async def _capture_and_stop(**kwargs: object) -> None:
            captured.update(kwargs)
            raise _StopTest("captured")

        provider.async_client.chat.completions.create.side_effect = _capture_and_stop

        with pytest.raises(_StopTest):
            async for _ in provider.call_with_tools_stream(
                messages=[{"role": "user", "content": "hello"}],
                tools=[_DUMMY_TOOL],
            ):
                pass

        assert "tools" in captured
        assert "reasoning_effort" not in captured, (
            "Non-GPT-5 models must NOT receive reasoning_effort in stream path"
        )
