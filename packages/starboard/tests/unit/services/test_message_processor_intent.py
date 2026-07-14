# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for Message Processor with Intent Classification (Phase 2).

Tests the integration of IntentClassifierService into MessageProcessor
for conversation extension pattern support.
"""

import pytest
from starboard_core.models.conversation import Message
from starboard.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
    UserIntentType,
)
from starboard.services.messaging.message_processor import (
    MessageProcessor,
    ProcessingType,
)


class TestMessageProcessorWithIntent:
    """Test MessageProcessor with intent classification enabled."""

    @pytest.mark.asyncio
    async def test_process_with_intent_classification_enabled(self):
        """Test that intent classification is performed when enabled."""
        processor = MessageProcessor(classify_intent=True)

        # No options, first message
        result = await processor.process_message(
            user_input="Analyze query performance",
            available_options=None,
            conversation_history=(),
            previous_agent_response_content=None,
        )

        assert result.processing_type == ProcessingType.INTENT_CLASSIFIED
        assert result.intent_classification is not None
        assert result.intent_classification.intent_type == UserIntentType.NEW_QUERY

    @pytest.mark.asyncio
    async def test_process_without_intent_classification(self):
        """Test that intent classification is skipped when disabled."""
        processor = MessageProcessor(classify_intent=False)

        result = await processor.process_message(
            user_input="Analyze query performance",
            available_options=None,
            conversation_history=(),
            previous_agent_response_content=None,
        )

        assert result.processing_type == ProcessingType.FREE_TEXT
        assert result.intent_classification is None

    @pytest.mark.asyncio
    async def test_classify_extension_intent(self):
        """Test detecting EXTENSION intent."""
        processor = MessageProcessor(classify_intent=True)

        history = (
            Message(role="user", content="Analyze query performance", metadata={}),
            Message(role="assistant", content="Query runs in 45 seconds", metadata={}),
        )

        result = await processor.process_message(
            user_input="What about performance in the mornings?",
            available_options=None,
            conversation_history=history,
            previous_agent_response_content=None,
        )

        assert result.processing_type == ProcessingType.INTENT_CLASSIFIED
        assert result.intent_classification is not None
        assert result.intent_classification.intent_type == UserIntentType.EXTENSION
        assert result.intent_classification.confidence > 0.7

    @pytest.mark.asyncio
    async def test_classify_refinement_intent(self):
        """Test detecting REFINEMENT intent."""
        processor = MessageProcessor(classify_intent=True)

        history = (
            Message(role="user", content="Check prod warehouse", metadata={}),
            Message(role="assistant", content="Analyzing prod...", metadata={}),
        )

        result = await processor.process_message(
            user_input="Actually, I meant the staging warehouse",
            available_options=None,
            conversation_history=history,
            previous_agent_response_content=None,
        )

        assert result.intent_classification is not None
        assert result.intent_classification.intent_type == UserIntentType.REFINEMENT

    @pytest.mark.asyncio
    async def test_classify_clarification_intent(self):
        """Test detecting CLARIFICATION intent."""
        processor = MessageProcessor(classify_intent=True)

        history = (
            Message(
                role="assistant",
                content="Should I include cached results?",
                metadata={},
            ),
        )

        result = await processor.process_message(
            user_input="yes",
            available_options=None,
            conversation_history=history,
            previous_agent_response_content=None,
        )

        assert result.intent_classification is not None
        assert result.intent_classification.intent_type == UserIntentType.CLARIFICATION
        assert result.intent_classification.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_classify_feedback_intent(self):
        """Test detecting FEEDBACK intent."""
        processor = MessageProcessor(classify_intent=True)

        history = (
            Message(role="assistant", content="Analysis complete!", metadata={}),
        )

        result = await processor.process_message(
            user_input="Thanks, that's helpful!",
            available_options=None,
            conversation_history=history,
            previous_agent_response_content=None,
        )

        assert result.intent_classification is not None
        assert result.intent_classification.intent_type == UserIntentType.FEEDBACK

    @pytest.mark.asyncio
    async def test_option_selection_skips_intent_classification(self):
        """Test that option selection bypasses intent classification."""
        processor = MessageProcessor(classify_intent=True)

        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Optimize query",
                description=None,
                action_type=ActionType.TOOL_CALL,
                target_agent=None,
                tool_name="optimize_query",
                parameters={},
            ),
        )

        history = (Message(role="user", content="Analyze query", metadata={}),)

        result = await processor.process_message(
            user_input="1",
            available_options=options,
            conversation_history=history,
            previous_agent_response_content=None,
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        # Intent classification should be None when option is selected
        assert result.intent_classification is None

    @pytest.mark.asyncio
    async def test_intent_classification_with_entity_extraction(self):
        """Test that entities are extracted during intent classification."""
        processor = MessageProcessor(classify_intent=True)

        history = (
            Message(role="user", content="Analyze warehouse", metadata={}),
            Message(role="assistant", content="Analysis in progress...", metadata={}),
        )

        result = await processor.process_message(
            user_input="Check performance in the mornings for prod_dw warehouse",
            available_options=None,
            conversation_history=history,
            previous_agent_response_content=None,
        )

        assert result.intent_classification is not None
        assert result.intent_classification.intent_type == UserIntentType.EXTENSION
        assert len(result.intent_classification.extracted_entities) > 0
        # Should extract timeframe and warehouse
        entities = result.intent_classification.extracted_entities
        assert "timeframe" in entities or any(
            "morning" in str(v).lower() for v in entities.values()
        )

    @pytest.mark.asyncio
    async def test_default_behavior_without_conversation_history(self):
        """Test default behavior when no conversation history provided."""
        processor = MessageProcessor(classify_intent=True)

        # Call without conversation_history (should default to empty tuple)
        result = await processor.process_message(
            user_input="Analyze query",
            available_options=None,
        )

        assert result.intent_classification is not None
        assert result.intent_classification.intent_type == UserIntentType.NEW_QUERY


class TestBackwardCompatibility:
    """Test backward compatibility with Phase 1 usage."""

    @pytest.mark.asyncio
    async def test_existing_code_without_intent_params(self):
        """Test that existing code works without new parameters."""
        processor = MessageProcessor()

        # Call with only original parameters (Phase 1)
        result = await processor.process_message(
            user_input="Test message",
            available_options=None,
        )

        assert result.processing_type == ProcessingType.FREE_TEXT
        # Intent classification should be None by default (backward compatible)
        assert result.intent_classification is None

    @pytest.mark.asyncio
    async def test_existing_option_selection_still_works(self):
        """Test that Phase 1 option selection still works."""
        processor = MessageProcessor()

        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Test option",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters={},
            ),
        )

        result = await processor.process_message(
            user_input="1",
            available_options=options,
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.selected_option is not None
        assert result.selected_option.number == 1


class TestEdgeCases:
    """Test edge cases for intent-aware message processing."""

    @pytest.mark.asyncio
    async def test_empty_conversation_history(self):
        """Test with empty conversation history."""
        processor = MessageProcessor(classify_intent=True)

        result = await processor.process_message(
            user_input="Test",
            available_options=None,
            conversation_history=(),
            previous_agent_response_content=None,
        )

        assert result.intent_classification is not None
        assert result.intent_classification.intent_type == UserIntentType.NEW_QUERY

    @pytest.mark.asyncio
    async def test_none_previous_agent_response(self):
        """Test with None previous_agent_response."""
        processor = MessageProcessor(classify_intent=True)

        result = await processor.process_message(
            user_input="Test",
            available_options=None,
            conversation_history=(Message(role="user", content="Hi", metadata={}),),
            previous_agent_response_content=None,
        )

        assert result.intent_classification is not None

    @pytest.mark.asyncio
    async def test_empty_user_input_with_intent(self):
        """Test empty user input with intent classification."""
        processor = MessageProcessor(classify_intent=True)

        result = await processor.process_message(
            user_input="",
            available_options=None,
            conversation_history=(),
            previous_agent_response_content=None,
        )

        assert result.processing_type == ProcessingType.INTENT_CLASSIFIED
        # Should still classify (as NEW_QUERY with low confidence)
        assert result.intent_classification is not None
