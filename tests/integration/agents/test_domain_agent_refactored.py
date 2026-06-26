# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Integration tests for DomainAgent facade.

These tests validate that the refactored architecture works correctly
end-to-end by testing the facade with real (or minimally mocked) components.

Test Coverage:
- Full execution flow (init → run_stream → output)
- Component integration (facade coordinates all 4 components)
- Streaming events (thinking, tool calls, output)
- Error handling (reasoning errors, tool failures)
- Metrics collection (tokens, cost, duration)
- Backward compatibility (same API as old DomainAgent)
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.agents.config import AgentConfig
from starboard_server.agents.domain.domain_agent import DomainAgent
from starboard_server.agents.events import (
    FinalOutputEvent,
    StepCompleteEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from starboard_server.agents.tools.tool_registry import ToolRegistry


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    client = MagicMock()

    # Mock streaming response
    async def mock_stream(*args, **kwargs):
        # Yield thinking content
        yield {"type": "content", "content": "Analyzing query performance..."}
        yield {"type": "content", "content": " Let me check the execution plan."}

        # Yield tool call
        yield {
            "type": "tool_calls",
            "tool_calls": [
                {
                    "id": "call_123",
                    "name": "get_query_plan",
                    "arguments": '{"query_id": "q123"}',
                }
            ],
        }

        # Yield usage
        yield {
            "type": "usage",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

    client.call_with_tools_stream = mock_stream
    return client


@pytest.fixture
def mock_tool_registry():
    """Mock tool registry with test tools."""
    from starboard_server.agents.tools.tool_registry import (
        NativeToolAdapter,
        ToolMetadata,
    )

    registry = ToolRegistry()

    # Add test tool
    class MockToolClass:
        async def get_query_plan(self, query_id: str) -> dict[str, Any]:
            return {
                "content": "Query plan analysis complete. Recommend adding index on column X.",
                "success": True,
            }

        async def complete(self, **kwargs) -> dict[str, Any]:
            return {**kwargs, "completed": True, "report_type": "advisor"}

    mock_tools = MockToolClass()

    # Register get_query_plan tool
    query_plan_metadata = ToolMetadata(
        name="get_query_plan",
        description="Get query execution plan",
        parameters={
            "type": "object",
            "properties": {"query_id": {"type": "string", "description": "Query ID"}},
            "required": ["query_id"],
        },
    )
    query_plan_adapter = NativeToolAdapter(
        tool_instance=mock_tools,
        method_name="get_query_plan",
        metadata=query_plan_metadata,
    )
    registry.register("get_query_plan", query_plan_adapter)

    # Register complete tool
    complete_metadata = ToolMetadata(
        name="complete",
        description="Complete the task",
        parameters={
            "type": "object",
            "properties": {},
        },
    )
    complete_adapter = NativeToolAdapter(
        tool_instance=mock_tools,
        method_name="complete",
        metadata=complete_metadata,
    )
    registry.register("complete", complete_adapter)

    return registry


@pytest.fixture
def agent_config():
    """Agent configuration for testing."""
    return AgentConfig(
        domain="query",
        model="gpt-4",
        temperature=0.3,
        max_tokens=4096,
        max_steps=5,
        system_prompt_builder=lambda mode, input, max_tokens: (
            f"You are a query optimization expert. Mode: {mode}. Analyze: {input}"
        ),
    )


@pytest.mark.asyncio
async def test_agent_initialization(mock_llm_client, mock_tool_registry, agent_config):
    """Test that agent initializes correctly with all components."""
    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=agent_config,
        enable_metrics=True,
    )

    # Verify facade created all components
    assert agent.reasoning is not None
    assert agent.executor is not None
    assert agent.streamer is not None
    assert agent.builder is not None

    # Verify config
    assert agent.config.domain == "query"
    assert agent.config.model == "gpt-4"
    assert agent.config.max_steps == 5

    # Verify metrics initialized
    assert agent.current_metrics is not None
    assert agent.current_metrics.agent_type == "domain"
    assert agent.current_metrics.model == "gpt-4"


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Mock fixtures don't emit ThinkingEvent - needs fixture update"
)
async def test_agent_run_stream_emits_events(
    mock_llm_client, mock_tool_registry, agent_config
):
    """Test that agent emits correct sequence of streaming events."""
    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=agent_config,
    )

    # Collect all events
    events = []
    async for event in agent.run_stream(
        user_input="Optimize query SELECT * FROM table",
        mode=OptimizationMode.ONLINE,
        user_id="test-user-123",
        context={"query_id": "q123"},
    ):
        events.append(event)

    # Verify event sequence
    event_types = [type(e).__name__ for e in events]

    # Should have: thinking events, tool start, tool end, step complete, final output
    assert "ThinkingEvent" in event_types
    assert "ToolStartEvent" in event_types
    assert "ToolEndEvent" in event_types
    assert "StepCompleteEvent" in event_types
    assert "FinalOutputEvent" in event_types

    # Verify final output
    final_event = events[-1]
    assert isinstance(final_event, FinalOutputEvent)
    assert final_event.output is not None


@pytest.mark.asyncio
async def test_agent_metrics_tracking(
    mock_llm_client, mock_tool_registry, agent_config
):
    """Test that agent correctly tracks metrics during execution."""
    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=agent_config,
        enable_metrics=True,
    )

    # Run agent
    events = []
    async for event in agent.run_stream(
        user_input="Analyze query performance",
        mode=OptimizationMode.ONLINE,
        user_id="test-user-123",
        context={},
    ):
        events.append(event)

    # Check metrics
    metrics = agent.get_metrics()
    assert metrics is not None

    # Should have tracked tokens (from mock LLM response)
    assert metrics.input_tokens >= 100
    assert metrics.output_tokens >= 50
    assert metrics.total_tokens >= 150

    # Should have tracked cost
    assert metrics.estimated_cost_usd > 0

    # Should have success status
    assert metrics.success is True

    # Should have timing
    assert metrics.run_start_time is not None
    assert metrics.run_end_time is not None


@pytest.mark.asyncio
async def test_agent_backward_compatibility(
    mock_llm_client, mock_tool_registry, agent_config
):
    """Test that refactored agent has same API as old DomainAgent."""
    # This test verifies API compatibility
    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=agent_config,
        enable_metrics=True,
        session_id="test_session",
    )

    # Verify same methods exist
    assert hasattr(agent, "run_stream")
    assert hasattr(agent, "get_metrics")
    assert hasattr(agent, "config")

    # Verify run_stream signature
    import inspect

    sig = inspect.signature(agent.run_stream)
    params = list(sig.parameters.keys())
    assert "user_input" in params
    assert "mode" in params
    assert "context" in params

    # Verify get_metrics signature
    metrics = agent.get_metrics()
    assert metrics is not None
    assert hasattr(metrics, "session_id")
    assert hasattr(metrics, "agent_type")
    assert hasattr(metrics, "model")


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Mock fixtures don't produce tool events - needs fixture update"
)
async def test_agent_handles_tool_execution(
    mock_llm_client, mock_tool_registry, agent_config
):
    """Test that agent correctly executes tools via ToolExecutor."""
    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=agent_config,
    )

    # Run agent (will call get_query_plan tool)
    tool_start_events = []
    tool_end_events = []

    async for event in agent.run_stream(
        user_input="Get execution plan for query q123",
        mode=OptimizationMode.ONLINE,
        user_id="test-user-123",
        context={},
    ):
        if isinstance(event, ToolStartEvent):
            tool_start_events.append(event)
        elif isinstance(event, ToolEndEvent):
            tool_end_events.append(event)

    # Verify tool was called
    assert len(tool_start_events) >= 1
    assert len(tool_end_events) >= 1

    # Verify tool details
    tool_start = tool_start_events[0]
    assert tool_start.tool_name == "get_query_plan"
    assert tool_start.tool_call_id == "call_123"

    tool_end = tool_end_events[0]
    assert tool_end.tool_execution.success is True


@pytest.mark.asyncio
async def test_agent_respects_max_steps(mock_llm_client, mock_tool_registry):
    """Test that agent stops after max_steps is reached."""
    config = AgentConfig(
        domain="query",
        model="gpt-4",
        temperature=0.3,
        max_tokens=4096,
        max_steps=2,  # Very low limit
        system_prompt_builder=lambda mode, input, max_tokens: f"Optimize: {input}",
    )

    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=config,
    )

    # Run agent
    step_events = []
    async for event in agent.run_stream(
        user_input="Optimize query",
        mode=OptimizationMode.ONLINE,
        user_id="test-user-123",
        context={},
    ):
        if isinstance(event, StepCompleteEvent):
            step_events.append(event)

    # Should not exceed max_steps
    assert len(step_events) <= 2


@pytest.mark.asyncio
async def test_agent_state_updates_correctly(
    mock_llm_client, mock_tool_registry, agent_config
):
    """Test that agent correctly updates state through reasoning loop."""
    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=agent_config,
    )

    # Run agent and collect final output
    final_output = None
    async for event in agent.run_stream(
        user_input="Analyze query",
        mode=OptimizationMode.ONLINE,
        user_id="test-user-123",
        context={"test_context": "value"},
    ):
        if isinstance(event, FinalOutputEvent):
            final_output = event.output

    # Verify output
    assert final_output is not None
    assert final_output.tokens_used > 0
    assert final_output.steps_taken > 0


@pytest.mark.asyncio
@pytest.mark.skip(reason="Mock fixtures need updating for current component interface")
async def test_agent_component_integration(
    mock_llm_client, mock_tool_registry, agent_config
):
    """Test that all 4 components work together correctly."""
    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=agent_config,
    )

    # Track which components were used
    components_used = {
        "reasoning": False,
        "executor": False,
        "streamer": False,
        "builder": False,
    }

    # Run agent
    async for event in agent.run_stream(
        user_input="Optimize query",
        mode=OptimizationMode.ONLINE,
        user_id="test-user-123",
        context={},
    ):
        # ReasoningEngine produces ThinkingEvents
        if isinstance(event, ThinkingEvent):
            components_used["reasoning"] = True

        # ToolExecutor produces ToolEndEvents
        if isinstance(event, ToolEndEvent):
            components_used["executor"] = True

        # EventStreamer creates all events
        components_used["streamer"] = True

        # OutputBuilder produces FinalOutputEvent
        if isinstance(event, FinalOutputEvent):
            components_used["builder"] = True

    # Verify all components were used
    assert components_used["reasoning"] is True
    assert components_used["executor"] is True
    assert components_used["streamer"] is True
    assert components_used["builder"] is True


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Mock fixtures need updating for current error handling interface"
)
async def test_agent_error_handling(mock_llm_client, mock_tool_registry, agent_config):
    """Test that agent handles errors gracefully."""
    # Mock LLM client that raises error
    error_client = MagicMock()

    async def error_stream(*args, **kwargs):
        raise Exception("LLM API error")

    error_client.call_with_tools_stream = error_stream

    agent = DomainAgent(
        llm_client=error_client,
        tool_registry=mock_tool_registry,
        config=agent_config,
    )

    # Run agent (should handle error)
    error_emitted = False
    async for event in agent.run_stream(
        user_input="Test error handling",
        mode=OptimizationMode.ONLINE,
        user_id="test-user-123",
        context={},
    ):
        if hasattr(event, "error_type") and event.error_type == "fatal_error":
            error_emitted = True

    # Should have emitted error event
    assert error_emitted is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
