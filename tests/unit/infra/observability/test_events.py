# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for event system with emitters and handlers.

Coverage targets:
- Event creation and formatting
- Event emitter functionality
- Event handler registration
- Event bubbling through parent emitters
"""

from unittest.mock import Mock

from starboard_server.infra.observability.events import (
    EventEmitter,
    EventType,
    StatusEvent,
)


class TestStatusEvent:
    """Tests for StatusEvent dataclass."""

    def test_status_event_creation(self) -> None:
        """Test creating a basic status event."""
        # Act
        event = StatusEvent(
            type=EventType.INFO, source="test_source", message="Test message"
        )

        # Assert
        assert event.type == EventType.INFO
        assert event.source == "test_source"
        assert event.message == "Test message"
        assert event.data is None
        assert event.phase is None

    def test_status_event_with_data(self) -> None:
        """Test creating an event with additional data."""
        # Arrange
        test_data = {"key1": "value1", "count": 42}

        # Act
        event = StatusEvent(
            type=EventType.TRACE,
            source="task:discover",
            message="Discovery complete",
            data=test_data,
        )

        # Assert
        assert event.data == test_data
        assert event.data["key1"] == "value1"
        assert event.data["count"] == 42

    def test_status_event_with_phase(self) -> None:
        """Test creating an event with a phase."""
        # Act
        event = StatusEvent(
            type=EventType.INFO,
            source="orchestrator",
            message="Phase started",
            phase="planning",
        )

        # Assert
        assert event.phase == "planning"

    def test_status_event_str_without_phase(self) -> None:
        """Test string representation without phase."""
        # Arrange
        event = StatusEvent(
            type=EventType.INFO, source="test_source", message="Test message"
        )

        # Act
        event_str = str(event)

        # Assert
        assert event_str == "test_source: Test message"
        assert "[" not in event_str  # No phase indicator

    def test_status_event_str_with_phase(self) -> None:
        """Test string representation with phase."""
        # Arrange
        event = StatusEvent(
            type=EventType.INFO,
            source="test_source",
            message="Test message",
            phase="execution",
        )

        # Act
        event_str = str(event)

        # Assert
        assert event_str == "[execution] test_source: Test message"
        assert "[execution]" in event_str

    def test_event_type_values(self) -> None:
        """Test EventType enum values."""
        assert EventType.INFO == "info"
        assert EventType.TRACE == "trace"


class TestEventEmitter:
    """Tests for EventEmitter functionality."""

    def test_event_emitter_creation(self) -> None:
        """Test creating an event emitter."""
        # Act
        emitter = EventEmitter()

        # Assert
        assert emitter.handlers == []
        assert emitter.parent is None

    def test_event_emitter_with_parent(self) -> None:
        """Test creating an emitter with a parent."""
        # Arrange
        parent = EventEmitter()

        # Act
        child = EventEmitter(parent=parent)

        # Assert
        assert child.parent is parent

    def test_register_event_handler(self) -> None:
        """Test registering an event handler."""
        # Arrange
        emitter = EventEmitter()
        handler = Mock()

        # Act
        emitter.on(handler)

        # Assert
        assert len(emitter.handlers) == 1
        assert handler in emitter.handlers

    def test_register_multiple_handlers(self) -> None:
        """Test registering multiple event handlers."""
        # Arrange
        emitter = EventEmitter()
        handler1 = Mock()
        handler2 = Mock()
        handler3 = Mock()

        # Act
        emitter.on(handler1)
        emitter.on(handler2)
        emitter.on(handler3)

        # Assert
        assert len(emitter.handlers) == 3
        assert all(h in emitter.handlers for h in [handler1, handler2, handler3])

    def test_emit_event_calls_handler(self) -> None:
        """Test that emitting an event calls registered handlers."""
        # Arrange
        emitter = EventEmitter()
        handler = Mock()
        emitter.on(handler)

        event = StatusEvent(type=EventType.INFO, source="test", message="Test message")

        # Act
        emitter.emit(event)

        # Assert
        handler.assert_called_once_with(event)

    def test_emit_event_calls_all_handlers(self) -> None:
        """Test that emitting calls all registered handlers."""
        # Arrange
        emitter = EventEmitter()
        handler1 = Mock()
        handler2 = Mock()
        handler3 = Mock()

        emitter.on(handler1)
        emitter.on(handler2)
        emitter.on(handler3)

        event = StatusEvent(type=EventType.INFO, source="test", message="Test message")

        # Act
        emitter.emit(event)

        # Assert
        handler1.assert_called_once_with(event)
        handler2.assert_called_once_with(event)
        handler3.assert_called_once_with(event)

    def test_emit_event_bubbles_to_parent(self) -> None:
        """Test that events bubble to parent emitter."""
        # Arrange
        parent_handler = Mock()
        child_handler = Mock()

        parent = EventEmitter()
        parent.on(parent_handler)

        child = EventEmitter(parent=parent)
        child.on(child_handler)

        event = StatusEvent(type=EventType.INFO, source="child", message="Child event")

        # Act
        child.emit(event)

        # Assert
        # Both child and parent handlers should be called
        child_handler.assert_called_once_with(event)
        parent_handler.assert_called_once_with(event)

    def test_emit_event_handler_exception_caught(self) -> None:
        """Test that handler exceptions are caught and don't stop other handlers."""
        # Arrange
        emitter = EventEmitter()
        failing_handler = Mock(side_effect=Exception("Handler error"))
        working_handler = Mock()

        emitter.on(failing_handler)
        emitter.on(working_handler)

        event = StatusEvent(type=EventType.INFO, source="test", message="Test message")

        # Act - should not raise
        emitter.emit(event)

        # Assert
        # Both handlers should have been called
        failing_handler.assert_called_once_with(event)
        working_handler.assert_called_once_with(event)

    def test_emit_without_handlers(self) -> None:
        """Test emitting an event with no handlers registered."""
        # Arrange
        emitter = EventEmitter()
        event = StatusEvent(type=EventType.INFO, source="test", message="Test message")

        # Act & Assert - should not raise
        emitter.emit(event)

    def test_multi_level_event_bubbling(self) -> None:
        """Test event bubbling through multiple levels."""
        # Arrange
        grandparent_handler = Mock()
        parent_handler = Mock()
        child_handler = Mock()

        grandparent = EventEmitter()
        grandparent.on(grandparent_handler)

        parent = EventEmitter(parent=grandparent)
        parent.on(parent_handler)

        child = EventEmitter(parent=parent)
        child.on(child_handler)

        event = StatusEvent(
            type=EventType.TRACE, source="child_task", message="Deep event"
        )

        # Act
        child.emit(event)

        # Assert
        # All three levels should receive the event
        child_handler.assert_called_once_with(event)
        parent_handler.assert_called_once_with(event)
        grandparent_handler.assert_called_once_with(event)


class TestEventIntegration:
    """Integration tests for event system."""

    def test_task_to_orchestrator_event_flow(self) -> None:
        """Test event flow from task to orchestrator."""
        # Arrange
        orchestrator_events = []

        def orchestrator_handler(event: StatusEvent) -> None:
            orchestrator_events.append(event)

        orchestrator = EventEmitter()
        orchestrator.on(orchestrator_handler)

        task_emitter = EventEmitter(parent=orchestrator)

        # Act
        task_emitter.emit(
            StatusEvent(
                type=EventType.INFO,
                source="task:discover_tables",
                message="Found 5 tables",
                data={"count": 5},
                phase="discovery",
            )
        )

        task_emitter.emit(
            StatusEvent(
                type=EventType.TRACE,
                source="task:analyze_schema",
                message="Analyzing schema",
                phase="analysis",
            )
        )

        # Assert
        assert len(orchestrator_events) == 2
        assert orchestrator_events[0].source == "task:discover_tables"
        assert orchestrator_events[1].source == "task:analyze_schema"

    def test_filtering_events_by_type(self) -> None:
        """Test filtering events by type in handler."""
        # Arrange
        info_events = []
        trace_events = []

        def info_handler(event: StatusEvent) -> None:
            if event.type == EventType.INFO:
                info_events.append(event)

        def trace_handler(event: StatusEvent) -> None:
            if event.type == EventType.TRACE:
                trace_events.append(event)

        emitter = EventEmitter()
        emitter.on(info_handler)
        emitter.on(trace_handler)

        # Act
        emitter.emit(
            StatusEvent(type=EventType.INFO, source="test", message="Info message")
        )
        emitter.emit(
            StatusEvent(type=EventType.TRACE, source="test", message="Trace message")
        )
        emitter.emit(
            StatusEvent(
                type=EventType.INFO, source="test", message="Another info message"
            )
        )

        # Assert
        assert len(info_events) == 2
        assert len(trace_events) == 1

    def test_event_data_preservation(self) -> None:
        """Test that event data is preserved through emission."""
        # Arrange
        received_events = []

        def handler(event: StatusEvent) -> None:
            received_events.append(event)

        emitter = EventEmitter()
        emitter.on(handler)

        test_data = {
            "tables": ["table1", "table2"],
            "metadata": {"count": 2, "schema": "public"},
        }

        # Act
        emitter.emit(
            StatusEvent(
                type=EventType.INFO,
                source="discovery",
                message="Tables discovered",
                data=test_data,
            )
        )

        # Assert
        assert len(received_events) == 1
        event = received_events[0]
        assert event.data == test_data
        assert event.data["tables"] == ["table1", "table2"]
        assert event.data["metadata"]["count"] == 2
