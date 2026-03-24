"""
Event system for optimization workflows.

This module provides status event handling that allows messages to bubble up
from tasks through the orchestrator to the optimizer caller.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class EventType(str, Enum):
    """Event types for status messages."""

    INFO = "info"  # General information messages
    TRACE = "trace"  # Detailed execution trace messages


@dataclass
class StatusEvent:
    """
    Status event message.

    Represents a status message that bubbles up through the execution stack.

    Attributes:
        type: Event type (info or trace)
        source: Source component (e.g., "task:discover_tables", "orchestrator")
        message: Human-readable message
        data: Optional additional structured data
        phase: Optional workflow phase (e.g., "planner", "execution", "synthesis")
    """

    type: EventType
    source: str
    message: str
    data: dict[str, Any] | None = None
    phase: str | None = None

    def __str__(self) -> str:
        """Format event as string for logging."""
        phase_str = f"[{self.phase}] " if self.phase else ""
        return f"{phase_str}{self.source}: {self.message}"


EventHandler = Callable[[StatusEvent], None]


class EventEmitter:
    """
    Event emitter for status messages.

    Provides methods to emit events and manage event handlers.
    Events can be chained through parent emitters to create bubbling behavior.

    Attributes:
        handlers: List of event handler functions
        parent: Optional parent emitter for event bubbling
    """

    def __init__(self, parent: EventEmitter | None = None) -> None:
        """
        Initialize event emitter.

        Args:
            parent: Optional parent emitter for event bubbling
        """
        self.handlers: list[EventHandler] = []
        self.parent = parent

    def on(self, handler: EventHandler) -> None:
        """
        Register an event handler.

        Args:
            handler: Function that accepts StatusEvent
        """
        self.handlers.append(handler)

    def emit(self, event: StatusEvent) -> None:
        """
        Emit a status event.

        Calls all registered handlers and bubbles to parent if present.

        Args:
            event: Status event to emit
        """
        # Call local handlers
        for handler in self.handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error("event_handler_error", error=str(e), exc_info=True)

        # Bubble to parent
        if self.parent:
            self.parent.emit(event)

    def emit_info(
        self,
        source: str,
        message: str,
        data: dict[str, Any] | None = None,
        phase: str | None = None,
    ) -> None:
        """
        Emit an info event.

        Convenience method for emitting info-level events.

        Args:
            source: Event source identifier
            message: Human-readable message
            data: Optional additional structured data
            phase: Optional workflow phase
        """
        self.emit(
            StatusEvent(
                type=EventType.INFO,
                source=source,
                message=message,
                data=data,
                phase=phase,
            )
        )

    def emit_trace(
        self,
        source: str,
        message: str,
        data: dict[str, Any] | None = None,
        phase: str | None = None,
    ) -> None:
        """
        Emit a trace event.

        Convenience method for emitting trace-level events.

        Args:
            source: Event source identifier
            message: Human-readable message
            data: Optional additional structured data
            phase: Optional workflow phase
        """
        self.emit(
            StatusEvent(
                type=EventType.TRACE,
                source=source,
                message=message,
                data=data,
                phase=phase,
            )
        )
