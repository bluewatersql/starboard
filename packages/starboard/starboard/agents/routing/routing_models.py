# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Models for multi-agent routing decisions.

This module defines data structures for routing requests between domain
specialist agents. These models are used by the IntentRouter to make
routing decisions and track agent handoffs.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

AgentDomain = Literal[
    "query",
    "job",
    "uc",
    "cluster",
    "diagnostic",
    "analytics",
    "warehouse",
    "discovery",
]
"""Type for domain specialist identifiers (excluding router).

Note: "uc" (Unity Catalog) replaces the deprecated "table" domain.
The UC agent handles all table-related operations plus extended governance,
lineage, and policy capabilities.

Note: "warehouse" handles SQL warehouse portfolio optimization.
Note: "cluster" handles Databricks cluster configuration and optimization.
Note: "discovery" handles workspace health assessment and discovery.
"""


@dataclass(frozen=True)
class RouteDecision:
    """
    Router's decision on which specialist agent to invoke.

    This dataclass represents the outcome of intent classification,
    including the target domain, confidence level, extracted identifiers,
    and reasoning for the decision.

    Attributes:
        domain: Target domain specialist
        confidence: Classification confidence (0.0-1.0, higher is more confident)
        extracted_ids: Extracted identifiers from user input
            (statement_id, job_id, table_name, cluster_id, warehouse_id)
        context: Additional context to pass to the specialist agent
        clarification_needed: Whether user clarification is required
        reasoning: Explanation of why this domain was chosen

    Example:
        >>> decision = RouteDecision(
        ...     domain="query",
        ...     confidence=1.0,
        ...     extracted_ids={"statement_id": "abc123"},
        ...     context={},
        ...     clarification_needed=False,
        ...     reasoning="Statement ID detected"
        ... )
        >>> decision.should_route()
        True
        >>> decision.domain
        'query'
    """

    domain: AgentDomain
    confidence: float
    extracted_ids: dict[str, str]
    context: dict[str, Any]
    clarification_needed: bool
    reasoning: str

    def __post_init__(self) -> None:
        """Validate RouteDecision after initialization."""
        # Validate confidence range
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be between 0.0 and 1.0, got {self.confidence}"
            )

        # Validate domain using canonical ROUTABLE_DOMAINS constant
        from starboard.prompts.base import ROUTABLE_DOMAINS

        if self.domain not in ROUTABLE_DOMAINS:
            raise ValueError(
                f"Invalid domain: {self.domain}. Must be one of: {ROUTABLE_DOMAINS}"
            )

    def should_route(self) -> bool:
        """
        Determine whether confidence is sufficient to route immediately.

        Returns True if the decision is confident enough to proceed with
        routing (confidence >= 0.7) and no clarification is needed.

        Returns:
            True if should route to specialist, False if need more info

        Example:
            >>> # High confidence, no clarification needed
            >>> decision = RouteDecision(
            ...     domain="query", confidence=0.9, extracted_ids={},
            ...     context={}, clarification_needed=False, reasoning="SQL detected"
            ... )
            >>> decision.should_route()
            True
            >>>
            >>> # Low confidence
            >>> decision = RouteDecision(
            ...     domain="query", confidence=0.5, extracted_ids={},
            ...     context={}, clarification_needed=False, reasoning="Guessing"
            ... )
            >>> decision.should_route()
            False
            >>>
            >>> # Clarification needed
            >>> decision = RouteDecision(
            ...     domain="diagnostic", confidence=0.8, extracted_ids={},
            ...     context={}, clarification_needed=True, reasoning="Need details"
            ... )
            >>> decision.should_route()
            False
        """
        return self.confidence >= 0.7 and not self.clarification_needed


@dataclass(frozen=True)
class AgentTransition:
    """
    Record of agent handoff in a conversation.

    This dataclass tracks when control passes from one agent to another,
    including the reason for the handoff and any context that was passed.
    Useful for conversation history, debugging, and analytics.

    Attributes:
        from_agent: Source agent identifier (e.g., "router", "query")
        to_agent: Target agent identifier (e.g., "query", "diagnostic")
        timestamp: When the transition occurred (UTC)
        reason: Why the handoff happened
        context_passed: Context data passed to the target agent

    Example:
        >>> transition = AgentTransition(
        ...     from_agent="router",
        ...     to_agent="query",
        ...     timestamp=datetime(2025, 11, 18, 12, 0, 0),
        ...     reason="Statement ID abc123 detected",
        ...     context_passed={"statement_id": "abc123"}
        ... )
        >>> transition.from_agent
        'router'
        >>> transition.to_agent
        'query'
    """

    from_agent: str
    to_agent: str
    timestamp: datetime
    reason: str
    context_passed: dict[str, Any]

    def __post_init__(self) -> None:
        """Validate AgentTransition after initialization."""
        # Validate from_agent is not empty
        if not self.from_agent:
            raise ValueError("from_agent cannot be empty")

        # Validate to_agent is not empty
        if not self.to_agent:
            raise ValueError("to_agent cannot be empty")

        # Validate they're different (can't transition to self)
        if self.from_agent == self.to_agent:
            raise ValueError(
                f"Cannot transition to same agent: {self.from_agent} -> {self.to_agent}"
            )

        # Validate timestamp is not in the future (allow 5 sec tolerance)
        # Handle both naive and aware datetimes
        if self.timestamp.tzinfo is not None:
            # Timestamp is timezone-aware
            now = datetime.now(UTC)
        else:
            # Timestamp is naive
            now = datetime.now(UTC)

        if (self.timestamp - now).total_seconds() > 5:
            raise ValueError(
                f"Timestamp cannot be in the future: {self.timestamp} > {now}"
            )

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary for storage.

        Returns:
            Dictionary representation
        """
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
            "context_passed": self.context_passed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentTransition":
        """
        Deserialize from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            AgentTransition instance
        """
        return cls(
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            reason=data["reason"],
            context_passed=data.get("context_passed", {}),
        )


# =============================================================================
# Helper Functions
# =============================================================================


def create_query_decision(
    extracted_ids: dict[str, str],
    confidence: float = 1.0,
    reasoning: str = "Statement ID or SQL detected",
) -> RouteDecision:
    """
    Create a RouteDecision for query domain.

    Helper function to create query routing decisions with common defaults.

    Args:
        extracted_ids: Extracted identifiers (e.g., {"statement_id": "abc123"})
        confidence: Classification confidence (default 1.0)
        reasoning: Explanation for the decision

    Returns:
        RouteDecision for query domain

    Example:
        >>> decision = create_query_decision(
        ...     extracted_ids={"statement_id": "abc123"},
        ...     confidence=1.0
        ... )
        >>> decision.domain
        'query'
        >>> decision.should_route()
        True
    """
    return RouteDecision(
        domain="query",
        confidence=confidence,
        extracted_ids=extracted_ids,
        context={},
        clarification_needed=False,
        reasoning=reasoning,
    )


def create_job_decision(
    extracted_ids: dict[str, str],
    confidence: float = 1.0,
    reasoning: str = "Job ID detected",
) -> RouteDecision:
    """
    Create a RouteDecision for job domain.

    Helper function to create job routing decisions with common defaults.

    Args:
        extracted_ids: Extracted identifiers (e.g., {"job_id": "456"})
        confidence: Classification confidence (default 1.0)
        reasoning: Explanation for the decision

    Returns:
        RouteDecision for job domain

    Example:
        >>> decision = create_job_decision(
        ...     extracted_ids={"job_id": "456"},
        ...     confidence=1.0
        ... )
        >>> decision.domain
        'job'
    """
    return RouteDecision(
        domain="job",
        confidence=confidence,
        extracted_ids=extracted_ids,
        context={},
        clarification_needed=False,
        reasoning=reasoning,
    )


def create_diagnostic_decision(
    extracted_ids: dict[str, str],
    confidence: float = 0.7,
    clarification_needed: bool = True,
    reasoning: str = "Diagnostic keywords detected",
) -> RouteDecision:
    """
    Create a RouteDecision for diagnostic domain.

    Helper function to create diagnostic routing decisions. By default,
    diagnostic decisions require clarification since troubleshooting
    typically needs more context.

    Args:
        extracted_ids: Extracted identifiers (if any)
        confidence: Classification confidence (default 0.7)
        clarification_needed: Whether to ask for more info (default True)
        reasoning: Explanation for the decision

    Returns:
        RouteDecision for diagnostic domain

    Example:
        >>> decision = create_diagnostic_decision(
        ...     extracted_ids={},
        ...     confidence=0.7
        ... )
        >>> decision.domain
        'diagnostic'
        >>> decision.clarification_needed
        True
    """
    return RouteDecision(
        domain="diagnostic",
        confidence=confidence,
        extracted_ids=extracted_ids,
        context={},
        clarification_needed=clarification_needed,
        reasoning=reasoning,
    )
