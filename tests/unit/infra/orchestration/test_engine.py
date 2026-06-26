# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for workflow engine execution.

Tests cover:
- Sequential and parallel step execution
- Context passing between steps
- Error handling and graceful degradation
- Workflow result aggregation
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.infra.orchestration.engine import (
    WorkflowContext,
    WorkflowEngine,
    WorkflowResult,
)
from starboard_server.infra.orchestration.workflow import (
    Workflow,
    WorkflowStep,
)


class TestWorkflowContext:
    """Tests for WorkflowContext."""

    def test_create_context(self) -> None:
        """Test creating a workflow context."""
        context = WorkflowContext(workflow_id="test")

        assert context.workflow_id == "test"
        assert context.results == {}
        assert context.errors == {}
        assert context.metadata == {}

    def test_get_and_set(self) -> None:
        """Test getting and setting values."""
        context = WorkflowContext(workflow_id="test")

        context.set("key1", "value1")
        assert context.get("key1") == "value1"
        assert context.get("nonexistent") is None
        assert context.get("nonexistent", "default") == "default"

    def test_has_error(self) -> None:
        """Test checking for errors."""
        context = WorkflowContext(workflow_id="test")

        assert context.has_error("step1") is False

        context.errors["step1"] = ValueError("test error")
        assert context.has_error("step1") is True


class TestWorkflowResult:
    """Tests for WorkflowResult."""

    def test_successful_result(self) -> None:
        """Test successful workflow result."""
        result = WorkflowResult(
            workflow_id="test",
            success=True,
            result={"final": "output"},
            step_results={"step1": "result1", "step2": "result2"},
            errors={},
        )

        assert result.success is True
        assert result.get_step_result("step1") == "result1"
        assert result.has_partial_results() is False

    def test_failed_result_with_partial(self) -> None:
        """Test failed workflow with partial results."""
        result = WorkflowResult(
            workflow_id="test",
            success=False,
            result=None,
            step_results={"step1": "result1"},
            errors={"step2": ValueError("failed")},
        )

        assert result.success is False
        assert result.has_partial_results() is True


class TestWorkflowEngine:
    """Tests for WorkflowEngine."""

    @pytest.fixture
    def mock_tool_registry(self) -> MagicMock:
        """Create a mock tool registry."""
        registry = MagicMock()
        registry.execute_tool = AsyncMock()
        return registry

    @pytest.fixture
    def engine(self, mock_tool_registry: MagicMock) -> WorkflowEngine:
        """Create a workflow engine with mock registry."""
        return WorkflowEngine(tool_registry=mock_tool_registry)

    @pytest.mark.asyncio
    async def test_execute_empty_workflow(self, engine: WorkflowEngine) -> None:
        """Test executing an empty workflow."""
        workflow = Workflow(
            workflow_id="empty",
            name="Empty",
            description="No steps",
            steps=(),
        )

        result = await engine.execute(workflow)

        assert result.success is True
        assert result.result == {}

    @pytest.mark.asyncio
    async def test_execute_single_step(
        self,
        engine: WorkflowEngine,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test executing a single step workflow."""
        # Setup mock
        mock_result = MagicMock()
        mock_result.is_error.return_value = False
        mock_result.content = {"data": "test"}
        mock_tool_registry.execute_tool.return_value = mock_result

        workflow = Workflow(
            workflow_id="single",
            name="Single Step",
            description="One step",
            steps=(
                WorkflowStep(
                    step_id="step1",
                    tool_name="test_tool",
                    parameters={"param": "value"},
                    result_key="output",
                ),
            ),
        )

        result = await engine.execute(workflow)

        assert result.success is True
        assert result.step_results.get("output") == {"data": "test"}
        mock_tool_registry.execute_tool.assert_called_once_with(
            "test_tool",
            param="value",
        )

    @pytest.mark.asyncio
    async def test_execute_sequential_steps(
        self,
        engine: WorkflowEngine,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test executing sequential steps with context passing."""
        # Setup mock to return different results
        call_count = 0

        async def mock_execute(tool_name: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.is_error.return_value = False
            result.content = {"step": call_count, "tool": tool_name}
            return result

        mock_tool_registry.execute_tool.side_effect = mock_execute

        workflow = Workflow(
            workflow_id="sequential",
            name="Sequential",
            description="Two sequential steps",
            steps=(
                WorkflowStep(
                    step_id="step1",
                    tool_name="tool1",
                    parameters={"input": "initial"},
                    result_key="first_result",
                ),
                WorkflowStep(
                    step_id="step2",
                    tool_name="tool2",
                    parameters=lambda ctx: {"data": ctx.get("first_result")},
                    depends_on=("step1",),
                    result_key="second_result",
                ),
            ),
        )

        result = await engine.execute(workflow)

        assert result.success is True
        assert result.step_results.get("first_result") == {"step": 1, "tool": "tool1"}
        assert result.step_results.get("second_result") == {"step": 2, "tool": "tool2"}

    @pytest.mark.asyncio
    async def test_execute_parallel_steps(
        self,
        engine: WorkflowEngine,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test executing parallel steps."""

        # Setup mock
        async def mock_execute(tool_name: str, **kwargs: Any) -> MagicMock:
            result = MagicMock()
            result.is_error.return_value = False
            result.content = {"tool": tool_name}
            return result

        mock_tool_registry.execute_tool.side_effect = mock_execute

        workflow = Workflow(
            workflow_id="parallel",
            name="Parallel",
            description="Three parallel steps",
            steps=(
                WorkflowStep(
                    step_id="a", tool_name="tool_a", parameters={}, result_key="a"
                ),
                WorkflowStep(
                    step_id="b", tool_name="tool_b", parameters={}, result_key="b"
                ),
                WorkflowStep(
                    step_id="c", tool_name="tool_c", parameters={}, result_key="c"
                ),
            ),
        )

        result = await engine.execute(workflow)

        assert result.success is True
        assert result.step_results.get("a") == {"tool": "tool_a"}
        assert result.step_results.get("b") == {"tool": "tool_b"}
        assert result.step_results.get("c") == {"tool": "tool_c"}

    @pytest.mark.asyncio
    async def test_required_step_failure_aborts(
        self,
        engine: WorkflowEngine,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test that required step failure aborts the workflow."""
        # Setup mock to fail
        mock_result = MagicMock()
        mock_result.is_error.return_value = True
        mock_result.error = "Tool failed"
        mock_tool_registry.execute_tool.return_value = mock_result

        workflow = Workflow(
            workflow_id="failing",
            name="Failing",
            description="Step will fail",
            steps=(
                WorkflowStep(
                    step_id="step1",
                    tool_name="failing_tool",
                    parameters={},
                    required=True,
                ),
            ),
        )

        result = await engine.execute(workflow)

        assert result.success is False
        assert "step1" in result.errors

    @pytest.mark.asyncio
    async def test_optional_step_failure_continues(
        self,
        engine: WorkflowEngine,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test that optional step failure uses fallback and continues."""
        call_count = 0

        async def mock_execute(tool_name: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if tool_name == "failing_tool":
                result.is_error.return_value = True
                result.error = "Tool failed"
            else:
                result.is_error.return_value = False
                result.content = {"tool": tool_name}
            return result

        mock_tool_registry.execute_tool.side_effect = mock_execute

        workflow = Workflow(
            workflow_id="optional",
            name="Optional",
            description="Optional step fails but workflow continues",
            steps=(
                WorkflowStep(
                    step_id="optional_step",
                    tool_name="failing_tool",
                    parameters={},
                    required=False,
                    fallback_value={"fallback": True},
                    result_key="optional_result",
                ),
                WorkflowStep(
                    step_id="final_step",
                    tool_name="final_tool",
                    parameters={},
                    result_key="final_result",
                ),
            ),
        )

        result = await engine.execute(workflow)

        assert result.success is True
        assert result.step_results.get("optional_result") == {"fallback": True}
        assert result.step_results.get("final_result") == {"tool": "final_tool"}
        assert "optional_step" in result.errors

    @pytest.mark.asyncio
    async def test_aggregator_is_applied(
        self,
        engine: WorkflowEngine,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test that custom aggregator is applied to results."""
        mock_result = MagicMock()
        mock_result.is_error.return_value = False
        mock_result.content = {"data": 42}
        mock_tool_registry.execute_tool.return_value = mock_result

        def aggregator(results: dict) -> dict:
            return {"aggregated": sum(r.get("data", 0) for r in results.values())}

        workflow = Workflow(
            workflow_id="with_agg",
            name="With Aggregator",
            description="Has aggregator",
            steps=(
                WorkflowStep(
                    step_id="step1",
                    tool_name="tool1",
                    parameters={},
                    result_key="result1",
                ),
            ),
            aggregator=aggregator,
        )

        result = await engine.execute(workflow)

        assert result.success is True
        assert result.result == {"aggregated": 42}

    @pytest.mark.asyncio
    async def test_initial_context_is_passed(
        self,
        engine: WorkflowEngine,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test that initial context is available to steps."""
        captured_params: dict[str, Any] = {}

        async def mock_execute(tool_name: str, **kwargs: Any) -> MagicMock:
            captured_params.update(kwargs)
            result = MagicMock()
            result.is_error.return_value = False
            result.content = {}
            return result

        mock_tool_registry.execute_tool.side_effect = mock_execute

        workflow = Workflow(
            workflow_id="with_context",
            name="With Context",
            description="Uses initial context",
            steps=(
                WorkflowStep(
                    step_id="step1",
                    tool_name="tool1",
                    parameters=lambda ctx: {"warehouse_id": ctx.get("warehouse_id")},
                ),
            ),
        )

        await engine.execute(workflow, initial_context={"warehouse_id": "wh-123"})

        assert captured_params == {"warehouse_id": "wh-123"}

    @pytest.mark.asyncio
    async def test_step_result_key_defaults_to_step_id(
        self,
        engine: WorkflowEngine,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test that result_key defaults to step_id when not specified."""
        mock_result = MagicMock()
        mock_result.is_error.return_value = False
        mock_result.content = {"data": "test"}
        mock_tool_registry.execute_tool.return_value = mock_result

        workflow = Workflow(
            workflow_id="default_key",
            name="Default Key",
            description="No result_key specified",
            steps=(
                WorkflowStep(
                    step_id="my_step",
                    tool_name="tool1",
                    parameters={},
                    # result_key not specified
                ),
            ),
        )

        result = await engine.execute(workflow)

        assert result.step_results.get("my_step") == {"data": "test"}

    @pytest.mark.asyncio
    async def test_max_parallel_is_respected(
        self,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Test that max_parallel limit is respected."""
        concurrent_count = 0
        max_concurrent = 0

        async def mock_execute(tool_name: str, **kwargs: Any) -> MagicMock:
            nonlocal concurrent_count, max_concurrent
            import asyncio

            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.01)  # Small delay to allow concurrency
            concurrent_count -= 1

            result = MagicMock()
            result.is_error.return_value = False
            result.content = {}
            return result

        mock_tool_registry.execute_tool.side_effect = mock_execute

        engine = WorkflowEngine(tool_registry=mock_tool_registry, max_parallel=2)

        # Create 5 parallel steps
        steps = tuple(
            WorkflowStep(step_id=f"step{i}", tool_name=f"tool{i}", parameters={})
            for i in range(5)
        )

        workflow = Workflow(
            workflow_id="limited",
            name="Limited",
            description="Limited parallelism",
            steps=steps,
        )

        await engine.execute(workflow)

        assert max_concurrent <= 2
