"""Workflow models for declarative workflow definitions.

This module provides the core data structures for defining workflows:
- WorkflowStep: A single step in a workflow
- Workflow: A collection of steps with dependencies

Workflows are defined declaratively and can be executed by the WorkflowEngine.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowStep:
    """Single step in a workflow.

    A step defines a tool to execute with its parameters. Steps can depend on
    other steps and can resolve parameters dynamically from workflow context.

    Attributes:
        step_id: Unique identifier for this step within the workflow.
        tool_name: Name of the tool to execute.
        parameters: Static dict or callable that receives context and returns params.
        depends_on: Tuple of step IDs that must complete before this step.
        required: If True, step failure aborts the workflow.
        fallback_value: Value to use if step fails and is not required.
        result_key: Key to store result in context. Defaults to step_id.

    Example:
        ```python
        # Static parameters
        step = WorkflowStep(
            step_id="fetch",
            tool_name="fetch_data",
            parameters={"warehouse_id": "wh-123"},
        )

        # Dynamic parameters from context
        step = WorkflowStep(
            step_id="process",
            tool_name="process_data",
            parameters=lambda ctx: {"data": ctx["fetch"]},
            depends_on=("fetch",),
        )
        ```
    """

    step_id: str
    tool_name: str
    parameters: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]

    # Dependency management
    depends_on: tuple[str, ...] = ()

    # Error handling
    required: bool = True
    fallback_value: Any = None

    # Result handling
    result_key: str | None = None

    def resolve_parameters(self, context: dict[str, Any]) -> dict[str, Any]:
        """Resolve parameters, potentially using context from previous steps.

        Args:
            context: Current workflow context with results from completed steps.

        Returns:
            Resolved parameters dictionary.
        """
        if callable(self.parameters):
            return self.parameters(context)
        return self.parameters


@dataclass(frozen=True)
class Workflow:
    """Declarative workflow definition.

    A workflow is a collection of steps with optional dependencies. The workflow
    engine uses topological sort to determine execution order and runs independent
    steps in parallel.

    Attributes:
        workflow_id: Unique identifier for this workflow.
        name: Human-readable name.
        description: Description of what the workflow does.
        steps: Tuple of workflow steps.
        aggregator: Optional function to aggregate results from all steps.

    Example:
        ```python
        workflow = Workflow(
            workflow_id="portfolio_analysis",
            name="Portfolio Analysis",
            description="Analyze all warehouses in parallel",
            steps=(
                WorkflowStep(step_id="list", tool_name="list_warehouses", parameters={}),
                WorkflowStep(
                    step_id="fetch_a",
                    tool_name="fetch_config",
                    parameters={"id": "wh-a"},
                ),
                WorkflowStep(
                    step_id="fetch_b",
                    tool_name="fetch_config",
                    parameters={"id": "wh-b"},
                ),
                WorkflowStep(
                    step_id="analyze",
                    tool_name="analyze",
                    parameters=lambda ctx: {"configs": [ctx["fetch_a"], ctx["fetch_b"]]},
                    depends_on=("fetch_a", "fetch_b"),
                ),
            ),
        )
        ```
    """

    workflow_id: str
    name: str
    description: str
    steps: tuple[WorkflowStep, ...]

    # Aggregation
    aggregator: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def get_execution_order(self) -> list[list[str]]:
        """Return steps grouped by execution tier (parallel within tier).

        Uses Kahn's algorithm for topological sort. Steps in the same tier
        have no dependencies on each other and can be executed in parallel.

        Returns:
            List of tiers, where each tier is a list of step IDs that can
            run in parallel.

        Raises:
            ValueError: If there's a cyclic dependency or missing dependency.

        Example:
            ```python
            # Given: a -> b -> c (sequential)
            tiers = workflow.get_execution_order()
            # Returns: [["a"], ["b"], ["c"]]

            # Given: a, b, c (all parallel)
            tiers = workflow.get_execution_order()
            # Returns: [["a", "b", "c"]]
            ```
        """
        return self._topological_sort()

    def _topological_sort(self) -> list[list[str]]:
        """Group steps into parallel execution tiers using Kahn's algorithm.

        Returns:
            List of tiers with step IDs.

        Raises:
            ValueError: On cyclic or missing dependencies.
        """
        if not self.steps:
            return []

        # Build step lookup
        step_map = {step.step_id: step for step in self.steps}

        # Validate dependencies exist
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_map:
                    raise ValueError(
                        f"Unknown dependency '{dep}' in step '{step.step_id}'"
                    )

        # Build adjacency list and in-degree count
        # in_degree[step_id] = number of steps that step depends on
        in_degree: dict[str, int] = {
            step.step_id: len(step.depends_on) for step in self.steps
        }

        # dependents[step_id] = steps that depend on this step
        dependents: dict[str, list[str]] = defaultdict(list)
        for step in self.steps:
            for dep in step.depends_on:
                dependents[dep].append(step.step_id)

        # Initialize queue with steps that have no dependencies
        queue: deque[str] = deque(
            step_id for step_id, degree in in_degree.items() if degree == 0
        )

        tiers: list[list[str]] = []
        processed_count = 0

        while queue:
            # Current tier: all items currently in queue
            current_tier = list(queue)
            queue.clear()
            tiers.append(current_tier)
            processed_count += len(current_tier)

            # Process each step in current tier
            for step_id in current_tier:
                # Reduce in-degree for all dependents
                for dependent in dependents[step_id]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        # Check for cycle: if we didn't process all steps, there's a cycle
        if processed_count != len(self.steps):
            raise ValueError(
                "Cyclic dependency detected in workflow. "
                "Check step dependencies for circular references."
            )

        return tiers
