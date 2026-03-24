"""
Fixtures for multi-agent baseline tests.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from starboard_server.agents.output.llm_responses import ToolResult
from starboard_server.agents.tools import ToolMetadata, ToolRegistry


@pytest.fixture
def mock_llm_client():
    """
    Provide a mocked LLM client for baseline tests.

    Returns a mock with minimal methods needed for _build_system_prompt tests.
    """
    mock = Mock()
    mock.json_response = AsyncMock(
        return_value={
            "goal": "Test optimization",
            "mode": "online",
            "intents": [{"intent": "analyze_query", "reason": "Test reason"}],
        }
    )
    mock.text_response = AsyncMock(return_value="Test response text")
    mock.call_with_tools = Mock(return_value=Mock())
    mock.call_with_tools_stream = AsyncMock()

    return mock


@pytest.fixture
def mock_tool_registry():
    """
    Create a mock tool registry for baseline tests.

    Returns a minimal registry with a few mock tools for testing purposes.
    """
    registry = ToolRegistry()

    # Add a simple mock tool
    def mock_tool_func(**kwargs):
        return ToolResult(
            tool_call_id="test_id",
            tool_name="mock_tool",
            content="Mock tool response",
        )

    # Register mock tool
    metadata = ToolMetadata(
        name="mock_tool",
        description="A mock tool for testing",
        parameters={
            "type": "object",
            "properties": {},
        },
    )

    from starboard_server.agents.tools import NativeToolAdapter

    class MockToolWrapper:
        async def mock_tool(self) -> dict:
            return {"result": "success"}

    adapter = NativeToolAdapter(MockToolWrapper(), "mock_tool", metadata)
    registry.register("mock_tool", adapter)

    return registry
