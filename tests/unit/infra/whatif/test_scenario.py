# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for scenario models.

Tests cover:
- ScenarioParameter creation and change calculation
- Scenario creation and parameter access
- Scenario factory functions
"""

from __future__ import annotations

from starboard.infra.whatif.scenario import (
    Scenario,
    ScenarioParameter,
    create_warehouse_scenario,
)


class TestScenarioParameter:
    """Tests for ScenarioParameter model."""

    def test_create_parameter(self) -> None:
        """Test creating a scenario parameter."""
        param = ScenarioParameter(
            name="warehouse_type",
            current_value="standard",
            proposed_value="serverless",
        )

        assert param.name == "warehouse_type"
        assert param.current_value == "standard"
        assert param.proposed_value == "serverless"
        assert param.unit is None

    def test_create_parameter_with_unit(self) -> None:
        """Test creating a parameter with unit."""
        param = ScenarioParameter(
            name="auto_stop_mins",
            current_value=10,
            proposed_value=30,
            unit="minutes",
        )

        assert param.unit == "minutes"

    def test_change_pct_numeric_increase(self) -> None:
        """Test percentage change for numeric increase."""
        param = ScenarioParameter(
            name="min_clusters",
            current_value=2,
            proposed_value=4,
        )

        assert param.change_pct == 100.0  # 100% increase

    def test_change_pct_numeric_decrease(self) -> None:
        """Test percentage change for numeric decrease."""
        param = ScenarioParameter(
            name="max_clusters",
            current_value=10,
            proposed_value=5,
        )

        assert param.change_pct == -50.0  # 50% decrease

    def test_change_pct_zero_current(self) -> None:
        """Test percentage change when current value is zero."""
        param = ScenarioParameter(
            name="value",
            current_value=0,
            proposed_value=10,
        )

        assert param.change_pct is None  # Division by zero handled

    def test_change_pct_non_numeric(self) -> None:
        """Test percentage change for non-numeric values."""
        param = ScenarioParameter(
            name="type",
            current_value="standard",
            proposed_value="serverless",
        )

        assert param.change_pct is None


class TestScenario:
    """Tests for Scenario model."""

    def test_create_scenario(self) -> None:
        """Test creating a scenario."""
        scenario = Scenario(
            scenario_id="test-scenario",
            name="Test Scenario",
            description="A test scenario",
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(
                ScenarioParameter("type", "standard", "serverless"),
                ScenarioParameter("size", 2, 4),
            ),
        )

        assert scenario.scenario_id == "test-scenario"
        assert scenario.name == "Test Scenario"
        assert scenario.entity_type == "warehouse"
        assert scenario.entity_id == "wh-123"
        assert len(scenario.parameters) == 2

    def test_get_parameter(self) -> None:
        """Test getting a parameter by name."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test",
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(
                ScenarioParameter("type", "standard", "serverless"),
                ScenarioParameter("size", 2, 4),
            ),
        )

        param = scenario.get_parameter("size")
        assert param is not None
        assert param.proposed_value == 4

    def test_get_parameter_not_found(self) -> None:
        """Test getting a non-existent parameter."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test",
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(),
        )

        param = scenario.get_parameter("nonexistent")
        assert param is None

    def test_get_proposed_config(self) -> None:
        """Test getting proposed configuration as dict."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test",
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(
                ScenarioParameter("type", "standard", "serverless"),
                ScenarioParameter("min_size", 2, 1),
                ScenarioParameter("max_size", 4, 2),
            ),
        )

        config = scenario.get_proposed_config()

        assert config == {
            "type": "serverless",
            "min_size": 1,
            "max_size": 2,
        }

    def test_default_baseline_window(self) -> None:
        """Test default baseline window days."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test",
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(),
        )

        assert scenario.baseline_window_days == 30


class TestWarehouseScenarioFactory:
    """Tests for warehouse scenario factory."""

    def test_create_warehouse_scenario_type_change(self) -> None:
        """Test creating scenario with type change."""
        current_config = {
            "warehouse_type": "standard",
            "min_num_clusters": 2,
            "max_num_clusters": 4,
        }

        scenario = create_warehouse_scenario(
            scenario_id="to-serverless",
            warehouse_id="wh-123",
            current_config=current_config,
            new_warehouse_type="serverless",
        )

        assert scenario.entity_type == "warehouse"
        assert scenario.entity_id == "wh-123"

        type_param = scenario.get_parameter("warehouse_type")
        assert type_param is not None
        assert type_param.current_value == "standard"
        assert type_param.proposed_value == "serverless"

    def test_create_warehouse_scenario_sizing(self) -> None:
        """Test creating scenario with size changes."""
        current_config = {
            "warehouse_type": "standard",
            "min_num_clusters": 2,
            "max_num_clusters": 4,
        }

        scenario = create_warehouse_scenario(
            scenario_id="resize",
            warehouse_id="wh-123",
            current_config=current_config,
            new_min_size=1,
            new_max_size=2,
        )

        min_param = scenario.get_parameter("min_num_clusters")
        assert min_param is not None
        assert min_param.proposed_value == 1

        max_param = scenario.get_parameter("max_num_clusters")
        assert max_param is not None
        assert max_param.proposed_value == 2

    def test_create_warehouse_scenario_auto_stop(self) -> None:
        """Test creating scenario with auto-stop change."""
        current_config = {
            "auto_stop_mins": 10,
        }

        scenario = create_warehouse_scenario(
            scenario_id="longer-stop",
            warehouse_id="wh-123",
            current_config=current_config,
            new_auto_stop_minutes=30,
        )

        auto_stop_param = scenario.get_parameter("auto_stop_mins")
        assert auto_stop_param is not None
        assert auto_stop_param.proposed_value == 30
        assert auto_stop_param.unit == "minutes"

    def test_create_warehouse_scenario_no_changes(self) -> None:
        """Test creating scenario with no parameter changes."""
        scenario = create_warehouse_scenario(
            scenario_id="baseline",
            warehouse_id="wh-123",
            current_config={},
        )

        assert len(scenario.parameters) == 0
