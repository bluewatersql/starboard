# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for MessageProcessor with clarification pattern (Phase 7).

Tests the full integration of:
- MessageProcessor
- ClarificationManager
- AmbiguityDetector
- QuestionGenerator
- ToolRegistry

These tests verify the complete clarification flow from ambiguous query
to clarification request generation.
"""

from typing import Any

import pytest
from starboard.agents.tools.tool_registry import ToolMetadata, ToolRegistry
from starboard.services.clarification.clarification_manager import (
    ClarificationManager,
)
from starboard.services.messaging.message_processor import (
    MessageProcessor,
    ProcessingType,
)


class MockToolAdapter:
    """Mock tool adapter for testing."""

    def __init__(self, metadata: ToolMetadata):
        self.metadata = metadata

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Mock execute method."""
        return {"status": "success"}


@pytest.fixture
def tool_registry():
    """Create tool registry with realistic Databricks tools."""
    registry = ToolRegistry()

    # Register create_warehouse tool (requires name and size)
    create_wh_metadata = ToolMetadata(
        name="create_warehouse",
        description="Create a new SQL warehouse for query execution",
        parameters={
            "type": "object",
            "properties": {
                "warehouse_name": {
                    "type": "string",
                    "description": "Name for the warehouse",
                },
                "warehouse_size": {
                    "type": "string",
                    "description": "Size of the warehouse",
                    "enum": ["X-Small", "Small", "Medium", "Large", "X-Large"],
                },
                "cluster_size": {
                    "type": "string",
                    "description": "Number of workers (optional)",
                },
            },
            "required": ["warehouse_name", "warehouse_size"],
        },
    )
    registry.register("create_warehouse", MockToolAdapter(create_wh_metadata))

    # Register list_warehouses tool (no required params)
    list_wh_metadata = ToolMetadata(
        name="list_warehouses",
        description="List all SQL warehouses",
        parameters={
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status (optional)",
                },
            },
            "required": [],
        },
    )
    registry.register("list_warehouses", MockToolAdapter(list_wh_metadata))

    # Register create_cluster tool (requires name and size)
    create_cluster_metadata = ToolMetadata(
        name="create_cluster",
        description="Create a new cluster",
        parameters={
            "type": "object",
            "properties": {
                "cluster_name": {"type": "string"},
                "cluster_size": {"type": "string"},
                "spark_version": {"type": "string"},
            },
            "required": ["cluster_name", "cluster_size"],
        },
    )
    registry.register("create_cluster", MockToolAdapter(create_cluster_metadata))

    return registry


@pytest.fixture
def clarification_manager(tool_registry):
    """Create clarification manager with tool registry."""
    return ClarificationManager(tool_registry=tool_registry)


@pytest.fixture
def message_processor_with_clarification(clarification_manager):
    """Create message processor with clarification enabled."""
    return MessageProcessor(
        classify_intent=False,  # Don't need intent classification for these tests
        routing_engine=None,
        handoff_manager=None,
        clarification_manager=clarification_manager,
        enable_clarification=True,
    )


@pytest.fixture
def message_processor_without_clarification():
    """Create message processor with clarification disabled."""
    return MessageProcessor(
        classify_intent=False,
        routing_engine=None,
        handoff_manager=None,
        clarification_manager=None,
        enable_clarification=False,
    )


class TestClarificationIntegrationBasics:
    """Test basic clarification integration with MessageProcessor."""

    async def test_ambiguous_query_triggers_clarification(
        self, message_processor_with_clarification
    ):
        """Test that an ambiguous query triggers clarification request."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert result.processing_type == ProcessingType.CLARIFICATION_NEEDED
        assert result.clarification_request is not None
        assert result.confidence == 1.0  # High confidence that clarification is needed

        # Check clarification request details
        clarification = result.clarification_request
        assert clarification.conversation_id == "conv_123"
        assert clarification.message_id == "msg_456"
        assert clarification.question is not None
        assert len(clarification.question) > 0
        assert "warehouse" in clarification.question.lower()

    async def test_clear_query_bypasses_clarification(
        self, message_processor_with_clarification
    ):
        """Test that a clear query with all parameters bypasses clarification."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse my-warehouse size Medium",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Should NOT trigger clarification
        assert result.processing_type != ProcessingType.CLARIFICATION_NEEDED
        assert result.clarification_request is None

        # Should process as free text (or intent classification if enabled)
        assert result.processing_type == ProcessingType.FREE_TEXT

    async def test_partial_query_triggers_clarification(
        self, message_processor_with_clarification
    ):
        """Test that a partially complete query triggers clarification."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse my-warehouse",  # Missing size
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert result.processing_type == ProcessingType.CLARIFICATION_NEEDED
        assert result.clarification_request is not None

        # Question should mention the missing parameter
        assert "size" in result.clarification_request.question.lower()

    async def test_tool_with_no_required_params_no_clarification(
        self, message_processor_with_clarification
    ):
        """Test that tools with no required params don't trigger clarification."""
        result = await message_processor_with_clarification.process_message(
            user_input="list warehouses",
            available_options=None,
            target_tool="list_warehouses",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Should NOT trigger clarification (no required params)
        assert result.processing_type != ProcessingType.CLARIFICATION_NEEDED
        assert result.clarification_request is None


class TestClarificationFeatureFlag:
    """Test feature flag for enabling/disabling clarification."""

    async def test_clarification_disabled_by_flag(
        self, message_processor_without_clarification
    ):
        """Test that clarification can be disabled via feature flag."""
        result = await message_processor_without_clarification.process_message(
            user_input="create warehouse",  # Ambiguous
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Should NOT trigger clarification (flag disabled)
        assert result.processing_type != ProcessingType.CLARIFICATION_NEEDED
        assert result.clarification_request is None

        # Should process as free text
        assert result.processing_type == ProcessingType.FREE_TEXT

    async def test_clarification_disabled_when_manager_is_none(
        self, message_processor_without_clarification
    ):
        """Test graceful handling when clarification_manager is None."""
        # Create processor with manager=None but enable_clarification=True
        processor = MessageProcessor(
            clarification_manager=None,  # No manager
            enable_clarification=True,  # But flag is on
        )

        result = await processor.process_message(
            user_input="create warehouse",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Should gracefully skip clarification
        assert result.clarification_request is None


class TestClarificationWithOptions:
    """Test clarification request with predefined options."""

    async def test_clarification_includes_warehouse_size_options(
        self, message_processor_with_clarification
    ):
        """Test that warehouse_size parameter gets predefined options."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse my-wh",  # Missing size
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert result.clarification_request is not None
        clarification = result.clarification_request

        # Should have options for warehouse_size
        assert clarification.options is not None
        assert len(clarification.options) > 0

        # Check option format
        first_option = clarification.options[0]
        assert first_option.option_id is not None
        assert first_option.display_text is not None
        assert first_option.value is not None

        # At least one option should be recommended
        has_recommended = any(opt.is_recommended for opt in clarification.options)
        assert has_recommended

    async def test_clarification_for_cluster_size(
        self, message_processor_with_clarification
    ):
        """Test clarification for cluster creation."""
        result = await message_processor_with_clarification.process_message(
            user_input="create cluster",
            available_options=None,
            target_tool="create_cluster",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert result.processing_type == ProcessingType.CLARIFICATION_NEEDED
        assert result.clarification_request is not None


class TestClarificationWithoutTargetTool:
    """Test behavior when target_tool is not provided."""

    async def test_no_clarification_without_target_tool(
        self, message_processor_with_clarification
    ):
        """Test that clarification is skipped if target_tool is not provided."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse",
            available_options=None,
            target_tool=None,  # No target tool specified
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Should not trigger clarification without target tool
        assert result.clarification_request is None


class TestClarificationRequestMetadata:
    """Test clarification request metadata and tracking."""

    async def test_clarification_has_unique_id(
        self, message_processor_with_clarification
    ):
        """Test that each clarification request has a unique ID."""
        result1 = await message_processor_with_clarification.process_message(
            user_input="create warehouse",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        result2 = await message_processor_with_clarification.process_message(
            user_input="create warehouse",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_789",  # Different message
        )

        assert result1.clarification_request is not None
        assert result2.clarification_request is not None

        # IDs should be different
        assert (
            result1.clarification_request.clarification_id
            != result2.clarification_request.clarification_id
        )

    async def test_clarification_has_timestamp(
        self, message_processor_with_clarification
    ):
        """Test that clarification requests include timestamps."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert result.clarification_request is not None
        clarification = result.clarification_request

        assert clarification.created_at is not None
        assert clarification.resolved_at is None  # Not yet resolved
        assert clarification.resolution is None

    async def test_clarification_tracks_conversation_and_message(
        self, message_processor_with_clarification
    ):
        """Test that clarification tracks conversation and message IDs."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_abc",
            message_id="msg_xyz",
        )

        assert result.clarification_request is not None
        clarification = result.clarification_request

        assert clarification.conversation_id == "conv_abc"
        assert clarification.message_id == "msg_xyz"


class TestBackwardCompatibility:
    """Test backward compatibility with existing flows."""

    async def test_option_selection_takes_precedence(
        self, message_processor_with_clarification
    ):
        """Test that option selection is processed before clarification."""
        from starboard.domain.models.conversation_patterns import (
            ActionType,
            NextStepOption,
        )

        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Create warehouse",
                description="Create a new warehouse",
                action_type=ActionType.TOOL_CALL,
                target_agent=None,
                tool_name="create_warehouse",
                parameters={"warehouse_name": "test", "warehouse_size": "Medium"},
            ),
        )

        result = await message_processor_with_clarification.process_message(
            user_input="1",  # Selecting option
            available_options=options,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Should select the option, NOT trigger clarification
        assert result.processing_type == ProcessingType.OPTION_SELECTED
        assert result.clarification_request is None
        assert result.selected_option is not None

    async def test_free_text_without_target_tool(
        self, message_processor_with_clarification
    ):
        """Test free text processing when no target tool is identified."""
        result = await message_processor_with_clarification.process_message(
            user_input="What can you help me with?",
            available_options=None,
            target_tool=None,  # No target tool yet
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Should process as free text (intent classification would happen here)
        assert result.processing_type == ProcessingType.FREE_TEXT
        assert result.clarification_request is None


class TestMultipleParameterClarification:
    """Test clarification when multiple parameters are missing."""

    async def test_clarification_mentions_multiple_parameters(
        self, message_processor_with_clarification
    ):
        """Test that clarification mentions all missing parameters."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse",  # Missing both name and size
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert result.clarification_request is not None
        question = result.clarification_request.question.lower()

        # Question should mention parameters (name and/or size)
        assert "warehouse" in question or "name" in question or "size" in question

    async def test_clarification_for_one_missing_of_many(
        self, message_processor_with_clarification
    ):
        """Test clarification when only one of multiple params is missing."""
        result = await message_processor_with_clarification.process_message(
            user_input="create warehouse test-wh",  # Has name, missing size
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert result.processing_type == ProcessingType.CLARIFICATION_NEEDED
        assert result.clarification_request is not None

        # Should ask about the missing parameter (size)
        question = result.clarification_request.question.lower()
        assert "size" in question


class TestEdgeCases:
    """Test edge cases and error handling."""

    async def test_empty_query_string(self, message_processor_with_clarification):
        """Test handling of empty query string."""
        result = await message_processor_with_clarification.process_message(
            user_input="",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Empty query should trigger clarification (all params missing)
        assert result.processing_type == ProcessingType.CLARIFICATION_NEEDED
        assert result.clarification_request is not None

    async def test_whitespace_only_query(self, message_processor_with_clarification):
        """Test handling of whitespace-only query."""
        result = await message_processor_with_clarification.process_message(
            user_input="   ",
            available_options=None,
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Whitespace should be treated as empty (all params missing)
        assert result.processing_type == ProcessingType.CLARIFICATION_NEEDED

    async def test_unknown_tool_name(self, message_processor_with_clarification):
        """Test graceful handling of unknown tool name."""
        result = await message_processor_with_clarification.process_message(
            user_input="do something",
            available_options=None,
            target_tool="nonexistent_tool",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Should not crash, should skip clarification for unknown tool
        assert result.clarification_request is None
