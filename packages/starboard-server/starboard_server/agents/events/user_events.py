"""
User interaction events.

This module defines events related to user interaction:
- UserInputRequestEvent: Agent requests user input
- UserInputResponseEvent: User provides input
- FinalOutputEvent: Final agent output

Example:
    >>> from starboard_server.agents.events import UserInputRequestEvent, FinalOutputEvent
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from starboard_server.agents.events.base import EventType, StreamingEvent


class UserInputRequestEvent(StreamingEvent):
    """
    User input request event.

    Emitted when the agent needs clarification or additional information from the user.
    Execution pauses until user provides a response.

    This event enables human-in-the-loop workflows where the agent can ask follow-up
    questions to gather missing context, resolve ambiguities, or confirm assumptions.

    Attributes:
        type: Always EventType.USER_INPUT_REQUEST
        step: Current reasoning step
        question: The question to ask the user
        context: Why this information is needed (helps user understand)
        suggestions: Optional list of suggested answers/options
        timeout_seconds: Optional timeout for response (None = no timeout)
        request_id: Unique identifier for this request

    Example:
        >>> event = UserInputRequestEvent(
        ...     step=2,
        ...     question="Which warehouse would you like to use?",
        ...     context="Multiple warehouses found in your account",
        ...     suggestions=["warehouse_prod", "warehouse_dev"],
        ...     timeout_seconds=300,
        ...     request_id="input_abc123",
        ... )
    """

    type: Literal[EventType.USER_INPUT_REQUEST] = Field(
        default=EventType.USER_INPUT_REQUEST
    )
    question: str = Field(..., description="Question to ask the user")
    context: str | None = Field(None, description="Why this information is needed")
    suggestions: list[str] = Field(
        default_factory=list, description="Suggested answers"
    )
    timeout_seconds: int | None = Field(
        None, description="Timeout in seconds (None = no timeout)"
    )
    request_id: str = Field(..., description="Unique identifier for this request")

    def __str__(self) -> str:
        return f"[Step {self.step}] User Input Request: {self.question[:50]}..."

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format with message_id and all user input request fields."""
        return {
            "message_id": message_id,
            "request_id": self.request_id,
            "question": self.question,
            "context": self.context,
            "suggestions": self.suggestions,
            "timeout_seconds": self.timeout_seconds,
        }


class UserInputResponseEvent(StreamingEvent):
    """
    User input response event.

    Emitted when the user has provided a response to a UserInputRequestEvent.
    Signals that execution can resume with the user's input.

    Attributes:
        type: Always EventType.USER_INPUT_RESPONSE
        step: Current reasoning step
        request_id: Unique identifier matching the UserInputRequestEvent
        user_response: The user's response text
        timed_out: Whether the response timed out (False if user responded)

    Example:
        >>> event = UserInputResponseEvent(
        ...     step=2,
        ...     request_id="input_abc123",
        ...     user_response="warehouse_prod",
        ...     timed_out=False,
        ... )
    """

    type: Literal[EventType.USER_INPUT_RESPONSE] = Field(
        default=EventType.USER_INPUT_RESPONSE
    )
    request_id: str = Field(..., description="Unique identifier for this request")
    user_response: str = Field(..., description="The user's response text")
    timed_out: bool = Field(False, description="Whether the request timed out")

    def __str__(self) -> str:
        status = (
            "timeout"
            if self.timed_out
            else f"response ({len(self.user_response)} chars)"
        )
        return f"[Step {self.step}] User Input {status}"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format with message_id and all user input response fields."""
        return {
            "message_id": message_id,
            "request_id": self.request_id,
            "user_response": self.user_response,
            "timed_out": self.timed_out,
        }


class FinalOutputEvent(BaseModel):
    """
    Final output event containing complete AgentOutput.

    Emitted at the end of streaming to provide the complete AgentOutput
    without requiring a second reasoning loop. This event doesn't belong
    to a specific step, so it doesn't inherit from StreamingEvent.

    Attributes:
        type: Always EventType.FINAL_OUTPUT
        output: Complete AgentOutput with recommendations and metrics

    Example:
        >>> event = FinalOutputEvent(output=agent_output)
        >>> print(f"Status: {event.output.status}")
        >>> print(f"Recommendations: {len(event.output.recommendations)}")
    """

    type: Literal[EventType.FINAL_OUTPUT] = Field(default=EventType.FINAL_OUTPUT)
    output: Any = Field(
        ..., description="Complete AgentOutput"
    )  # Avoid circular import

    model_config = ConfigDict(
        frozen=True,  # Immutable
        use_enum_values=True,  # Serialize enums as values
    )

    def __str__(self) -> str:
        return f"Final Output: status={getattr(self.output, 'status', 'unknown')}"

    def to_sse_data(
        self,
        message_id: str | None = None,
        domain: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Format as final_output event with nested output structure and formatted report.

        Args:
            message_id: Message ID for the response
            domain: Agent domain for envelope generation (optional)
            trace_id: Request trace ID for envelope generation (optional)

        Returns:
            SSE data dict with output, formatted_markdown, and optional envelope
        """
        from starboard_server.infra.observability.logging import get_logger

        logger_local = get_logger(__name__)

        output = self.output

        # Extract complete_report (source of truth for all rendering)
        complete_report = getattr(output, "complete_report", None)
        formatted_markdown = None  # Initialize to None

        if complete_report:
            # Ensure complete_report is a dict
            if not isinstance(complete_report, dict):
                if hasattr(complete_report, "model_dump"):
                    complete_report = complete_report.model_dump()
                else:
                    complete_report = {"summary": {"overview": str(complete_report)}}

            # FALLBACK: Fix malformed structure where LLM put summary inside analysis
            # Correct: {summary: {...}, analysis: {findings: [...]}}
            # Malformed: {analysis: {summary: {...}}} - missing summary at root
            if isinstance(complete_report, dict):
                analysis = complete_report.get("analysis", {})
                if (
                    isinstance(analysis, dict)
                    and "summary" in analysis
                    and "summary" not in complete_report
                ):
                    logger_local.warning(
                        "normalized_malformed_complete_report",
                        note="LLM put 'summary' inside 'analysis' - moved to root level",
                    )
                    # Move summary to root level where it belongs
                    complete_report["summary"] = analysis["summary"]
                    # Remove it from analysis
                    analysis_copy = dict(analysis)
                    del analysis_copy["summary"]
                    complete_report["analysis"] = analysis_copy

            # Format complete_report to markdown for message.content
            try:
                from starboard_server.agents.report_formatters import (
                    format_agent_report,
                )

                formatted_markdown = format_agent_report(complete_report)
                logger_local.info(
                    "formatted_report_to_markdown",
                    report_type=complete_report.get("report_type"),
                    markdown_length=len(formatted_markdown),
                )
            except Exception as e:
                logger_local.error(
                    "failed_to_format_report",
                    error=str(e),
                    report_type=complete_report.get("report_type"),
                    exc_info=True,
                )
                # Fallback to summary if formatting fails
                formatted_markdown = complete_report.get("summary", {}).get(
                    "overview", "Analysis complete."
                )

            logger_local.debug(
                "complete_report_prepared_for_streaming",
                report_type=complete_report.get("report_type"),
            )
        else:
            logger_local.warning(
                "no_complete_report_available",
                output_status=getattr(output, "status", "unknown"),
            )

        # SIMPLE APPROACH: Just include formatted_markdown in the data dict
        # Don't try to add it to AgentOutput - that's too complex

        # Extract next_steps from output (convert to dicts if needed)
        next_steps = getattr(output, "next_steps", None)
        next_steps_serialized = None
        if next_steps:
            from starboard_server.agents.serialization import serialize_step

            next_steps_serialized = [serialize_step(step) for step in next_steps]
            logger_local.info(
                "next_steps_serialized_for_sse",
                count=len(next_steps_serialized),
            )

        # Log complete_report visualization for debugging
        if complete_report and isinstance(complete_report, dict):
            viz = complete_report.get("visualization")
            if viz and isinstance(viz, dict):
                chart_config = viz.get("chart_config")
                logger_local.debug(
                    "sse_visualization_before_payload",
                    has_visualization=True,
                    has_chart_config=chart_config is not None,
                    chart_config_type=type(chart_config).__name__
                    if chart_config
                    else None,
                    chart_config_keys=list(chart_config.keys())
                    if isinstance(chart_config, dict)
                    else [],
                    chart_config_sample=str(chart_config)[:300]
                    if chart_config
                    else None,
                )

        output_payload: dict[str, Any] = {
            "status": getattr(output, "status", "unknown"),
            "complete_report": complete_report,
            "next_steps": next_steps_serialized,  # Include next steps in output
            "tokens_used": getattr(output, "tokens_used", 0),
            "cost_usd": getattr(output, "cost_usd", 0.0),
            "duration_seconds": getattr(output, "duration_seconds", 0),
            "steps_taken": getattr(output, "steps_taken", 0),
        }

        result: dict[str, Any] = {
            "message_id": message_id,
            "output": output_payload,
            "formatted_markdown": formatted_markdown,  # Send separately, not in output
        }

        # Log final SSE payload structure for debugging
        if output_payload.get("complete_report"):
            viz = output_payload["complete_report"].get("visualization")
            if viz and isinstance(viz, dict):
                chart_config = viz.get("chart_config")
                logger_local.debug(
                    "sse_final_payload_visualization",
                    has_chart_config=chart_config is not None,
                    chart_config_keys=list(chart_config.keys())
                    if isinstance(chart_config, dict)
                    else [],
                )

        # Generate envelope if domain and trace_id provided (Phase 1 - additive)
        if domain and trace_id:
            try:
                from starboard_server.agents.output.envelope_translator import (
                    EnvelopeTranslator,
                )

                translator = EnvelopeTranslator()
                envelope = translator.translate(
                    output=output,
                    domain=domain,
                    trace_id=trace_id,
                )
                # Add envelope to output (additive - preserves existing fields)
                output_payload["envelope"] = envelope.model_dump(mode="json")
                logger_local.debug(
                    "envelope_added_to_sse",
                    domain=domain,
                    trace_id=trace_id,
                    envelope_status=envelope.status,
                )
            except Exception as e:
                # Envelope generation failure should not break SSE
                logger_local.error(
                    "envelope_generation_failed",
                    error=str(e),
                    domain=domain,
                    trace_id=trace_id,
                    exc_info=True,
                )

        logger_local.info(
            "sse_data_prepared_simple",
            has_formatted_markdown=formatted_markdown is not None,
            formatted_markdown_length=(
                len(formatted_markdown) if formatted_markdown else 0
            ),
            formatted_markdown_type=type(formatted_markdown).__name__,
            result_keys=list(result.keys()),
            formatted_markdown_in_result=result.get("formatted_markdown") is not None,
            has_next_steps=next_steps_serialized is not None,
            next_steps_count=len(next_steps_serialized) if next_steps_serialized else 0,
            has_envelope="envelope" in output_payload,
        )

        return result
