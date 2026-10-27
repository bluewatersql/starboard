# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""MCP response and error models.

All models are frozen (immutable) and use Pydantic V2 ``ConfigDict``.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class MCPToolResponse(BaseModel):
    """Structured response from an MCP tool invocation.

    Attributes:
        status: Outcome of the tool call.
        workspace_id_used: Which workspace was resolved for this call.
        data: Tool-specific result payload.
        truncated: Whether the response was truncated to fit size limits.
        total_count: Total item count before truncation (if applicable).
        warnings: Non-fatal warnings emitted during execution.
        trace_id: Distributed tracing identifier for this call.
        duration_ms: Wall-clock execution time in milliseconds.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["success", "error", "truncated"]
    workspace_id_used: str
    data: dict[str, Any]
    truncated: bool = False
    total_count: int | None = None
    warnings: list[str] | None = None
    trace_id: str | None = None
    duration_ms: float | None = None


class MCPResponseMetadata(BaseModel):
    """Metadata about an MCP agent execution.

    Provides routing context, confidence, and tracing information
    for an agent response.

    Attributes:
        workspace_id_used: Which workspace was resolved for this call.
        domain_selected: The domain agent that handled the request.
        confidence: Routing confidence (0.0–1.0).
        low_confidence: Whether routing confidence was below threshold.
        auto_selected_path: Whether the domain was auto-selected by the router.
        reasoning_summary: Brief explanation of routing decision.
        trace_id: Distributed tracing identifier for this call.
        duration_ms: Wall-clock execution time in milliseconds.
        conversation_id: Optional conversation ID for continuity.
    """

    model_config = ConfigDict(frozen=True)

    workspace_id_used: str
    domain_selected: str
    confidence: float
    low_confidence: bool = False
    auto_selected_path: bool = False
    reasoning_summary: str = ""
    trace_id: str = ""
    duration_ms: float = 0.0
    conversation_id: str | None = None


class MCPAgentResponse(BaseModel):
    """Structured response from an MCP agent invocation.

    Attributes:
        status: Outcome of the agent call.
        workspace_id_used: Which workspace was resolved for this call.
        agent_domain: The domain agent that handled the request.
        response_text: Agent's natural-language response.
        tools_used: List of tools the agent invoked.
        confidence: Agent's confidence in its response (0.0–1.0).
        trace_id: Distributed tracing identifier for this call.
        duration_ms: Wall-clock execution time in milliseconds.
        envelope: Serialized ``AgentResultEnvelope`` (if available).
        mcp_metadata: Routing and execution metadata.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["success", "error", "timeout", "partial"]
    workspace_id_used: str
    agent_domain: str
    response_text: str
    tools_used: list[str] | None = None
    confidence: float | None = None
    trace_id: str | None = None
    duration_ms: float | None = None
    envelope: dict[str, Any] | None = None
    mcp_metadata: MCPResponseMetadata | None = None
    progress_events: list[dict[str, Any]] | None = None


class MCPError(BaseModel):
    """Structured error returned through the MCP protocol.

    Attributes:
        code: Machine-readable error code (e.g. ``EXEC_FAILED``).
        message: Human-readable error description.
        details: Additional context for debugging.
        retry_after: Seconds to wait before retrying (rate-limit errors).
    """

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    details: dict[str, Any] | None = None
    retry_after: int | None = None
