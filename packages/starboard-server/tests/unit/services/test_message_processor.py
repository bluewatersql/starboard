"""Unit tests for message processor service.

Tests message processing with option selection detection and handling.

Part of Phase 1: Foundation - Component 6
"""

import pytest
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)
from starboard_server.services.messaging.message_processor import (
    MessageProcessingResult,
    MessageProcessor,
    ProcessingType,
)


class TestMessageProcessorBasics:
    """Test basic message processor functionality."""

    def test_init_processor(self):
        """MessageProcessor can be initialized."""
        processor = MessageProcessor()
        assert processor is not None

    @pytest.mark.asyncio
    async def test_process_free_text_without_options(self):
        """Process free text when no options are available."""
        processor = MessageProcessor()

        result = await processor.process_message(
            user_input="Tell me about performance",
            available_options=None,
        )

        assert result.processing_type == ProcessingType.FREE_TEXT
        assert result.original_input == "Tell me about performance"
        assert result.selected_option is None


class TestOptionSelection:
    """Test option selection detection."""

    @pytest.fixture
    def sample_options(self) -> tuple[NextStepOption, ...]:
        """Create sample next step options."""
        return (
            NextStepOption(
                id="opt1",
                number=1,
                title="Optimize query",
                description="Rewrite query for better performance",
                action_type=ActionType.TOOL_CALL,
                target_agent=None,
                tool_name="optimize_query",
                parameters={"query_id": "123"},
            ),
            NextStepOption(
                id="opt2",
                number=2,
                title="Route to specialist",
                description=None,
                action_type=ActionType.ROUTE,
                target_agent="cost_analyzer",
                tool_name=None,
                parameters=None,
            ),
        )

    @pytest.mark.asyncio
    async def test_detect_numeric_selection(self, sample_options):
        """Detect when user selects an option by number."""
        processor = MessageProcessor()

        result = await processor.process_message(
            user_input="2",
            available_options=sample_options,
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.selected_option is not None
        assert result.selected_option.number == 2
        assert result.selected_option.action_type == ActionType.ROUTE
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_detect_word_form_selection(self, sample_options):
        """Detect when user selects using word form."""
        processor = MessageProcessor()

        result = await processor.process_message(
            user_input="one",
            available_options=sample_options,
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.selected_option.number == 1
        assert result.selected_option.action_type == ActionType.TOOL_CALL

    @pytest.mark.asyncio
    async def test_detect_keyword_selection(self, sample_options):
        """Detect when user uses keywords like 'option 2'."""
        processor = MessageProcessor()

        result = await processor.process_message(
            user_input="option 1",
            available_options=sample_options,
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.selected_option.number == 1
        assert result.confidence == 0.95  # Slightly lower than exact match

    @pytest.mark.asyncio
    async def test_free_text_with_options_available(self, sample_options):
        """Free text input when options are available."""
        processor = MessageProcessor()

        result = await processor.process_message(
            user_input="Tell me more about costs",
            available_options=sample_options,
        )

        assert result.processing_type == ProcessingType.FREE_TEXT
        assert result.selected_option is None
        assert result.confidence == 1.0


class TestActionExtraction:
    """Test extracting executable actions from option selections."""

    @pytest.mark.asyncio
    async def test_extract_tool_call_action(self):
        """Extract tool call action from selected option."""
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Analyze performance",
            description=None,
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="analyze_performance",
            parameters={"warehouse_id": "prod"},
        )

        processor = MessageProcessor()
        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.action_to_execute is not None
        assert result.action_to_execute["type"] == "tool_call"
        assert result.action_to_execute["tool_name"] == "analyze_performance"
        assert result.action_to_execute["parameters"] == {"warehouse_id": "prod"}

    @pytest.mark.asyncio
    async def test_extract_route_action(self):
        """Extract routing action from selected option."""
        option = NextStepOption(
            id="opt2",
            number=2,
            title="Route to specialist",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="cost_analyzer",
            tool_name=None,
            parameters={"context": "cost_analysis"},
        )

        processor = MessageProcessor()
        result = await processor.process_message(
            user_input="2",
            available_options=(option,),
        )

        assert result.action_to_execute is not None
        assert result.action_to_execute["type"] == "route"
        assert result.action_to_execute["target_agent"] == "cost_analyzer"
        assert result.action_to_execute["parameters"] == {"context": "cost_analysis"}

    @pytest.mark.asyncio
    async def test_extract_continue_action(self):
        """Extract continue action from selected option."""
        option = NextStepOption(
            id="opt3",
            number=3,
            title="Continue analysis",
            description=None,
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        processor = MessageProcessor()
        result = await processor.process_message(
            user_input="3",
            available_options=(option,),
        )

        assert result.action_to_execute is not None
        assert result.action_to_execute["type"] == "continue"


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Handle empty user input."""
        processor = MessageProcessor()

        result = await processor.process_message(
            user_input="",
            available_options=None,
        )

        assert result.processing_type == ProcessingType.FREE_TEXT
        assert result.original_input == ""

    @pytest.mark.asyncio
    async def test_whitespace_only_input(self):
        """Handle whitespace-only input."""
        processor = MessageProcessor()

        result = await processor.process_message(
            user_input="   ",
            available_options=None,
        )

        assert result.processing_type == ProcessingType.FREE_TEXT

    @pytest.mark.asyncio
    async def test_invalid_option_number(self):
        """Handle selection of non-existent option."""
        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Test",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        )

        processor = MessageProcessor()
        result = await processor.process_message(
            user_input="5",  # Option 5 doesn't exist
            available_options=options,
        )

        # Should be treated as free text
        assert result.processing_type == ProcessingType.FREE_TEXT

    @pytest.mark.asyncio
    async def test_empty_options_list(self):
        """Handle empty options list."""
        processor = MessageProcessor()

        result = await processor.process_message(
            user_input="1",
            available_options=(),  # Empty tuple
        )

        assert result.processing_type == ProcessingType.FREE_TEXT


class TestProcessingResult:
    """Test MessageProcessingResult model."""

    def test_result_immutability(self):
        """ProcessingResult should be immutable."""
        result = MessageProcessingResult(
            processing_type=ProcessingType.FREE_TEXT,
            original_input="test",
            selected_option=None,
            action_to_execute=None,
            confidence=1.0,
        )

        with pytest.raises(Exception):  # Frozen dataclass
            result.processing_type = ProcessingType.OPTION_SELECTED  # type: ignore

    def test_result_with_all_fields(self):
        """ProcessingResult with all fields populated."""
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Test",
            description=None,
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="test_tool",
            parameters={},
        )

        result = MessageProcessingResult(
            processing_type=ProcessingType.OPTION_SELECTED,
            original_input="1",
            selected_option=option,
            action_to_execute={"type": "tool_call", "tool_name": "test_tool"},
            confidence=1.0,
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.selected_option == option
        assert result.action_to_execute is not None
        assert result.confidence == 1.0


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    @pytest.mark.asyncio
    async def test_scenario_user_selects_optimization(self):
        """Scenario: User selects query optimization option."""
        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Optimize query execution plan",
                description="Analyze and rewrite query for better performance",
                action_type=ActionType.TOOL_CALL,
                target_agent=None,
                tool_name="optimize_query_plan",
                parameters={"query_id": "stmt_123", "mode": "aggressive"},
            ),
            NextStepOption(
                id="opt2",
                number=2,
                title="Analyze cost impact",
                description=None,
                action_type=ActionType.ROUTE,
                target_agent="cost_analyzer",
                tool_name=None,
                parameters=None,
            ),
        )

        processor = MessageProcessor()
        result = await processor.process_message(
            user_input="1",
            available_options=options,
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.selected_option.title == "Optimize query execution plan"
        assert result.action_to_execute["type"] == "tool_call"
        assert result.action_to_execute["tool_name"] == "optimize_query_plan"
        assert result.action_to_execute["parameters"]["query_id"] == "stmt_123"

    @pytest.mark.asyncio
    async def test_scenario_user_asks_followup_question(self):
        """Scenario: User ignores options and asks follow-up question."""
        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Continue",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        )

        processor = MessageProcessor()
        result = await processor.process_message(
            user_input="What about the morning slowdown issue?",
            available_options=options,
        )

        assert result.processing_type == ProcessingType.FREE_TEXT
        assert "morning slowdown" in result.original_input

    @pytest.mark.asyncio
    async def test_scenario_user_routes_to_different_agent(self):
        """Scenario: User selects routing to different specialist."""
        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Continue with current analysis",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
            NextStepOption(
                id="opt2",
                number=2,
                title="Analyze warehouse costs",
                description="Route to cost specialist",
                action_type=ActionType.ROUTE,
                target_agent="cost_analyzer",
                tool_name=None,
                parameters={"context": "warehouse_analysis"},
            ),
        )

        processor = MessageProcessor()
        result = await processor.process_message(
            user_input="two",  # Word form
            available_options=options,
        )

        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.action_to_execute["type"] == "route"
        assert result.action_to_execute["target_agent"] == "cost_analyzer"


class TestConfidenceLevels:
    """Test confidence levels for different match types."""

    @pytest.fixture
    def simple_option(self) -> tuple[NextStepOption, ...]:
        return (
            NextStepOption(
                id="opt1",
                number=1,
                title="Test",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        )

    @pytest.mark.asyncio
    async def test_exact_numeric_has_highest_confidence(self, simple_option):
        """Exact numeric match has confidence 1.0."""
        processor = MessageProcessor()
        result = await processor.process_message("1", simple_option)

        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_word_form_has_high_confidence(self, simple_option):
        """Word form match has confidence 1.0."""
        processor = MessageProcessor()
        result = await processor.process_message("one", simple_option)

        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_keyword_has_slightly_lower_confidence(self, simple_option):
        """Keyword match has slightly lower confidence."""
        processor = MessageProcessor()
        result = await processor.process_message("option 1", simple_option)

        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_free_text_has_full_confidence(self, simple_option):
        """Free text classification has confidence 1.0."""
        processor = MessageProcessor()
        result = await processor.process_message("tell me more", simple_option)

        assert result.confidence == 1.0
