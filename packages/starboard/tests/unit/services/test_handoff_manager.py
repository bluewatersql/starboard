# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for agent handoff manager.

Phase 3 Component 3: Handoff Manager & Persistence

Tests cover:
- AgentHandoff domain model
- HandoffManager handoff lifecycle
- Handoff initiation
- Handoff completion (success/failure)
- Handoff persistence
- Handoff retrieval
- Context preservation
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from starboard.services.coordination.handoff_manager import (
    AgentHandoff,
    HandoffManager,
    HandoffStatus,
)


class TestAgentHandoff:
    """Tests for AgentHandoff domain model."""

    def test_handoff_creation(self):
        """AgentHandoff can be created with all fields."""
        handoff_id = uuid4()
        now = datetime.now(UTC)

        handoff = AgentHandoff(
            handoff_id=handoff_id,
            conversation_id="conv_123",
            source_agent_id="query_optimizer",
            target_agent_id="performance_analyzer",
            capability_id="identify_slow_queries",
            status=HandoffStatus.INITIATED,
            handoff_context={"warehouse_id": "prod_dw"},
            initiated_at=now,
            completed_at=None,
            failure_reason=None,
        )

        assert handoff.handoff_id == handoff_id
        assert handoff.conversation_id == "conv_123"
        assert handoff.source_agent_id == "query_optimizer"
        assert handoff.target_agent_id == "performance_analyzer"
        assert handoff.status == HandoffStatus.INITIATED
        assert handoff.handoff_context["warehouse_id"] == "prod_dw"
        assert handoff.initiated_at == now
        assert handoff.completed_at is None

    def test_handoff_immutable(self):
        """AgentHandoff is immutable (frozen dataclass)."""
        handoff = AgentHandoff(
            handoff_id=uuid4(),
            conversation_id="conv_123",
            source_agent_id="test",
            target_agent_id="test2",
            capability_id=None,
            status=HandoffStatus.INITIATED,
            handoff_context={},
            initiated_at=datetime.now(UTC),
            completed_at=None,
            failure_reason=None,
        )

        with pytest.raises(AttributeError):
            handoff.status = HandoffStatus.COMPLETED  # type: ignore

    def test_handoff_status_enum(self):
        """HandoffStatus enum has expected values."""
        assert HandoffStatus.INITIATED.value == "initiated"
        assert HandoffStatus.COMPLETED.value == "completed"
        assert HandoffStatus.FAILED.value == "failed"

    def test_handoff_with_failure(self):
        """AgentHandoff can capture failure information."""
        now = datetime.now(UTC)

        handoff = AgentHandoff(
            handoff_id=uuid4(),
            conversation_id="conv_123",
            source_agent_id="test",
            target_agent_id="nonexistent",
            capability_id=None,
            status=HandoffStatus.FAILED,
            handoff_context={},
            initiated_at=now,
            completed_at=now,
            failure_reason="Target agent not found",
        )

        assert handoff.status == HandoffStatus.FAILED
        assert handoff.failure_reason == "Target agent not found"
        assert handoff.completed_at is not None


class TestHandoffManager:
    """Tests for HandoffManager."""

    @pytest.fixture
    def repository(self):
        """Create mock repository."""
        repo = Mock()
        repo.save_handoff_model = AsyncMock()
        repo.get_handoff = AsyncMock()
        repo.update_handoff_status = AsyncMock()
        repo.get_handoffs_for_conversation = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def manager(self, repository):
        """Create handoff manager."""
        return HandoffManager(repository=repository)

    @pytest.mark.asyncio
    async def test_initiate_handoff(self, manager, repository):
        """HandoffManager can initiate handoff."""
        handoff = await manager.initiate_handoff(
            conversation_id="conv_123",
            source_agent_id="query_optimizer",
            target_agent_id="performance_analyzer",
            capability_id="identify_slow_queries",
            handoff_context={"warehouse_id": "prod_dw"},
        )

        # Check handoff structure
        assert handoff.conversation_id == "conv_123"
        assert handoff.source_agent_id == "query_optimizer"
        assert handoff.target_agent_id == "performance_analyzer"
        assert handoff.capability_id == "identify_slow_queries"
        assert handoff.status == HandoffStatus.INITIATED
        assert handoff.handoff_context["warehouse_id"] == "prod_dw"
        assert handoff.initiated_at is not None
        assert handoff.completed_at is None

        # Check persistence
        repository.save_handoff_model.assert_called_once()
        saved_handoff = repository.save_handoff_model.call_args[0][0]
        assert saved_handoff.handoff_id == handoff.handoff_id

    @pytest.mark.asyncio
    async def test_complete_handoff_success(self, manager, repository):
        """HandoffManager can mark handoff as completed."""
        handoff_id = uuid4()

        await manager.complete_handoff(
            handoff_id=handoff_id,
            success=True,
        )

        # Check status update
        repository.update_handoff_status.assert_called_once_with(
            handoff_id=handoff_id,
            status=HandoffStatus.COMPLETED,
            failure_reason=None,
        )

    @pytest.mark.asyncio
    async def test_complete_handoff_failure(self, manager, repository):
        """HandoffManager can mark handoff as failed."""
        handoff_id = uuid4()
        failure_reason = "Target agent returned error"

        await manager.complete_handoff(
            handoff_id=handoff_id,
            success=False,
            failure_reason=failure_reason,
        )

        # Check status update
        repository.update_handoff_status.assert_called_once_with(
            handoff_id=handoff_id,
            status=HandoffStatus.FAILED,
            failure_reason=failure_reason,
        )

    @pytest.mark.asyncio
    async def test_get_handoff_by_id(self, manager, repository):
        """HandoffManager can retrieve handoff by ID."""
        handoff_id = uuid4()
        mock_handoff = AgentHandoff(
            handoff_id=handoff_id,
            conversation_id="conv_123",
            source_agent_id="test",
            target_agent_id="test2",
            capability_id=None,
            status=HandoffStatus.COMPLETED,
            handoff_context={},
            initiated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            failure_reason=None,
        )
        repository.get_handoff.return_value = mock_handoff

        result = await manager.get_handoff(handoff_id)

        assert result == mock_handoff
        repository.get_handoff.assert_called_once_with(handoff_id)

    @pytest.mark.asyncio
    async def test_get_handoff_not_found(self, manager, repository):
        """HandoffManager returns None if handoff not found."""
        handoff_id = uuid4()
        repository.get_handoff.return_value = None

        result = await manager.get_handoff(handoff_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_handoffs(self, manager, repository):
        """HandoffManager can retrieve all handoffs for conversation."""
        conv_id = "conv_123"
        mock_handoffs = [
            AgentHandoff(
                handoff_id=uuid4(),
                conversation_id=conv_id,
                source_agent_id="agent1",
                target_agent_id="agent2",
                capability_id=None,
                status=HandoffStatus.COMPLETED,
                handoff_context={},
                initiated_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                failure_reason=None,
            ),
            AgentHandoff(
                handoff_id=uuid4(),
                conversation_id=conv_id,
                source_agent_id="agent2",
                target_agent_id="agent3",
                capability_id=None,
                status=HandoffStatus.INITIATED,
                handoff_context={},
                initiated_at=datetime.now(UTC),
                completed_at=None,
                failure_reason=None,
            ),
        ]
        repository.get_handoffs_for_conversation.return_value = mock_handoffs

        result = await manager.get_conversation_handoffs(conv_id)

        assert len(result) == 2
        assert result[0].source_agent_id == "agent1"
        assert result[1].source_agent_id == "agent2"
        repository.get_handoffs_for_conversation.assert_called_once_with(conv_id)

    @pytest.mark.asyncio
    async def test_handoff_preserves_context(self, manager):
        """Handoff context is preserved during handoff."""
        context = {
            "warehouse_id": "prod_dw",
            "user_constraints": ["performance", "cost < 100"],
            "conversation_summary": "User analyzing query performance",
        }

        handoff = await manager.initiate_handoff(
            conversation_id="conv_123",
            source_agent_id="query_optimizer",
            target_agent_id="performance_analyzer",
            capability_id="identify_slow_queries",
            handoff_context=context,
        )

        assert handoff.handoff_context["warehouse_id"] == "prod_dw"
        assert len(handoff.handoff_context["user_constraints"]) == 2
        assert "performance" in handoff.handoff_context["user_constraints"]

    @pytest.mark.asyncio
    async def test_handoff_count_for_conversation(self, manager, repository):
        """Can count handoffs for circular routing prevention."""
        conv_id = "conv_123"
        mock_handoffs = [
            AgentHandoff(
                handoff_id=uuid4(),
                conversation_id=conv_id,
                source_agent_id=f"agent{i}",
                target_agent_id=f"agent{i + 1}",
                capability_id=None,
                status=HandoffStatus.COMPLETED,
                handoff_context={},
                initiated_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                failure_reason=None,
            )
            for i in range(3)
        ]
        repository.get_handoffs_for_conversation.return_value = mock_handoffs

        count = await manager.get_handoff_count(conv_id)

        assert count == 3

    @pytest.mark.asyncio
    async def test_circular_routing_detection(self, manager, repository):
        """Manager can detect potential circular routing."""
        conv_id = "conv_123"
        # Simulate 3 completed handoffs (at max limit)
        mock_handoffs = [
            AgentHandoff(
                handoff_id=uuid4(),
                conversation_id=conv_id,
                source_agent_id=f"agent{i}",
                target_agent_id=f"agent{i + 1}",
                capability_id=None,
                status=HandoffStatus.COMPLETED,
                handoff_context={},
                initiated_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                failure_reason=None,
            )
            for i in range(3)
        ]
        repository.get_handoffs_for_conversation.return_value = mock_handoffs

        # Should return True when at/above limit
        is_circular = await manager.is_circular_routing(conv_id, max_handoffs=3)

        assert is_circular is True

    @pytest.mark.asyncio
    async def test_circular_routing_under_limit(self, manager, repository):
        """Manager allows routing under limit."""
        conv_id = "conv_123"
        # Only 2 handoffs
        mock_handoffs = [
            AgentHandoff(
                handoff_id=uuid4(),
                conversation_id=conv_id,
                source_agent_id=f"agent{i}",
                target_agent_id=f"agent{i + 1}",
                capability_id=None,
                status=HandoffStatus.COMPLETED,
                handoff_context={},
                initiated_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                failure_reason=None,
            )
            for i in range(2)
        ]
        repository.get_handoffs_for_conversation.return_value = mock_handoffs

        is_circular = await manager.is_circular_routing(conv_id, max_handoffs=3)

        assert is_circular is False

    @pytest.mark.asyncio
    async def test_handoff_with_empty_context(self, manager):
        """Handoff works with empty context."""
        handoff = await manager.initiate_handoff(
            conversation_id="conv_123",
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_context={},
        )

        assert handoff.handoff_context == {}
        assert handoff.status == HandoffStatus.INITIATED

    @pytest.mark.asyncio
    async def test_handoff_without_capability(self, manager):
        """Handoff works without explicit capability ID."""
        handoff = await manager.initiate_handoff(
            conversation_id="conv_123",
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_context={"test": "value"},
        )

        assert handoff.capability_id is None
        assert handoff.status == HandoffStatus.INITIATED
