"""Multi-tool orchestration framework.

This module provides a declarative workflow engine for coordinating multiple tool
executions in sequence or parallel. It supports:

- Declarative workflow definitions with dependency management
- Parallel execution with topological sort
- Pre-built patterns: fan-out, pipeline, map-reduce
- Observable with structured events
- Graceful degradation with optional steps and fallbacks

Example:
    ```python
    from starboard_server.infra.orchestration import (
        Workflow,
        WorkflowEngine,
        WorkflowStep,
        create_fanout_workflow,
    )

    # Create a simple workflow
    workflow = Workflow(
        workflow_id="my_workflow",
        name="My Workflow",
        description="Fetch and process data",
        steps=(
            WorkflowStep(
                step_id="fetch",
                tool_name="fetch_data",
                parameters={"source": "db"},
            ),
            WorkflowStep(
                step_id="process",
                tool_name="process_data",
                parameters=lambda ctx: {"data": ctx["fetch"]},
                depends_on=("fetch",),
            ),
        ),
    )

    # Execute workflow
    engine = WorkflowEngine(tool_registry=registry)
    result = await engine.execute(workflow)
    ```
"""

from starboard_server.infra.orchestration.engine import (
    ToolExecutionError,
    WorkflowContext,
    WorkflowEngine,
    WorkflowResult,
    WorkflowStepError,
)
from starboard_server.infra.orchestration.patterns import (
    create_fanout_workflow,
    create_map_reduce_workflow,
    create_pipeline_workflow,
)
from starboard_server.infra.orchestration.workflow import (
    Workflow,
    WorkflowStep,
)

__all__ = [
    # Models
    "Workflow",
    "WorkflowStep",
    # Engine
    "WorkflowContext",
    "WorkflowEngine",
    "WorkflowResult",
    # Errors
    "ToolExecutionError",
    "WorkflowStepError",
    # Patterns
    "create_fanout_workflow",
    "create_map_reduce_workflow",
    "create_pipeline_workflow",
]
