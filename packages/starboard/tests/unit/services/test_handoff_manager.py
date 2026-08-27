# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for agent handoff domain models.

Tests cover:
- AgentHandoff domain model
- HandoffStatus enum
- Context preservation
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from starboard.services.coordination.handoff_manager import (
    AgentHandoff,
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
