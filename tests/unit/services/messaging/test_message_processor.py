# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Simplified unit tests for MessageProcessor service.

Tests core functionality with minimal dependencies.
"""

from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import Message
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
    UserIntentType,
)
from starboard_server.services.messaging.message_processor import (
    MessageProcessor,
    ProcessingType,
)


@pytest.fixture
def processor():
    """Create message processor without intent classification."""
    return MessageProcessor(classify_intent=False)


@pytest.fixture
def processor_with_intent():
    """Create message processor with intent classification."""
    return MessageProcessor(classify_intent=True)


@pytest.fixture
def timestamp():
    """Create a test timestamp."""
    return datetime.now(UTC)


@pytest.fixture
def tool_option():
    """Create a tool call option."""
    return NextStepOption(
        id="opt_optimize",
        number=1,
        title="Optimize Query",
        description="Optimize the query",
        action_type=ActionType.TOOL_CALL,
        target_agent=None,
        tool_name="optimize_query",
        parameters={"query_id": "123"},
    )


@pytest.fixture
def route_option():
    """Create a routing option."""
    return NextStepOption(
        id="opt_route",
        number=2,
        title="Hand off to Cost Analyzer",
        description="Route to cost analyzer",
        action_type=ActionType.ROUTE,
        target_agent="cost_analyzer",
        tool_name=None,
        parameters={},
    )


@pytest.fixture
def continue_option():
    """Create a continue option."""
    return NextStepOption(
        id="opt_continue",
        number=3,
        title="Continue",
        description="Continue analysis",
        action_type=ActionType.CONTINUE,
        target_agent=None,
        tool_name=None,
        parameters={},
    )


@pytest.mark.asyncio
async def test_process_option_selection(processor, tool_option):
    """Test processing a user's option selection."""
    result = await processor.process_message(
        user_input="1",
        available_options=(tool_option,),
    )

    assert result.processing_type == ProcessingType.OPTION_SELECTED
    assert result.selected_option == tool_option
    assert result.action_to_execute is not None
    assert result.action_to_execute["type"] == "tool_call"


@pytest.mark.asyncio
async def test_process_free_text_no_options(processor):
    """Test processing free text when no options available."""
    result = await processor.process_message(
        user_input="Show me the queries",
        available_options=None,
    )

    assert result.processing_type == ProcessingType.FREE_TEXT
    assert result.selected_option is None
    assert result.action_to_execute is None


@pytest.mark.asyncio
async def test_extract_tool_call_action(processor, tool_option):
    """Test extracting tool call action from option."""
    action = processor._extract_action(tool_option)

    assert action["type"] == "tool_call"
    assert action["tool_name"] == "optimize_query"
    assert action["parameters"] == {"query_id": "123"}


@pytest.mark.asyncio
async def test_extract_route_action(processor, route_option):
    """Test extracting route action from option."""
    action = processor._extract_action(route_option)

    assert action["type"] == "route"
    assert action["target_agent"] == "cost_analyzer"


@pytest.mark.asyncio
async def test_extract_continue_action(processor, continue_option):
    """Test extracting continue action from option."""
    action = processor._extract_action(continue_option)

    assert action["type"] == "continue"


@pytest.mark.asyncio
async def test_intent_classification_for_free_text(processor_with_intent, timestamp):
    """Test that free text messages get intent classification."""
    history = (
        Message(
            role="user", content="Analyze queries", timestamp=timestamp, metadata={}
        ),
        Message(role="assistant", content="Done", timestamp=timestamp, metadata={}),
    )

    # Use longer message to avoid short-answer clarification classification
    result = await processor_with_intent.process_message(
        user_input="Also check the performance during morning hours",
        available_options=None,
        conversation_history=history,
    )

    assert result.processing_type == ProcessingType.INTENT_CLASSIFIED
    assert result.intent_classification is not None
    assert result.intent_classification.intent_type == UserIntentType.EXTENSION


@pytest.mark.asyncio
async def test_no_intent_for_option_selection(processor_with_intent, tool_option):
    """Test that option selections don't get intent classification."""
    result = await processor_with_intent.process_message(
        user_input="1",
        available_options=(tool_option,),
    )

    assert result.processing_type == ProcessingType.OPTION_SELECTED
    assert result.intent_classification is None


@pytest.mark.asyncio
async def test_empty_user_input(processor):
    """Test handling of empty user input."""
    result = await processor.process_message(
        user_input="",
        available_options=None,
    )

    assert result.processing_type == ProcessingType.FREE_TEXT
    assert result.original_input == ""


@pytest.mark.asyncio
async def test_whitespace_only_input(processor):
    """Test handling of whitespace-only input."""
    result = await processor.process_message(
        user_input="   ",
        available_options=None,
    )

    assert result.processing_type == ProcessingType.FREE_TEXT


@pytest.mark.asyncio
async def test_none_conversation_history(processor):
    """Test handling of None conversation history."""
    result = await processor.process_message(
        user_input="test",
        available_options=None,
        conversation_history=None,
    )

    assert result.processing_type == ProcessingType.FREE_TEXT


@pytest.mark.asyncio
async def test_preserve_original_input(processor):
    """Test that original user input is preserved."""
    original = "Show me the query performance metrics"

    result = await processor.process_message(
        user_input=original,
        available_options=None,
    )

    assert result.original_input == original


@pytest.mark.asyncio
async def test_high_confidence_for_option_selection(processor, tool_option):
    """Test high confidence for clear option selection."""
    result = await processor.process_message(
        user_input="1",
        available_options=(tool_option,),
    )

    assert result.confidence >= 0.9


@pytest.mark.asyncio
async def test_confidence_for_free_text(processor):
    """Test confidence score for free text."""
    result = await processor.process_message(
        user_input="Show me data",
        available_options=None,
    )

    assert 0.0 <= result.confidence <= 1.0
