# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for v2 LLM response dataclasses."""

from dataclasses import FrozenInstanceError

import pytest
from starboard_server.agents.output.llm_responses import (
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolResult,
)


class TestTokenUsage:
    """Tests for TokenUsage dataclass."""

    def test_create_token_usage(self):
        """Test creating token usage."""
        usage = TokenUsage(
            prompt_tokens=1500,
            completion_tokens=300,
            total_tokens=1800,
        )

        assert usage.prompt_tokens == 1500
        assert usage.completion_tokens == 300
        assert usage.total_tokens == 1800

    def test_estimate_cost(self):
        """Test cost estimation."""
        usage = TokenUsage(1500, 300, 1800)

        # GPT-4o-mini pricing
        cost = usage.estimate_cost(0.15, 0.60)

        # (1500/1M * 0.15) + (300/1M * 0.60) = 0.000225 + 0.00018 = 0.000405
        assert abs(cost - 0.000405) < 0.000001

    def test_estimate_cost_zero_tokens(self):
        """Test cost estimation with zero tokens."""
        usage = TokenUsage(0, 0, 0)
        cost = usage.estimate_cost(0.15, 0.60)
        assert cost == 0.0

    def test_invalid_negative_prompt_tokens(self):
        """Test that negative prompt tokens raises error."""
        with pytest.raises(ValueError, match="prompt_tokens must be >= 0"):
            TokenUsage(-100, 300, 200)

    def test_invalid_negative_completion_tokens(self):
        """Test that negative completion tokens raises error."""
        with pytest.raises(ValueError, match="completion_tokens must be >= 0"):
            TokenUsage(1500, -300, 1200)

    def test_invalid_negative_total_tokens(self):
        """Test that negative total tokens raises error."""
        with pytest.raises(ValueError, match="total_tokens must be >= 0"):
            TokenUsage(1500, 300, -1800)

    def test_token_usage_immutability(self):
        """Test that token usage is immutable."""
        usage = TokenUsage(1500, 300, 1800)

        with pytest.raises(FrozenInstanceError):
            usage.prompt_tokens = 2000  # type: ignore


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_create_tool_call(self):
        """Test creating a tool call."""
        tool_call = ToolCall(
            id="call_abc123",
            name="resolve_query",
            arguments='{"statement_id": "abc123"}',
        )

        assert tool_call.id == "call_abc123"
        assert tool_call.name == "resolve_query"
        assert tool_call.arguments == '{"statement_id": "abc123"}'

    def test_parse_arguments(self):
        """Test parsing tool call arguments."""
        tool_call = ToolCall(
            id="call_123",
            name="search",
            arguments='{"query": "test", "limit": 10}',
        )

        args = tool_call.parse_arguments()

        assert isinstance(args, dict)
        assert args["query"] == "test"
        assert args["limit"] == 10

    def test_parse_arguments_complex(self):
        """Test parsing complex nested arguments."""
        tool_call = ToolCall(
            id="call_456",
            name="analyze",
            arguments='{"filters": {"status": "active", "type": "query"}, "limit": 100}',
        )

        args = tool_call.parse_arguments()

        assert args["filters"]["status"] == "active"
        assert args["filters"]["type"] == "query"
        assert args["limit"] == 100

    def test_invalid_empty_id(self):
        """Test that empty id raises error."""
        with pytest.raises(ValueError, match="Tool call id cannot be empty"):
            ToolCall(id="", name="test", arguments="{}")

    def test_invalid_empty_name(self):
        """Test that empty name raises error."""
        with pytest.raises(ValueError, match="Tool call name cannot be empty"):
            ToolCall(id="call_123", name="", arguments="{}")

    def test_empty_arguments_normalized_to_empty_json(self):
        """Empty arguments are normalized to '{}' for tools with optional params."""
        tc = ToolCall(id="call_123", name="test", arguments="")
        assert tc.arguments == "{}"
        assert tc.parse_arguments() == {}

    def test_whitespace_arguments_normalized_to_empty_json(self):
        """Whitespace-only arguments are normalized to '{}'."""
        tc = ToolCall(id="call_123", name="test", arguments="   ")
        assert tc.arguments == "{}"

    def test_invalid_json_arguments(self):
        """Test that invalid JSON arguments raises error."""
        with pytest.raises(ValueError, match="arguments must be valid JSON"):
            ToolCall(
                id="call_123",
                name="test",
                arguments="not valid json",
            )

    def test_tool_call_immutability(self):
        """Test that tool call is immutable."""
        tool_call = ToolCall("call_123", "test", "{}")

        with pytest.raises(FrozenInstanceError):
            tool_call.name = "other"  # type: ignore


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_create_successful_result(self):
        """Test creating a successful tool result."""
        result = ToolResult(
            tool_call_id="call_123",
            tool_name="resolve_query",
            content="Query: SELECT * FROM users",
        )

        assert result.tool_call_id == "call_123"
        assert result.tool_name == "resolve_query"
        assert result.content == "Query: SELECT * FROM users"
        assert result.error is None
        assert not result.is_error()

    def test_create_error_result(self):
        """Test creating an error tool result."""
        result = ToolResult(
            tool_call_id="call_456",
            tool_name="invalid_tool",
            content="",
            error="Tool not found: invalid_tool",
        )

        assert result.error == "Tool not found: invalid_tool"
        assert result.is_error()

    def test_to_message_dict_success(self):
        """Test converting successful result to message dict."""
        result = ToolResult(
            tool_call_id="call_123",
            tool_name="search",
            content="Found 5 results",
        )

        msg = result.to_message_dict()

        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_123"
        assert msg["name"] == "search"
        assert msg["content"] == "Found 5 results"

    def test_to_message_dict_error(self):
        """Test converting error result to message dict."""
        result = ToolResult(
            tool_call_id="call_456",
            tool_name="failed_tool",
            content="",
            error="Execution failed",
        )

        msg = result.to_message_dict()

        assert msg["role"] == "tool"
        assert msg["content"] == "Error: Execution failed"

    def test_empty_tool_call_id_allowed(self):
        """Test that empty tool_call_id is allowed (will be set by caller)."""
        # Empty tool_call_id is now allowed (logged as debug)
        result = ToolResult("", "test", "content")
        assert result.tool_call_id == ""
        assert result.tool_name == "test"

    def test_invalid_empty_tool_name(self):
        """Test that empty tool_name raises error."""
        with pytest.raises(ValueError, match="tool_name cannot be empty"):
            ToolResult("call_123", "", "content")


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_create_text_response(self):
        """Test creating a text-only response."""
        response = LLMResponse(
            content="The query can be optimized by adding an index.",
            tool_calls=(),
            usage=TokenUsage(1500, 300, 1800),
            finish_reason="stop",
            model="gpt-4o-mini",
        )

        assert response.content == "The query can be optimized by adding an index."
        assert len(response.tool_calls) == 0
        assert response.finish_reason == "stop"
        assert response.model == "gpt-4o-mini"
        assert response.has_content()
        assert not response.has_tool_calls()

    def test_create_tool_call_response(self):
        """Test creating a tool call response."""
        response = LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="call_123",
                    name="resolve_query",
                    arguments='{"statement_id": "abc123"}',
                ),
            ),
            usage=TokenUsage(1200, 50, 1250),
            finish_reason="tool_calls",
            model="gpt-4o",
        )

        assert response.content is None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "resolve_query"
        assert not response.has_content()
        assert response.has_tool_calls()

    def test_create_mixed_response(self):
        """Test creating response with both content and tool calls."""
        response = LLMResponse(
            content="Let me check that for you.",
            tool_calls=(
                ToolCall(
                    id="call_456",
                    name="search",
                    arguments='{"query": "test"}',
                ),
            ),
            usage=TokenUsage(1000, 200, 1200),
            finish_reason="tool_calls",
            model="gpt-4o",
        )

        assert response.has_content()
        assert response.has_tool_calls()

    def test_create_multiple_tool_calls(self):
        """Test creating response with multiple tool calls."""
        response = LLMResponse(
            content=None,
            tool_calls=(
                ToolCall("call_1", "tool_1", '{"arg": "val1"}'),
                ToolCall("call_2", "tool_2", '{"arg": "val2"}'),
                ToolCall("call_3", "tool_3", '{"arg": "val3"}'),
            ),
            usage=TokenUsage(1500, 100, 1600),
            finish_reason="tool_calls",
            model="gpt-4o",
        )

        assert len(response.tool_calls) == 3
        assert response.tool_calls[0].name == "tool_1"
        assert response.tool_calls[1].name == "tool_2"
        assert response.tool_calls[2].name == "tool_3"

    def test_has_content_empty_string(self):
        """Test that empty string content returns False for has_content()."""
        response = LLMResponse(
            content="   ",  # Whitespace only
            tool_calls=(),
            usage=TokenUsage(100, 0, 100),
            finish_reason="stop",
            model="gpt-4o-mini",
        )

        assert not response.has_content()

    def test_to_dict(self):
        """Test converting response to dictionary."""
        response = LLMResponse(
            content="Test content",
            tool_calls=(ToolCall("call_123", "test_tool", '{"key": "value"}'),),
            usage=TokenUsage(1000, 200, 1200),
            finish_reason="stop",
            model="gpt-4o-mini",
        )

        result = response.to_dict()

        assert isinstance(result, dict)
        assert result["content"] == "Test content"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "test_tool"
        assert result["usage"]["prompt_tokens"] == 1000
        assert result["finish_reason"] == "stop"
        assert result["model"] == "gpt-4o-mini"

    def test_response_immutability(self):
        """Test that response is immutable."""
        response = LLMResponse(
            content="test",
            tool_calls=(),
            usage=TokenUsage(100, 50, 150),
            finish_reason="stop",
            model="gpt-4o-mini",
        )

        with pytest.raises(FrozenInstanceError):
            response.content = "modified"  # type: ignore


class TestIntegration:
    """Integration tests for LLM response dataclasses."""

    def test_full_tool_call_workflow(self):
        """Test complete tool call workflow."""
        # 1. LLM requests tool call
        response = LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="call_abc123",
                    name="resolve_query",
                    arguments='{"statement_id": "query_456"}',
                ),
            ),
            usage=TokenUsage(1500, 50, 1550),
            finish_reason="tool_calls",
            model="gpt-4o",
        )

        # 2. Parse tool call
        assert response.has_tool_calls()
        tool_call = response.tool_calls[0]
        args = tool_call.parse_arguments()

        assert args["statement_id"] == "query_456"

        # 3. Execute tool (simulated)
        result_content = (
            f"Query resolved: SELECT * FROM users WHERE id = {args['statement_id']}"
        )

        # 4. Create tool result
        tool_result = ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content=result_content,
        )

        # 5. Convert to message for next LLM call
        result_msg = tool_result.to_message_dict()

        assert result_msg["role"] == "tool"
        assert result_msg["tool_call_id"] == "call_abc123"
        assert "Query resolved" in result_msg["content"]

    def test_error_handling_workflow(self):
        """Test workflow with tool error."""
        # 1. LLM requests invalid tool
        response = LLMResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="call_error",
                    name="nonexistent_tool",
                    arguments="{}",
                ),
            ),
            usage=TokenUsage(1000, 30, 1030),
            finish_reason="tool_calls",
            model="gpt-4o-mini",
        )

        # 2. Tool execution fails
        tool_result = ToolResult(
            tool_call_id=response.tool_calls[0].id,
            tool_name=response.tool_calls[0].name,
            content="",
            error="Tool not found: nonexistent_tool",
        )

        # 3. Verify error handling
        assert tool_result.is_error()

        # 4. Convert to message
        result_msg = tool_result.to_message_dict()
        assert "Error:" in result_msg["content"]
