# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
API clarification models.

Models for handling clarification requests and responses:
- RespondToClarificationRequest: Request to respond to clarification
- RespondToClarificationResponse: Response after providing clarification
- ClarificationRequestEventData: Event data for clarification requests

Extracted from models.py for better organization.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RespondToClarificationRequest(BaseModel):
    """
    Request to respond to a clarification question.

    When the framework detects an ambiguous query and asks for clarification,
    use this endpoint to provide the requested information.

    Args:
        clarification_id: ID of the clarification request (from event)
        response_type: Type of response (option_selected, custom_text)
        selected_option_id: ID of selected option (if choosing from options)
        custom_text: Free-form text response (if allow_custom_response=true)
        metadata: Optional additional context

    Examples:
        >>> # User selects option 2 (Medium warehouse size)
        >>> request = RespondToClarificationRequest(
        ...     clarification_id="clar_abc123",
        ...     response_type="option_selected",
        ...     selected_option_id="2",
        ... )

        >>> # User provides custom text
        >>> request = RespondToClarificationRequest(
        ...     clarification_id="clar_abc123",
        ...     response_type="custom_text",
        ...     custom_text="my-custom-warehouse",
        ... )
    """

    clarification_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Clarification ID from the clarification.request event",
    )
    response_type: Literal["option_selected", "custom_text"] = Field(
        ...,
        description="Type of response provided",
    )
    selected_option_id: str | None = Field(
        None,
        max_length=50,
        description="ID of selected option (required if response_type=option_selected)",
    )
    custom_text: str | None = Field(
        None,
        max_length=500,
        description="Free-form text response (required if response_type=custom_text)",
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Optional additional context",
    )

    @field_validator("selected_option_id")
    @classmethod
    def validate_option_selected(cls, v: str | None, info) -> str | None:
        """Validate selected_option_id when response_type is option_selected."""
        response_type = info.data.get("response_type")
        if response_type == "option_selected" and not v:
            raise ValueError(
                "selected_option_id required when response_type=option_selected"
            )
        return v

    @field_validator("custom_text")
    @classmethod
    def validate_custom_text(cls, v: str | None, info) -> str | None:
        """Validate custom_text when response_type is custom_text."""
        response_type = info.data.get("response_type")
        if response_type == "custom_text" and not v:
            raise ValueError("custom_text required when response_type=custom_text")
        return v


class RespondToClarificationResponse(BaseModel):
    """
    Response after responding to clarification.

    Args:
        response_id: Unique identifier for this response
        clarification_id: ID of the clarification being answered
        status: Processing status (accepted, processing, completed, error)
        enriched_query: The original query enriched with clarification response
        message: Status message
        created_at: Timestamp of response

    Examples:
        >>> response = RespondToClarificationResponse(
        ...     response_id="resp_xyz789",
        ...     clarification_id="clar_abc123",
        ...     status="accepted",
        ...     enriched_query="create warehouse my-wh size Medium",
        ...     message="Clarification accepted, continuing with execution",
        ...     created_at=datetime.now(timezone.utc),
        ... )
    """

    response_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier for this response",
    )
    clarification_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="ID of the clarification being answered",
    )
    status: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Processing status (accepted, processing, completed, error)",
    )
    enriched_query: str | None = Field(
        None,
        max_length=1000,
        description="The original query enriched with clarification response",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Status message",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp of response",
    )


class ClarificationRequestEventData(BaseModel):
    """
    Event data for clarification requests.

    Args:
        clarification_id: Unique identifier for this clarification request
        question: The clarification question being asked
        options: Available options (if multiple choice)
        allow_custom_response: Whether user can provide free-form text
        default_option_id: ID of default/recommended option

    Examples:
        >>> data = ClarificationRequestEventData(
        ...     clarification_id="clar_abc123",
        ...     question="What size warehouse would you like?",
        ...     options=[
        ...         {"id": "1", "label": "Small (X-Small)"},
        ...         {"id": "2", "label": "Medium (Small)"},
        ...         {"id": "3", "label": "Large (Medium/Large)"},
        ...     ],
        ...     allow_custom_response=True,
        ...     default_option_id="2",
        ... )
    """

    clarification_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier for this clarification request",
    )
    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The clarification question being asked",
    )
    options: list[dict[str, str]] | None = Field(
        None,
        description="Available options (id, label pairs)",
    )
    allow_custom_response: bool = Field(
        default=False,
        description="Whether user can provide free-form text instead of selecting option",
    )
    default_option_id: str | None = Field(
        None,
        max_length=50,
        description="ID of default/recommended option",
    )
