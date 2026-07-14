# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ReasoningEngine."""

import pytest
from starboard.agents.domain.reasoning_engine import (
    ReasoningEngine,
    ReasoningStep,
)
from starboard.agents.state.agent_state import AgentState, Message, WorkingMemory
from starboard.agents.tools.tool_registry import ToolRegistry


class MockLLMClient:
    """Mock LLM client for testing."""

    def __init__(self, response_chunks=None):
        self.response_chunks = response_chunks or []
        self.call_count = 0

    async def call_with_tools_stream(self, messages, tools, temperature, max_tokens):
        """Mock streaming response."""
        self.call_count += 1
        for chunk in self.response_chunks:
            yield chunk


@pytest.fixture
def mock_llm():
    """Create mock LLM client."""
    return MockLLMClient()


class MockToolClass:
    """Mock tool class for testing."""

    async def test_tool(self, **kwargs):
        """Mock test tool."""
        return {"result": "test"}

    async def complete(self, **kwargs):
        """Mock complete tool."""
        return {"result": "done"}


@pytest.fixture
def tool_registry():
    """Create minimal tool registry."""
    from starboard.agents.tools.tool_registry import (
        NativeToolAdapter,
        ToolMetadata,
    )

    registry = ToolRegistry()
    mock_tools = MockToolClass()

    # Add test tool
    test_tool_metadata = ToolMetadata(
        name="test_tool",
        description="Test tool",
        parameters={
            "type": "object",
            "properties": {},
        },
    )
    test_tool_adapter = NativeToolAdapter(
        tool_instance=mock_tools,
        method_name="test_tool",
        metadata=test_tool_metadata,
    )
    registry.register("test_tool", test_tool_adapter)

    # Add complete tool
    complete_metadata = ToolMetadata(
        name="complete",
        description="Complete reasoning",
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
def agent_state():
    """Create test agent state."""
    return AgentState(
        user_id="test_user",
        goal="Test goal",
        mode="online",
        current_step=0,
        completed=False,
        conversation_history=(
            Message(role="system", content="You are a test agent"),
            Message(role="user", content="Test query"),
        ),
        working_memory=WorkingMemory(),
        context={},
        budget_remaining=1000,
        final_output=None,
    )


@pytest.mark.asyncio
async def test_reasoning_engine_initialization(mock_llm, tool_registry):
    """Test ReasoningEngine can be initialized."""
    engine = ReasoningEngine(
        llm_client=mock_llm,
        tool_registry=tool_registry,
        max_steps=10,
        temperature=0.4,
    )

    assert engine.llm_client is mock_llm
    assert engine.tool_registry is tool_registry
    assert engine.max_steps == 10
    assert engine.temperature == 0.4


@pytest.mark.asyncio
async def test_execute_step_stream_with_thinking(mock_llm, tool_registry, agent_state):
    """Test reasoning engine streams thinking content."""
    # Configure mock to return thinking chunks
    mock_llm.response_chunks = [
        {"type": "content_delta", "content": "I need to "},
        {"type": "content_delta", "content": "analyze this"},
        {"type": "tool_calls_delta", "tool_calls": []},
        {
            "type": "usage",
            "usage": {
                "total_tokens": 100,
                "prompt_tokens": 50,
                "completion_tokens": 50,
            },
        },
    ]

    engine = ReasoningEngine(mock_llm, tool_registry)

    chunks = []
    async for chunk in engine.execute_step_stream(agent_state):
        chunks.append(chunk)

    # Should have thinking chunks + complete chunk
    thinking_chunks = [c for c in chunks if c["type"] == "thinking"]
    assert len(thinking_chunks) >= 2  # At least 2 content deltas

    # Should have final complete chunk
    complete_chunks = [c for c in chunks if c["type"] == "complete"]
    assert len(complete_chunks) == 1

    step_result = complete_chunks[0]["step"]
    assert isinstance(step_result, ReasoningStep)
    assert step_result.thinking_content == "I need to analyze this"
    assert not step_result.completed  # No complete tool called


@pytest.mark.asyncio
async def test_execute_step_stream_with_tool_calls(
    mock_llm, tool_registry, agent_state
):
    """Test reasoning engine handles tool calls."""
    # Configure mock to return tool calls
    mock_llm.response_chunks = [
        {"type": "content_delta", "content": "I will use a tool"},
        {
            "type": "tool_calls_delta",
            "tool_calls": [{"id": "call_1", "name": "test_tool", "arguments": "{}"}],
        },
        {"type": "usage", "usage": {"total_tokens": 120}},
    ]

    engine = ReasoningEngine(mock_llm, tool_registry)

    chunks = []
    async for chunk in engine.execute_step_stream(agent_state):
        chunks.append(chunk)

    # Should have tool_calls chunk
    tool_call_chunks = [c for c in chunks if c["type"] == "tool_calls"]
    assert len(tool_call_chunks) == 1
    assert len(tool_call_chunks[0]["tool_calls"]) == 1

    # Final step should include tool calls
    complete_chunk = [c for c in chunks if c["type"] == "complete"][0]
    step_result = complete_chunk["step"]
    assert len(step_result.tool_calls) == 1
    assert step_result.tool_calls[0]["name"] == "test_tool"


@pytest.mark.asyncio
async def test_execute_step_stream_completion(mock_llm, tool_registry, agent_state):
    """Test reasoning engine recognizes completion."""
    # Configure mock to call complete tool
    mock_llm.response_chunks = [
        {"type": "content_delta", "content": "Task complete"},
        {
            "type": "tool_calls_delta",
            "tool_calls": [{"id": "call_1", "name": "complete", "arguments": "{}"}],
        },
        {"type": "usage", "usage": {"total_tokens": 80}},
    ]

    engine = ReasoningEngine(mock_llm, tool_registry)

    chunks = []
    async for chunk in engine.execute_step_stream(agent_state):
        chunks.append(chunk)

    # Final step should mark as completed
    complete_chunk = [c for c in chunks if c["type"] == "complete"][0]
    step_result = complete_chunk["step"]
    assert step_result.completed  # Complete tool was called


@pytest.mark.asyncio
async def test_execute_step_max_steps_reached(mock_llm, tool_registry, agent_state):
    """Test reasoning engine stops at max steps."""
    engine = ReasoningEngine(mock_llm, tool_registry, max_steps=5)

    # Create state at max steps
    state_at_max = agent_state.__replace__(current_step=5)

    chunks = []
    async for chunk in engine.execute_step_stream(state_at_max):
        chunks.append(chunk)

    # Should immediately return completion
    assert len(chunks) == 1
    assert chunks[0]["type"] == "complete"

    step_result = chunks[0]["step"]
    assert step_result.completed
    assert step_result.error == "max_steps_reached"


@pytest.mark.asyncio
async def test_get_tool_schemas_filters_used_tools(tool_registry, agent_state):
    """Test tool schema filtering based on used tools."""
    # Mark test_tool as used
    memory_with_used = agent_state.working_memory.add_tool_used("test_tool")
    state_with_used = agent_state.__replace__(working_memory=memory_with_used)

    engine = ReasoningEngine(MockLLMClient(), tool_registry)
    schemas = engine._get_tool_schemas_for_step(state_with_used)

    # test_tool should be filtered out
    tool_names = [s.get("function", {}).get("name") for s in schemas]
    assert "test_tool" not in tool_names

    # complete should always be available
    assert "complete" in tool_names


@pytest.mark.asyncio
async def test_build_messages_converts_to_dicts(tool_registry, agent_state):
    """Test message conversion to API format."""
    engine = ReasoningEngine(MockLLMClient(), tool_registry)

    messages = engine._build_messages(agent_state)

    # Should have 2 messages (system + user)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    # Should be dicts, not Message objects
    assert isinstance(messages[0], dict)
    assert isinstance(messages[1], dict)


@pytest.mark.asyncio
async def test_build_messages_handles_tool_calls_metadata(tool_registry):
    """Test message conversion extracts tool_calls from metadata."""
    # Create state with tool call in metadata
    state = AgentState(
        user_id="test_user",
        goal="Test",
        mode="online",
        current_step=1,
        completed=False,
        conversation_history=(
            Message(role="system", content="Test"),
            Message(
                role="assistant",
                content="",
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "test", "arguments": "{}"},
                        }
                    ]
                },
            ),
        ),
        working_memory=WorkingMemory(),
        context={},
        budget_remaining=1000,
    )

    engine = ReasoningEngine(MockLLMClient(), tool_registry)
    messages = engine._build_messages(state)

    # Assistant message should have tool_calls at top level
    assistant_msg = messages[1]
    assert "tool_calls" in assistant_msg
    assert len(assistant_msg["tool_calls"]) == 1

    # metadata should be removed
    assert "metadata" not in assistant_msg

    # Empty content should be removed when tool_calls present
    assert "content" not in assistant_msg


@pytest.mark.asyncio
async def test_build_messages_sanitizes_empty_tool_call_arguments(tool_registry):
    """Empty tool_call arguments in metadata are normalized to '{}' for the API."""
    state = AgentState(
        user_id="test_user",
        goal="Test",
        mode="online",
        current_step=1,
        completed=False,
        conversation_history=(
            Message(role="system", content="Test"),
            Message(
                role="assistant",
                content="",
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "discover_active_products",
                                "arguments": "",
                            },
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "another_tool",
                                "arguments": "   ",
                            },
                        },
                        {
                            "id": "call_3",
                            "type": "function",
                            "function": {
                                "name": "valid_tool",
                                "arguments": '{"key": "value"}',
                            },
                        },
                    ]
                },
            ),
        ),
        working_memory=WorkingMemory(),
        context={},
        budget_remaining=1000,
    )

    engine = ReasoningEngine(MockLLMClient(), tool_registry)
    messages = engine._build_messages(state)

    assistant_msg = messages[1]
    tool_calls = assistant_msg["tool_calls"]

    assert tool_calls[0]["function"]["arguments"] == "{}"
    assert tool_calls[1]["function"]["arguments"] == "{}"
    assert tool_calls[2]["function"]["arguments"] == '{"key": "value"}'
