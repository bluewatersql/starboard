# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Agent result envelope models.

This module defines the standardized envelope pattern for agent responses.
All domain agents emit responses in this format for consistent downstream handling.

The envelope pattern provides:
- Stable metadata fields across all agents
- Polymorphic payload varying by report_type
- Explicit partial/error semantics
- Schema versioning for forward compatibility

Version: 1.0
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Envelope version - bump on breaking changes
ENVELOPE_VERSION: Literal["1.0"] = "1.0"


class AgentMetrics(BaseModel):
    """
    Execution metrics for observability and cost tracking.

    All values must be non-negative. These metrics are used for:
    - Cost attribution and budgeting
    - Performance monitoring
    - Usage analytics

    Attributes:
        tokens_used: Total tokens consumed (input + output)
        cost_usd: Estimated cost in USD
        duration_seconds: Total execution time
        steps_taken: Number of reasoning steps executed

    Example:
        >>> metrics = AgentMetrics(
        ...     tokens_used=1500,
        ...     cost_usd=0.025,
        ...     duration_seconds=12.5,
        ...     steps_taken=5,
        ... )
    """

    model_config = ConfigDict(frozen=True)

    tokens_used: int = Field(..., ge=0, description="Total tokens consumed")
    cost_usd: float = Field(..., ge=0, description="Estimated cost in USD")
    duration_seconds: float = Field(..., ge=0, description="Total execution time")
    steps_taken: int = Field(..., ge=0, description="Number of reasoning steps")


class StructuredError(BaseModel):
    """
    Structured validation or execution error.

    Provides machine-readable error information for logging and debugging.
    Use this instead of raw error strings to enable structured logging
    and programmatic error handling.

    Attributes:
        code: Machine-readable error code (e.g., "VALIDATION_ERROR")
        message: Human-readable error message
        field: Optional field path that caused the error
        details: Optional additional error context

    Example:
        >>> error = StructuredError(
        ...     code="SCHEMA_MISMATCH",
        ...     message="Expected string, got int",
        ...     field="summary.overview",
        ...     details={"expected": "str", "got": "int"},
        ... )
    """

    model_config = ConfigDict(frozen=True)

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    field: str | None = Field(None, description="Field path that caused error")
    details: dict[str, Any] | None = Field(None, description="Additional context")


class PartialInfo(BaseModel):
    """
    Explicit partial response metadata.

    When an agent cannot complete its analysis (budget exhaustion, timeout,
    validation failure), it emits a partial response with this metadata.
    This enables downstream consumers to handle partial results gracefully.

    Attributes:
        is_partial: Always True (discriminator for type checking)
        reason: Why the response is partial
        missing_fields: List of field paths that couldn't be populated
        recovery_hint: Suggestion for how to get complete results

    Example:
        >>> partial = PartialInfo(
        ...     reason="budget_exceeded",
        ...     missing_fields=["analysis.findings"],
        ...     recovery_hint="Continue analysis for full findings",
        ... )
    """

    model_config = ConfigDict(frozen=True)

    is_partial: bool = Field(default=True, description="Discriminator - always True")
    reason: Literal[
        "budget_exceeded", "timeout", "validation_failed", "agent_stuck"
    ] = Field(..., description="Why response is partial")
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Field paths that couldn't be populated",
    )
    recovery_hint: str | None = Field(
        None,
        description="Suggestion for getting complete results",
    )


class AgentResultEnvelope(BaseModel):
    """
    Standardized wrapper for all domain agent responses.

    The envelope pattern provides a stable contract for downstream consumers
    while allowing domain-specific variation in the payload. Key guarantees:

    1. Stable metadata: schema_version, domain, status, metrics are always present
    2. Explicit partial semantics: partial responses are valid, not errors
    3. Typed errors: validation/execution errors are structured
    4. Forward compatible: schema_version enables gradual migration

    Attributes:
        schema_version: Envelope schema version (currently "1.0")
        domain: Agent domain (query, job, uc, analytics, etc.)
        timestamp: When the response was generated
        trace_id: Request trace ID for observability
        status: Response status (success, partial, error, etc.)
        report_type: Discriminator for payload type
        payload: Domain-specific report data
        metrics: Execution metrics
        partial: Metadata if response is partial (None if complete)
        errors: List of structured errors (empty if no errors)
        next_steps: Suggested next actions

    Example:
        >>> envelope = AgentResultEnvelope(
        ...     domain="query",
        ...     timestamp=datetime.now(UTC),
        ...     trace_id="trace_abc123",
        ...     status="success",
        ...     report_type="advisor",
        ...     payload=advisor_report,
        ...     metrics=metrics,
        ... )
    """

    model_config = ConfigDict(frozen=True)

    # Envelope metadata (STABLE across all agents)
    schema_version: Literal["1.0"] = Field(
        default=ENVELOPE_VERSION,
        description="Envelope schema version",
    )
    domain: str = Field(..., description="Agent domain (query, job, uc, etc.)")
    timestamp: datetime = Field(..., description="Response generation time")
    trace_id: str = Field(..., description="Request trace ID")

    # Status (STABLE)
    status: Literal[
        "success", "partial", "budget_exceeded", "max_steps_reached", "error"
    ] = Field(..., description="Response status")

    # Polymorphic payload
    report_type: Literal["advisor", "analytics", "compute"] = Field(
        ...,
        description="Report type discriminator",
    )
    payload: dict[str, Any] = Field(
        ...,
        description="Domain-specific report data",
    )

    # Metrics (STABLE)
    metrics: AgentMetrics = Field(..., description="Execution metrics")

    # Partial/error semantics (STABLE)
    partial: PartialInfo | None = Field(
        None,
        description="Partial response metadata (None if complete)",
    )
    errors: list[StructuredError] = Field(
        default_factory=list,
        description="Structured errors (empty if none)",
    )

    # Next steps (STABLE structure, domain-specific content)
    next_steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Suggested next actions",
    )
