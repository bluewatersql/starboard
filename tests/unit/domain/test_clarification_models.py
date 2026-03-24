"""Unit tests for clarification domain models (Phase 7).

Tests cover:
- Model immutability (frozen dataclasses)
- Serialization (to_dict/from_dict)
- Enum validation
- Edge cases

Following TDD approach: Write tests first, implement models to pass.
"""

from datetime import UTC, datetime

import pytest
from starboard_core.domain.models.clarification import (
    AmbiguityScore,
    ClarificationOption,
    ClarificationRequest,
    ClarificationResponse,
    ClarificationType,
)


class TestClarificationType:
    """Test ClarificationType enum."""

    def test_enum_values(self):
        """Test all clarification types are defined."""
        assert ClarificationType.MISSING_PARAMETER.value == "missing_parameter"
        assert ClarificationType.AMBIGUOUS_ENTITY.value == "ambiguous_entity"
        assert ClarificationType.MULTIPLE_MATCHES.value == "multiple_matches"
        assert ClarificationType.INSUFFICIENT_CONTEXT.value == "insufficient_context"
        assert ClarificationType.UNCLEAR_INTENT.value == "unclear_intent"
        assert ClarificationType.VAGUE_REFERENCE.value == "vague_reference"

    def test_enum_from_string(self):
        """Test creating enum from string value."""
        assert (
            ClarificationType("missing_parameter")
            == ClarificationType.MISSING_PARAMETER
        )
        assert (
            ClarificationType("ambiguous_entity") == ClarificationType.AMBIGUOUS_ENTITY
        )


class TestClarificationOption:
    """Test ClarificationOption model."""

    def test_create_option(self):
        """Test creating a clarification option."""
        option = ClarificationOption(
            option_id="opt_1",
            display_text="prod-analytics (10 nodes)",
            value="cluster_123",
            is_recommended=True,
            metadata={"nodes": 10, "status": "running"},
        )

        assert option.option_id == "opt_1"
        assert option.display_text == "prod-analytics (10 nodes)"
        assert option.value == "cluster_123"
        assert option.is_recommended is True
        assert option.metadata == {"nodes": 10, "status": "running"}

    def test_option_defaults(self):
        """Test option default values."""
        option = ClarificationOption(
            option_id="opt_1",
            display_text="Option 1",
            value="value_1",
        )

        assert option.is_recommended is False
        assert option.metadata is None

    def test_option_immutability(self):
        """Test that options are immutable."""
        option = ClarificationOption(
            option_id="opt_1",
            display_text="Option 1",
            value="value_1",
        )

        with pytest.raises(Exception):  # dataclass frozen
            option.option_id = "opt_2"  # type: ignore

    def test_option_to_dict(self):
        """Test option serialization."""
        option = ClarificationOption(
            option_id="opt_1",
            display_text="prod-analytics",
            value="cluster_123",
            is_recommended=True,
            metadata={"nodes": 10},
        )

        data = option.to_dict()

        assert data == {
            "option_id": "opt_1",
            "display_text": "prod-analytics",
            "value": "cluster_123",
            "is_recommended": True,
            "metadata": {"nodes": 10},
        }

    def test_option_from_dict(self):
        """Test option deserialization."""
        data = {
            "option_id": "opt_1",
            "display_text": "prod-analytics",
            "value": "cluster_123",
            "is_recommended": True,
            "metadata": {"nodes": 10},
        }

        option = ClarificationOption.from_dict(data)

        assert option.option_id == "opt_1"
        assert option.display_text == "prod-analytics"
        assert option.value == "cluster_123"
        assert option.is_recommended is True
        assert option.metadata == {"nodes": 10}


class TestClarificationRequest:
    """Test ClarificationRequest model."""

    def test_create_request(self):
        """Test creating a clarification request."""
        now = datetime.now(UTC)
        request = ClarificationRequest(
            clarification_id="clar_123",
            conversation_id="conv_456",
            message_id="msg_789",
            clarification_type=ClarificationType.MISSING_PARAMETER,
            question="What warehouse size would you like?",
            options=None,
            allow_custom_response=True,
            is_required=True,
            default_value="Medium",
            created_at=now,
            resolved_at=None,
            resolution=None,
        )

        assert request.clarification_id == "clar_123"
        assert request.conversation_id == "conv_456"
        assert request.message_id == "msg_789"
        assert request.clarification_type == ClarificationType.MISSING_PARAMETER
        assert request.question == "What warehouse size would you like?"
        assert request.options is None
        assert request.allow_custom_response is True
        assert request.is_required is True
        assert request.default_value == "Medium"
        assert request.created_at == now
        assert request.resolved_at is None
        assert request.resolution is None

    def test_request_with_options(self):
        """Test request with multiple options."""
        options = (
            ClarificationOption("1", "Small", "small", False, None),
            ClarificationOption("2", "Medium", "medium", True, None),
            ClarificationOption("3", "Large", "large", False, None),
        )

        request = ClarificationRequest(
            clarification_id="clar_123",
            conversation_id="conv_456",
            message_id="msg_789",
            clarification_type=ClarificationType.MULTIPLE_MATCHES,
            question="Which warehouse?",
            options=options,
            allow_custom_response=False,
            is_required=True,
            default_value=None,
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolution=None,
        )

        assert len(request.options) == 3
        assert request.options[1].is_recommended is True
        assert request.allow_custom_response is False

    def test_request_immutability(self):
        """Test that requests are immutable."""
        request = ClarificationRequest(
            clarification_id="clar_123",
            conversation_id="conv_456",
            message_id="msg_789",
            clarification_type=ClarificationType.MISSING_PARAMETER,
            question="Test question?",
            options=None,
            allow_custom_response=True,
            is_required=True,
            default_value=None,
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolution=None,
        )

        with pytest.raises(Exception):  # dataclass frozen
            request.question = "New question?"  # type: ignore

    def test_request_to_dict(self):
        """Test request serialization."""
        now = datetime.now(UTC)
        options = (
            ClarificationOption("1", "Option 1", "value_1", False, None),
            ClarificationOption("2", "Option 2", "value_2", True, None),
        )

        request = ClarificationRequest(
            clarification_id="clar_123",
            conversation_id="conv_456",
            message_id="msg_789",
            clarification_type=ClarificationType.MULTIPLE_MATCHES,
            question="Which one?",
            options=options,
            allow_custom_response=True,
            is_required=True,
            default_value="value_2",
            created_at=now,
            resolved_at=None,
            resolution=None,
        )

        data = request.to_dict()

        assert data["clarification_id"] == "clar_123"
        assert data["clarification_type"] == "multiple_matches"
        assert data["question"] == "Which one?"
        assert len(data["options"]) == 2
        assert data["options"][0]["option_id"] == "1"
        assert data["default_value"] == "value_2"
        assert data["resolved_at"] is None

    def test_request_from_dict(self):
        """Test request deserialization."""
        now = datetime.now(UTC)
        data = {
            "clarification_id": "clar_123",
            "conversation_id": "conv_456",
            "message_id": "msg_789",
            "clarification_type": "missing_parameter",
            "question": "What size?",
            "options": None,
            "allow_custom_response": True,
            "is_required": True,
            "default_value": "Medium",
            "created_at": now.isoformat(),
            "resolved_at": None,
            "resolution": None,
        }

        request = ClarificationRequest.from_dict(data)

        assert request.clarification_id == "clar_123"
        assert request.clarification_type == ClarificationType.MISSING_PARAMETER
        assert request.question == "What size?"
        assert request.default_value == "Medium"


class TestClarificationResponse:
    """Test ClarificationResponse model."""

    def test_create_response_with_option(self):
        """Test creating response with selected option."""
        now = datetime.now(UTC)
        response = ClarificationResponse(
            clarification_id="clar_123",
            selected_option_id="opt_2",
            custom_response=None,
            confidence=1.0,
            resolved_entities={"cluster_id": "cluster_123"},
            timestamp=now,
        )

        assert response.clarification_id == "clar_123"
        assert response.selected_option_id == "opt_2"
        assert response.custom_response is None
        assert response.confidence == 1.0
        assert response.resolved_entities == {"cluster_id": "cluster_123"}
        assert response.timestamp == now

    def test_create_response_with_custom_text(self):
        """Test creating response with custom text."""
        now = datetime.now(UTC)
        response = ClarificationResponse(
            clarification_id="clar_123",
            selected_option_id=None,
            custom_response="my-custom-warehouse",
            confidence=0.8,
            resolved_entities={"warehouse_name": "my-custom-warehouse"},
            timestamp=now,
        )

        assert response.selected_option_id is None
        assert response.custom_response == "my-custom-warehouse"
        assert response.confidence == 0.8

    def test_response_immutability(self):
        """Test that responses are immutable."""
        response = ClarificationResponse(
            clarification_id="clar_123",
            selected_option_id="opt_1",
            custom_response=None,
            confidence=1.0,
            resolved_entities={},
            timestamp=datetime.now(UTC),
        )

        with pytest.raises(Exception):  # dataclass frozen
            response.confidence = 0.5  # type: ignore

    def test_response_to_dict(self):
        """Test response serialization."""
        now = datetime.now(UTC)
        response = ClarificationResponse(
            clarification_id="clar_123",
            selected_option_id="opt_2",
            custom_response=None,
            confidence=1.0,
            resolved_entities={"warehouse_size": "Medium"},
            timestamp=now,
        )

        data = response.to_dict()

        assert data["clarification_id"] == "clar_123"
        assert data["selected_option_id"] == "opt_2"
        assert data["custom_response"] is None
        assert data["confidence"] == 1.0
        assert data["resolved_entities"] == {"warehouse_size": "Medium"}

    def test_response_from_dict(self):
        """Test response deserialization."""
        now = datetime.now(UTC)
        data = {
            "clarification_id": "clar_123",
            "selected_option_id": "opt_1",
            "custom_response": None,
            "confidence": 1.0,
            "resolved_entities": {"cluster_id": "cluster_456"},
            "timestamp": now.isoformat(),
        }

        response = ClarificationResponse.from_dict(data)

        assert response.clarification_id == "clar_123"
        assert response.selected_option_id == "opt_1"
        assert response.resolved_entities == {"cluster_id": "cluster_456"}


class TestAmbiguityScore:
    """Test AmbiguityScore model."""

    def test_create_score(self):
        """Test creating an ambiguity score."""
        score = AmbiguityScore(
            query="create warehouse",
            overall_score=0.4,
            entity_clarity=1.0,
            parameter_completeness=0.3,
            intent_clarity=0.8,
            reference_resolution=1.0,
            ambiguous_entities=(),
            missing_parameters=("warehouse_name", "warehouse_size"),
            vague_references=(),
            requires_clarification=True,
        )

        assert score.query == "create warehouse"
        assert score.overall_score == 0.4
        assert score.parameter_completeness == 0.3
        assert len(score.missing_parameters) == 2
        assert "warehouse_name" in score.missing_parameters
        assert score.requires_clarification is True

    def test_score_clear_query(self):
        """Test score for clear query."""
        score = AmbiguityScore(
            query="create warehouse my-warehouse size Medium",
            overall_score=0.95,
            entity_clarity=1.0,
            parameter_completeness=1.0,
            intent_clarity=0.9,
            reference_resolution=1.0,
            ambiguous_entities=(),
            missing_parameters=(),
            vague_references=(),
            requires_clarification=False,
        )

        assert score.overall_score == 0.95
        assert score.requires_clarification is False
        assert len(score.missing_parameters) == 0

    def test_score_multiple_issues(self):
        """Test score with multiple ambiguity issues."""
        score = AmbiguityScore(
            query="check it",
            overall_score=0.2,
            entity_clarity=0.0,
            parameter_completeness=0.5,
            intent_clarity=0.3,
            reference_resolution=0.0,
            ambiguous_entities=("cluster",),
            missing_parameters=("cluster_id",),
            vague_references=("it",),
            requires_clarification=True,
        )

        assert score.overall_score == 0.2
        assert len(score.ambiguous_entities) == 1
        assert len(score.missing_parameters) == 1
        assert len(score.vague_references) == 1
        assert score.requires_clarification is True

    def test_score_immutability(self):
        """Test that scores are immutable."""
        score = AmbiguityScore(
            query="test query",
            overall_score=0.5,
            entity_clarity=0.5,
            parameter_completeness=0.5,
            intent_clarity=0.5,
            reference_resolution=0.5,
            ambiguous_entities=(),
            missing_parameters=(),
            vague_references=(),
            requires_clarification=True,
        )

        with pytest.raises(Exception):  # dataclass frozen
            score.overall_score = 0.8  # type: ignore

    def test_score_to_dict(self):
        """Test score serialization."""
        score = AmbiguityScore(
            query="optimize query",
            overall_score=0.6,
            entity_clarity=0.5,
            parameter_completeness=0.7,
            intent_clarity=0.8,
            reference_resolution=0.4,
            ambiguous_entities=("query",),
            missing_parameters=(),
            vague_references=(),
            requires_clarification=True,
        )

        data = score.to_dict()

        assert data["query"] == "optimize query"
        assert data["overall_score"] == 0.6
        assert data["entity_clarity"] == 0.5
        assert data["ambiguous_entities"] == ["query"]
        assert data["requires_clarification"] is True

    def test_score_from_dict(self):
        """Test score deserialization."""
        data = {
            "query": "test query",
            "overall_score": 0.5,
            "entity_clarity": 0.6,
            "parameter_completeness": 0.4,
            "intent_clarity": 0.5,
            "reference_resolution": 0.6,
            "ambiguous_entities": ["cluster"],
            "missing_parameters": ["cluster_id"],
            "vague_references": [],
            "requires_clarification": True,
        }

        score = AmbiguityScore.from_dict(data)

        assert score.query == "test query"
        assert score.overall_score == 0.5
        assert score.ambiguous_entities == ("cluster",)
        assert score.missing_parameters == ("cluster_id",)
        assert score.requires_clarification is True
