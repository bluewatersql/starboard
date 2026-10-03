# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Long-term memory domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Episode:
    """Episodic memory: summary of past conversation."""

    id: str
    user_id: str
    conversation_id: str | None
    summary: str
    key_points: list[str]
    embedding: list[float] | None
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "summary": self.summary,
            "key_points": self.key_points,
            "embedding": self.embedding,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Episode:
        """Deserialize from dict."""
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            conversation_id=data.get("conversation_id"),
            summary=data["summary"],
            key_points=data.get("key_points", []),
            embedding=data.get("embedding"),
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class Fact:
    """Semantic memory: extracted fact."""

    id: str
    user_id: str
    statement: str
    category: str  # e.g., "job_preference", "technical_skill"
    confidence: float  # 0.0 to 1.0
    source: str | None  # e.g., "conversation:abc123"
    verified: bool
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "statement": self.statement,
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
            "verified": self.verified,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fact:
        """Deserialize from dict."""
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            statement=data["statement"],
            category=data["category"],
            confidence=data.get("confidence", 1.0),
            source=data.get("source"),
            verified=data.get("verified", False),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {}),
        )


class UserProfile(BaseModel):
    """User profile and preferences."""

    user_id: str
    job_preferences: dict[str, Any] = Field(default_factory=dict)
    technical_context: dict[str, Any] = Field(default_factory=dict)
    communication_preferences: dict[str, Any] = Field(default_factory=dict)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SemanticQuery(BaseModel):
    """Query for semantic memory search."""

    text: str
    categories: list[str] | None = None
    min_confidence: float = 0.0
    limit: int = 10
    include_unverified: bool = False
