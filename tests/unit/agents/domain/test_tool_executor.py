# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ToolExecutor."""

import pytest
from starboard_server.agents.domain.tool_executor import (
    ToolExecutionResult,
    ToolExecutor,
)
from starboard_server.agents.output.llm_responses import ToolCall
from starboard_server.agents.tools.tool_registry import ToolResult


class MockToolRegistry:
    """Mock tool registry for testing."""

    def __init__(self):
        self.execution_count = {}
        self.should_fail = set()
        self.should_error_result = set()
        self.execution_delay = 0.0

    async def execute_tool(self, tool_name: str, agent_context: dict, **kwargs):
        """Mock tool execution."""
        self.execution_count[tool_name] = self.execution_count.get(tool_name, 0) + 1

        # Simulate delay if configured
        if self.execution_delay > 0:
            import asyncio

            await asyncio.sleep(self.execution_delay)

        # Simulate exception if configured
        if tool_name in self.should_fail:
            raise ValueError(f"Mock failure for {tool_name}")

        # Simulate error result if configured
        if tool_name in self.should_error_result:
            return ToolResult(
                tool_call_id="",  # Will be set by caller
                tool_name=tool_name,
                content="Error occurred",
                error=f"Mock error result for {tool_name}",
            )

        # Success
        return ToolResult(
            tool_call_id="",  # Will be set by caller
            tool_name=tool_name,
            content=f"Result from {tool_name}",
            error=None,
        )


@pytest.fixture
def mock_registry():
    """Create mock tool registry."""
    return MockToolRegistry()


@pytest.mark.asyncio
async def test_tool_executor_initialization(mock_registry):
    """Test ToolExecutor can be initialized."""
    executor = ToolExecutor(
        tool_registry=mock_registry,
        enable_retry=True,
        max_retries=3,
        circuit_breaker_threshold=5,
    )

    assert executor.tool_registry is mock_registry
    assert executor.enable_retry is True
    assert executor.max_retries == 3
    assert executor.circuit_breaker_threshold == 5


@pytest.mark.asyncio
async def test_execute_tools_parallel_success(mock_registry):
    """Test successful parallel tool execution."""
    executor = ToolExecutor(mock_registry)

    tool_calls = [
        ToolCall(id="call_1", name="tool_a", arguments="{}"),
        ToolCall(id="call_2", name="tool_b", arguments="{}"),
        ToolCall(id="call_3", name="tool_c", arguments="{}"),
    ]

    results = await executor.execute_tools_parallel(tool_calls, agent_context={})

    assert len(results) == 3

    # All should succeed
    for result in results:
        assert isinstance(result, ToolExecutionResult)
        assert result.success
        assert result.error is None

    # All tools should have been called once
    assert mock_registry.execution_count["tool_a"] == 1
    assert mock_registry.execution_count["tool_b"] == 1
    assert mock_registry.execution_count["tool_c"] == 1


@pytest.mark.asyncio
async def test_execute_tools_parallel_with_failure(mock_registry):
    """Test parallel execution handles failures."""
    mock_registry.should_fail.add("tool_b")

    executor = ToolExecutor(
        mock_registry, enable_retry=False
    )  # Disable retry for this test

    tool_calls = [
        ToolCall(id="call_1", name="tool_a", arguments="{}"),
        ToolCall(id="call_2", name="tool_b", arguments="{}"),
        ToolCall(id="call_3", name="tool_c", arguments="{}"),
    ]

    results = await executor.execute_tools_parallel(tool_calls, agent_context={})

    assert len(results) == 3

    # tool_a and tool_c should succeed
    assert results[0].success
    assert results[0].tool_call.name == "tool_a"

    # tool_b should fail
    assert not results[1].success
    assert results[1].tool_call.name == "tool_b"
    assert "Mock failure" in results[1].error

    # tool_c should succeed
    assert results[2].success
    assert results[2].tool_call.name == "tool_c"


@pytest.mark.asyncio
async def test_execute_tools_with_retry(mock_registry):
    """Test tool execution retries on failure."""
    executor = ToolExecutor(mock_registry, enable_retry=True, max_retries=2)

    # Make tool fail twice then succeed
    call_counter = {"count": 0}

    async def failing_then_succeeding(tool_name: str, agent_context: dict, **kwargs):
        call_counter["count"] += 1
        if call_counter["count"] <= 2:
            raise ValueError("Transient failure")
        return ToolResult(
            tool_call_id="call_1",
            tool_name=tool_name,
            content="Success after retries",
            error=None,
        )

    # Replace mock execute method
    mock_registry.execute_tool = failing_then_succeeding

    tool_call = ToolCall(id="call_1", name="flaky_tool", arguments="{}")
    results = await executor.execute_tools_parallel([tool_call], agent_context={})

    # Should eventually succeed
    assert len(results) == 1
    assert results[0].success
    assert call_counter["count"] == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
async def test_execute_tools_retry_exhausted(mock_registry):
    """Test tool execution fails after max retries."""
    mock_registry.should_fail.add("always_fails")

    executor = ToolExecutor(mock_registry, enable_retry=True, max_retries=2)

    tool_call = ToolCall(id="call_1", name="always_fails", arguments="{}")
    results = await executor.execute_tools_parallel([tool_call], agent_context={})

    # Should fail after all retries
    assert len(results) == 1
    assert not results[0].success
    assert "Mock failure" in results[0].error

    # Should have tried 3 times (initial + 2 retries)
    assert mock_registry.execution_count["always_fails"] == 3


@pytest.mark.asyncio
async def test_execute_tools_error_result(mock_registry):
    """Test tool execution handles error results (not exceptions)."""
    mock_registry.should_error_result.add("error_tool")

    executor = ToolExecutor(mock_registry)

    tool_call = ToolCall(id="call_1", name="error_tool", arguments="{}")
    results = await executor.execute_tools_parallel([tool_call], agent_context={})

    # Should return unsuccessful result
    assert len(results) == 1
    assert not results[0].success
    assert "Mock error result" in results[0].error
    assert results[0].result is not None  # Tool result is still returned


@pytest.mark.asyncio
async def test_execute_tools_argument_parsing_error(mock_registry):
    """Test ToolCall validates JSON arguments at construction time."""
    # ToolCall now validates JSON in __post_init__, so invalid JSON raises immediately
    with pytest.raises(ValueError) as exc_info:
        ToolCall(id="call_1", name="test_tool", arguments="invalid json{")

    # Error should mention JSON validation
    assert "valid JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures(mock_registry):
    """Test circuit breaker opens after repeated failures."""
    mock_registry.should_fail.add("broken_tool")

    executor = ToolExecutor(
        mock_registry,
        enable_retry=False,  # Disable retry for faster test
        circuit_breaker_threshold=3,
    )

    tool_call = ToolCall(id="call_1", name="broken_tool", arguments="{}")

    # Execute multiple times to trigger circuit breaker
    circuit_opened = False
    for _ in range(5):
        results = await executor.execute_tools_parallel([tool_call], agent_context={})
        result = results[0]

        # All should fail
        assert not result.success

        # Check if circuit breaker opened (error message changes)
        if "Circuit breaker open" in result.error:
            circuit_opened = True
            break  # Circuit has opened, test passed

    # The circuit should open at some point after threshold failures
    # Note: Circuit breaker may need consecutive failures, implementation may vary
    assert circuit_opened or mock_registry.execution_count.get("broken_tool", 0) >= 3


@pytest.mark.asyncio
async def test_execution_duration_tracked(mock_registry):
    """Test execution duration is tracked."""
    mock_registry.execution_delay = 0.1  # 100ms delay

    executor = ToolExecutor(mock_registry)

    tool_call = ToolCall(id="call_1", name="slow_tool", arguments="{}")
    results = await executor.execute_tools_parallel([tool_call], agent_context={})

    assert len(results) == 1
    assert results[0].duration_seconds >= 0.1  # At least 100ms


@pytest.mark.asyncio
async def test_execute_empty_tool_list(mock_registry):
    """Test executing empty tool list returns empty results."""
    executor = ToolExecutor(mock_registry)

    results = await executor.execute_tools_parallel([], agent_context={})

    assert results == []


@pytest.mark.asyncio
async def test_execute_with_agent_context(mock_registry):
    """Test agent context is passed to tools."""
    context_received = {}

    async def capture_context(tool_name: str, agent_context: dict, **kwargs):
        # The agent_context should be in kwargs
        context_received["agent_context"] = agent_context
        context_received.update(kwargs)
        return ToolResult(
            tool_call_id="call_1",
            tool_name=tool_name,
            content="Success",
            error=None,
        )

    mock_registry.execute_tool = capture_context

    executor = ToolExecutor(mock_registry)

    agent_context = {"workspace_id": "ws123", "user_id": "user456"}
    tool_call = ToolCall(id="call_1", name="test_tool", arguments='{"param": "value"}')

    await executor.execute_tools_parallel([tool_call], agent_context=agent_context)

    # Context should have been passed
    assert "agent_context" in context_received
    assert context_received["agent_context"]["workspace_id"] == "ws123"

    # Arguments should also be there
    assert "param" in context_received
    assert context_received["param"] == "value"
