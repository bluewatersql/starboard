# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Regression tests: reasoning-model streaming deltas must flatten to text.

Reasoning models served over the OpenAI-compatible endpoint (e.g.
``databricks-claude-sonnet-5``) emit ``delta.content`` as a **list of content
blocks** (``[{"type": "reasoning", "summary": [{"type": "summary_text",
"text": ...}]}]``) rather than a plain string. The SDK-shape absorber
(:mod:`starboard.adapters.llm.openai.sdk_types`) flattens that to text so every
streaming path yields ``str`` and the reasoning engine's
``accumulated_content += content`` never hits ``str + list``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from starboard.adapters.llm.openai.sdk_types import get_delta_content

# --------------------------------------------------------------------------- #
# Fakes shaped like the OpenAI streaming SDK objects                           #
# --------------------------------------------------------------------------- #


def _chunk(content: Any) -> SimpleNamespace:
    """A streaming chunk whose single choice carries ``delta.content``."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(choices=[choice], usage=None)


# The reasoning-model shape that used to crash the stream.
_REASONING_BLOCKS = [
    {"type": "reasoning", "summary": [{"type": "summary_text", "text": "think "}]},
    {"type": "text", "text": "answer"},
]


# --------------------------------------------------------------------------- #
# get_delta_content                                                            #
# --------------------------------------------------------------------------- #


def test_get_delta_content_plain_string() -> None:
    assert get_delta_content(SimpleNamespace(content="hello")) == "hello"


def test_get_delta_content_none_and_empty() -> None:
    assert get_delta_content(SimpleNamespace(content=None)) is None
    assert get_delta_content(SimpleNamespace(content="")) is None
    assert get_delta_content(SimpleNamespace(content=[])) is None


def test_get_delta_content_flattens_reasoning_blocks() -> None:
    out = get_delta_content(SimpleNamespace(content=_REASONING_BLOCKS))
    assert out == "think answer"
    assert isinstance(out, str)


def test_get_delta_content_text_block_object() -> None:
    block = SimpleNamespace(type="text", text="hi", summary=None)
    assert get_delta_content(SimpleNamespace(content=[block])) == "hi"


# --------------------------------------------------------------------------- #
# THE LIVE PATH: OpenAIProvider.call_with_tools_stream (what the reasoning     #
# engine consumes). This is the path that actually crashed on reasoning models #
# --------------------------------------------------------------------------- #


def test_client_call_with_tools_stream_flattens_reasoning() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from starboard.adapters.llm.openai.client import OpenAIProvider
    from starboard.infra.core.config import EnvConfig

    with patch("starboard.adapters.llm.openai.client.AsyncOpenAI"):
        provider = OpenAIProvider(
            cfg=EnvConfig(
                llm_provider="openai",
                llm_api_key="test-key",
                llm_model="databricks-claude-sonnet-5",
            )
        )

    async def fake_stream() -> Any:
        yield _chunk(_REASONING_BLOCKS)

    provider.async_client = MagicMock()
    provider.async_client.chat.completions.create = AsyncMock(return_value=fake_stream())

    async def run() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for ev in provider.call_with_tools_stream(
            messages=[{"role": "user", "content": "hi"}], tools=[]
        ):
            events.append(ev)
        return events

    events = asyncio.run(run())
    deltas = [e for e in events if e.get("type") == "content_delta"]
    assert deltas, "expected a content_delta event from the live client path"
    assert all(isinstance(e["content"], str) for e in deltas)
    # Reproduce the reasoning engine's accumulation — must not raise str + list.
    acc = ""
    for e in deltas:
        acc += e["content"]
    assert acc == "think answer"
