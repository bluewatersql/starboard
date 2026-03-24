"""Tests for turn context."""

from starboard_server.api.turn_context import TurnContext, create_turn_context


def test_turn_context_creation():
    """Should create turn context with required fields."""
    context = TurnContext(conversation_id="conv-1", user_id="user-1")

    assert context.conversation_id == "conv-1"
    assert context.user_id == "user-1"
    assert context.turn_id is not None
    assert context.trace_id is not None
    assert context.step_count == 0
    assert context.tokens_used == 0
    assert context.tools_called == 0


def test_turn_context_factory():
    """Should create turn context via factory function."""
    context = create_turn_context("conv-1", "user-1")

    assert context.conversation_id == "conv-1"
    assert context.user_id == "user-1"


def test_turn_context_scratchpad():
    """Should store and retrieve scratchpad values."""
    context = TurnContext(conversation_id="conv-1", user_id="user-1")

    context.set_scratch("query", "SELECT * FROM users")
    assert context.get_scratch("query") == "SELECT * FROM users"

    # Non-existent key
    assert context.get_scratch("nonexistent") is None
    assert context.get_scratch("nonexistent", "default") == "default"


def test_turn_context_tool_results():
    """Should record and retrieve tool results."""
    context = TurnContext(conversation_id="conv-1", user_id="user-1")

    result = {"rows": 10, "data": []}
    context.record_tool_result("tool-abc", result)

    assert context.get_tool_result("tool-abc") == result
    assert context.tools_called == 1

    # Record another tool
    context.record_tool_result("tool-def", {"status": "ok"})
    assert context.tools_called == 2


def test_turn_context_increment_step():
    """Should increment step counter."""
    context = TurnContext(conversation_id="conv-1", user_id="user-1")

    context.increment_step()
    assert context.step_count == 1

    context.increment_step()
    assert context.step_count == 2


def test_turn_context_add_tokens():
    """Should track token usage."""
    context = TurnContext(conversation_id="conv-1", user_id="user-1")

    context.add_tokens(100)
    assert context.tokens_used == 100

    context.add_tokens(50)
    assert context.tokens_used == 150


def test_turn_context_to_dict():
    """Should serialize to dict for logging."""
    context = TurnContext(conversation_id="conv-1", user_id="user-1")
    context.increment_step()
    context.add_tokens(100)
    context.record_tool_result("tool-1", {})

    result = context.to_dict()

    assert result["turn_id"] == context.turn_id
    assert result["trace_id"] == context.trace_id
    assert result["conversation_id"] == "conv-1"
    assert result["user_id"] == "user-1"
    assert result["step_count"] == 1
    assert result["tokens_used"] == 100
    assert result["tools_called"] == 1
    assert "scratchpad" not in result  # Should not include sensitive data
    assert "tool_results" not in result  # Should not include large data


def test_turn_context_unique_ids():
    """Should generate unique IDs for each context."""
    context1 = create_turn_context("conv-1", "user-1")
    context2 = create_turn_context("conv-1", "user-1")

    assert context1.turn_id != context2.turn_id
    assert context1.trace_id != context2.trace_id
