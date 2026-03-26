"""Handoff recommendation domain models.

Defines structures for domain agents to recommend handoffs to other agents
without direct coupling. Part of the router-centric orchestration pattern.

Part of Phase 9: Service Catalog & Next-Step Suggestions

Examples:
    >>> recommendation = HandoffRecommendation(
    ...     target_domain="performance",
    ...     confidence=HandoffConfidence.HIGH,
    ...     reason="User's query is slow, needs deep performance analysis",
    ... )
    >>> recommendation.target_domain
    'performance'
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from typing import Any


@total_ordering
class HandoffConfidence(StrEnum):
    """Confidence level for handoff recommendations.

    Used to prioritize recommendations when multiple handoffs are suggested.
    Higher confidence recommendations should be presented more prominently.

    Attributes:
        HIGH: Strong recommendation, clearly beneficial to user
        MEDIUM: Moderate recommendation, likely helpful
        LOW: Weak recommendation, optionally helpful
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def __lt__(self, other: object) -> bool:
        """Define ordering: HIGH > MEDIUM > LOW.

        Args:
            other: Another HandoffConfidence to compare

        Returns:
            True if self is lower priority than other

        Examples:
            >>> HandoffConfidence.LOW < HandoffConfidence.HIGH
            True
        """
        if not isinstance(other, HandoffConfidence):
            return NotImplemented

        order = {
            HandoffConfidence.HIGH: 3,
            HandoffConfidence.MEDIUM: 2,
            HandoffConfidence.LOW: 1,
        }
        return order[self] < order[other]


@dataclass(frozen=True)
class HandoffRecommendation:
    """Represents a recommendation for cross-agent handoff.

    Domain agents return these to suggest that the router should present
    options for transitioning to other agents. The router uses these hints
    to query the service catalog and generate next-step options.

    Attributes:
        target_domain: Domain to hand off to (e.g., "performance", "finops")
        confidence: How strongly this handoff is recommended
        reason: Why this handoff would benefit the user (>10 chars)
        context_to_pass: Optional context data to pass to target agent

    Examples:
        >>> recommendation = HandoffRecommendation(
        ...     target_domain="performance",
        ...     confidence=HandoffConfidence.HIGH,
        ...     reason="Query execution time exceeds 45 seconds",
        ...     context_to_pass={"query_id": "abc123"},
        ... )
        >>> recommendation.confidence
        <HandoffConfidence.HIGH: 'high'>
    """

    target_domain: str
    confidence: HandoffConfidence
    reason: str
    context_to_pass: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate handoff recommendation after initialization.

        Raises:
            ValueError: If required fields are invalid
        """
        # Validate target_domain
        if not self.target_domain or not self.target_domain.strip():
            raise ValueError("target_domain cannot be empty")

        # Validate reason
        if not self.reason or not self.reason.strip():
            raise ValueError("reason cannot be empty")

        if len(self.reason.strip()) < 10:
            raise ValueError(
                f"reason must be at least 10 characters long: got {len(self.reason.strip())} chars"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert handoff recommendation to dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization

        Examples:
            >>> rec = HandoffRecommendation(...)
            >>> data = rec.to_dict()
            >>> data["target_domain"]
            'performance'
        """
        return {
            "target_domain": self.target_domain,
            "confidence": self.confidence.value,
            "reason": self.reason,
            "context_to_pass": self.context_to_pass,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandoffRecommendation:
        """Create handoff recommendation from dictionary.

        Args:
            data: Dictionary containing recommendation fields

        Returns:
            HandoffRecommendation instance

        Examples:
            >>> data = {
            ...     "target_domain": "performance",
            ...     "confidence": "high",
            ...     "reason": "Query is slow",
            ... }
            >>> rec = HandoffRecommendation.from_dict(data)
        """
        return cls(
            target_domain=data["target_domain"],
            confidence=HandoffConfidence(data["confidence"]),
            reason=data["reason"],
            context_to_pass=data.get("context_to_pass"),
        )
