"""
Interruptible reasoning lifecycle events.

This module defines events related to interruptible reasoning patterns:
- CheckpointEvent: Agent creates a checkpoint
- InterruptReceivedEvent: User interrupts agent
- ReplanEvent: Agent replans after interrupt
- SolicitationEvent: Agent solicits additional information

Example:
    >>> from starboard_server.agents.events import CheckpointEvent, InterruptReceivedEvent
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from starboard_server.agents.events.base import EventType, StreamingEvent


class CheckpointEvent(StreamingEvent):
    """
    Checkpoint created event (Phase 3).

    Emitted when the agent creates a checkpoint during reasoning. Checkpoints
    are points where user interrupts can be processed without losing progress.

    Attributes:
        type: Always EventType.CHECKPOINT
        step: Current reasoning step
        checkpoint_id: Unique checkpoint identifier
        checkpoint_type: Type of checkpoint (reasoning_step, tool_call, solicitation, etc.)
        can_interrupt: Whether interrupts are allowed at this checkpoint
        metadata: Additional context about the checkpoint

    Example:
        >>> event = CheckpointEvent(
        ...     step=3,
        ...     checkpoint_id="ckpt_abc123",
        ...     checkpoint_type="reasoning_step",
        ...     can_interrupt=True,
        ... )
    """

    type: Literal[EventType.CHECKPOINT] = Field(default=EventType.CHECKPOINT)
    checkpoint_id: str = Field(..., description="Unique checkpoint identifier")
    checkpoint_type: str = Field(..., description="Type of checkpoint")
    can_interrupt: bool = Field(default=True, description="Whether interrupts allowed")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional context"
    )

    def __str__(self) -> str:
        return f"[Step {self.step}] Checkpoint: {self.checkpoint_id} ({self.checkpoint_type})"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format with message_id and all checkpoint fields."""
        return {
            "message_id": message_id,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_type": self.checkpoint_type,
            "can_interrupt": self.can_interrupt,
            "metadata": self.metadata,
        }


class InterruptReceivedEvent(StreamingEvent):
    """
    User interrupt received event (Phase 3).

    Emitted when the agent receives user input during active reasoning. The
    agent will analyze the impact and decide on a replanning strategy.

    Attributes:
        type: Always EventType.INTERRUPT_RECEIVED
        step: Current reasoning step
        input_id: Unique user input identifier
        input_type: Type of input (context_injection, replan_request, cancel_request)
        content_preview: Preview of user input (first 100 chars)
        checkpoint_id: Checkpoint where interrupt was received

    Example:
        >>> event = InterruptReceivedEvent(
        ...     step=3,
        ...     input_id="input_xyz789",
        ...     input_type="context_injection",
        ...     content_preview="Focus on partition pruning...",
        ...     checkpoint_id="ckpt_abc123",
        ... )
    """

    type: Literal[EventType.INTERRUPT_RECEIVED] = Field(
        default=EventType.INTERRUPT_RECEIVED
    )
    input_id: str = Field(..., description="Unique user input identifier")
    input_type: str = Field(..., description="Type of user input")
    content_preview: str = Field(..., description="Preview of user input")
    checkpoint_id: str = Field(..., description="Checkpoint where interrupt received")

    def __str__(self) -> str:
        return f"[Step {self.step}] Interrupt: {self.input_type} (ID: {self.input_id})"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format with message_id and all interrupt fields."""
        return {
            "message_id": message_id,
            "input_id": self.input_id,
            "input_type": self.input_type,
            "content_preview": self.content_preview,
            "checkpoint_id": self.checkpoint_id,
        }


class ReplanEvent(StreamingEvent):
    """
    Replanning decision made event (Phase 3).

    Emitted when the agent decides on a replanning strategy after receiving
    user input. Shows the strategy and reasoning behind the decision.

    Attributes:
        type: Always EventType.REPLAN
        step: Current reasoning step
        decision_id: Unique replan decision identifier
        strategy: Replan strategy (continue, soft_replan, hard_replan, cancel)
        reasoning: LLM explanation of why this strategy was chosen
        impact_score: Impact severity (0.0 = no impact, 1.0 = complete replan)
        affected_steps: Step numbers that will be revised
        actions: List of actions to execute

    Example:
        >>> event = ReplanEvent(
        ...     step=3,
        ...     decision_id="dec_def456",
        ...     strategy="soft_replan",
        ...     reasoning="User clarified DB schema; update query only",
        ...     impact_score=0.6,
        ...     affected_steps=[2, 3],
        ...     actions=["Update SQL in step 3", "Re-run step 3"],
        ... )
    """

    type: Literal[EventType.REPLAN] = Field(default=EventType.REPLAN)
    decision_id: str = Field(..., description="Unique replan decision identifier")
    strategy: str = Field(..., description="Replan strategy")
    reasoning: str = Field(..., description="Why this strategy was chosen")
    impact_score: float = Field(..., ge=0.0, le=1.0, description="Impact severity")
    affected_steps: list[int] = Field(
        default_factory=list, description="Steps to revise"
    )
    actions: list[str] = Field(default_factory=list, description="Actions to execute")

    def __str__(self) -> str:
        return f"[Step {self.step}] Replan: {self.strategy} (impact: {self.impact_score:.1%})"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format with message_id and all replan fields."""
        return {
            "message_id": message_id,
            "decision_id": self.decision_id,
            "strategy": self.strategy,
            "reasoning": self.reasoning,
            "impact_score": self.impact_score,
            "affected_steps": self.affected_steps,
            "actions": self.actions,
        }


class SolicitationEvent(StreamingEvent):
    """
    Agent solicitation event (Phase 3).

    Emitted when the agent asks the user for information during reasoning.
    The agent will wait for a response before continuing.

    Attributes:
        type: Always EventType.SOLICITATION
        step: Current reasoning step
        solicitation_id: Unique solicitation identifier
        question: Question the agent is asking
        context: Why the agent needs this information
        expected_response_type: Type of response expected (e.g., "text", "choice")
        suggestions: Suggested answers (if applicable)
        timeout_seconds: How long to wait for response

    Example:
        >>> event = SolicitationEvent(
        ...     step=3,
        ...     solicitation_id="sol_ghi789",
        ...     question="Which service principal should I use?",
        ...     context="Need credentials to access production database",
        ...     expected_response_type="text",
        ...     suggestions=["sp-prod-reader", "sp-prod-writer"],
        ...     timeout_seconds=300,
        ... )
    """

    type: Literal[EventType.SOLICITATION] = Field(default=EventType.SOLICITATION)
    solicitation_id: str = Field(..., description="Unique solicitation identifier")
    question: str = Field(..., description="Question being asked")
    context: str | None = Field(None, description="Why this information is needed")
    expected_response_type: str = Field(
        default="text", description="Expected response type"
    )
    suggestions: list[str] = Field(
        default_factory=list, description="Suggested answers"
    )
    timeout_seconds: int | None = Field(None, description="Timeout for response")

    def __str__(self) -> str:
        return f"[Step {self.step}] Solicitation: {self.question[:50]}..."

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format with message_id and all solicitation fields."""
        return {
            "message_id": message_id,
            "solicitation_id": self.solicitation_id,
            "question": self.question,
            "context": self.context,
            "expected_response_type": self.expected_response_type,
            "suggestions": self.suggestions,
            "timeout_seconds": self.timeout_seconds,
        }
