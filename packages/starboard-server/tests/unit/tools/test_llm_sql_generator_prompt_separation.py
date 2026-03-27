"""Tests for prompt separation in LLMSQLGenerator (item 3).

TDD: These tests are written BEFORE the implementation.

Verifies:
- User query text is placed in a separate user-role message, NOT interpolated
  into the system prompt via f-string.
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.rag.models import RAGContext
from starboard_server.tools.domain.analytics_sql.llm_sql_generator import (
    LLMSQLGenerator,
)
from starboard_server.tools.domain.analytics_sql.models import (
    QueryDomain,
    QueryIntent,
    QueryIntentContext,
)


class CapturingLLMClient:
    """Test double that captures messages sent to the LLM."""

    def __init__(self) -> None:
        self.captured_messages: list[dict[str, Any]] = []
        self.response: dict[str, Any] = {
            "sql": "SELECT 1",
            "explanation": "test",
            "confidence": 0.9,
            "missing_context": ["none"],
            "confidence_reasoning": "test",
            "visualization_hints": {
                "query_intent": "test",
                "recommended_chart_types": ["table"],
                "is_time_series": False,
                "is_top_n": False,
                "aggregation_type": "none",
            },
        }

    async def json_response(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.captured_messages = messages
        return self.response


def _make_context() -> tuple[QueryIntentContext, RAGContext]:
    """Build minimal valid context objects."""
    intent_ctx = QueryIntentContext(
        intent=QueryIntent.TREND_ANALYSIS,
        domain=QueryDomain.BILLING,
        confidence=0.9,
        reasoning="test classification",
    )
    rag_ctx = RAGContext(
        tables=[],
        nuance=[],
        codebook=[],
        facets=[],
        learnings=[],
    )
    return intent_ctx, rag_ctx


@pytest.mark.asyncio
async def test_user_query_in_separate_user_message() -> None:
    """User query text must appear in a user-role message, not the system prompt."""
    client = CapturingLLMClient()
    generator = LLMSQLGenerator(client)
    intent_ctx, rag_ctx = _make_context()

    user_query = "Show me warehouse costs for the last 30 days"
    await generator.generate(
        user_query=user_query,
        intent_context=intent_ctx,
        rag_context=rag_ctx,
    )

    assert client.captured_messages, "LLM was not called"

    user_messages = [m for m in client.captured_messages if m.get("role") == "user"]
    assert user_messages, "No user-role message found"

    user_content = " ".join(m.get("content", "") for m in user_messages)
    assert user_query in user_content, (
        f"User query not found in user-role messages. "
        f"Messages: {client.captured_messages}"
    )


@pytest.mark.asyncio
async def test_user_query_not_in_system_message() -> None:
    """User query text must NOT be embedded in the system prompt."""
    client = CapturingLLMClient()
    generator = LLMSQLGenerator(client)
    intent_ctx, rag_ctx = _make_context()

    user_query = "UNIQUE_MARKER_ABC_show warehouse costs"
    await generator.generate(
        user_query=user_query,
        intent_context=intent_ctx,
        rag_context=rag_ctx,
    )

    assert client.captured_messages, "LLM was not called"

    system_messages = [m for m in client.captured_messages if m.get("role") == "system"]
    for msg in system_messages:
        content = msg.get("content", "")
        assert "UNIQUE_MARKER_ABC" not in content, (
            "User query was interpolated into the system prompt. "
            "User query must be in a separate user-role message."
        )


@pytest.mark.asyncio
async def test_messages_follow_system_user_structure() -> None:
    """LLM messages must follow system-then-user structure."""
    client = CapturingLLMClient()
    generator = LLMSQLGenerator(client)
    intent_ctx, rag_ctx = _make_context()

    await generator.generate(
        user_query="show costs",
        intent_context=intent_ctx,
        rag_context=rag_ctx,
    )

    assert client.captured_messages

    roles = [m.get("role") for m in client.captured_messages]
    assert "system" in roles
    assert "user" in roles

    first_system = roles.index("system")
    last_user = len(roles) - 1 - roles[::-1].index("user")
    assert first_system < last_user
