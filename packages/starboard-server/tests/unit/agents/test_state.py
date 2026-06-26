# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for agent state management."""

from dataclasses import FrozenInstanceError, replace

import pytest
from starboard_server.agents.state.agent_state import (
    AgentOutput,
    AgentState,
    Message,
    WorkingMemory,
)


class TestMessage:
    """Tests for Message dataclass."""

    def test_create_system_message(self):
        """Test creating a system message."""
        msg = Message(role="system", content="You are an expert")

        assert msg.role == "system"
        assert msg.content == "You are an expert"
        assert msg.name is None
        assert msg.tool_call_id is None
        assert msg.metadata == {}

    def test_create_user_message(self):
        """Test creating a user message."""
        msg = Message(role="user", content="Optimize query abc123")

        assert msg.role == "user"
        assert msg.content == "Optimize query abc123"

    def test_create_assistant_message(self):
        """Test creating an assistant message."""
        msg = Message(role="assistant", content="I'll analyze the query")

        assert msg.role == "assistant"
        assert msg.content == "I'll analyze the query"

    def test_create_tool_message(self):
        """Test creating a tool message."""
        msg = Message(
            role="tool",
            name="resolve_query",
            content="Query resolved: SELECT * FROM users",
            tool_call_id="call_123",
            metadata={"execution_time_ms": 45},
        )

        assert msg.role == "tool"
        assert msg.name == "resolve_query"
        assert msg.tool_call_id == "call_123"
        assert msg.metadata["execution_time_ms"] == 45

    def test_invalid_role(self):
        """Test that invalid role raises error."""
        with pytest.raises(ValueError, match="Invalid role"):
            Message(role="invalid", content="test")  # type: ignore

    def test_message_immutability(self):
        """Test that messages are immutable."""
        msg = Message(role="user", content="test")

        with pytest.raises(FrozenInstanceError):
            msg.content = "modified"  # type: ignore

    def test_message_with_metadata(self):
        """Test message with custom metadata."""
        msg = Message(
            role="assistant",
            content="Response",
            metadata={"timestamp": "2025-11-13", "tokens": 100},
        )

        assert msg.metadata["timestamp"] == "2025-11-13"
        assert msg.metadata["tokens"] == 100


class TestWorkingMemory:
    """Tests for WorkingMemory dataclass."""

    def test_create_empty_memory(self):
        """Test creating empty working memory."""
        memory = WorkingMemory()

        assert memory.summaries == {}
        assert memory.facts == ()
        assert memory.tools_used == ()
        assert memory.metrics == {}

    def test_create_memory_with_data(self):
        """Test creating memory with initial data."""
        memory = WorkingMemory(
            summaries={"tool1": "result1"},
            facts=("fact1", "fact2"),
            tools_used=("tool1", "tool2"),
            metrics={"metric1": 100},
        )

        assert memory.summaries["tool1"] == "result1"
        assert len(memory.facts) == 2
        assert "fact1" in memory.facts
        assert len(memory.tools_used) == 2
        assert memory.metrics["metric1"] == 100

    def test_add_summary(self):
        """Test adding a tool summary."""
        memory = WorkingMemory()
        new_memory = memory.add_summary("resolve_query", "Query resolved")

        # Original unchanged
        assert "resolve_query" not in memory.summaries

        # New memory has summary
        assert new_memory.summaries["resolve_query"] == "Query resolved"

    def test_add_fact(self):
        """Test adding a fact."""
        memory = WorkingMemory(facts=("fact1",))
        new_memory = memory.add_fact("fact2")

        # Original unchanged
        assert len(memory.facts) == 1

        # New memory has both facts
        assert len(new_memory.facts) == 2
        assert "fact2" in new_memory.facts

    def test_add_tool_used(self):
        """Test recording tool usage."""
        memory = WorkingMemory()
        new_memory = memory.add_tool_used("resolve_query")

        # Original unchanged
        assert len(memory.tools_used) == 0

        # New memory has tool
        assert len(new_memory.tools_used) == 1
        assert "resolve_query" in new_memory.tools_used

    def test_update_metrics(self):
        """Test updating metrics."""
        memory = WorkingMemory(metrics={"metric1": 100})
        new_memory = memory.update_metrics({"metric2": 200, "metric3": 300})

        # Original unchanged
        assert "metric2" not in memory.metrics

        # New memory has all metrics
        assert new_memory.metrics["metric1"] == 100
        assert new_memory.metrics["metric2"] == 200
        assert new_memory.metrics["metric3"] == 300

    def test_memory_immutability(self):
        """Test that memory attributes are immutable."""
        memory = WorkingMemory()

        # Frozen dataclass prevents attribute reassignment
        with pytest.raises(FrozenInstanceError):
            memory.summaries = {}  # type: ignore

        # Note: frozen=True doesn't prevent mutation of mutable values,
        # which is why we use immutable update methods (add_summary, etc.)

    def test_chained_updates(self):
        """Test chaining multiple memory updates."""
        memory = WorkingMemory()

        new_memory = (
            memory.add_summary("tool1", "result1")
            .add_fact("fact1")
            .add_tool_used("tool1")
            .update_metrics({"metric1": 100})
        )

        assert "tool1" in new_memory.summaries
        assert "fact1" in new_memory.facts
        assert "tool1" in new_memory.tools_used
        assert new_memory.metrics["metric1"] == 100


class TestAgentState:
    """Tests for AgentState dataclass."""

    def test_create_initial_state(self):
        """Test creating initial agent state."""
        msg = Message(role="user", content="test")
        memory = WorkingMemory()

        state = AgentState(
            user_id="test_user",
            conversation_history=(msg,),
            working_memory=memory,
            current_step=0,
            goal="Optimize query",
            mode="online",
            context={"warehouse_id": "abc"},
            budget_remaining=100_000,
        )

        assert len(state.conversation_history) == 1
        assert state.current_step == 0
        assert state.goal == "Optimize query"
        assert state.budget_remaining == 100_000
        assert state.completed is False
        assert state.final_output is None
        assert state.error is None

    def test_add_message(self):
        """Test adding a message to state."""
        state = AgentState(
            user_id="test_user",
            conversation_history=(Message(role="user", content="test"),),
            working_memory=WorkingMemory(),
            current_step=0,
            goal="test",
            mode="online",
            context={},
            budget_remaining=100_000,
        )

        new_state = state.add_message(Message(role="assistant", content="response"))

        # Original unchanged
        assert len(state.conversation_history) == 1

        # New state has both messages
        assert len(new_state.conversation_history) == 2
        assert new_state.conversation_history[1].role == "assistant"

    def test_increment_step(self):
        """Test incrementing step counter."""
        state = AgentState(
            user_id="test_user",
            conversation_history=(),
            working_memory=WorkingMemory(),
            current_step=0,
            goal="test",
            mode="online",
            context={},
            budget_remaining=100_000,
        )

        new_state = state.increment_step()

        assert state.current_step == 0
        assert new_state.current_step == 1

    def test_consume_budget(self):
        """Test consuming tokens from budget."""
        state = AgentState(
            user_id="test_user",
            conversation_history=(),
            working_memory=WorkingMemory(),
            current_step=0,
            goal="test",
            mode="online",
            context={},
            budget_remaining=100_000,
        )

        new_state = state.consume_budget(5000)

        assert state.budget_remaining == 100_000
        assert new_state.budget_remaining == 95_000

    def test_consume_budget_insufficient(self):
        """Test consuming more budget than available raises error."""
        state = AgentState(
            user_id="test_user",
            conversation_history=(),
            working_memory=WorkingMemory(),
            current_step=0,
            goal="test",
            mode="online",
            context={},
            budget_remaining=1000,
        )

        # Should raise ValueError when enforce=True
        with pytest.raises(ValueError, match="Insufficient budget"):
            state.consume_budget(5000, enforce=True)

    def test_mark_completed(self):
        """Test marking state as completed."""
        state = AgentState(
            user_id="test_user",
            conversation_history=(),
            working_memory=WorkingMemory(),
            current_step=5,
            goal="test",
            mode="online",
            context={},
            budget_remaining=50_000,
        )

        output = {"recommendations": [{"title": "test"}]}
        new_state = state.mark_completed(output)

        assert state.completed is False
        assert new_state.completed is True
        assert new_state.final_output == output

    def test_mark_error(self):
        """Test marking state with error."""
        state = AgentState(
            user_id="test_user",
            conversation_history=(),
            working_memory=WorkingMemory(),
            current_step=3,
            goal="test",
            mode="online",
            context={},
            budget_remaining=50_000,
        )

        new_state = state.mark_error("Something went wrong")

        assert state.error is None
        assert new_state.error == "Something went wrong"
        assert new_state.completed is True

    def test_invalid_current_step(self):
        """Test that negative step raises error."""
        with pytest.raises(ValueError, match="current_step must be >= 0"):
            AgentState(
                user_id="test_user",
                conversation_history=(),
                working_memory=WorkingMemory(),
                current_step=-1,
                goal="test",
                mode="online",
                context={},
                budget_remaining=100_000,
            )

    def test_invalid_budget(self):
        """Test that negative budget is allowed (for tracking without enforcement)."""
        # Negative budget is allowed per design (see state.py:415 comment)
        # It tracks usage even when budget isn't enforced
        state = AgentState(
            user_id="test_user",
            conversation_history=(),
            working_memory=WorkingMemory(),
            current_step=0,
            goal="test",
            mode="online",
            context={},
            budget_remaining=-1000,
        )
        assert state.budget_remaining == -1000

    def test_state_immutability(self):
        """Test that state is immutable."""
        state = AgentState(
            user_id="test_user",
            conversation_history=(),
            working_memory=WorkingMemory(),
            current_step=0,
            goal="test",
            mode="online",
            context={},
            budget_remaining=100_000,
        )

        with pytest.raises(FrozenInstanceError):
            state.current_step = 5  # type: ignore


class TestAgentOutput:
    """Tests for AgentOutput dataclass."""

    def test_create_success_output(self):
        """Test creating successful output."""
        output = AgentOutput(
            status="success",
            recommendations=[{"title": "Add index", "priority": "high"}],
            reasoning_trace=[{"step": 1, "action": "resolve_query"}],
            steps_taken=5,
            tools_used=["resolve_query", "analyze_plan"],
            tokens_used=12_000,
            cost_usd=0.0018,
            duration_seconds=45.3,
        )

        assert output.status == "success"
        assert len(output.recommendations) == 1
        assert len(output.reasoning_trace) == 1
        assert output.steps_taken == 5
        assert len(output.tools_used) == 2
        assert output.error_message is None

    def test_create_error_output(self):
        """Test creating error output."""
        output = AgentOutput(
            status="error",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=3,
            tools_used=["resolve_query"],
            tokens_used=5000,
            cost_usd=0.0008,
            duration_seconds=15.2,
            error_message="Tool execution failed",
        )

        assert output.status == "error"
        assert output.error_message == "Tool execution failed"

    def test_to_dict(self):
        """Test converting output to dictionary."""
        output = AgentOutput(
            status="success",
            recommendations=[{"title": "test"}],
            reasoning_trace=[],
            steps_taken=5,
            tools_used=["tool1"],
            tokens_used=10_000,
            cost_usd=0.0015,
            duration_seconds=30.0,
        )

        output_dict = output.to_dict()

        assert isinstance(output_dict, dict)
        assert output_dict["status"] == "success"
        assert output_dict["steps_taken"] == 5
        assert output_dict["tokens_used"] == 10_000

    def test_invalid_steps_taken(self):
        """Test that negative steps_taken raises error."""
        with pytest.raises(ValueError, match="steps_taken must be >= 0"):
            AgentOutput(
                status="success",
                recommendations=[],
                reasoning_trace=[],
                steps_taken=-1,
                tools_used=[],
                tokens_used=0,
                cost_usd=0.0,
                duration_seconds=0.0,
            )

    def test_invalid_tokens_used(self):
        """Test that negative tokens_used raises error."""
        with pytest.raises(ValueError, match="tokens_used must be >= 0"):
            AgentOutput(
                status="success",
                recommendations=[],
                reasoning_trace=[],
                steps_taken=0,
                tools_used=[],
                tokens_used=-1000,
                cost_usd=0.0,
                duration_seconds=0.0,
            )

    def test_output_immutability(self):
        """Test that output is immutable."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=5,
            tools_used=[],
            tokens_used=10_000,
            cost_usd=0.0015,
            duration_seconds=30.0,
        )

        with pytest.raises(FrozenInstanceError):
            output.status = "error"  # type: ignore


class TestStateIntegration:
    """Integration tests for state management."""

    def test_full_state_workflow(self):
        """Test complete state workflow."""
        # Initialize
        initial_state = AgentState(
            user_id="test_user",
            conversation_history=(
                Message(role="system", content="System prompt"),
                Message(role="user", content="Optimize query abc123"),
            ),
            working_memory=WorkingMemory(),
            current_step=0,
            goal="Optimize query abc123",
            mode="online",
            context={"warehouse_id": "w1"},
            budget_remaining=100_000,
        )

        # Step 1: Add tool result
        state = initial_state
        state = state.add_message(
            Message(role="tool", name="resolve_query", content="Query resolved")
        )
        state = state.increment_step()
        state = state.consume_budget(5000)

        # Update memory
        new_memory = (
            state.working_memory.add_summary("resolve_query", "Query identified")
            .add_fact("Query has 3 tables")
            .add_tool_used("resolve_query")
        )
        state = replace(state, working_memory=new_memory)

        # Step 2: Complete
        final_output = {
            "recommendations": [{"title": "Add index", "priority": "high"}],
        }
        state = state.mark_completed(final_output)

        # Verify final state
        assert state.completed is True
        assert state.current_step == 1
        assert state.budget_remaining == 95_000
        assert len(state.conversation_history) == 3
        assert "resolve_query" in state.working_memory.tools_used
        assert len(state.working_memory.facts) == 1
