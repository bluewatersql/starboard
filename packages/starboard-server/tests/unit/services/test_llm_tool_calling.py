"""Unit tests for LLM client tool calling (v2)."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
from starboard_server.adapters.llm.openai.client import OpenAIProvider
from starboard_server.agents.output.llm_responses import (
    LLMResponse,
)
from starboard_server.infra.core.config import EnvConfig


@dataclass
class MockFunction:
    """Mock function object from OpenAI response."""

    name: str
    arguments: str


@dataclass
class MockToolCall:
    """Mock tool call object from OpenAI response."""

    id: str
    type: str
    function: MockFunction


@dataclass
class MockMessage:
    """Mock message object from OpenAI response."""

    content: str | None
    tool_calls: list[MockToolCall] | None


@dataclass
class MockChoice:
    """Mock choice object from OpenAI response."""

    message: MockMessage
    finish_reason: str


@dataclass
class MockUsage:
    """Mock usage object from OpenAI response."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class MockChatCompletion:
    """Mock ChatCompletion response from OpenAI."""

    choices: list[MockChoice]
    usage: MockUsage


class TestCallWithTools:
    """Tests for call_with_tools method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.cfg = EnvConfig(
            llm_api_key="test_key",
            llm_model="gpt-4o-mini",
            llm_temperature=0.7,
            llm_max_tokens=4096,
            databricks_host="test_host",
            databricks_token="test_token",
            databricks_warehouse_id="test_dw",
        )

    def _create_client(self):
        """Create an OpenAIProvider with mocked AsyncOpenAI."""
        with patch("starboard_server.adapters.llm.openai.client.AsyncOpenAI"):
            return OpenAIProvider(self.cfg)

    @pytest.mark.asyncio
    async def test_call_with_tools_text_response(self):
        """Test tool call that returns text response (no tools called)."""
        client = self._create_client()

        # Mock OpenAI response with text only
        mock_response = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content="Here's my analysis of the query.",
                        tool_calls=None,
                    ),
                    finish_reason="stop",
                )
            ],
            usage=MockUsage(
                prompt_tokens=1500,
                completion_tokens=300,
                total_tokens=1800,
            ),
        )

        # Mock the API call
        client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Call with tools
        messages = [{"role": "user", "content": "Analyze this query"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "analyze_query",
                    "description": "Analyze a SQL query",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        response = await client.call_with_tools(messages, tools)

        # Verify response
        assert isinstance(response, LLMResponse)
        assert response.content == "Here's my analysis of the query."
        assert len(response.tool_calls) == 0
        assert response.finish_reason == "stop"
        assert response.usage.prompt_tokens == 1500
        assert response.usage.completion_tokens == 300
        assert response.has_content()
        assert not response.has_tool_calls()

    @pytest.mark.asyncio
    async def test_call_with_tools_single_tool_call(self):
        """Test tool call that requests single tool execution."""
        client = self._create_client()

        # Mock OpenAI response with tool call
        mock_response = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                id="call_abc123",
                                type="function",
                                function=MockFunction(
                                    name="resolve_query",
                                    arguments='{"statement_id": "query_456"}',
                                ),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=MockUsage(
                prompt_tokens=1200,
                completion_tokens=50,
                total_tokens=1250,
            ),
        )

        client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Call with tools
        messages = [{"role": "user", "content": "Resolve query query_456"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "resolve_query",
                    "description": "Resolve a query from statement_id",
                    "parameters": {
                        "type": "object",
                        "properties": {"statement_id": {"type": "string"}},
                        "required": ["statement_id"],
                    },
                },
            }
        ]

        response = await client.call_with_tools(messages, tools)

        # Verify response
        assert isinstance(response, LLMResponse)
        assert response.content is None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].id == "call_abc123"
        assert response.tool_calls[0].name == "resolve_query"
        assert response.finish_reason == "tool_calls"
        assert not response.has_content()
        assert response.has_tool_calls()

        # Verify tool call arguments
        args = response.tool_calls[0].parse_arguments()
        assert args["statement_id"] == "query_456"

    @pytest.mark.asyncio
    async def test_call_with_tools_multiple_tool_calls(self):
        """Test tool call that requests multiple tools in parallel."""
        client = self._create_client()

        # Mock OpenAI response with multiple tool calls
        mock_response = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                id="call_1",
                                type="function",
                                function=MockFunction(
                                    name="get_table_metadata",
                                    arguments='{"table_name": "users"}',
                                ),
                            ),
                            MockToolCall(
                                id="call_2",
                                type="function",
                                function=MockFunction(
                                    name="get_table_metadata",
                                    arguments='{"table_name": "orders"}',
                                ),
                            ),
                            MockToolCall(
                                id="call_3",
                                type="function",
                                function=MockFunction(
                                    name="analyze_query_plan",
                                    arguments='{"query_id": "q123"}',
                                ),
                            ),
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=MockUsage(
                prompt_tokens=2000,
                completion_tokens=150,
                total_tokens=2150,
            ),
        )

        client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Call with tools
        messages = [{"role": "user", "content": "Analyze this query"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_table_metadata",
                    "description": "Get table metadata",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze_query_plan",
                    "description": "Analyze query execution plan",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

        response = await client.call_with_tools(messages, tools)

        # Verify response
        assert len(response.tool_calls) == 3
        assert response.tool_calls[0].name == "get_table_metadata"
        assert response.tool_calls[1].name == "get_table_metadata"
        assert response.tool_calls[2].name == "analyze_query_plan"

    @pytest.mark.asyncio
    async def test_call_with_tools_mixed_content_and_tools(self):
        """Test response with both content and tool calls."""
        client = self._create_client()

        # Mock OpenAI response with both content and tool calls
        mock_response = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content="Let me check that for you.",
                        tool_calls=[
                            MockToolCall(
                                id="call_search",
                                type="function",
                                function=MockFunction(
                                    name="search_logs",
                                    arguments='{"query": "error"}',
                                ),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=MockUsage(
                prompt_tokens=1000,
                completion_tokens=100,
                total_tokens=1100,
            ),
        )

        client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Call with tools
        messages = [{"role": "user", "content": "Find errors in logs"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_logs",
                    "description": "Search application logs",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        response = await client.call_with_tools(messages, tools)

        # Verify both content and tool calls present
        assert response.has_content()
        assert response.has_tool_calls()
        assert response.content == "Let me check that for you."
        assert len(response.tool_calls) == 1

    @pytest.mark.asyncio
    async def test_call_with_tools_no_tools_provided(self):
        """Test call with tools when no tools are provided."""
        client = self._create_client()

        # Mock OpenAI response
        mock_response = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content="I can help with that.",
                        tool_calls=None,
                    ),
                    finish_reason="stop",
                )
            ],
            usage=MockUsage(
                prompt_tokens=500,
                completion_tokens=50,
                total_tokens=550,
            ),
        )

        client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Call with empty tools list
        messages = [{"role": "user", "content": "Help me"}]
        tools = []

        response = await client.call_with_tools(messages, tools)

        # Verify regular text response
        assert response.has_content()
        assert not response.has_tool_calls()

    @pytest.mark.asyncio
    async def test_call_with_tools_token_usage(self):
        """Test that token usage is properly captured."""
        client = self._create_client()

        # Mock response
        mock_response = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(content="Response", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=MockUsage(
                prompt_tokens=2500,
                completion_tokens=750,
                total_tokens=3250,
            ),
        )

        client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Call
        response = await client.call_with_tools(
            [{"role": "user", "content": "test"}], []
        )

        # Verify usage
        assert response.usage.prompt_tokens == 2500
        assert response.usage.completion_tokens == 750
        assert response.usage.total_tokens == 3250

        # Verify cost estimation works
        cost = response.usage.estimate_cost(0.15, 0.60)
        assert cost > 0

    @pytest.mark.asyncio
    async def test_call_with_tools_model_override(self):
        """Test that model can be overridden."""
        client = self._create_client()

        # Mock response
        mock_response = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(content="Response", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=MockUsage(100, 50, 150),
        )

        mock_create = AsyncMock(return_value=mock_response)
        client.async_client.chat.completions.create = mock_create

        # Call with model override
        await client.call_with_tools(
            [{"role": "user", "content": "test"}],
            [],
            model="gpt-4o",
        )

        # Verify model was passed correctly
        call_args = mock_create.call_args
        assert call_args[1]["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_call_with_tools_temperature_override(self):
        """Test that temperature can be overridden."""
        client = self._create_client()

        # Mock response
        mock_response = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(content="Response", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=MockUsage(100, 50, 150),
        )

        mock_create = AsyncMock(return_value=mock_response)
        client.async_client.chat.completions.create = mock_create

        # Call with temperature override
        await client.call_with_tools(
            [{"role": "user", "content": "test"}],
            [],
            temperature=0.2,
        )

        # Verify temperature was passed correctly
        call_args = mock_create.call_args
        assert call_args[1]["temperature"] == 0.2


class TestToolCallIntegration:
    """Integration tests for tool calling workflow."""

    def setup_method(self):
        """Set up test fixtures."""
        self.cfg = EnvConfig(
            llm_api_key="test_key",
            llm_model="gpt-4o-mini",
            llm_temperature=0.7,
            llm_max_tokens=4096,
            databricks_host="test_host",
            databricks_token="test_token",
            databricks_warehouse_id="test_dw",
        )

    @pytest.mark.asyncio
    async def test_full_tool_call_conversation(self):
        """Test complete tool call conversation flow."""
        with patch("starboard_server.adapters.llm.openai.client.AsyncOpenAI"):
            client = OpenAIProvider(self.cfg)

        # Step 1: User asks question, LLM requests tool
        mock_response_1 = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                id="call_resolve",
                                type="function",
                                function=MockFunction(
                                    name="resolve_query",
                                    arguments='{"statement_id": "q123"}',
                                ),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=MockUsage(1000, 30, 1030),
        )

        client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_response_1
        )

        messages_1 = [{"role": "user", "content": "Analyze query q123"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "resolve_query",
                    "description": "Resolve a query",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        response_1 = await client.call_with_tools(messages_1, tools)

        # Verify tool call requested
        assert response_1.has_tool_calls()
        tool_call = response_1.tool_calls[0]
        assert tool_call.name == "resolve_query"

        # Step 2: Execute tool (simulated)
        from starboard_server.agents.output.llm_responses import ToolResult

        tool_result = ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content="Query: SELECT * FROM users WHERE status='active'",
        )

        # Step 3: Send tool result back, LLM provides final answer
        mock_response_2 = MockChatCompletion(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content="This query can be optimized by adding an index on the status column.",
                        tool_calls=None,
                    ),
                    finish_reason="stop",
                )
            ],
            usage=MockUsage(1500, 200, 1700),
        )

        client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_response_2
        )

        messages_2 = messages_1 + [tool_result.to_message_dict()]

        response_2 = await client.call_with_tools(messages_2, tools)

        # Verify final response
        assert response_2.has_content()
        assert not response_2.has_tool_calls()
        assert "optimized" in response_2.content.lower()
