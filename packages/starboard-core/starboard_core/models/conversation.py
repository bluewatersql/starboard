"""Conversation domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Message:
    """Single message in a conversation."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    tool_calls: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "tool_calls": self.tool_calls,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Deserialize from dict."""
        # Handle missing timestamp for backward compatibility
        # (agent messages don't have timestamps when first created)
        timestamp_str = data.get("timestamp")
        timestamp = (
            datetime.fromisoformat(timestamp_str)
            if timestamp_str
            else datetime.now(UTC)
        )

        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=timestamp,
            tool_calls=data.get("tool_calls", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Conversation:
    """Conversation entity."""

    id: str
    user_id: str
    messages: list[Message]
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    archived: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "title": self.title,
            "tags": self.tags,
            "archived": self.archived,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Conversation:
        """Deserialize from dict."""
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            messages=[Message.from_dict(m) for m in data["messages"]],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            title=data.get("title"),
            tags=data.get("tags", []),
            archived=data.get("archived", False),
            metadata=data.get("metadata", {}),
        )


class ConversationMetadata(BaseModel):
    """Lightweight conversation metadata for listing."""

    id: str
    user_id: str
    title: str | None
    message_count: int
    last_message_preview: str | None
    created_at: datetime
    updated_at: datetime
    tags: list[str] = Field(default_factory=list)
    archived: bool = False

    @classmethod
    def from_conversation(cls, conv: Conversation) -> ConversationMetadata:
        """Create metadata from full conversation."""
        last_message = conv.messages[-1] if conv.messages else None
        preview = last_message.content[:100] if last_message else None

        return cls(
            id=conv.id,
            user_id=conv.user_id,
            title=conv.title,
            message_count=len(conv.messages),
            last_message_preview=preview,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            tags=conv.tags,
            archived=conv.archived,
        )
