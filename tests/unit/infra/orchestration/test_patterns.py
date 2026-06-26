# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for pre-built workflow patterns.

Tests cover:
- Fan-out pattern
- Pipeline pattern
- Map-reduce pattern
"""

from __future__ import annotations

from typing import Any

from starboard_server.infra.orchestration.patterns import (
    create_fanout_workflow,
    create_map_reduce_workflow,
    create_pipeline_workflow,
)


class TestFanoutPattern:
    """Tests for fan-out workflow pattern."""

    def test_create_fanout_workflow(self) -> None:
        """Test creating a fan-out workflow."""
        items = ["wh-1", "wh-2", "wh-3"]

        workflow = create_fanout_workflow(
            workflow_id="fetch_all_configs",
            items=items,
            tool_name="fetch_warehouse_config",
            item_param_name="warehouse_id",
        )

        assert workflow.workflow_id == "fetch_all_configs"
        assert len(workflow.steps) == 3

        # All steps should have no dependencies (parallel)
        for step in workflow.steps:
            assert step.depends_on == ()
            assert step.tool_name == "fetch_warehouse_config"

        # Each step should target different item
        param_values = {step.parameters["warehouse_id"] for step in workflow.steps}
        assert param_values == {"wh-1", "wh-2", "wh-3"}

    def test_fanout_with_custom_aggregator(self) -> None:
        """Test fan-out with custom aggregator function."""

        def custom_agg(results: dict[str, Any]) -> dict[str, Any]:
            return {"items": list(results.values())}

        workflow = create_fanout_workflow(
            workflow_id="with_agg",
            items=["a", "b"],
            tool_name="process",
            item_param_name="item",
            aggregator=custom_agg,
        )

        assert workflow.aggregator is not None
        result = workflow.aggregator({"result_a": 1, "result_b": 2})
        assert result == {"items": [1, 2]}

    def test_fanout_empty_items(self) -> None:
        """Test fan-out with empty items list."""
        workflow = create_fanout_workflow(
            workflow_id="empty",
            items=[],
            tool_name="tool",
            item_param_name="param",
        )

        assert len(workflow.steps) == 0

    def test_fanout_execution_order(self) -> None:
        """Test that fanout execution order has single tier."""
        workflow = create_fanout_workflow(
            workflow_id="parallel",
            items=["a", "b", "c"],
            tool_name="tool",
            item_param_name="item",
        )

        tiers = workflow.get_execution_order()

        # All items in single tier (parallel execution)
        assert len(tiers) == 1
        assert len(tiers[0]) == 3


class TestPipelinePattern:
    """Tests for pipeline workflow pattern."""

    def test_create_pipeline_workflow(self) -> None:
        """Test creating a pipeline workflow."""
        steps_config = [
            ("fetch", "fetch_data", {"source": "db"}),
            ("transform", "transform_data", {"format": "json"}),
            ("load", "load_data", {"target": "warehouse"}),
        ]

        workflow = create_pipeline_workflow(
            workflow_id="etl_pipeline",
            steps=steps_config,
        )

        assert workflow.workflow_id == "etl_pipeline"
        assert len(workflow.steps) == 3

        # Check dependencies form a chain
        assert workflow.steps[0].depends_on == ()
        assert workflow.steps[1].depends_on == ("fetch",)
        assert workflow.steps[2].depends_on == ("transform",)

    def test_pipeline_execution_order(self) -> None:
        """Test pipeline execution order is sequential."""
        steps_config = [
            ("a", "tool_a", {}),
            ("b", "tool_b", {}),
            ("c", "tool_c", {}),
        ]

        workflow = create_pipeline_workflow(
            workflow_id="sequential",
            steps=steps_config,
        )

        tiers = workflow.get_execution_order()

        # Should be 3 sequential tiers
        assert len(tiers) == 3
        assert tiers[0] == ["a"]
        assert tiers[1] == ["b"]
        assert tiers[2] == ["c"]

    def test_pipeline_single_step(self) -> None:
        """Test pipeline with single step."""
        workflow = create_pipeline_workflow(
            workflow_id="single",
            steps=[("only_step", "tool", {"param": "value"})],
        )

        assert len(workflow.steps) == 1
        assert workflow.steps[0].depends_on == ()

    def test_pipeline_empty(self) -> None:
        """Test pipeline with no steps."""
        workflow = create_pipeline_workflow(
            workflow_id="empty",
            steps=[],
        )

        assert len(workflow.steps) == 0


class TestMapReducePattern:
    """Tests for map-reduce workflow pattern."""

    def test_create_map_reduce_workflow(self) -> None:
        """Test creating a map-reduce workflow."""
        workflow = create_map_reduce_workflow(
            workflow_id="process_warehouses",
            map_items=["wh-1", "wh-2", "wh-3"],
            map_tool="fetch_fingerprint",
            map_param_name="warehouse_id",
            reduce_tool="analyze_topology",
            reduce_param_name="fingerprints",
        )

        assert workflow.workflow_id == "process_warehouses"
        # 3 map steps + 1 reduce step
        assert len(workflow.steps) == 4

        # Find the reduce step
        reduce_step = next(s for s in workflow.steps if s.step_id == "reduce")

        # Reduce should depend on all map steps
        assert len(reduce_step.depends_on) == 3
        map_step_ids = {s.step_id for s in workflow.steps if s.step_id != "reduce"}
        assert set(reduce_step.depends_on) == map_step_ids

    def test_map_reduce_execution_order(self) -> None:
        """Test map-reduce execution has two tiers."""
        workflow = create_map_reduce_workflow(
            workflow_id="mr",
            map_items=["a", "b", "c"],
            map_tool="map_tool",
            map_param_name="item",
            reduce_tool="reduce_tool",
            reduce_param_name="items",
        )

        tiers = workflow.get_execution_order()

        # Two tiers: all maps in parallel, then reduce
        assert len(tiers) == 2
        assert len(tiers[0]) == 3  # 3 map steps
        assert len(tiers[1]) == 1  # 1 reduce step
        assert "reduce" in tiers[1]

    def test_map_reduce_with_single_item(self) -> None:
        """Test map-reduce with single item."""
        workflow = create_map_reduce_workflow(
            workflow_id="single",
            map_items=["only"],
            map_tool="map",
            map_param_name="item",
            reduce_tool="reduce",
            reduce_param_name="items",
        )

        assert len(workflow.steps) == 2

    def test_map_reduce_empty_items(self) -> None:
        """Test map-reduce with empty items still has reduce step."""
        workflow = create_map_reduce_workflow(
            workflow_id="empty_map",
            map_items=[],
            map_tool="map",
            map_param_name="item",
            reduce_tool="reduce",
            reduce_param_name="items",
        )

        # Should still have reduce step
        assert len(workflow.steps) == 1
        assert workflow.steps[0].step_id == "reduce"
