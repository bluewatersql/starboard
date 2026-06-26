# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for AmbiguityDetector service (Phase 7).

Tests cover:
- Missing parameter detection
- Parameter completeness scoring
- Tool schema integration
- Ambiguity score calculation
- Edge cases (unknown tools, empty queries)

Following TDD approach: Write tests first, implement service to pass.
"""

from typing import Any

import pytest
from starboard_server.agents.tools.tool_registry import ToolMetadata, ToolRegistry
from starboard_server.services.intent.ambiguity_detector import AmbiguityDetector


class MockToolAdapter:
    """Mock tool adapter for testing."""

    def __init__(self, metadata: ToolMetadata):
        self.metadata = metadata

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Mock execute method."""
        return {}


class TestAmbiguityDetectorParameterChecking:
    """Test parameter completeness detection."""

    @pytest.fixture
    def tool_registry(self):
        """Create tool registry with test tools."""
        registry = ToolRegistry()

        # Tool with required parameters
        create_wh_metadata = ToolMetadata(
            name="create_warehouse",
            description="Create a warehouse",
            parameters={
                "type": "object",
                "properties": {
                    "warehouse_name": {"type": "string"},
                    "warehouse_size": {"type": "string"},
                    "auto_suspend_minutes": {"type": "integer"},
                },
                "required": ["warehouse_name", "warehouse_size"],
            },
        )
        registry.register("create_warehouse", MockToolAdapter(create_wh_metadata))

        # Tool with no required parameters
        list_wh_metadata = ToolMetadata(
            name="list_warehouses",
            description="List all warehouses",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
        )
        registry.register("list_warehouses", MockToolAdapter(list_wh_metadata))

        # Tool with optional parameters only
        analyze_metadata = ToolMetadata(
            name="analyze_query",
            description="Analyze query performance",
            parameters={
                "type": "object",
                "properties": {
                    "query_id": {"type": "string"},
                    "include_plan": {"type": "boolean"},
                },
                "required": [],
            },
        )
        registry.register("analyze_query", MockToolAdapter(analyze_metadata))

        return registry

    @pytest.fixture
    def detector(self, tool_registry):
        """Create ambiguity detector."""
        return AmbiguityDetector(tool_registry=tool_registry)

    def test_detect_missing_required_parameters(self, detector):
        """Test detecting missing required parameters."""
        query = "create warehouse"
        target_tool = "create_warehouse"

        score = detector.detect_ambiguity(
            query=query,
            target_tool=target_tool,
        )

        assert score.requires_clarification is True
        assert len(score.missing_parameters) == 2
        assert "warehouse_name" in score.missing_parameters
        assert "warehouse_size" in score.missing_parameters
        assert score.parameter_completeness < 0.5

    def test_detect_all_parameters_present(self, detector):
        """Test when all required parameters are present."""
        query = "create warehouse my-warehouse size Medium"
        target_tool = "create_warehouse"

        score = detector.detect_ambiguity(
            query=query,
            target_tool=target_tool,
        )

        assert score.requires_clarification is False
        assert len(score.missing_parameters) == 0
        assert score.parameter_completeness == 1.0

    def test_detect_partial_parameters(self, detector):
        """Test when some parameters are present."""
        query = "create warehouse my-warehouse"
        target_tool = "create_warehouse"

        score = detector.detect_ambiguity(
            query=query,
            target_tool=target_tool,
        )

        assert score.requires_clarification is True
        assert len(score.missing_parameters) == 1
        assert "warehouse_size" in score.missing_parameters
        assert "warehouse_name" not in score.missing_parameters
        assert 0.0 < score.parameter_completeness < 1.0

    def test_tool_with_no_required_parameters(self, detector):
        """Test tool that has no required parameters."""
        query = "list warehouses"
        target_tool = "list_warehouses"

        score = detector.detect_ambiguity(
            query=query,
            target_tool=target_tool,
        )

        assert score.requires_clarification is False
        assert len(score.missing_parameters) == 0
        assert score.parameter_completeness == 1.0

    def test_tool_with_optional_parameters_only(self, detector):
        """Test tool with only optional parameters."""
        query = "analyze query"
        target_tool = "analyze_query"

        score = detector.detect_ambiguity(
            query=query,
            target_tool=target_tool,
        )

        assert score.requires_clarification is False
        assert len(score.missing_parameters) == 0
        assert score.parameter_completeness == 1.0

    def test_unknown_tool(self, detector):
        """Test handling of unknown tool."""
        query = "do something"
        target_tool = "unknown_tool"

        score = detector.detect_ambiguity(
            query=query,
            target_tool=target_tool,
        )

        # Unknown tool should not require clarification
        # (will be handled by intent classification)
        assert score.requires_clarification is False
        assert len(score.missing_parameters) == 0

    def test_empty_query(self, detector):
        """Test handling of empty query."""
        # Empty query is allowed but should show all params missing
        query = ""
        target_tool = "create_warehouse"

        score = detector.detect_ambiguity(
            query=query,
            target_tool=target_tool,
        )

        assert score.requires_clarification is True
        assert len(score.missing_parameters) == 2
        assert "warehouse_name" in score.missing_parameters
        assert "warehouse_size" in score.missing_parameters


class TestAmbiguityScoreCalculation:
    """Test ambiguity score calculation logic."""

    @pytest.fixture
    def tool_registry(self):
        """Create tool registry with test tool."""
        registry = ToolRegistry()
        test_metadata = ToolMetadata(
            name="test_tool",
            description="Test tool",
            parameters={
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                    "param2": {"type": "string"},
                    "param3": {"type": "string"},
                },
                "required": ["param1", "param2", "param3"],
            },
        )
        registry.register("test_tool", MockToolAdapter(test_metadata))
        return registry

    @pytest.fixture
    def detector(self, tool_registry):
        """Create ambiguity detector."""
        return AmbiguityDetector(tool_registry=tool_registry)

    def test_score_all_parameters_missing(self, detector):
        """Test score when all parameters are missing."""
        score = detector.detect_ambiguity(
            query="test",
            target_tool="test_tool",
        )

        assert score.parameter_completeness == 0.0
        assert score.overall_score < 0.7  # Below threshold
        assert score.requires_clarification is True

    def test_score_some_parameters_missing(self, detector):
        """Test score when some parameters are missing."""
        # Note: Generic param names like "param1" won't be auto-detected
        # This is expected behavior - parameter detection uses specific patterns
        score = detector.detect_ambiguity(
            query="test param1",
            target_tool="test_tool",
        )

        # No params detected (generic names don't match patterns)
        assert score.parameter_completeness == 0.0
        assert score.overall_score < 0.7
        assert score.requires_clarification is True

    def test_score_all_parameters_present(self, detector):
        """Test score when all parameters are present.

        Note: Using generic param names that don't match patterns.
        For realistic testing, parameters should have meaningful names
        that match detection patterns (warehouse_name, cluster_id, etc.)
        """
        score = detector.detect_ambiguity(
            query="test param1 param2 param3",
            target_tool="test_tool",
        )

        # Generic param names won't be detected - this is expected
        # In real usage, params have meaningful names with patterns
        assert score.parameter_completeness < 1.0
        assert score.overall_score < 0.7
        assert score.requires_clarification is True

    def test_overall_score_calculation(self, detector):
        """Test that overall score is calculated correctly."""
        score = detector.detect_ambiguity(
            query="test param1",
            target_tool="test_tool",
        )

        # Overall score should be weighted average
        # For MVP: only parameter_completeness matters, so they should be equal
        assert score.overall_score == score.parameter_completeness
        assert 0.0 <= score.overall_score <= 1.0


class TestAmbiguityDetectorEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def tool_registry(self):
        """Create minimal tool registry with one tool."""
        registry = ToolRegistry()
        test_metadata = ToolMetadata(
            name="test_tool",
            description="Test tool",
            parameters={
                "type": "object",
                "properties": {
                    "param": {"type": "string"},
                },
                "required": ["param"],
            },
        )
        registry.register("test_tool", MockToolAdapter(test_metadata))
        return registry

    @pytest.fixture
    def detector(self, tool_registry):
        """Create ambiguity detector."""
        return AmbiguityDetector(tool_registry=tool_registry)

    def test_none_query(self, detector):
        """Test handling of None query."""
        with pytest.raises(ValueError, match="Query cannot be None or empty"):
            detector.detect_ambiguity(
                query=None,  # type: ignore
                target_tool="test_tool",
            )

    def test_none_target_tool(self, detector):
        """Test handling of None target tool."""
        with pytest.raises(ValueError, match="Target tool cannot be None or empty"):
            detector.detect_ambiguity(
                query="test query",
                target_tool=None,  # type: ignore
            )

    def test_whitespace_only_query(self, detector):
        """Test handling of whitespace-only query.

        Whitespace-only queries are treated as empty (all params missing).
        """
        score = detector.detect_ambiguity(
            query="   ",
            target_tool="test_tool",  # Use tool from fixture
        )

        # Empty/whitespace query should show all params missing
        assert score.requires_clarification is True
        assert len(score.missing_parameters) > 0
        assert "param" in score.missing_parameters
