"""Turn-local state management."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class TurnContext:
    """
    Ephemeral state for a single agent turn.

    This context is created at request start and discarded at request end.
    It should NEVER be persisted to any store.

    Lifecycle:
        1. Created at request start (per API call)
        2. Passed through agent execution
        3. Used for scratchpad and tool results
        4. Discarded at request end

    Important:
        - Turn-local only (not session/conversation state)
        - In-memory only (never persisted)
        - Request-scoped (one per API call)
        - Thread-local (not shared across requests)
    """

    # Identity
    conversation_id: str
    user_id: str
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Scratchpad (working memory for this turn)
    scratchpad: dict[str, Any] = field(default_factory=dict)

    # Tool results (keyed by tool call ID)
    tool_results: dict[str, Any] = field(default_factory=dict)

    # Metadata
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    step_count: int = 0
    tokens_used: int = 0
    tools_called: int = 0

    def set_scratch(self, key: str, value: Any) -> None:
        """
        Store value in scratchpad.

        Args:
            key: Scratchpad key
            value: Value to store
        """
        self.scratchpad[key] = value

    def get_scratch(self, key: str, default: Any = None) -> Any:
        """
        Retrieve value from scratchpad.

        Args:
            key: Scratchpad key
            default: Default value if key not found

        Returns:
            Scratchpad value or default
        """
        return self.scratchpad.get(key, default)

    def record_tool_result(self, tool_call_id: str, result: Any) -> None:
        """
        Record tool execution result.

        Args:
            tool_call_id: Unique tool call identifier
            result: Tool execution result
        """
        self.tool_results[tool_call_id] = result
        self.tools_called += 1

    def get_tool_result(self, tool_call_id: str) -> Any | None:
        """
        Retrieve tool result by ID.

        Args:
            tool_call_id: Tool call identifier

        Returns:
            Tool result if found, None otherwise
        """
        return self.tool_results.get(tool_call_id)

    def increment_step(self) -> None:
        """Increment step counter."""
        self.step_count += 1

    def add_tokens(self, tokens: int) -> None:
        """
        Add token usage to counter.

        Args:
            tokens: Number of tokens used in this operation
        """
        self.tokens_used += tokens

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dict for logging/observability.

        Note:
            Does NOT serialize scratchpad or tool_results
            (they may be large or contain sensitive data).

        Returns:
            Dictionary with turn metadata
        """
        return {
            "turn_id": self.turn_id,
            "trace_id": self.trace_id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "started_at": self.started_at.isoformat(),
            "step_count": self.step_count,
            "tokens_used": self.tokens_used,
            "tools_called": self.tools_called,
        }


def create_turn_context(conversation_id: str, user_id: str) -> TurnContext:
    """
    Factory function for creating turn context.

    Args:
        conversation_id: Conversation identifier
        user_id: User identifier

    Returns:
        New TurnContext instance

    Example:
        context = create_turn_context("conv-123", "user-456")
        context.set_scratch("query", "SELECT * FROM users")
        context.record_tool_result("tool-abc", {"rows": 10})
    """
    return TurnContext(
        conversation_id=conversation_id,
        user_id=user_id,
    )
