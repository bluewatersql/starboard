# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for multi-turn conversation ID generation and threading."""

import re

import pytest
from starboard.mcp.agent_bridge import generate_conversation_id


class TestGenerateConversationId:
    """Tests for generate_conversation_id utility."""

    def test_returns_string(self) -> None:
        cid = generate_conversation_id()
        assert isinstance(cid, str)

    def test_starts_with_prefix(self) -> None:
        cid = generate_conversation_id()
        assert cid.startswith("mcp-conv-")

    def test_has_correct_length(self) -> None:
        # "mcp-conv-" (9 chars) + 12 hex chars = 21
        cid = generate_conversation_id()
        assert len(cid) == 21

    def test_hex_suffix(self) -> None:
        cid = generate_conversation_id()
        suffix = cid[len("mcp-conv-") :]
        assert re.fullmatch(r"[0-9a-f]{12}", suffix)

    def test_unique_ids(self) -> None:
        ids = {generate_conversation_id() for _ in range(100)}
        assert len(ids) == 100


class TestConversationIdAutoGeneration:
    """Tests that MCPAgentExecutor auto-generates conversation_id."""

    @pytest.fixture()
    def _mock_executor(self) -> tuple:
        """Create an executor with mocked dependencies."""
        from unittest.mock import AsyncMock, MagicMock

        from starboard.mcp.agent_bridge import MCPAgentExecutor

        factory = MagicMock()
        factory.events = None
        mock_agent = MagicMock()
        mock_agent.config.domain = "query"
        mock_agent.run_stream = AsyncMock(return_value=iter([]))
        factory.get_agent.return_value = mock_agent

        executor = MCPAgentExecutor(
            agent_factory=factory,
            intent_router=None,
            default_timeout=30,
        )
        return executor, factory, mock_agent

    @pytest.mark.asyncio()
    async def test_auto_generates_when_none(self, _mock_executor: tuple) -> None:
        executor, _factory, mock_agent = _mock_executor

        # Make run_stream return an empty async iterator
        async def _empty_stream(**_kwargs: object) -> object:
            return
            yield  # type: ignore[misc]  # noqa: RET503

        mock_agent.run_stream = _empty_stream

        response = await executor.execute(
            message="test",
            workspace_id="ws-1",
            domain="query",
            conversation_id=None,
        )
        # Response metadata should have a generated conversation_id
        assert response.mcp_metadata is not None
        assert response.mcp_metadata.conversation_id is not None
        assert response.mcp_metadata.conversation_id.startswith("mcp-conv-")

    @pytest.mark.asyncio()
    async def test_preserves_provided_id(self, _mock_executor: tuple) -> None:
        executor, _factory, mock_agent = _mock_executor

        async def _empty_stream(**_kwargs: object) -> object:
            return
            yield  # type: ignore[misc]  # noqa: RET503

        mock_agent.run_stream = _empty_stream

        response = await executor.execute(
            message="test",
            workspace_id="ws-1",
            domain="query",
            conversation_id="user-provided-123",
        )
        assert response.mcp_metadata is not None
        assert response.mcp_metadata.conversation_id == "user-provided-123"
