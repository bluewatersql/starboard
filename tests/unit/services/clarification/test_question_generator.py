"""Unit tests for QuestionGenerator service (Phase 7).

Tests cover:
- Question generation for missing parameters
- Option formatting
- Default value suggestions
- Multiple parameter handling
- Progressive disclosure

Following TDD approach: Write tests first, implement service to pass.
"""

from datetime import UTC, datetime

import pytest
from starboard_core.domain.models.clarification import (
    ClarificationOption,
    ClarificationRequest,
    ClarificationType,
)
from starboard_server.services.clarification.question_generator import QuestionGenerator


class TestQuestionGeneratorMissingParameters:
    """Test question generation for missing parameters."""

    @pytest.fixture
    def generator(self):
        """Create question generator."""
        return QuestionGenerator()

    def test_generate_single_parameter_question(self, generator):
        """Test generating question for single missing parameter."""
        question = generator.generate_missing_parameter_question(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_name"],
            tool_name="create_warehouse",
        )

        assert question.clarification_type == ClarificationType.MISSING_PARAMETER
        assert question.conversation_id == "conv_123"
        assert question.message_id == "msg_456"
        # Should use friendly name "warehouse name" not "warehouse_name"
        assert "warehouse" in question.question.lower()
        assert "name" in question.question.lower()
        assert question.allow_custom_response is True
        assert question.is_required is True

    def test_generate_multiple_parameters_question(self, generator):
        """Test generating question for multiple missing parameters."""
        question = generator.generate_missing_parameter_question(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_name", "warehouse_size"],
            tool_name="create_warehouse",
        )

        assert question.clarification_type == ClarificationType.MISSING_PARAMETER
        # Question should mention both parameters (with friendly names)
        assert "warehouse" in question.question.lower()
        assert "name" in question.question.lower()
        assert "size" in question.question.lower()

    def test_generate_question_with_friendly_names(self, generator):
        """Test that questions use friendly parameter names."""
        question = generator.generate_missing_parameter_question(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_name"],
            tool_name="create_warehouse",
        )

        # Should use "warehouse name" not "warehouse_name"
        assert (
            "warehouse name" in question.question.lower()
            or "name" in question.question.lower()
        )

    def test_generate_question_includes_tool_context(self, generator):
        """Test that questions include tool context."""
        question = generator.generate_missing_parameter_question(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_name"],
            tool_name="create_warehouse",
        )

        # Should mention what we're trying to do
        assert (
            "warehouse" in question.question.lower()
            or "create" in question.question.lower()
        )


class TestQuestionGeneratorOptions:
    """Test option generation and formatting."""

    @pytest.fixture
    def generator(self):
        """Create question generator."""
        return QuestionGenerator()

    def test_generate_options_for_warehouse_size(self, generator):
        """Test generating size options for warehouse."""
        options = generator.generate_parameter_options(
            parameter_name="warehouse_size",
            tool_name="create_warehouse",
        )

        assert len(options) > 0
        assert isinstance(options[0], ClarificationOption)

        # Check for common sizes
        option_values = [opt.value.lower() for opt in options]
        assert any("small" in val for val in option_values)
        assert any("medium" in val for val in option_values)

    def test_options_have_display_text(self, generator):
        """Test that options have clear display text."""
        options = generator.generate_parameter_options(
            parameter_name="warehouse_size",
            tool_name="create_warehouse",
        )

        for option in options:
            assert option.display_text
            assert len(option.display_text) > 0

    def test_options_have_recommended_flag(self, generator):
        """Test that one option is recommended."""
        options = generator.generate_parameter_options(
            parameter_name="warehouse_size",
            tool_name="create_warehouse",
        )

        # At least one should be recommended
        recommended = [opt for opt in options if opt.is_recommended]
        assert len(recommended) >= 1

    def test_option_ids_are_sequential(self, generator):
        """Test that option IDs are numbered sequentially."""
        options = generator.generate_parameter_options(
            parameter_name="warehouse_size",
            tool_name="create_warehouse",
        )

        # Option IDs should be "1", "2", "3", etc.
        for idx, option in enumerate(options, 1):
            assert option.option_id == str(idx)

    def test_no_options_for_free_text_parameters(self, generator):
        """Test that name parameters don't get predefined options."""
        options = generator.generate_parameter_options(
            parameter_name="warehouse_name",
            tool_name="create_warehouse",
        )

        # Name should be free text, no predefined options
        assert len(options) == 0


class TestQuestionGeneratorFormatting:
    """Test question formatting."""

    @pytest.fixture
    def generator(self):
        """Create question generator."""
        return QuestionGenerator()

    def test_format_options_as_list(self, generator):
        """Test formatting options as numbered list."""
        options = [
            ClarificationOption("1", "Small (2 credits/hr)", "small", False, None),
            ClarificationOption("2", "Medium (4 credits/hr)", "medium", True, None),
            ClarificationOption("3", "Large (8 credits/hr)", "large", False, None),
        ]

        formatted = generator.format_options(options)

        assert "1" in formatted or "1." in formatted
        assert "Small" in formatted
        assert "Medium" in formatted
        assert "Large" in formatted

    def test_format_recommended_option(self, generator):
        """Test that recommended option is marked."""
        options = [
            ClarificationOption("1", "Small", "small", False, None),
            ClarificationOption("2", "Medium", "medium", True, None),
        ]

        formatted = generator.format_options(options)

        # Recommended option should have a marker
        assert (
            "recommended" in formatted.lower() or "⭐" in formatted or "*" in formatted
        )

    def test_format_friendly_parameter_name(self, generator):
        """Test converting parameter names to friendly text."""
        friendly = generator.format_parameter_name("warehouse_size")
        assert friendly == "warehouse size" or friendly == "Warehouse Size"

        friendly = generator.format_parameter_name("cluster_id")
        assert "cluster" in friendly.lower()


class TestQuestionGeneratorCompleteRequest:
    """Test generating complete clarification requests."""

    @pytest.fixture
    def generator(self):
        """Create question generator."""
        return QuestionGenerator()

    def test_generate_request_with_options(self, generator):
        """Test generating request with predefined options."""
        request = generator.generate_clarification_request(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_size"],
            tool_name="create_warehouse",
        )

        assert isinstance(request, ClarificationRequest)
        assert request.clarification_type == ClarificationType.MISSING_PARAMETER
        assert request.options is not None
        assert len(request.options) > 0
        assert request.allow_custom_response is True

    def test_generate_request_without_options(self, generator):
        """Test generating request for free-text parameter."""
        request = generator.generate_clarification_request(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_name"],
            tool_name="create_warehouse",
        )

        assert isinstance(request, ClarificationRequest)
        # Name parameters are free text
        assert request.options is None or len(request.options) == 0
        assert request.allow_custom_response is True

    def test_generate_request_has_unique_id(self, generator):
        """Test that each request has unique ID."""
        request1 = generator.generate_clarification_request(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_name"],
            tool_name="create_warehouse",
        )

        request2 = generator.generate_clarification_request(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_name"],
            tool_name="create_warehouse",
        )

        assert request1.clarification_id != request2.clarification_id

    def test_generate_request_has_timestamp(self, generator):
        """Test that requests include creation timestamp."""
        request = generator.generate_clarification_request(
            conversation_id="conv_123",
            message_id="msg_456",
            missing_parameters=["warehouse_name"],
            tool_name="create_warehouse",
        )

        assert request.created_at is not None
        # Should be recent (within last minute)
        now = datetime.now(UTC)
        delta = now - request.created_at
        assert delta.total_seconds() < 60
