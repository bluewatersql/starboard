# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Format tool execution results into ``MCPToolResponse`` objects.

Handles JSON serialisation, truncation at configurable byte limits, and
extraction of ``total_count`` from list-shaped payloads.
"""

from __future__ import annotations

import json
from typing import Any

from starboard.agents.output.llm_responses import ToolResult
from starboard.mcp.models import MCPToolResponse


def _json_default(obj: object) -> Any:
    """Fallback serialiser for non-standard types."""
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _extract_total_count(data: dict[str, Any]) -> int | None:
    """Return count of the first list-valued top-level key, if any."""
    for value in data.values():
        if isinstance(value, list):
            return len(value)
    return None


def format_tool_result(
    raw_result: ToolResult | dict[str, Any],
    workspace_id_used: str,
    max_response_size_bytes: int = 32_768,
    trace_id: str | None = None,
    duration_ms: float | None = None,
) -> MCPToolResponse:
    """Convert a raw tool result into an ``MCPToolResponse``.

    Args:
        raw_result: ``ToolResult`` from ``ToolRegistry.execute_tool`` or a plain dict.
        workspace_id_used: Workspace that was used for this execution.
        max_response_size_bytes: Maximum byte length before truncation.
        trace_id: Optional distributed-tracing identifier.
        duration_ms: Optional execution duration in milliseconds.

    Returns:
        Formatted ``MCPToolResponse``.
    """
    # --- extract data from ToolResult or dict --------------------------------
    if isinstance(raw_result, ToolResult):
        if raw_result.error:
            return MCPToolResponse(
                status="error",
                workspace_id_used=workspace_id_used,
                data={"error": raw_result.error},
                trace_id=trace_id,
                duration_ms=duration_ms,
            )
        content_str = raw_result.content
        try:
            data: dict[str, Any] = json.loads(content_str) if content_str else {}
        except json.JSONDecodeError:
            data = {"raw": content_str}
    else:
        data = raw_result
        content_str = json.dumps(data, indent=2, default=_json_default)

    # --- truncation ----------------------------------------------------------
    if not content_str:
        content_str = json.dumps(data, indent=2, default=_json_default)

    total_count = _extract_total_count(data) if isinstance(data, dict) else None
    truncated = False
    warnings: list[str] = []

    encoded = content_str.encode("utf-8")
    if len(encoded) > max_response_size_bytes:
        truncated = True
        cut = encoded[:max_response_size_bytes].decode("utf-8", errors="ignore")
        # Prefer a newline boundary
        last_nl = cut.rfind("\n")
        if last_nl > 0:
            cut = cut[:last_nl]
        try:
            data = json.loads(cut)
        except json.JSONDecodeError:
            data = {"raw_truncated": cut}
        warnings.append("Result truncated. Consider narrowing the query.")

    status: str = "truncated" if truncated else "success"

    return MCPToolResponse(
        status=status,  # type: ignore[arg-type]
        workspace_id_used=workspace_id_used,
        data=data,
        truncated=truncated,
        total_count=total_count,
        warnings=warnings if warnings else None,
        trace_id=trace_id,
        duration_ms=duration_ms,
    )
