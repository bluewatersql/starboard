"""Response models for the Starboard SDK."""

from __future__ import annotations

import dataclasses
from typing import NotRequired, TypedDict


class RawAgentOutput(TypedDict, total=False):
    """Typed dictionary for raw agent output.

    All fields are optional because the agent may not populate every key.
    """

    user_goal: str
    summary: str
    domain: str
    steps_taken: int
    tools_used: list[str]
    tokens_used: int
    cost_usd: float
    duration_seconds: float
    conversation_id: str
    complete_report: dict[str, object]
    formatted_markdown: str
    recommendations: list[dict[str, str]]


@dataclasses.dataclass(frozen=True)
class AgentResponse:
    """Response from a single agent turn.

    Attributes:
        question: The user message that produced this response.
        report: Formatted markdown report (from the agent's complete_report).
        raw_output: Full agent output dictionary.
        tools_used: List of tool names invoked during this turn.
        tokens_used: Total tokens consumed (if available).
        cost_usd: Estimated cost in USD (if available).
        duration_seconds: Wall-clock time for this turn in seconds.
        domain: Domain agent that handled the request.
        conversation_id: Underlying conversation identifier.
        turn_number: Which turn this response corresponds to.
        error: Non-recoverable agent error message if the turn failed,
            ``None`` when the turn completed successfully.
    """

    question: str
    report: str | None
    raw_output: RawAgentOutput
    tools_used: list[str]
    tokens_used: int | None
    cost_usd: float | None
    duration_seconds: float
    domain: str | None
    conversation_id: str
    turn_number: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True if the turn produced a report without a fatal error."""
        return self.error is None and bool(self.report or self.raw_output)

    @property
    def markdown(self) -> str:
        """Return the report as markdown, falling back to a plain summary."""
        if self.report:
            return self.report
        if self.error:
            return f"**Agent error:** {self.error}"
        summary = self.raw_output.get("summary", "")
        return summary or f"[No report — turn {self.turn_number}, domain={self.domain}]"

    def __str__(self) -> str:
        """Return the report text, or a summary if no report."""
        return self.markdown
