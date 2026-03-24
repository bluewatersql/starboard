"""
Envelope translator for agent output.

This module translates AgentOutput dataclass to AgentResultEnvelope Pydantic model.
The translator handles:
- Status mapping (including partial semantics)
- Metrics extraction
- Report type inference
- Next steps serialization
- Error structuring

Example:
    >>> translator = EnvelopeTranslator()
    >>> envelope = translator.translate(
    ...     output=agent_output,
    ...     domain="query",
    ...     trace_id="trace_abc123",
    ... )
"""

from datetime import UTC, datetime
from typing import Any

from starboard_server.agents.output.envelope import (
    AgentMetrics,
    AgentResultEnvelope,
    PartialInfo,
    StructuredError,
)
from starboard_server.agents.state.agent_state import AgentOutput
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


# Domain to default report type mapping
DOMAIN_REPORT_TYPE_MAP: dict[str, str] = {
    "query": "advisor",
    "job": "advisor",
    "uc": "advisor",
    "diagnostic": "advisor",
    "analytics": "analytics",
    "warehouse": "compute",
    "cluster": "compute",
    "compute": "compute",
    "discovery": "advisor",
}


class EnvelopeTranslator:
    """
    Translates AgentOutput to AgentResultEnvelope.

    The translator handles the conversion from the internal AgentOutput
    dataclass to the standardized envelope format for downstream consumers.

    Key responsibilities:
    - Map status values (add partial semantics for budget_exceeded)
    - Extract and validate metrics
    - Infer report_type from complete_report or domain
    - Serialize next_steps to dicts
    - Structure error messages

    Example:
        >>> translator = EnvelopeTranslator()
        >>> envelope = translator.translate(
        ...     output=output,
        ...     domain="query",
        ...     trace_id="trace_abc",
        ... )
        >>> print(envelope.status)
        "success"
    """

    def translate(
        self,
        output: AgentOutput,
        domain: str,
        trace_id: str,
    ) -> AgentResultEnvelope:
        """
        Translate AgentOutput to AgentResultEnvelope.

        Args:
            output: AgentOutput from domain agent
            domain: Agent domain (query, job, uc, etc.)
            trace_id: Request trace ID for observability

        Returns:
            AgentResultEnvelope with standardized structure
        """
        # Extract metrics
        metrics = self._extract_metrics(output)

        # Determine report type
        report_type = self._infer_report_type(output, domain)

        # Extract payload
        payload = self._extract_payload(output)

        # Determine status and partial info
        status = output.status
        partial = self._build_partial_info(output)

        # Build errors list
        errors = self._build_errors(output)

        # Serialize next steps
        next_steps = self._serialize_next_steps(output)

        logger.debug(
            "envelope_translated",
            domain=domain,
            trace_id=trace_id,
            status=status,
            report_type=report_type,
            has_partial=partial is not None,
            error_count=len(errors),
            next_steps_count=len(next_steps),
        )

        return AgentResultEnvelope(
            domain=domain,
            timestamp=datetime.now(UTC),
            trace_id=trace_id,
            status=status,  # type: ignore
            report_type=report_type,  # type: ignore
            payload=payload,
            metrics=metrics,
            partial=partial,
            errors=errors,
            next_steps=next_steps,
        )

    def _extract_metrics(self, output: AgentOutput) -> AgentMetrics:
        """Extract metrics from AgentOutput."""
        return AgentMetrics(
            tokens_used=output.tokens_used,
            cost_usd=output.cost_usd,
            duration_seconds=output.duration_seconds,
            steps_taken=output.steps_taken,
        )

    def _infer_report_type(self, output: AgentOutput, domain: str) -> str:
        """
        Infer report type from complete_report or domain.

        Priority:
        1. report_type in complete_report
        2. Default based on domain
        """
        if output.complete_report and isinstance(output.complete_report, dict):
            report_type = output.complete_report.get("report_type")
            if report_type in ("advisor", "analytics", "compute"):
                return report_type

        # Default based on domain
        return DOMAIN_REPORT_TYPE_MAP.get(domain, "advisor")

    def _extract_payload(self, output: AgentOutput) -> dict[str, Any]:
        """Extract payload from complete_report."""
        if output.complete_report and isinstance(output.complete_report, dict):
            return output.complete_report
        return {}

    def _build_partial_info(self, output: AgentOutput) -> PartialInfo | None:
        """Build partial info for non-success statuses."""
        if output.status == "budget_exceeded":
            return PartialInfo(
                reason="budget_exceeded",
                missing_fields=[],
                recovery_hint="Continue analysis for complete results",
            )
        elif output.status == "max_steps_reached":
            # max_steps_reached is a limit, not a partial response
            return None
        elif output.status == "error":
            # Errors have their own handling via errors list
            return None
        return None

    def _build_errors(self, output: AgentOutput) -> list[StructuredError]:
        """Build structured errors from error_message."""
        errors: list[StructuredError] = []

        if output.status == "error" and output.error_message:
            errors.append(
                StructuredError(
                    code="AGENT_ERROR",
                    message=output.error_message,
                )
            )

        return errors

    def _serialize_next_steps(self, output: AgentOutput) -> list[dict[str, Any]]:
        """Serialize next_steps to list of dicts."""
        if not output.next_steps:
            return []

        result: list[dict[str, Any]] = []
        for step in output.next_steps:
            if hasattr(step, "to_dict"):
                result.append(step.to_dict())
            elif hasattr(step, "model_dump"):
                result.append(step.model_dump())
            elif isinstance(step, dict):
                result.append(step)
            else:
                # Fallback for unknown types
                result.append(
                    {
                        "id": getattr(step, "id", "unknown"),
                        "number": getattr(step, "number", 0),
                        "title": getattr(step, "title", ""),
                        "description": getattr(step, "description", None),
                        "action_type": getattr(
                            getattr(step, "action_type", None), "value", "continue"
                        ),
                        "target_agent": getattr(step, "target_agent", None),
                        "tool_name": getattr(step, "tool_name", None),
                        "parameters": getattr(step, "parameters", None),
                    }
                )

        return result
