# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for handoff streaming events.

Phase 3 Component 5: Streaming Events for Handoffs

Tests cover:
- HandoffEvent creation and serialization
- Event type registration
- SSE event conversion
- Handoff metadata structure
"""

from datetime import datetime
from uuid import uuid4

import pytest
from starboard.agents.events import (
    EventType,
    HandoffEvent,
)


class TestHandoffEvent:
    """Tests for HandoffEvent streaming event."""

    def test_event_type_registered(self):
        """HANDOFF event type is registered."""
        assert hasattr(EventType, "HANDOFF")
        assert EventType.HANDOFF == "handoff"

    def test_handoff_event_creation(self):
        """HandoffEvent can be created with all required fields."""
        handoff_id = uuid4()
        event = HandoffEvent(
            handoff_id=handoff_id,
            source_agent_id="query_optimizer",
            target_agent_id="performance_analyzer",
            capability_id="identify_slow_queries",
            handoff_reason="Identify slowest queries in warehouse",
            status="initiated",
        )

        assert event.handoff_id == handoff_id
        assert event.source_agent_id == "query_optimizer"
        assert event.target_agent_id == "performance_analyzer"
        assert event.capability_id == "identify_slow_queries"
        assert event.handoff_reason == "Identify slowest queries in warehouse"
        assert event.status == "initiated"

    def test_handoff_event_without_capability(self):
        """HandoffEvent works without capability_id."""
        event = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_reason="General routing",
            status="initiated",
        )

        assert event.capability_id is None

    def test_handoff_event_to_dict(self):
        """HandoffEvent serializes to dictionary correctly."""
        handoff_id = uuid4()
        event = HandoffEvent(
            handoff_id=handoff_id,
            source_agent_id="query_optimizer",
            target_agent_id="performance_analyzer",
            capability_id="identify_slow_queries",
            handoff_reason="Find slowest queries",
            status="initiated",
        )

        data = event.to_dict()

        assert data["type"] == EventType.HANDOFF
        assert data["handoff_id"] == str(handoff_id)
        assert data["source_agent_id"] == "query_optimizer"
        assert data["target_agent_id"] == "performance_analyzer"
        assert data["capability_id"] == "identify_slow_queries"
        assert data["handoff_reason"] == "Find slowest queries"
        assert data["status"] == "initiated"
        assert "timestamp" in data

    def test_handoff_event_timestamp(self):
        """HandoffEvent includes timestamp."""
        event = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_reason="Test",
            status="initiated",
        )

        data = event.to_dict()
        assert "timestamp" in data
        # Timestamp should be recent (within last minute)
        timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        now = datetime.now(timestamp.tzinfo)
        time_diff = (now - timestamp).total_seconds()
        assert 0 <= time_diff < 60

    def test_handoff_event_status_values(self):
        """HandoffEvent supports different status values."""
        statuses = ["initiated", "completed", "failed"]

        for status in statuses:
            event = HandoffEvent(
                handoff_id=uuid4(),
                source_agent_id="agent1",
                target_agent_id="agent2",
                capability_id=None,
                handoff_reason="Test",
                status=status,
            )

            data = event.to_dict()
            assert data["status"] == status

    def test_handoff_event_with_long_reason(self):
        """HandoffEvent handles long handoff reasons."""
        long_reason = "A" * 500  # Very long reason
        event = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_reason=long_reason,
            status="initiated",
        )

        data = event.to_dict()
        assert data["handoff_reason"] == long_reason

    def test_handoff_event_uuid_conversion(self):
        """HandoffEvent converts UUID to string in serialization."""
        handoff_id = uuid4()
        event = HandoffEvent(
            handoff_id=handoff_id,
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_reason="Test",
            status="initiated",
        )

        data = event.to_dict()
        # Should be string, not UUID object
        assert isinstance(data["handoff_id"], str)
        assert data["handoff_id"] == str(handoff_id)

    def test_handoff_event_immutable(self):
        """HandoffEvent is immutable (frozen Pydantic model)."""
        from pydantic import ValidationError

        event = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_reason="Test",
            status="initiated",
        )

        # Pydantic frozen models raise ValidationError, not AttributeError
        with pytest.raises(ValidationError):
            event.status = "completed"  # type: ignore

    def test_handoff_event_with_special_characters(self):
        """HandoffEvent handles special characters in reason."""
        reason_with_special = 'Test with "quotes" and \\backslash\\ and émojis 🚀'
        event = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_reason=reason_with_special,
            status="initiated",
        )

        data = event.to_dict()
        assert data["handoff_reason"] == reason_with_special

    def test_handoff_event_metadata_structure(self):
        """HandoffEvent has expected metadata structure."""
        event = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="query_optimizer",
            target_agent_id="performance_analyzer",
            capability_id="identify_slow_queries",
            handoff_reason="Find slowest queries",
            status="initiated",
        )

        data = event.to_dict()

        # Check all required keys present
        required_keys = {
            "type",
            "handoff_id",
            "source_agent_id",
            "target_agent_id",
            "capability_id",
            "handoff_reason",
            "status",
            "timestamp",
        }
        assert set(data.keys()) == required_keys

    def test_handoff_event_for_sse_streaming(self):
        """HandoffEvent is suitable for SSE streaming."""
        event = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="query_optimizer",
            target_agent_id="performance_analyzer",
            capability_id="identify_slow_queries",
            handoff_reason="Find slowest queries",
            status="initiated",
        )

        data = event.to_dict()

        # Should be JSON-serializable (all values are primitives)
        import json

        json_str = json.dumps(data)
        assert isinstance(json_str, str)

        # Should be parseable back
        parsed = json.loads(json_str)
        assert parsed["type"] == EventType.HANDOFF
        assert parsed["source_agent_id"] == "query_optimizer"

    def test_multiple_handoff_events(self):
        """Multiple HandoffEvents can be created independently."""
        event1 = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="agent1",
            target_agent_id="agent2",
            capability_id=None,
            handoff_reason="First handoff",
            status="initiated",
        )

        event2 = HandoffEvent(
            handoff_id=uuid4(),
            source_agent_id="agent2",
            target_agent_id="agent3",
            capability_id=None,
            handoff_reason="Second handoff",
            status="initiated",
        )

        # Should have different IDs
        assert event1.handoff_id != event2.handoff_id

        # Should have different data
        data1 = event1.to_dict()
        data2 = event2.to_dict()
        assert data1["handoff_id"] != data2["handoff_id"]
        assert data1["source_agent_id"] != data2["source_agent_id"]
