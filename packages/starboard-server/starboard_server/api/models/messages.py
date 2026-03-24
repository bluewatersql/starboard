"""API message models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import MessageRole, MessageStatus

# =============================================================================
# FILE ATTACHMENT MODELS
# =============================================================================


class FileAttachment(BaseModel):
    """Represents a file attachment in a message.

    For large files (>50KB), content is stored in cache and only
    metadata is passed through the message pipeline.

    Attributes:
        id: Cache key for retrieving content (set for large files)
        filename: Original filename
        size: File size in bytes
        content: Full file content (only for small files)
        content_preview: First 500 chars for display
        is_large_file: True if content is stored in cache
        detected_type: Auto-detected artifact type (optional)

    Note:
        This model accepts both camelCase (from frontend) and snake_case field names
        via populate_by_name=True and alias configuration.
    """

    # Accept both camelCase (frontend) and snake_case (Python convention)
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(None, description="Cache key for large file content")
    filename: str = Field(..., description="Original filename")
    size: int = Field(..., description="File size in bytes")
    content: str | None = Field(None, description="Content (small files only)")
    content_preview: str | None = Field(
        None, description="First 500 chars for display", alias="contentPreview"
    )
    is_large_file: bool = Field(
        False, description="True if stored in cache", alias="isLargeFile"
    )
    detected_type: str | None = Field(
        None, description="Auto-detected artifact type", alias="detectedType"
    )


class ToolCall(BaseModel):
    """Tool call information for display."""

    tool_call_id: str = Field(..., description="Unique tool call identifier")
    tool_name: str = Field(..., description="Internal tool name")
    friendly_name: str | None = Field(None, description="Display name for tool")
    status: str = Field(..., description="Tool call status (running/completed/failed)")
    arguments: dict[str, Any] | None = Field(None, description="Tool input arguments")
    output: str | None = Field(None, description="Tool result summary")
    error: str | None = Field(None, description="Error message if failed")
    duration_ms: int | None = Field(None, description="Execution time in milliseconds")


class Message(BaseModel):
    """API message model."""

    id: str
    conversation_id: str
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    status: MessageStatus = MessageStatus.COMPLETED
    metadata: dict = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(
        default_factory=list, description="Tool calls executed in this message"
    )
    next_steps: list[Any] | None = Field(
        None, description="Next step options for interactive conversation flow"
    )


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation.

    Supports file attachments for artifact analysis. Large files (>50KB)
    are automatically routed to the diagnostic agent for incremental discovery.
    """

    content: str = Field(..., description="Message content", min_length=1)
    attachments: list[FileAttachment] | None = Field(
        None, description="Optional file attachments"
    )
    metadata: dict[str, Any] | None = Field(None, description="Optional metadata")


class MessageResponse(BaseModel):
    """Response after submitting a message."""

    message_id: str
    conversation_id: str
    status: MessageStatus
    trace_id: str | None = None
