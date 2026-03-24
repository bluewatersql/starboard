"""Unit tests for ConversationContextStrategy and ContextWindow."""

import pytest
from starboard_server.agents.state.agent_state import Message
from starboard_server.agents.state.context_strategy import (
    ContextWindow,
    ConversationContextStrategy,
)


def _make_history(turns: int) -> list[dict]:
    """Create conversation history with user/assistant message pairs."""
    history = []
    for i in range(turns):
        history.append({"role": "user", "content": f"User question {i+1}"})
        history.append({"role": "assistant", "content": f"Agent response {i+1}"})
    return history


# -----------------------------------------------------------------------------
# prepare_context tests
# -----------------------------------------------------------------------------


@pytest.mark.unit
def test_short_conversation_no_summarization() -> None:
    """2 turns: full history returned, was_summarized=False."""
    strategy = ConversationContextStrategy()
    history = _make_history(2)

    window = strategy.prepare_context(history)

    assert window.turn_count == 2
    assert window.was_summarized is False
    assert window.summary == ""
    assert len(window.recent_messages) == 4  # 2 turns = 4 messages
    assert window.recent_messages[0]["content"] == "User question 1"
    assert window.recent_messages[1]["content"] == "Agent response 1"
    assert window.recent_messages[2]["content"] == "User question 2"
    assert window.recent_messages[3]["content"] == "Agent response 2"


@pytest.mark.unit
def test_medium_conversation_with_summarization() -> None:
    """7 turns: should summarize earlier, keep recent 3."""
    strategy = ConversationContextStrategy()
    history = _make_history(7)

    window = strategy.prepare_context(history)

    assert window.turn_count == 7
    assert window.was_summarized is True
    assert len(window.summary) > 0
    # Recent 3 turns = 6 messages
    assert len(window.recent_messages) == 6
    assert window.recent_messages[0]["content"] == "User question 5"
    assert window.recent_messages[-1]["content"] == "Agent response 7"


@pytest.mark.unit
def test_long_conversation_compression() -> None:
    """12 turns with threshold=5, verify summary + recent window."""
    strategy = ConversationContextStrategy(full_history_threshold=5)
    history = _make_history(12)

    window = strategy.prepare_context(history)

    assert window.turn_count == 12
    assert window.was_summarized is True
    assert len(window.summary) > 0
    # Default recent_window_turns=3, so 6 messages
    assert len(window.recent_messages) == 6
    assert window.recent_messages[0]["content"] == "User question 10"
    assert window.recent_messages[-1]["content"] == "Agent response 12"


@pytest.mark.unit
def test_custom_thresholds() -> None:
    """Pass custom full_history_threshold=2, recent_window_turns=1."""
    strategy = ConversationContextStrategy(
        full_history_threshold=2,
        recent_window_turns=1,
    )
    history = _make_history(4)

    window = strategy.prepare_context(history)

    assert window.turn_count == 4
    assert window.was_summarized is True
    # recent_window_turns=1 -> only last turn (2 messages)
    assert len(window.recent_messages) == 2
    assert window.recent_messages[0]["content"] == "User question 4"
    assert window.recent_messages[1]["content"] == "Agent response 4"


@pytest.mark.unit
def test_prepare_context_with_working_memory() -> None:
    """Pass working_memory dict with discovered_entities and user_constraints."""
    strategy = ConversationContextStrategy()
    history = _make_history(2)
    working_memory = {
        "metrics": {
            "discovered_entities": {
                "tables": ["schema.users", "schema.orders"],
                "queries": ["q_abc123"],
            },
            "user_constraints": {
                "max_cost": "100",
                "focus": "partition pruning",
            },
        },
    }

    window = strategy.prepare_context(history, working_memory=working_memory)

    assert window.working_memory_snapshot["discovered_entities"] == {
        "tables": ["schema.users", "schema.orders"],
        "queries": ["q_abc123"],
    }
    assert window.working_memory_snapshot["user_constraints"] == {
        "max_cost": "100",
        "focus": "partition pruning",
    }


@pytest.mark.unit
def test_prepare_context_with_existing_summary() -> None:
    """Pre-existing summary used instead of re-generating."""
    strategy = ConversationContextStrategy()
    history = _make_history(7)
    existing_summary = "Prior discussion about query optimization."

    window = strategy.prepare_context(
        history,
        existing_summary=existing_summary,
    )

    assert window.was_summarized is True
    assert window.summary == existing_summary


# -----------------------------------------------------------------------------
# build_enriched_input tests
# -----------------------------------------------------------------------------


@pytest.mark.unit
def test_build_enriched_input_empty_context() -> None:
    """No summarization needed, returns original input."""
    strategy = ConversationContextStrategy()
    context = ContextWindow(
        summary="",
        recent_messages=[],
        working_memory_snapshot={},
        turn_count=2,
        was_summarized=False,
    )

    result = strategy.build_enriched_input("What is the status?", context)

    assert result == "What is the status?"


@pytest.mark.unit
def test_build_enriched_input_with_summary() -> None:
    """Summary added as [Prior Conversation Summary]."""
    strategy = ConversationContextStrategy()
    context = ContextWindow(
        summary="Earlier we discussed query abc123 and partition pruning.",
        recent_messages=[],
        working_memory_snapshot={},
        turn_count=7,
        was_summarized=True,
    )

    result = strategy.build_enriched_input("Continue the analysis.", context)

    assert "[Prior Conversation Summary]" in result
    assert "Earlier we discussed query abc123 and partition pruning." in result
    assert "Continue the analysis." in result


@pytest.mark.unit
def test_build_enriched_input_with_entities() -> None:
    """Discovered entities section added."""
    strategy = ConversationContextStrategy()
    context = ContextWindow(
        summary="",
        recent_messages=[],
        working_memory_snapshot={
            "discovered_entities": {
                "tables": ["schema.users"],
                "queries": ["q_xyz"],
            },
        },
        turn_count=2,
        was_summarized=False,
    )

    result = strategy.build_enriched_input("Optimize further.", context)

    assert "[Discovered Entities]" in result
    assert "tables: schema.users" in result
    assert "queries: q_xyz" in result


@pytest.mark.unit
def test_build_enriched_input_with_constraints() -> None:
    """User constraints section added."""
    strategy = ConversationContextStrategy()
    context = ContextWindow(
        summary="",
        recent_messages=[],
        working_memory_snapshot={
            "user_constraints": {
                "max_cost": "50",
                "priority": "latency",
            },
        },
        turn_count=2,
        was_summarized=False,
    )

    result = strategy.build_enriched_input("Proceed.", context)

    assert "[Active Constraints]" in result
    assert "max_cost: 50" in result
    assert "priority: latency" in result


# -----------------------------------------------------------------------------
# Message format support
# -----------------------------------------------------------------------------


@pytest.mark.unit
def test_dict_messages_supported() -> None:
    """History as list of dicts works."""
    strategy = ConversationContextStrategy()
    history = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Second question"},
        {"role": "assistant", "content": "Second answer"},
    ]

    window = strategy.prepare_context(history)

    assert window.turn_count == 2
    assert window.was_summarized is False
    assert len(window.recent_messages) == 4
    assert window.recent_messages[0]["role"] == "user"
    assert window.recent_messages[0]["content"] == "First question"


@pytest.mark.unit
def test_message_objects_supported() -> None:
    """History as Message objects works."""
    strategy = ConversationContextStrategy()
    history = [
        Message(role="user", content="User msg 1"),
        Message(role="assistant", content="Agent msg 1"),
        Message(role="user", content="User msg 2"),
        Message(role="assistant", content="Agent msg 2"),
    ]

    window = strategy.prepare_context(history)

    assert window.turn_count == 2
    assert window.was_summarized is False
    assert len(window.recent_messages) == 4
    assert window.recent_messages[0]["role"] == "user"
    assert window.recent_messages[0]["content"] == "User msg 1"
