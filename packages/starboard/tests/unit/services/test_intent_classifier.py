# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for Intent Classifier service (Phase 2: Conversation Extension)."""

from starboard_core.models.conversation import Message
from starboard.domain.models.conversation_patterns import (
    AgentResponse,
    UserIntentType,
)
from starboard.services.intent.intent_classifier import IntentClassifierService


class TestIntentClassifierInit:
    """Test IntentClassifierService initialization."""

    def test_init_default(self):
        """Test initializing classifier with default settings."""
        classifier = IntentClassifierService()
        assert classifier is not None

    def test_init_with_confidence_threshold(self):
        """Test initializing with custom confidence threshold."""
        classifier = IntentClassifierService(min_confidence=0.75)
        assert classifier.min_confidence == 0.75


class TestNewQueryDetection:
    """Test detection of NEW_QUERY intent."""

    def test_classify_first_message_as_new_query(self):
        """Test that first message in conversation is classified as NEW_QUERY."""
        classifier = IntentClassifierService()

        result = classifier.classify(
            user_message="Analyze query performance for warehouse prod_dw",
            conversation_history=(),  # Empty history
            previous_agent_response=None,
        )

        assert result.intent_type == UserIntentType.NEW_QUERY
        assert result.confidence >= 0.9  # High confidence for first message
        assert (
            "first message" in result.reasoning.lower()
            or "new" in result.reasoning.lower()
        )

    def test_classify_topic_switch_as_new_query(self):
        """Test that completely different topic is classified as NEW_QUERY."""
        classifier = IntentClassifierService()

        # Previous conversation about query performance
        history = (
            Message(
                role="user",
                content="Analyze query performance for warehouse prod_dw",
                metadata={},
            ),
            Message(
                role="assistant",
                content="Query analysis complete. Execution time: 45s, needs optimization.",
                metadata={},
            ),
        )

        # User asks about completely different topic (costs)
        result = classifier.classify(
            user_message="What's my total Databricks spend for last month?",
            conversation_history=history,
            previous_agent_response=None,
        )

        assert result.intent_type == UserIntentType.NEW_QUERY
        assert result.confidence >= 0.7


class TestExtensionDetection:
    """Test detection of EXTENSION intent."""

    def test_classify_temporal_constraint_as_extension(self):
        """Test that adding temporal constraints is classified as EXTENSION."""
        classifier = IntentClassifierService()

        history = (
            Message(
                role="user",
                content="Analyze query performance",
                metadata={},
            ),
            Message(
                role="assistant",
                content="Query runs in 45 seconds on average.",
                metadata={},
            ),
        )

        # User adds temporal constraint
        result = classifier.classify(
            user_message="Users report it's slower in the mornings",
            conversation_history=history,
            previous_agent_response=None,
        )

        assert result.intent_type == UserIntentType.EXTENSION
        assert result.confidence >= 0.7
        assert "morning" in result.extracted_entities.get(
            "timeframe", ""
        ).lower() or any(
            "morning" in str(v).lower() for v in result.extracted_entities.values()
        )

    def test_classify_additional_constraint_keywords_as_extension(self):
        """Test that keywords like 'also', 'additionally' indicate EXTENSION."""
        classifier = IntentClassifierService()

        history = (
            Message(role="user", content="Show me slow queries", metadata={}),
            Message(
                role="assistant", content="Here are the slowest queries...", metadata={}
            ),
        )

        test_cases = [
            "Also check for queries with high memory usage",
            "Additionally, what about queries that scan full tables?",
            "What about queries running on warehouse prod_dw?",
            "How about checking concurrent queries?",
        ]

        for user_message in test_cases:
            result = classifier.classify(
                user_message=user_message,
                conversation_history=history,
                previous_agent_response=None,
            )

            assert result.intent_type == UserIntentType.EXTENSION, (
                f"Failed to detect EXTENSION for: {user_message}"
            )

    def test_extract_entities_from_extension(self):
        """Test that entities are extracted from EXTENSION messages."""
        classifier = IntentClassifierService()

        history = (
            Message(role="user", content="Analyze warehouse performance", metadata={}),
            Message(role="assistant", content="Analysis complete...", metadata={}),
        )

        result = classifier.classify(
            user_message="Also check the prod_dw warehouse during peak hours between 8am and 10am",
            conversation_history=history,
            previous_agent_response=None,
        )

        # Should extract warehouse, timeframe, or similar entities
        assert len(result.extracted_entities) > 0


class TestRefinementDetection:
    """Test detection of REFINEMENT intent."""

    def test_classify_correction_keywords_as_refinement(self):
        """Test that correction keywords indicate REFINEMENT."""
        classifier = IntentClassifierService()

        history = (
            Message(role="user", content="Check prod_dw warehouse", metadata={}),
            Message(role="assistant", content="Analyzing prod_dw...", metadata={}),
        )

        test_cases = [
            "Actually, I meant the staging warehouse",
            "Correction: use the dev_dw warehouse instead",
            "I meant queries from last week, not last month",
            "Instead, focus on queries with errors",
            "Rather, show me successful queries only",
        ]

        for user_message in test_cases:
            result = classifier.classify(
                user_message=user_message,
                conversation_history=history,
                previous_agent_response=None,
            )

            assert result.intent_type == UserIntentType.REFINEMENT, (
                f"Failed to detect REFINEMENT for: {user_message}"
            )

    def test_refinement_extracts_corrected_value(self):
        """Test that REFINEMENT extracts the corrected value."""
        classifier = IntentClassifierService()

        history = (
            Message(role="user", content="Analyze prod warehouse", metadata={}),
            Message(role="assistant", content="Analyzing...", metadata={}),
        )

        result = classifier.classify(
            user_message="Actually, I meant the dev_dw warehouse",
            conversation_history=history,
            previous_agent_response=None,
        )

        assert result.intent_type == UserIntentType.REFINEMENT
        # Should extract the corrected warehouse name
        assert len(result.extracted_entities) > 0


class TestClarificationDetection:
    """Test detection of CLARIFICATION intent."""

    def test_classify_yes_no_as_clarification(self):
        """Test that yes/no responses are classified as CLARIFICATION."""
        classifier = IntentClassifierService()

        history = (
            Message(role="user", content="Check query performance", metadata={}),
            Message(
                role="assistant",
                content="Should I include cached results?",
                metadata={},
            ),
        )

        test_cases = ["yes", "no", "Yes, please", "No, thanks", "yeah", "nope"]

        for user_message in test_cases:
            result = classifier.classify(
                user_message=user_message,
                conversation_history=history,
                previous_agent_response=None,
            )

            assert result.intent_type == UserIntentType.CLARIFICATION, (
                f"Failed to detect CLARIFICATION for: {user_message}"
            )
            assert result.confidence >= 0.9  # High confidence for yes/no

    def test_classify_short_answer_as_clarification(self):
        """Test that short direct answers are classified as CLARIFICATION."""
        classifier = IntentClassifierService()

        history = (
            Message(
                role="assistant",
                content="Which warehouse? prod_dw or staging?",
                metadata={},
            ),
        )

        result = classifier.classify(
            user_message="prod_dw",
            conversation_history=history,
            previous_agent_response=None,
        )

        assert result.intent_type == UserIntentType.CLARIFICATION
        assert result.confidence >= 0.75


class TestFeedbackDetection:
    """Test detection of FEEDBACK intent."""

    def test_classify_gratitude_as_feedback(self):
        """Test that expressions of gratitude are classified as FEEDBACK."""
        classifier = IntentClassifierService()

        history = (
            Message(
                role="assistant",
                content="Analysis complete. Here are the results...",
                metadata={},
            ),
        )

        test_cases = [
            "Thanks!",
            "Thank you",
            "That helps",
            "Perfect, thanks",
            "Great, that's exactly what I needed",
        ]

        for user_message in test_cases:
            result = classifier.classify(
                user_message=user_message,
                conversation_history=history,
                previous_agent_response=None,
            )

            assert result.intent_type == UserIntentType.FEEDBACK, (
                f"Failed to detect FEEDBACK for: {user_message}"
            )

    def test_classify_positive_sentiment_as_feedback(self):
        """Test that positive sentiment is classified as FEEDBACK."""
        classifier = IntentClassifierService()

        history = (
            Message(
                role="assistant", content="Query optimized successfully.", metadata={}
            ),
        )

        test_cases = [
            "Excellent work!",
            "This is helpful",
            "Perfect!",
            "That makes sense",
        ]

        for user_message in test_cases:
            result = classifier.classify(
                user_message=user_message,
                conversation_history=history,
                previous_agent_response=None,
            )

            assert result.intent_type == UserIntentType.FEEDBACK

    def test_feedback_extracts_sentiment(self):
        """Test that FEEDBACK extracts sentiment."""
        classifier = IntentClassifierService()

        result = classifier.classify(
            user_message="Thanks, that's very helpful!",
            conversation_history=(
                Message(role="assistant", content="Analysis complete.", metadata={}),
            ),
            previous_agent_response=None,
        )

        assert result.intent_type == UserIntentType.FEEDBACK
        assert "sentiment" in result.extracted_entities or any(
            "positive" in str(v).lower() for v in result.extracted_entities.values()
        )


class TestConfidenceScoring:
    """Test confidence score calculation."""

    def test_high_confidence_for_obvious_patterns(self):
        """Test that obvious patterns have high confidence (>0.9)."""
        classifier = IntentClassifierService()

        # Yes/no should be very high confidence
        result = classifier.classify(
            user_message="yes",
            conversation_history=(
                Message(role="assistant", content="Should I continue?", metadata={}),
            ),
            previous_agent_response=None,
        )

        assert result.confidence >= 0.9

    def test_lower_confidence_for_ambiguous_input(self):
        """Test that ambiguous input has lower confidence (<0.8)."""
        classifier = IntentClassifierService()

        # Ambiguous message that could be extension or new query
        result = classifier.classify(
            user_message="Show me more data",
            conversation_history=(
                Message(role="assistant", content="Here are the results.", metadata={}),
            ),
            previous_agent_response=None,
        )

        # Should still classify, but with lower confidence
        assert 0.5 <= result.confidence <= 0.9


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_user_message(self):
        """Test handling of empty user message."""
        classifier = IntentClassifierService()

        result = classifier.classify(
            user_message="",
            conversation_history=(),
            previous_agent_response=None,
        )

        # Should handle gracefully, likely as NEW_QUERY or low confidence
        assert result.intent_type in UserIntentType
        assert 0.0 <= result.confidence <= 1.0

    def test_very_long_message(self):
        """Test handling of very long message."""
        classifier = IntentClassifierService()

        long_message = " ".join(["This is a test sentence."] * 100)

        result = classifier.classify(
            user_message=long_message,
            conversation_history=(),
            previous_agent_response=None,
        )

        assert result.intent_type in UserIntentType

    def test_with_previous_agent_response(self):
        """Test classification with AgentResponse instead of just Message."""
        classifier = IntentClassifierService()

        prev_response = AgentResponse(
            content="Query analysis complete. Execution time: 45s.",
            next_steps=None,
            conversation_id="conv-123",
            message_id="msg-456",
            agent_name="query_optimizer",
            metadata={},
        )

        result = classifier.classify(
            user_message="What about morning performance?",
            conversation_history=(
                Message(role="user", content="Analyze query", metadata={}),
            ),
            previous_agent_response=prev_response,
        )

        assert result.intent_type == UserIntentType.EXTENSION
