"""
API reasoning models.

Models for interruptible reasoning and agent interactions:
- InjectInputRequest: Request to inject user input during reasoning
- InjectInputResponse: Response after injecting input
- RespondToSolicitationRequest: Request to respond to agent question
- RespondToSolicitationResponse: Response after answering solicitation
- CheckpointInfo: Information about a checkpoint
- CheckpointsResponse: Response with checkpoint information

Extracted from models.py for better organization.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class InjectInputRequest(BaseModel):
    """
    Request to inject user input during reasoning.

    Allows users to add context, request replanning, or cancel reasoning
    mid-execution at checkpoints.

    Args:
        input_type: Type of input (context_injection, replan_request, cancel_request)
        content: User's message/context
        checkpoint_id: Optional target checkpoint (None = current checkpoint)
        metadata: Optional additional context

    Examples:
        >>> request = InjectInputRequest(
        ...     input_type="context_injection",
        ...     content="Focus on partition pruning",
        ...     metadata={"priority": "high"}
        ... )
    """

    input_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Type of input (context_injection, replan_request, cancel_request, etc.)",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="User's message or context",
    )
    checkpoint_id: str | None = Field(
        default=None,
        max_length=100,
        description="Target checkpoint ID (None = current checkpoint)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional context",
    )

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        """Ensure content is not just whitespace."""
        if not v.strip():
            raise ValueError("Content cannot be empty or whitespace")
        return v


class InjectInputResponse(BaseModel):
    """
    Response after injecting user input.

    Args:
        input_id: Unique identifier for this input
        status: Processing status (accepted, rejected, queued)
        checkpoint_id: Checkpoint where input will be processed
        message: Human-readable status message

    Examples:
        >>> response = InjectInputResponse(
        ...     input_id="input_abc123",
        ...     status="accepted",
        ...     checkpoint_id="ckpt_def456",
        ...     message="Input will be processed at next checkpoint"
        ... )
    """

    input_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique input identifier",
    )
    status: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Processing status",
    )
    checkpoint_id: str | None = Field(
        default=None,
        max_length=100,
        description="Checkpoint where input will be processed",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Human-readable status message",
    )


class RespondToSolicitationRequest(BaseModel):
    """
    Request to respond to an agent solicitation.

    When the agent asks a question (solicitation), use this to provide
    the requested information.

    Args:
        solicitation_id: ID of the solicitation being answered
        content: User's response/answer
        metadata: Optional additional context

    Examples:
        >>> request = RespondToSolicitationRequest(
        ...     solicitation_id="sol_abc123",
        ...     content="Service principal: sp-prod-databricks",
        ...     metadata={"confidence": "high"}
        ... )
    """

    solicitation_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Solicitation ID being answered",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="User's response/answer",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional context",
    )

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        """Ensure content is not just whitespace."""
        if not v.strip():
            raise ValueError("Content cannot be empty or whitespace")
        return v


class RespondToSolicitationResponse(BaseModel):
    """
    Response after responding to solicitation.

    Args:
        response_id: Unique identifier for this response
        status: Processing status
        solicitation_id: Solicitation that was answered
        response_time_ms: Time taken by user to respond (milliseconds)

    Examples:
        >>> response = RespondToSolicitationResponse(
        ...     response_id="resp_xyz789",
        ...     status="accepted",
        ...     solicitation_id="sol_abc123",
        ...     response_time_ms=12345.6
        ... )
    """

    response_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique response identifier",
    )
    status: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Processing status",
    )
    solicitation_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Solicitation that was answered",
    )
    response_time_ms: float = Field(
        ...,
        ge=0,
        description="User response time in milliseconds",
    )


class CheckpointInfo(BaseModel):
    """
    Information about a checkpoint.

    Args:
        checkpoint_id: Unique checkpoint identifier
        step_number: Reasoning step number
        checkpoint_type: Type of checkpoint
        timestamp: When checkpoint was created
        can_interrupt: Whether interrupts are allowed

    Examples:
        >>> info = CheckpointInfo(
        ...     checkpoint_id="ckpt_abc123",
        ...     step_number=5,
        ...     checkpoint_type="reasoning_step",
        ...     timestamp=datetime.now(),
        ...     can_interrupt=True
        ... )
    """

    checkpoint_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique checkpoint identifier",
    )
    step_number: int = Field(
        ...,
        ge=0,
        description="Reasoning step number",
    )
    checkpoint_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Type of checkpoint",
    )
    timestamp: datetime = Field(
        ...,
        description="When checkpoint was created",
    )
    can_interrupt: bool = Field(
        ...,
        description="Whether interrupts are allowed",
    )


class CheckpointsResponse(BaseModel):
    """
    Response with checkpoint information.

    Args:
        checkpoints: List of recent checkpoints
        active_checkpoint: ID of currently active checkpoint (if any)

    Examples:
        >>> response = CheckpointsResponse(
        ...     checkpoints=[checkpoint_info1, checkpoint_info2],
        ...     active_checkpoint="ckpt_abc123"
        ... )
    """

    checkpoints: list[CheckpointInfo] = Field(
        default_factory=list,
        description="List of recent checkpoints",
    )
    active_checkpoint: str | None = Field(
        default=None,
        description="ID of currently active checkpoint",
    )
