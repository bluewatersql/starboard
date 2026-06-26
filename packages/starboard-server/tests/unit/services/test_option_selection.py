# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for option selection processor.

Tests the service that determines whether user input is:
1. Selecting a numbered option (e.g., "2", "option 2", "two")
2. Free text input (new query)

Part of Pattern 1: Option Selection
"""

import pytest
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)
from starboard_server.services.clarification.option_selection import (
    OptionSelectionProcessor,
)


@pytest.fixture
def sample_options() -> tuple[NextStepOption, ...]:
    """Create sample options for testing."""
    return (
        NextStepOption(
            id="opt1",
            number=1,
            title="Optimize query execution plan",
            description="Rewrite query for better performance",
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="optimize_query",
            parameters={"mode": "aggressive"},
        ),
        NextStepOption(
            id="opt2",
            number=2,
            title="Analyze table statistics",
            description="Check if statistics are up to date",
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="analyze_stats",
            parameters=None,
        ),
        NextStepOption(
            id="opt3",
            number=3,
            title="Review warehouse configuration",
            description="Ensure warehouse is sized correctly",
            action_type=ActionType.ROUTE,
            target_agent="warehouse_config_agent",
            tool_name=None,
            parameters={"warehouse_id": "prod_dw"},
        ),
    )


@pytest.fixture
def processor() -> OptionSelectionProcessor:
    """Create processor instance."""
    return OptionSelectionProcessor()


class TestNumericSelection:
    """Test direct numeric selection."""

    def test_single_digit_selection(self, processor, sample_options):
        """Test selection with single digit like '2'."""
        result = processor.process("2", sample_options)

        assert result.selection_type == "option"
        assert result.selected_option is not None
        assert result.selected_option.number == 2
        assert result.selected_option.id == "opt2"
        assert result.confidence == 1.0
        assert result.original_input == "2"

    def test_selection_with_whitespace(self, processor, sample_options):
        """Test that whitespace is handled correctly."""
        result = processor.process("  3  ", sample_options)

        assert result.selection_type == "option"
        assert result.selected_option.number == 3
        assert result.confidence == 1.0

    def test_all_valid_numbers(self, processor):
        """Test all numbers 1-9 work correctly."""
        # Create options for all 9 numbers
        options = tuple(
            NextStepOption(
                id=f"opt{i}",
                number=i,
                title=f"Option {i}",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            )
            for i in range(1, 10)
        )

        for i in range(1, 10):
            result = processor.process(str(i), options)
            assert result.selection_type == "option"
            assert result.selected_option.number == i
            assert result.confidence == 1.0


class TestWordFormSelection:
    """Test word form number selection."""

    def test_word_form_numbers(self, processor, sample_options):
        """Test word forms like 'two', 'three'."""
        word_forms = {
            "one": 1,
            "two": 2,
            "three": 3,
        }

        for word, number in word_forms.items():
            result = processor.process(word, sample_options)
            assert result.selection_type == "option"
            assert result.selected_option.number == number
            assert result.confidence == 1.0

    def test_word_form_case_insensitive(self, processor, sample_options):
        """Test that word forms are case-insensitive."""
        for word in ["TWO", "Two", "tWo"]:
            result = processor.process(word, sample_options)
            assert result.selection_type == "option"
            assert result.selected_option.number == 2


class TestKeywordSelection:
    """Test selection with keywords like 'option 2'."""

    def test_option_keyword(self, processor, sample_options):
        """Test 'option 2' format."""
        result = processor.process("option 2", sample_options)

        assert result.selection_type == "option"
        assert result.selected_option.number == 2
        assert result.confidence == 0.95  # Slightly lower confidence

    def test_choice_keyword(self, processor, sample_options):
        """Test 'choice 3' format."""
        result = processor.process("choice 3", sample_options)

        assert result.selection_type == "option"
        assert result.selected_option.number == 3
        assert result.confidence == 0.95

    def test_select_keyword(self, processor, sample_options):
        """Test 'select 1' format."""
        result = processor.process("select 1", sample_options)

        assert result.selection_type == "option"
        assert result.selected_option.number == 1
        assert result.confidence == 0.95

    def test_keyword_with_word_form(self, processor, sample_options):
        """Test 'option two' format."""
        result = processor.process("option two", sample_options)

        assert result.selection_type == "option"
        assert result.selected_option.number == 2
        assert result.confidence == 0.95


class TestInvalidSelection:
    """Test invalid or out-of-range selections."""

    def test_number_too_high(self, processor, sample_options):
        """Test number greater than available options."""
        result = processor.process("5", sample_options)

        assert result.selection_type == "free_text"
        assert result.selected_option is None
        assert result.original_input == "5"

    def test_number_zero(self, processor, sample_options):
        """Test invalid number 0."""
        result = processor.process("0", sample_options)

        assert result.selection_type == "free_text"
        assert result.selected_option is None

    def test_negative_number(self, processor, sample_options):
        """Test negative number."""
        result = processor.process("-1", sample_options)

        assert result.selection_type == "free_text"
        assert result.selected_option is None

    def test_number_ten_or_higher(self, processor, sample_options):
        """Test numbers >= 10."""
        for num in ["10", "11", "99"]:
            result = processor.process(num, sample_options)
            assert result.selection_type == "free_text"
            assert result.selected_option is None


class TestFreeTextInput:
    """Test free text input (not selecting an option)."""

    def test_unrelated_question(self, processor, sample_options):
        """Test completely unrelated input."""
        result = processor.process("How do I scale my warehouse?", sample_options)

        assert result.selection_type == "free_text"
        assert result.selected_option is None
        assert result.confidence == 1.0
        assert result.original_input == "How do I scale my warehouse?"

    def test_long_sentence(self, processor, sample_options):
        """Test long sentence that's not a selection."""
        result = processor.process(
            "I need to understand how the query optimizer works in Databricks",
            sample_options,
        )

        assert result.selection_type == "free_text"
        assert result.selected_option is None

    def test_sentence_containing_number(self, processor, sample_options):
        """Test sentence that contains a number but isn't a selection."""
        result = processor.process("I have 2 warehouses running", sample_options)

        # Should be treated as free text since it's not just the number
        assert result.selection_type == "free_text"
        assert result.selected_option is None

    def test_empty_input(self, processor, sample_options):
        """Test empty string input."""
        result = processor.process("", sample_options)

        assert result.selection_type == "free_text"
        assert result.selected_option is None


class TestEmptyOptions:
    """Test behavior with no available options."""

    def test_empty_options_list(self, processor):
        """Test with empty options tuple."""
        result = processor.process("2", ())

        assert result.selection_type == "free_text"
        assert result.selected_option is None

    def test_any_input_with_no_options(self, processor):
        """Test various inputs with no options."""
        inputs = ["1", "option 2", "help", ""]

        for user_input in inputs:
            result = processor.process(user_input, ())
            assert result.selection_type == "free_text"
            assert result.selected_option is None


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_number_in_sentence_with_keyword(self, processor, sample_options):
        """Test 'I want option 2 please'."""
        result = processor.process("I want option 2 please", sample_options)

        # Should still match because keyword + number present
        assert result.selection_type == "option"
        assert result.selected_option.number == 2

    def test_multiple_numbers(self, processor, sample_options):
        """Test input with multiple numbers."""
        result = processor.process("1 and 2", sample_options)

        # Ambiguous - should be free text
        assert result.selection_type == "free_text"

    def test_special_characters(self, processor, sample_options):
        """Test input with special characters."""
        result = processor.process("#2", sample_options)

        # Should not match - treat as free text
        assert result.selection_type == "free_text"

    def test_unicode_numbers(self, processor, sample_options):
        """Test unicode number characters."""
        result = processor.process("②", sample_options)

        # Should not match unicode - treat as free text
        assert result.selection_type == "free_text"

    def test_confidence_values(self, processor, sample_options):
        """Test that confidence values are in valid range."""
        test_inputs = ["2", "option 2", "help me"]

        for user_input in test_inputs:
            result = processor.process(user_input, sample_options)
            assert 0.0 <= result.confidence <= 1.0


class TestOptionMatching:
    """Test that correct options are matched."""

    def test_match_returns_correct_option_object(self, processor, sample_options):
        """Test that the returned option is the actual option object."""
        result = processor.process("2", sample_options)

        # Verify it's the same option
        assert result.selected_option.id == "opt2"
        assert result.selected_option.title == "Analyze table statistics"
        assert result.selected_option.action_type == ActionType.TOOL_CALL
        assert result.selected_option.tool_name == "analyze_stats"

    def test_single_option_available(self, processor):
        """Test with only one option."""
        single_option = (
            NextStepOption(
                id="only",
                number=1,
                title="Only option",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        )

        result = processor.process("1", single_option)
        assert result.selection_type == "option"
        assert result.selected_option.id == "only"

        # Trying to select option 2 should fail
        result2 = processor.process("2", single_option)
        assert result2.selection_type == "free_text"


class TestOriginalInputPreservation:
    """Test that original input is always preserved."""

    def test_original_input_preserved_on_match(self, processor, sample_options):
        """Test original input is preserved when option matched."""
        result = processor.process("option 2", sample_options)
        assert result.original_input == "option 2"

    def test_original_input_preserved_on_free_text(self, processor, sample_options):
        """Test original input is preserved for free text."""
        original = "Tell me about warehouse scaling"
        result = processor.process(original, sample_options)
        assert result.original_input == original

    def test_whitespace_in_original_input(self, processor, sample_options):
        """Test that original input keeps whitespace."""
        result = processor.process("  2  ", sample_options)
        # Original should be trimmed during processing but stored
        assert result.original_input == "  2  "
