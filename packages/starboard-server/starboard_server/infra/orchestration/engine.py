"""Workflow execution engine.

This module provides the WorkflowEngine class that executes workflows with
automatic parallelization based on step dependencies.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.orchestration.workflow import Workflow, WorkflowStep

logger = get_logger(__name__)


class ToolExecutionError(Exception):
    """Raised when a tool execution fails."""

    pass


class WorkflowStepError(Exception):
    """Raised when a required workflow step fails."""

    pass


class ToolResult(Protocol):
    """Protocol for tool execution results."""

    def is_error(self) -> bool:
        """Check if the result represents an error."""
        ...

    @property
    def content(self) -> Any:
        """Get the result content."""
        ...

    @property
    def error(self) -> str | None:
        """Get the error message if any."""
        ...


class ToolRegistry(Protocol):
    """Protocol for tool registries."""

    async def execute_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by name with the given parameters."""
        ...


class EventEmitter(Protocol):
    """Protocol for event emitters."""

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event."""
        ...


@dataclass
class WorkflowContext:
    """Mutable context passed through workflow execution.

    The context stores results from completed steps and any errors that occurred.
    Steps can read from the context to resolve dynamic parameters.

    Attributes:
        workflow_id: ID of the workflow being executed.
        results: Dictionary of step results keyed by result_key or step_id.
        errors: Dictionary of errors keyed by step_id.
        metadata: Additional metadata for the workflow execution.
    """

    workflow_id: str
    results: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from results.

        Args:
            key: The key to look up.
            default: Value to return if key is not found.

        Returns:
            The value for the key, or default if not found.
        """
        return self.results.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a value in results.

        Args:
            key: The key to set.
            value: The value to store.
        """
        self.results[key] = value

    def has_error(self, step_id: str) -> bool:
        """Check if a step had an error.

        Args:
            step_id: The step ID to check.

        Returns:
            True if the step had an error, False otherwise.
        """
        return step_id in self.errors


@dataclass(frozen=True)
class WorkflowResult:
    """Result of workflow execution.

    Attributes:
        workflow_id: ID of the executed workflow.
        success: Whether the workflow completed successfully.
        result: Final aggregated result (after aggregator if provided).
        step_results: Individual results from each step.
        errors: Any errors that occurred during execution.
    """

    workflow_id: str
    success: bool
    result: dict[str, Any] | None
    step_results: dict[str, Any]
    errors: dict[str, Exception]

    def get_step_result(self, step_id: str) -> Any:
        """Get the result of a specific step.

        Args:
            step_id: The step ID to get the result for.

        Returns:
            The step result, or None if not found.
        """
        return self.step_results.get(step_id)

    def has_partial_results(self) -> bool:
        """Check if there are partial results with some errors.

        Returns:
            True if there are both results and errors.
        """
        return bool(self.step_results) and bool(self.errors)


class WorkflowEngine:
    """Executes declarative workflows with parallel step execution.

    The engine analyzes step dependencies to determine which steps can run
    in parallel. Steps in the same tier (no dependencies between them) are
    executed concurrently using asyncio.gather.

    Attributes:
        tool_registry: Registry for looking up and executing tools.
        events: Optional event emitter for observability.
        max_parallel: Maximum number of concurrent step executions.

    Example:
        ```python
        engine = WorkflowEngine(tool_registry=registry, max_parallel=5)
        result = await engine.execute(workflow, initial_context={"key": "value"})
        if result.success:
            print(result.result)
        else:
            print(result.errors)
        ```
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        events: EventEmitter | None = None,
        max_parallel: int = 10,
    ) -> None:
        """Initialize the workflow engine.

        Args:
            tool_registry: Registry for executing tools.
            events: Optional event emitter for observability.
            max_parallel: Maximum concurrent step executions.
        """
        self.tool_registry = tool_registry
        self.events = events
        self.max_parallel = max_parallel

    async def execute(
        self,
        workflow: Workflow,
        initial_context: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Execute a workflow with automatic parallelization.

        Args:
            workflow: Workflow definition to execute.
            initial_context: Initial values for workflow context.

        Returns:
            WorkflowResult with aggregated results and any errors.
        """
        context = WorkflowContext(
            workflow_id=workflow.workflow_id,
            results=dict(initial_context) if initial_context else {},
        )

        self._emit_event("workflow_started", workflow.workflow_id)

        try:
            # Get execution tiers
            tiers = workflow.get_execution_order()

            for tier_idx, tier_step_ids in enumerate(tiers):
                logger.debug(
                    "executing_workflow_tier",
                    workflow_id=workflow.workflow_id,
                    tier=tier_idx,
                    steps=tier_step_ids,
                )

                # Execute all steps in this tier in parallel
                tier_steps = [s for s in workflow.steps if s.step_id in tier_step_ids]

                await self._execute_tier(tier_steps, context)

                # Check for required step failures
                for step in tier_steps:
                    if step.required and context.has_error(step.step_id):
                        raise WorkflowStepError(
                            f"Required step '{step.step_id}' failed: "
                            f"{context.errors[step.step_id]}"
                        )

            # Aggregate results
            final_result = context.results
            if workflow.aggregator:
                final_result = workflow.aggregator(context.results)

            self._emit_event("workflow_completed", workflow.workflow_id)

            return WorkflowResult(
                workflow_id=workflow.workflow_id,
                success=True,
                result=final_result,
                step_results=context.results,
                errors=context.errors,
            )

        except Exception as e:
            logger.error(
                "workflow_failed",
                workflow_id=workflow.workflow_id,
                error=str(e),
            )
            self._emit_event("workflow_failed", workflow.workflow_id, error=str(e))

            return WorkflowResult(
                workflow_id=workflow.workflow_id,
                success=False,
                result=None,
                step_results=context.results,
                errors={**context.errors, "_workflow": e},
            )

    async def _execute_tier(
        self,
        steps: list[WorkflowStep],
        context: WorkflowContext,
    ) -> None:
        """Execute a tier of steps in parallel.

        Args:
            steps: Steps to execute in this tier.
            context: Workflow context for reading/writing results.
        """

        async def execute_step(step: WorkflowStep) -> None:
            try:
                # Resolve parameters from context
                params = step.resolve_parameters(context.results)

                self._emit_event(
                    "step_started",
                    context.workflow_id,
                    step_id=step.step_id,
                )

                # Execute tool
                result = await self.tool_registry.execute_tool(
                    step.tool_name,
                    **params,
                )

                if result.is_error():
                    raise ToolExecutionError(result.error)

                # Store result
                key = step.result_key or step.step_id
                context.set(key, result.content)

                self._emit_event(
                    "step_completed",
                    context.workflow_id,
                    step_id=step.step_id,
                )

            except Exception as e:
                context.errors[step.step_id] = e

                if not step.required and step.fallback_value is not None:
                    key = step.result_key or step.step_id
                    context.set(key, step.fallback_value)

                self._emit_event(
                    "step_failed",
                    context.workflow_id,
                    step_id=step.step_id,
                    error=str(e),
                )

        # Execute all steps in parallel with semaphore for max concurrency
        sem = asyncio.Semaphore(self.max_parallel)

        async def bounded_execute(step: WorkflowStep) -> None:
            async with sem:
                await execute_step(step)

        await asyncio.gather(
            *[bounded_execute(step) for step in steps],
            return_exceptions=True,
        )

    def _emit_event(
        self,
        event_type: str,
        workflow_id: str,
        **kwargs: Any,
    ) -> None:
        """Emit workflow event for observability.

        Args:
            event_type: Type of event.
            workflow_id: ID of the workflow.
            **kwargs: Additional event data.
        """
        if self.events:
            self.events.emit(
                event_type,
                {"workflow_id": workflow_id, **kwargs},
            )
