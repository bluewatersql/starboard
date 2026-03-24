"""Pre-built workflow patterns.

This module provides factory functions for creating common workflow patterns:
- Fan-out: Execute the same tool for multiple items in parallel
- Pipeline: Execute tools sequentially in a chain
- Map-Reduce: Fan-out to process items, then reduce results

These patterns simplify common use cases and ensure correct dependency setup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starboard_server.infra.orchestration.workflow import Workflow, WorkflowStep


def _default_list_aggregator(results: dict[str, Any]) -> dict[str, Any]:
    """Default aggregator that returns results as a list.

    Args:
        results: Dictionary of step results.

    Returns:
        Dictionary with results as a list under 'items' key.
    """
    return {"items": list(results.values())}


def create_fanout_workflow(
    workflow_id: str,
    items: list[str],
    tool_name: str,
    item_param_name: str,
    aggregator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Workflow:
    """Create a fan-out workflow that applies the same tool to multiple items.

    All items are processed in parallel with no dependencies between them.

    Args:
        workflow_id: Unique identifier for the workflow.
        items: List of items to process.
        tool_name: Name of the tool to execute for each item.
        item_param_name: Parameter name for the item value.
        aggregator: Optional function to aggregate results.

    Returns:
        Workflow configured for fan-out execution.

    Example:
        ```python
        # Fetch configs for all warehouses in parallel
        workflow = create_fanout_workflow(
            workflow_id="fetch_all_configs",
            items=["wh-1", "wh-2", "wh-3"],
            tool_name="fetch_warehouse_config",
            item_param_name="warehouse_id",
        )
        ```
    """
    steps = tuple(
        WorkflowStep(
            step_id=f"{tool_name}_{i}",
            tool_name=tool_name,
            parameters={item_param_name: item},
            result_key=f"result_{item}",
        )
        for i, item in enumerate(items)
    )

    return Workflow(
        workflow_id=workflow_id,
        name=f"Fanout {tool_name}",
        description=f"Execute {tool_name} for {len(items)} items in parallel",
        steps=steps,
        aggregator=aggregator or _default_list_aggregator,
    )


def create_pipeline_workflow(
    workflow_id: str,
    steps: list[tuple[str, str, dict[str, Any]]],
) -> Workflow:
    """Create a sequential pipeline workflow.

    Steps are executed one after another, with each step depending on the previous.

    Args:
        workflow_id: Unique identifier for the workflow.
        steps: List of (step_id, tool_name, parameters) tuples.

    Returns:
        Workflow configured for sequential execution.

    Example:
        ```python
        # ETL pipeline
        workflow = create_pipeline_workflow(
            workflow_id="etl",
            steps=[
                ("fetch", "fetch_data", {"source": "db"}),
                ("transform", "transform_data", {"format": "json"}),
                ("load", "load_data", {"target": "warehouse"}),
            ],
        )
        ```
    """
    workflow_steps = []
    for i, (step_id, tool_name, params) in enumerate(steps):
        depends_on = (steps[i - 1][0],) if i > 0 else ()
        workflow_steps.append(
            WorkflowStep(
                step_id=step_id,
                tool_name=tool_name,
                parameters=params,
                depends_on=depends_on,
                result_key=step_id,
            )
        )

    return Workflow(
        workflow_id=workflow_id,
        name=f"Pipeline {workflow_id}",
        description=f"Sequential pipeline with {len(steps)} steps",
        steps=tuple(workflow_steps),
    )


def create_map_reduce_workflow(
    workflow_id: str,
    map_items: list[str],
    map_tool: str,
    map_param_name: str,
    reduce_tool: str,
    reduce_param_name: str,
) -> Workflow:
    """Create a map-reduce workflow.

    Map phase processes items in parallel, then reduce phase combines results.

    Args:
        workflow_id: Unique identifier for the workflow.
        map_items: Items to process in the map phase.
        map_tool: Tool to execute for each item.
        map_param_name: Parameter name for the item in map tool.
        reduce_tool: Tool to execute in reduce phase.
        reduce_param_name: Parameter name for the collected results.

    Returns:
        Workflow configured for map-reduce execution.

    Example:
        ```python
        # Fetch all fingerprints then analyze topology
        workflow = create_map_reduce_workflow(
            workflow_id="topology_analysis",
            map_items=["wh-1", "wh-2", "wh-3"],
            map_tool="fetch_fingerprint",
            map_param_name="warehouse_id",
            reduce_tool="analyze_topology",
            reduce_param_name="fingerprints",
        )
        ```
    """
    # Map steps (parallel)
    map_steps = [
        WorkflowStep(
            step_id=f"map_{i}",
            tool_name=map_tool,
            parameters={map_param_name: item},
            result_key=f"map_result_{item}",
        )
        for i, item in enumerate(map_items)
    ]

    # Create a closure to capture map_items for the reduce step
    def make_reduce_params(
        items_to_reduce: list[str],
        param_name: str,
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        """Create a parameter resolver for the reduce step."""

        def resolver(ctx: dict[str, Any]) -> dict[str, Any]:
            return {
                param_name: [
                    ctx.get(f"map_result_{item}")
                    for item in items_to_reduce
                    if ctx.get(f"map_result_{item}") is not None
                ]
            }

        return resolver

    # Reduce step (depends on all map steps)
    reduce_step = WorkflowStep(
        step_id="reduce",
        tool_name=reduce_tool,
        parameters=make_reduce_params(map_items, reduce_param_name),
        depends_on=tuple(s.step_id for s in map_steps),
        result_key="final_result",
    )

    return Workflow(
        workflow_id=workflow_id,
        name=f"MapReduce {workflow_id}",
        description=f"Map {len(map_items)} items then reduce",
        steps=tuple(map_steps) + (reduce_step,),
    )
