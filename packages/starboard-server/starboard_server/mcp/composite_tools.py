# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Composite MCP tools that chain quick-lookup tools without LLM calls.

Each composite orchestrates multiple tool calls and merges results into a
single response.  Partial failures are captured in ``CompositeResult``
rather than raising exceptions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


class ToolExecutor(Protocol):
    """Callback protocol for executing a single tool."""

    async def __call__(self, tool_name: str, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CompositeResult:
    """Result of a composite tool invocation.

    Attributes:
        data: Accumulated results keyed by step name.
        errors: Human-readable error messages for failed steps.
        partial: ``True`` when some (but not all) steps succeeded.
    """

    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    partial: bool = False

    @property
    def status(self) -> Literal["success", "partial", "error"]:
        """Derive overall status from data and errors."""
        if not self.errors:
            return "success"
        if self.data:
            return "partial"
        return "error"


# ---------------------------------------------------------------------------
# Tool metadata for MCP registration
# ---------------------------------------------------------------------------

COMPOSITE_TOOL_METADATA: list[dict[str, Any]] = [
    {
        "name": "get_job_summary",
        "description": (
            "Get comprehensive job overview: metadata, configuration, "
            "and latest run status in a single call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Job ID, name, or URL",
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Workspace ID (optional, uses default)",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "get_query_analysis",
        "description": (
            "Full query analysis: resolve SQL, runtime metrics, and "
            "execution plan analysis in one call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Statement ID or raw SQL text",
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Workspace ID (optional, uses default)",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "get_table_profile",
        "description": (
            "Table profile: metadata and recent history (last 5 operations)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Three-part table name (catalog.schema.table)",
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Workspace ID (optional, uses default)",
                },
            },
            "required": ["table"],
        },
    },
    {
        "name": "get_workspace_overview",
        "description": ("Workspace overview: clusters and SQL warehouses in parallel."),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Workspace ID (optional, uses default)",
                },
            },
            "required": [],
        },
    },
]


# Concurrency limiter for parallel composite steps
_SEMAPHORE = asyncio.Semaphore(5)


async def _guarded_call(
    executor: ToolExecutor, tool_name: str, **kwargs: Any
) -> dict[str, Any]:
    """Execute a tool call under the global concurrency semaphore."""
    async with _SEMAPHORE:
        return await executor(tool_name, **kwargs)


# ---------------------------------------------------------------------------
# Composite tool implementations
# ---------------------------------------------------------------------------


async def get_job_summary(
    executor: ToolExecutor,
    target: str,
) -> CompositeResult:
    """Resolve job → config → latest run status."""
    data: dict[str, Any] = {}
    errors: list[str] = []

    # Step 1: resolve_job (required)
    try:
        job = await _guarded_call(executor, "resolve_job", target=target)
        data["job"] = job
    except Exception as exc:
        return CompositeResult(errors=[f"resolve_job failed: {exc}"])

    job_id = job.get("job_id", target)

    # Step 2: get_job_config
    try:
        config = await _guarded_call(executor, "get_job_config", job_id=str(job_id))
        data["config"] = config
    except Exception as exc:
        errors.append(f"get_job_config failed: {exc}")

    return CompositeResult(data=data, errors=errors, partial=bool(errors))


async def get_query_analysis(
    executor: ToolExecutor,
    target: str,
) -> CompositeResult:
    """Resolve query → metrics → plan analysis."""
    data: dict[str, Any] = {}
    errors: list[str] = []

    # Step 1: resolve_query (required)
    try:
        query = await _guarded_call(executor, "resolve_query", target=target)
        data["query"] = query
    except Exception as exc:
        return CompositeResult(errors=[f"resolve_query failed: {exc}"])

    sql_text = query.get("sql_text", target)
    statement_id = query.get("statement_id")

    # Steps 2 & 3 can be concurrent
    async def _get_metrics() -> dict[str, Any] | None:
        if statement_id:
            try:
                return await _guarded_call(
                    executor,
                    "get_query_runtime_metrics",
                    statement_id=statement_id,
                )
            except Exception as exc:
                errors.append(f"get_query_runtime_metrics failed: {exc}")
        return None

    async def _get_plan() -> dict[str, Any] | None:
        try:
            return await _guarded_call(
                executor, "analyze_query_plan", sql_text=sql_text
            )
        except Exception as exc:
            errors.append(f"analyze_query_plan failed: {exc}")
        return None

    metrics_result, plan_result = await asyncio.gather(_get_metrics(), _get_plan())
    if metrics_result is not None:
        data["metrics"] = metrics_result
    if plan_result is not None:
        data["plan_analysis"] = plan_result

    return CompositeResult(data=data, errors=errors, partial=bool(errors))


async def get_table_profile(
    executor: ToolExecutor,
    table: str,
) -> CompositeResult:
    """Get table metadata → recent history."""
    data: dict[str, Any] = {}
    errors: list[str] = []

    # Step 1: get_table_metadata (required)
    try:
        metadata = await _guarded_call(executor, "get_table_metadata", table_name=table)
        data["metadata"] = metadata
    except Exception as exc:
        return CompositeResult(errors=[f"get_table_metadata failed: {exc}"])

    # Step 2: get_table_history
    try:
        history = await _guarded_call(
            executor, "get_table_history", table_name=table, limit=5
        )
        data["recent_history"] = history
    except Exception as exc:
        errors.append(f"get_table_history failed: {exc}")

    return CompositeResult(data=data, errors=errors, partial=bool(errors))


async def get_workspace_overview(
    executor: ToolExecutor,
) -> CompositeResult:
    """List clusters and warehouse portfolio in parallel."""
    data: dict[str, Any] = {}
    errors: list[str] = []

    async def _clusters() -> dict[str, Any] | None:
        try:
            return await _guarded_call(executor, "list_clusters")
        except Exception as exc:
            errors.append(f"list_clusters failed: {exc}")
        return None

    async def _warehouses() -> dict[str, Any] | None:
        try:
            return await _guarded_call(executor, "get_warehouse_portfolio")
        except Exception as exc:
            errors.append(f"get_warehouse_portfolio failed: {exc}")
        return None

    clusters, warehouses = await asyncio.gather(_clusters(), _warehouses())
    if clusters is not None:
        data["clusters"] = clusters
    if warehouses is not None:
        data["warehouses"] = warehouses

    partial = bool(errors) and bool(data)
    return CompositeResult(data=data, errors=errors, partial=partial)
