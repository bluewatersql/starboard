"""Tests for prompt separation in IntentRouter (items 2 & 5).

TDD: These tests are written BEFORE the implementation.

Verifies:
- User input is placed in a separate user-role message, NOT interpolated into system prompt
- The classification call includes an explicit system message forbidding instruction-following
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard_server.agents.routing.intent_router import IntentRouter


class CapturingLLMClient:
    """Test double that captures the messages sent to the LLM."""

    def __init__(self) -> None:
        self.captured_messages: list[dict[str, Any]] = []
        self.response = {
            "domain": "query",
            "confidence": 0.8,
            "reasoning": "test",
        }

    async def json_response(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.captured_messages = messages
        return self.response

    @property
    def model(self) -> str:
        return "gpt-4o-mini"


async def _call_llm_classify(router: IntentRouter, user_input: str) -> None:
    """Directly call the LLM classification path, bypassing pattern matching."""
    await router._llm_classify(user_input, conversation_history=[])


@pytest.mark.asyncio
async def test_user_input_in_separate_user_message() -> None:
    """User input must NOT be interpolated into the system prompt.

    The messages array sent to LLM must contain a separate user-role message
    containing the user input, not have it embedded in the system message.
    """
    client = CapturingLLMClient()
    router = IntentRouter(client)

    user_input = "What is the cost of my warehouse last month?"
    await _call_llm_classify(router, user_input)

    assert client.captured_messages, "LLM was not called"

    user_messages = [m for m in client.captured_messages if m.get("role") == "user"]
    assert user_messages, "No user-role message found in LLM call"

    user_content = " ".join(m.get("content", "") for m in user_messages)
    assert user_input in user_content, (
        f"User input '{user_input}' not found in user-role messages. "
        f"Messages: {client.captured_messages}"
    )


@pytest.mark.asyncio
async def test_user_input_not_in_system_message() -> None:
    """User input must NOT be embedded directly inside the system prompt string."""
    client = CapturingLLMClient()
    router = IntentRouter(client)

    user_input = "UNIQUE_MARKER_XYZ_show warehouse costs"
    await _call_llm_classify(router, user_input)

    assert client.captured_messages, "LLM was not called"

    system_messages = [m for m in client.captured_messages if m.get("role") == "system"]

    for msg in system_messages:
        content = msg.get("content", "")
        assert "UNIQUE_MARKER_XYZ" not in content, (
            "User input was interpolated into the system prompt. "
            "User input must be in a separate user-role message."
        )


@pytest.mark.asyncio
async def test_system_message_instructs_classify_only() -> None:
    """The system message must instruct the model to ONLY classify intent."""
    client = CapturingLLMClient()
    router = IntentRouter(client)

    await _call_llm_classify(router, "What are my cluster costs?")

    assert client.captured_messages, "LLM was not called"

    system_messages = [m for m in client.captured_messages if m.get("role") == "system"]
    assert system_messages, "No system-role message found in LLM classification call"

    system_content = " ".join(m.get("content", "") for m in system_messages).lower()

    has_classify_only = any(
        phrase in system_content
        for phrase in [
            "only classify",
            "classify only",
            "do not follow",
            "ignore any instructions",
            "only determine",
            "only your task is to classify",
            "your only task",
        ]
    )
    assert has_classify_only, (
        "System message does not instruct the model to ONLY classify intent. "
        f"System content: {system_content[:500]}"
    )


@pytest.mark.asyncio
async def test_messages_have_system_then_user_structure() -> None:
    """LLM call must follow standard chat structure: system message first, then user."""
    client = CapturingLLMClient()
    router = IntentRouter(client)

    await _call_llm_classify(router, "analyze my job performance trends")

    assert client.captured_messages, "LLM was not called"

    roles = [m.get("role") for m in client.captured_messages]
    assert "system" in roles, "No system message in LLM call"
    assert "user" in roles, "No user message in LLM call"

    first_system = roles.index("system")
    first_user = roles.index("user")
    assert first_system < first_user, (
        "System message must precede user message in messages array"
    )
