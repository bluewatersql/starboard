# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for recommendation models.

Tests cover:
- Action priority and category enums
- ActionCommand dataclass
- RecommendedAction dataclass with to_dict()
- Default values and optional fields
"""

from starboard_core.domain.models.recommendations import (
    ActionCategory,
    ActionCommand,
    ActionPriority,
    RecommendedAction,
)


class TestActionPriority:
    """Tests for ActionPriority enum."""

    def test_priority_values(self):
        """Test that all priority levels exist."""
        assert ActionPriority.LOW.value == "low"
        assert ActionPriority.MEDIUM.value == "medium"
        assert ActionPriority.HIGH.value == "high"

    def test_priority_from_value(self):
        """Test creating priority from value."""
        priority = ActionPriority("medium")
        assert priority == ActionPriority.MEDIUM


class TestActionCategory:
    """Tests for ActionCategory enum."""

    def test_category_values(self):
        """Test that all categories exist."""
        assert ActionCategory.TABLE_OPTIMIZATION.value == "table_optimization"
        assert ActionCategory.QUERY_REWRITE.value == "query_rewrite"
        assert ActionCategory.COMPUTE_CONFIG.value == "compute_config"
        assert ActionCategory.STATISTICS.value == "statistics"
        assert ActionCategory.BENCHMARK.value == "benchmark"
        assert ActionCategory.ANALYSIS.value == "analysis"

    def test_category_from_value(self):
        """Test creating category from value."""
        category = ActionCategory("query_rewrite")
        assert category == ActionCategory.QUERY_REWRITE


class TestActionCommand:
    """Tests for ActionCommand dataclass."""

    def test_valid_action_command(self):
        """Test creating valid ActionCommand."""
        command = ActionCommand(
            type="ANALYZE",
            target="my_catalog.my_schema.my_table",
            command="ANALYZE TABLE my_catalog.my_schema.my_table COMPUTE STATISTICS",
        )

        assert command.type == "ANALYZE"
        assert command.target == "my_catalog.my_schema.my_table"
        assert "ANALYZE TABLE" in command.command

    def test_action_command_fields_required(self):
        """Test that all fields are required."""
        # Should work
        cmd = ActionCommand(type="OPTIMIZE", target="table", command="OPTIMIZE table")
        assert cmd.type == "OPTIMIZE"


class TestRecommendedAction:
    """Tests for RecommendedAction dataclass."""

    def test_valid_recommended_action(self):
        """Test creating valid RecommendedAction with all fields."""
        action = RecommendedAction(
            action_id="analyze_table_001",
            title="Analyze table statistics",
            description="Update table statistics for better query planning",
            category=ActionCategory.STATISTICS,
            priority=ActionPriority.HIGH,
            commands=[
                ActionCommand(
                    type="ANALYZE", target="table", command="ANALYZE TABLE table"
                )
            ],
            context={"table_name": "table", "catalog": "main"},
            estimated_impact={"query_time_improvement": 0.30},
        )

        assert action.action_id == "analyze_table_001"
        assert action.title == "Analyze table statistics"
        assert action.priority == ActionPriority.HIGH
        assert len(action.commands) == 1
        assert action.context["table_name"] == "table"
        assert action.estimated_impact["query_time_improvement"] == 0.30

    def test_recommended_action_defaults(self):
        """Test RecommendedAction default values."""
        action = RecommendedAction(
            action_id="test_001", title="Test action", description="Test description"
        )

        assert action.category == ActionCategory.ANALYSIS
        assert action.priority == ActionPriority.MEDIUM
        assert action.commands is None
        assert action.context == {}
        assert action.estimated_impact is None

    def test_recommended_action_to_dict(self):
        """Test RecommendedAction to_dict() method."""
        action = RecommendedAction(
            action_id="test_001",
            title="Test action",
            description="Description",
            category=ActionCategory.QUERY_REWRITE,
            priority=ActionPriority.LOW,
            commands=[
                ActionCommand(
                    type="SELECT", target="query", command="SELECT * FROM table"
                )
            ],
            context={"key": "value"},
            estimated_impact={"speedup": 1.5},
        )

        result = action.to_dict()

        assert result["action_id"] == "test_001"
        assert result["title"] == "Test action"
        assert result["category"] == "query_rewrite"
        assert result["priority"] == "low"
        assert len(result["commands"]) == 1
        assert result["commands"][0]["type"] == "SELECT"
        assert result["context"] == {"key": "value"}
        assert result["estimated_impact"] == {"speedup": 1.5}

    def test_recommended_action_to_dict_no_commands(self):
        """Test to_dict() when commands is None."""
        action = RecommendedAction(
            action_id="test", title="Test", description="Test", commands=None
        )

        result = action.to_dict()

        assert result["commands"] is None

    def test_recommended_action_to_dict_no_impact(self):
        """Test to_dict() when estimated_impact is None."""
        action = RecommendedAction(
            action_id="test",
            title="Test",
            description="Test",
            estimated_impact=None,
        )

        result = action.to_dict()

        assert result["estimated_impact"] is None

    def test_recommended_action_multiple_commands(self):
        """Test action with multiple commands."""
        action = RecommendedAction(
            action_id="multi_cmd",
            title="Multi-step action",
            description="Multiple commands",
            commands=[
                ActionCommand(type="ANALYZE", target="t1", command="ANALYZE TABLE t1"),
                ActionCommand(
                    type="OPTIMIZE", target="t1", command="OPTIMIZE TABLE t1"
                ),
                ActionCommand(type="VACUUM", target="t1", command="VACUUM TABLE t1"),
            ],
        )

        assert len(action.commands) == 3
        assert action.commands[0].type == "ANALYZE"
        assert action.commands[1].type == "OPTIMIZE"
        assert action.commands[2].type == "VACUUM"

        result = action.to_dict()
        assert len(result["commands"]) == 3
