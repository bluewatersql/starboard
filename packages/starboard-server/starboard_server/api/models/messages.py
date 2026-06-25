"""API message models.

The canonical ``ToolCall``, ``Message``, and ``MessageResponse`` definitions
live in the domain layer (``starboard_server.domain.conversation.models``) and
are re-exported here. ``FileAttachment`` and ``SendMessageRequest`` are API-only
request models and remain defined locally.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from starboard_server.domain.conversation.models import (
    Message,
    MessageResponse,
    ToolCall,
)

__all__ = [
    "FileAttachment",
    "Message",
    "MessageResponse",
    "SendMessageRequest",
    "ToolCall",
]

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
