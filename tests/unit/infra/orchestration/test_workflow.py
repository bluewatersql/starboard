"""Tests for workflow models and definitions.

Tests cover:
- WorkflowStep creation and parameter resolution
- Workflow definition and dependency management
- Topological sort for execution ordering
"""

from __future__ import annotations

import pytest
from starboard_server.infra.orchestration.workflow import (
    Workflow,
    WorkflowStep,
)


class TestWorkflowStep:
    """Tests for WorkflowStep model."""

    def test_create_step_with_static_parameters(self) -> None:
        """Test creating a step with static parameters."""
        step = WorkflowStep(
            step_id="fetch_data",
            tool_name="fetch_warehouse_config",
            parameters={"warehouse_id": "wh-123"},
        )

        assert step.step_id == "fetch_data"
        assert step.tool_name == "fetch_warehouse_config"
        assert step.parameters == {"warehouse_id": "wh-123"}
        assert step.depends_on == ()
        assert step.required is True
        assert step.fallback_value is None
        assert step.result_key is None

    def test_create_step_with_dependencies(self) -> None:
        """Test creating a step with dependencies."""
        step = WorkflowStep(
            step_id="calculate",
            tool_name="calculate_fingerprint",
            parameters={"data": "placeholder"},
            depends_on=("fetch_data", "fetch_metrics"),
        )

        assert step.depends_on == ("fetch_data", "fetch_metrics")

    def test_create_optional_step(self) -> None:
        """Test creating an optional step with fallback."""
        step = WorkflowStep(
            step_id="optional_check",
            tool_name="check_slo",
            parameters={},
            required=False,
            fallback_value={"slo_compliant": True},
        )

        assert step.required is False
        assert step.fallback_value == {"slo_compliant": True}

    def test_resolve_static_parameters(self) -> None:
        """Test resolving static parameters."""
        step = WorkflowStep(
            step_id="test",
            tool_name="test_tool",
            parameters={"key": "value"},
        )

        context = {"other": "data"}
        resolved = step.resolve_parameters(context)

        assert resolved == {"key": "value"}

    def test_resolve_dynamic_parameters(self) -> None:
        """Test resolving parameters from context."""
        step = WorkflowStep(
            step_id="calculate",
            tool_name="calculate_fingerprint",
            parameters=lambda ctx: {
                "warehouse_id": ctx["warehouse_id"],
                "data": ctx["fetch_data"],
            },
        )

        context = {
            "warehouse_id": "wh-123",
            "fetch_data": {"config": "test"},
        }
        resolved = step.resolve_parameters(context)

        assert resolved == {
            "warehouse_id": "wh-123",
            "data": {"config": "test"},
        }

    def test_result_key_defaults_to_none(self) -> None:
        """Test that result_key defaults to None."""
        step = WorkflowStep(
            step_id="test",
            tool_name="test_tool",
            parameters={},
        )

        assert step.result_key is None

    def test_result_key_can_be_set(self) -> None:
        """Test setting a custom result key."""
        step = WorkflowStep(
            step_id="fetch",
            tool_name="fetch_data",
            parameters={},
            result_key="warehouse_config",
        )

        assert step.result_key == "warehouse_config"


class TestWorkflow:
    """Tests for Workflow model."""

    def test_create_simple_workflow(self) -> None:
        """Test creating a simple workflow."""
        steps = (
            WorkflowStep(
                step_id="step1",
                tool_name="tool1",
                parameters={},
            ),
        )

        workflow = Workflow(
            workflow_id="test_workflow",
            name="Test Workflow",
            description="A test workflow",
            steps=steps,
        )

        assert workflow.workflow_id == "test_workflow"
        assert workflow.name == "Test Workflow"
        assert workflow.description == "A test workflow"
        assert len(workflow.steps) == 1

    def test_get_execution_order_no_dependencies(self) -> None:
        """Test execution order with no dependencies (all parallel)."""
        steps = (
            WorkflowStep(step_id="a", tool_name="tool_a", parameters={}),
            WorkflowStep(step_id="b", tool_name="tool_b", parameters={}),
            WorkflowStep(step_id="c", tool_name="tool_c", parameters={}),
        )

        workflow = Workflow(
            workflow_id="parallel_test",
            name="Parallel Test",
            description="All steps run in parallel",
            steps=steps,
        )

        tiers = workflow.get_execution_order()

        # All steps should be in the first tier (parallel)
        assert len(tiers) == 1
        assert set(tiers[0]) == {"a", "b", "c"}

    def test_get_execution_order_sequential(self) -> None:
        """Test execution order with sequential dependencies."""
        steps = (
            WorkflowStep(step_id="a", tool_name="tool_a", parameters={}),
            WorkflowStep(
                step_id="b", tool_name="tool_b", parameters={}, depends_on=("a",)
            ),
            WorkflowStep(
                step_id="c", tool_name="tool_c", parameters={}, depends_on=("b",)
            ),
        )

        workflow = Workflow(
            workflow_id="sequential_test",
            name="Sequential Test",
            description="Steps run one after another",
            steps=steps,
        )

        tiers = workflow.get_execution_order()

        # Three tiers: a -> b -> c
        assert len(tiers) == 3
        assert tiers[0] == ["a"]
        assert tiers[1] == ["b"]
        assert tiers[2] == ["c"]

    def test_get_execution_order_fan_out_fan_in(self) -> None:
        """Test fan-out / fan-in pattern."""
        steps = (
            WorkflowStep(step_id="start", tool_name="start", parameters={}),
            WorkflowStep(
                step_id="branch1",
                tool_name="branch1",
                parameters={},
                depends_on=("start",),
            ),
            WorkflowStep(
                step_id="branch2",
                tool_name="branch2",
                parameters={},
                depends_on=("start",),
            ),
            WorkflowStep(
                step_id="branch3",
                tool_name="branch3",
                parameters={},
                depends_on=("start",),
            ),
            WorkflowStep(
                step_id="end",
                tool_name="end",
                parameters={},
                depends_on=("branch1", "branch2", "branch3"),
            ),
        )

        workflow = Workflow(
            workflow_id="fanout_test",
            name="Fan-out Test",
            description="Fan out then fan in",
            steps=steps,
        )

        tiers = workflow.get_execution_order()

        # Three tiers: start -> [branch1, branch2, branch3] -> end
        assert len(tiers) == 3
        assert tiers[0] == ["start"]
        assert set(tiers[1]) == {"branch1", "branch2", "branch3"}
        assert tiers[2] == ["end"]

    def test_get_execution_order_complex_dag(self) -> None:
        """Test complex DAG with mixed dependencies."""
        # DAG:
        #   a
        #  / \
        # b   c
        #  \ / \
        #   d   e
        #    \ /
        #     f
        steps = (
            WorkflowStep(step_id="a", tool_name="a", parameters={}),
            WorkflowStep(step_id="b", tool_name="b", parameters={}, depends_on=("a",)),
            WorkflowStep(step_id="c", tool_name="c", parameters={}, depends_on=("a",)),
            WorkflowStep(
                step_id="d", tool_name="d", parameters={}, depends_on=("b", "c")
            ),
            WorkflowStep(step_id="e", tool_name="e", parameters={}, depends_on=("c",)),
            WorkflowStep(
                step_id="f", tool_name="f", parameters={}, depends_on=("d", "e")
            ),
        )

        workflow = Workflow(
            workflow_id="complex_dag",
            name="Complex DAG",
            description="Complex dependency graph",
            steps=steps,
        )

        tiers = workflow.get_execution_order()

        # Verify order respects dependencies
        step_tier_map = {}
        for tier_idx, tier in enumerate(tiers):
            for step_id in tier:
                step_tier_map[step_id] = tier_idx

        # a must come first
        assert step_tier_map["a"] == 0

        # b and c depend on a
        assert step_tier_map["b"] > step_tier_map["a"]
        assert step_tier_map["c"] > step_tier_map["a"]

        # d depends on b and c
        assert step_tier_map["d"] > step_tier_map["b"]
        assert step_tier_map["d"] > step_tier_map["c"]

        # e depends on c
        assert step_tier_map["e"] > step_tier_map["c"]

        # f depends on d and e
        assert step_tier_map["f"] > step_tier_map["d"]
        assert step_tier_map["f"] > step_tier_map["e"]

    def test_workflow_with_aggregator(self) -> None:
        """Test workflow with custom aggregator function."""

        def my_aggregator(results: dict) -> dict:
            return {"summary": list(results.values())}

        workflow = Workflow(
            workflow_id="with_agg",
            name="With Aggregator",
            description="Workflow with aggregator",
            steps=(),
            aggregator=my_aggregator,
        )

        assert workflow.aggregator is not None
        result = workflow.aggregator({"a": 1, "b": 2})
        assert result == {"summary": [1, 2]}

    def test_empty_workflow(self) -> None:
        """Test empty workflow returns empty tiers."""
        workflow = Workflow(
            workflow_id="empty",
            name="Empty",
            description="No steps",
            steps=(),
        )

        tiers = workflow.get_execution_order()
        assert tiers == []

    def test_cyclic_dependency_detection(self) -> None:
        """Test that cyclic dependencies raise an error."""
        steps = (
            WorkflowStep(step_id="a", tool_name="a", parameters={}, depends_on=("c",)),
            WorkflowStep(step_id="b", tool_name="b", parameters={}, depends_on=("a",)),
            WorkflowStep(step_id="c", tool_name="c", parameters={}, depends_on=("b",)),
        )

        workflow = Workflow(
            workflow_id="cyclic",
            name="Cyclic",
            description="Has cycle",
            steps=steps,
        )

        with pytest.raises(ValueError, match="[Cc]yclic"):
            workflow.get_execution_order()

    def test_missing_dependency_detection(self) -> None:
        """Test that missing dependencies raise an error."""
        steps = (
            WorkflowStep(
                step_id="a", tool_name="a", parameters={}, depends_on=("nonexistent",)
            ),
        )

        workflow = Workflow(
            workflow_id="missing_dep",
            name="Missing Dep",
            description="Has missing dependency",
            steps=steps,
        )

        with pytest.raises(ValueError, match="[Uu]nknown|[Mm]issing"):
            workflow.get_execution_order()
