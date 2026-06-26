# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Simplified unit tests for IntentClassifierService.

Tests core functionality with minimal dependencies.
"""

from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import Message
from starboard_server.domain.models.conversation_patterns import UserIntentType
from starboard_server.services.intent.intent_classifier import IntentClassifierService


@pytest.fixture
def classifier():
    """Create intent classifier service."""
    return IntentClassifierService()


@pytest.fixture
def timestamp():
    """Create a test timestamp."""
    return datetime.now(UTC)


def test_first_message_is_new_query(classifier):
    """Test that first message is classified as NEW_QUERY."""
    result = classifier.classify(
        user_message="Analyze query performance",
        conversation_history=(),
        previous_agent_response=None,
    )

    assert result.intent_type == UserIntentType.NEW_QUERY
    assert result.confidence == 0.95


def test_empty_conversation_history_is_new_query(classifier):
    """Test empty history is treated as NEW_QUERY."""
    result = classifier.classify(
        user_message="Show me data",
        conversation_history=[],
        previous_agent_response=None,
    )

    assert result.intent_type == UserIntentType.NEW_QUERY


def test_extension_keyword_also(classifier, timestamp):
    """Test EXTENSION classification with 'also' keyword."""
    history = (Message(role="user", content="Test", timestamp=timestamp, metadata={}),)

    # Use longer message to avoid short-answer clarification classification
    result = classifier.classify(
        user_message="Also check the performance during peak hours",
        conversation_history=history,
        previous_agent_response=None,
    )

    assert result.intent_type == UserIntentType.EXTENSION
    assert "extension_keyword" in result.extracted_entities


def test_refinement_keyword_actually(classifier, timestamp):
    """Test REFINEMENT classification with 'actually' keyword."""
    history = (Message(role="user", content="Test", timestamp=timestamp, metadata={}),)

    result = classifier.classify(
        user_message="Actually, I meant something else",
        conversation_history=history,
        previous_agent_response=None,
    )

    assert result.intent_type == UserIntentType.REFINEMENT


def test_yes_clarification(classifier, timestamp):
    """Test CLARIFICATION for yes/no responses."""
    history = (Message(role="user", content="Test", timestamp=timestamp, metadata={}),)

    result = classifier.classify(
        user_message="yes",
        conversation_history=history,
        previous_agent_response=None,
    )

    assert result.intent_type == UserIntentType.CLARIFICATION
    assert result.confidence >= 0.9


def test_feedback_with_thanks(classifier, timestamp):
    """Test FEEDBACK classification."""
    history = (Message(role="user", content="Test", timestamp=timestamp, metadata={}),)

    result = classifier.classify(
        user_message="Thanks!",
        conversation_history=history,
        previous_agent_response=None,
    )

    assert result.intent_type == UserIntentType.FEEDBACK


def test_empty_message(classifier):
    """Test empty message handling."""
    result = classifier.classify(
        user_message="",
        conversation_history=(),
        previous_agent_response=None,
    )

    assert result.intent_type == UserIntentType.NEW_QUERY
    assert result.confidence == 0.5


def test_whitespace_message(classifier):
    """Test whitespace-only message."""
    result = classifier.classify(
        user_message="   ",
        conversation_history=(),
        previous_agent_response=None,
    )

    assert result.intent_type == UserIntentType.NEW_QUERY


def test_custom_confidence_threshold():
    """Test custom min_confidence setting."""
    classifier = IntentClassifierService(min_confidence=0.75)
    assert classifier.min_confidence == 0.75


def test_default_confidence_threshold():
    """Test default min_confidence value."""
    classifier = IntentClassifierService()
    assert classifier.min_confidence == 0.5


def test_reasoning_field_present(classifier, timestamp):
    """Test that reasoning is always provided."""
    history = (Message(role="user", content="Test", timestamp=timestamp, metadata={}),)

    result = classifier.classify(
        user_message="Also check",
        conversation_history=history,
        previous_agent_response=None,
    )

    assert result.reasoning is not None
    assert len(result.reasoning) > 0
