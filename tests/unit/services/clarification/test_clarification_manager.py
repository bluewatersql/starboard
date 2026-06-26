# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for ClarificationManager service (Phase 7 - MVP Simplified).

Tests cover:
- Request clarification for ambiguous queries
- Skip clarification for clear queries
- Integration with AmbiguityDetector and QuestionGenerator

Following TDD approach: Write tests first, implement service to pass.
"""

from typing import Any

import pytest
from starboard_server.agents.tools.tool_registry import ToolMetadata, ToolRegistry
from starboard_server.services.clarification.clarification_manager import (
    ClarificationManager,
)


class MockToolAdapter:
    """Mock tool adapter for testing."""

    def __init__(self, metadata: ToolMetadata):
        self.metadata = metadata

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Mock execute method."""
        return {}


class TestClarificationManagerBasics:
    """Test basic clarification manager functionality."""

    @pytest.fixture
    def tool_registry(self):
        """Create tool registry with test tool."""
        registry = ToolRegistry()
        metadata = ToolMetadata(
            name="create_warehouse",
            description="Create a warehouse",
            parameters={
                "type": "object",
                "properties": {
                    "warehouse_name": {"type": "string"},
                    "warehouse_size": {"type": "string"},
                },
                "required": ["warehouse_name", "warehouse_size"],
            },
        )
        registry.register("create_warehouse", MockToolAdapter(metadata))
        return registry

    @pytest.fixture
    def manager(self, tool_registry):
        """Create clarification manager."""
        return ClarificationManager(tool_registry=tool_registry)

    def test_request_clarification_for_ambiguous_query(self, manager):
        """Test requesting clarification for ambiguous query."""
        clarification = manager.request_clarification(
            query="create warehouse",
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert clarification is not None
        assert clarification.conversation_id == "conv_123"
        assert clarification.message_id == "msg_456"
        assert clarification.question is not None
        assert len(clarification.question) > 0

    def test_no_clarification_for_clear_query(self, manager):
        """Test that clear queries don't need clarification."""
        clarification = manager.request_clarification(
            query="create warehouse my-warehouse size Medium",
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert clarification is None

    def test_clarification_includes_missing_parameters(self, manager):
        """Test that clarification mentions missing parameters."""
        clarification = manager.request_clarification(
            query="create warehouse",
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert clarification is not None
        # Question should mention parameters
        question_lower = clarification.question.lower()
        assert (
            "warehouse" in question_lower
            or "name" in question_lower
            or "size" in question_lower
        )

    def test_partial_query_needs_clarification(self, manager):
        """Test that partially complete queries need clarification."""
        clarification = manager.request_clarification(
            query="create warehouse my-warehouse",  # Missing size
            target_tool="create_warehouse",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert clarification is not None
        assert "size" in clarification.question.lower()


class TestClarificationManagerIntegration:
    """Test integration with detector and generator."""

    @pytest.fixture
    def tool_registry(self):
        """Create tool registry."""
        registry = ToolRegistry()
        metadata = ToolMetadata(
            name="test_tool",
            description="Test tool",
            parameters={
                "type": "object",
                "properties": {
                    "warehouse_size": {"type": "string"},
                },
                "required": ["warehouse_size"],
            },
        )
        registry.register("test_tool", MockToolAdapter(metadata))
        return registry

    @pytest.fixture
    def manager(self, tool_registry):
        """Create manager."""
        return ClarificationManager(tool_registry=tool_registry)

    def test_clarification_has_options_for_size_parameter(self, manager):
        """Test that size parameters get predefined options."""
        clarification = manager.request_clarification(
            query="test",
            target_tool="test_tool",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert clarification is not None
        assert clarification.options is not None
        assert len(clarification.options) > 0

    def test_clarification_has_unique_id(self, manager):
        """Test that each clarification has unique ID."""
        clarification1 = manager.request_clarification(
            query="test",
            target_tool="test_tool",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        clarification2 = manager.request_clarification(
            query="test",
            target_tool="test_tool",
            conversation_id="conv_123",
            message_id="msg_456",
        )

        assert clarification1 is not None
        assert clarification2 is not None
        assert clarification1.clarification_id != clarification2.clarification_id
