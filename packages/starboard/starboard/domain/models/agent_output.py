# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Domain agent output models.

Defines the structure of responses from domain agents including in-domain
next steps and cross-domain handoff recommendations.

Part of Phase 9: Service Catalog & Next-Step Suggestions

Examples:
    >>> output = DomainAgentOutput(
    ...     primary_answer="Query analyzed. Missing indexes detected.",
    ...     in_domain_next_steps=(InDomainNextStep(...),),
    ...     handoff_recommendations=(HandoffRecommendation(...),),
    ...     metadata={"query_id": "abc123"},
    ... )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starboard.domain.models.handoff_recommendation import HandoffRecommendation


@dataclass(frozen=True)
class InDomainNextStep:
    """Represents an in-domain continuation option.

    These are suggestions for actions the user can take while staying within
    the current domain agent. Simpler than NextStepOption (UI-level model).

    Attributes:
        id: Unique identifier for this step
        title: Short, actionable title
        description: Longer explanation of what this step does
        suggested_prompt: Suggested user message to trigger this step

    Examples:
        >>> step = InDomainNextStep(
        ...     id="add_index",
        ...     title="Add Missing Index",
        ...     description="Create index on frequently queried columns",
        ...     suggested_prompt="Add index to customer_id column",
        ... )
        >>> step.title
        'Add Missing Index'
    """

    id: str
    title: str
    description: str
    suggested_prompt: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary.

        Returns:
            Dictionary representation

        Examples:
            >>> step = InDomainNextStep(...)
            >>> data = step.to_dict()
            >>> data["id"]
            'add_index'
        """
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "suggested_prompt": self.suggested_prompt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InDomainNextStep:
        """Deserialize from dictionary.

        Args:
            data: Dictionary with step data

        Returns:
            InDomainNextStep instance

        Examples:
            >>> data = {"id": "step1", "title": "Title", ...}
            >>> step = InDomainNextStep.from_dict(data)
        """
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            suggested_prompt=data["suggested_prompt"],
        )


@dataclass(frozen=True)
class DomainAgentOutput:
    """Output structure for domain agent responses.

    This is the internal format domain agents return. The router processes
    this to generate the final AgentResponse with NextStepOptions.

    Attributes:
        primary_answer: Main response content (markdown supported)
        in_domain_next_steps: Suggestions for continuing in current domain
        handoff_recommendations: Optional cross-domain handoff suggestions
        metadata: Additional metadata (query_id, execution_time, etc.)

    Examples:
        >>> output = DomainAgentOutput(
        ...     primary_answer="Query is missing indexes.",
        ...     in_domain_next_steps=(
        ...         InDomainNextStep(
        ...             id="add_index",
        ...             title="Add Index",
        ...             description="Create missing index",
        ...             suggested_prompt="Add index",
        ...         ),
        ...     ),
        ...     handoff_recommendations=(
        ...         HandoffRecommendation(
        ...             target_domain="performance",
        ...             confidence=HandoffConfidence.HIGH,
        ...             reason="Slow query needs deep analysis",
        ...         ),
        ...     ),
        ...     metadata={"query_id": "abc123"},
        ... )
        >>> output.primary_answer
        'Query is missing indexes.'
    """

    primary_answer: str
    in_domain_next_steps: tuple[InDomainNextStep, ...] | None
    handoff_recommendations: tuple[HandoffRecommendation, ...] | None
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        """Validate domain agent output after initialization.

        Raises:
            ValueError: If primary_answer is empty
        """
        if not self.primary_answer or not self.primary_answer.strip():
            raise ValueError("primary_answer cannot be empty")

    @property
    def _agent_output(self) -> dict[str, Any]:
        """Return the nested agent_output dict from metadata."""
        return self.metadata.get("agent_output", {})

    @property
    def complete_report(self) -> dict[str, Any]:
        """Return complete report for backward compatibility with streaming system.

        The streaming system expects a `complete_report` attribute to format the
        final output. This property wraps the primary_answer in the v2 format:
        {"summary": "string", "recommendations": [...]}

        Returns:
            Dictionary with summary (string) and recommendations (list) for v2 formatting
        """
        return {
            "summary": self.primary_answer,
            "recommendations": self._agent_output.get("recommendations", []),
        }

    @property
    def status(self) -> str:
        """Return status from metadata or 'success' as default."""
        return self._agent_output.get("status", "success")

    @property
    def tokens_used(self) -> int:
        """Return tokens_used from metadata or 0 as default."""
        return self._agent_output.get("tokens_used", 0)

    @property
    def cost_usd(self) -> float:
        """Return cost_usd from metadata or 0.0 as default."""
        return self._agent_output.get("cost_usd", 0.0)

    @property
    def duration_seconds(self) -> float:
        """Return duration_seconds from metadata or 0.0 as default."""
        return self._agent_output.get("duration_seconds", 0.0)

    @property
    def steps_taken(self) -> int:
        """Return steps_taken from metadata or 0 as default."""
        return self._agent_output.get("steps_taken", 0)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary.

        Returns:
            Dictionary representation with nested objects serialized

        Examples:
            >>> output = DomainAgentOutput(...)
            >>> data = output.to_dict()
            >>> isinstance(data["in_domain_next_steps"], list)
            True
        """
        return {
            "primary_answer": self.primary_answer,
            "in_domain_next_steps": (
                [step.to_dict() for step in self.in_domain_next_steps]
                if self.in_domain_next_steps
                else None
            ),
            "handoff_recommendations": (
                [rec.to_dict() for rec in self.handoff_recommendations]
                if self.handoff_recommendations
                else None
            ),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainAgentOutput:
        """Deserialize from dictionary.

        Args:
            data: Dictionary with domain agent output data

        Returns:
            DomainAgentOutput instance

        Examples:
            >>> data = {
            ...     "primary_answer": "Answer",
            ...     "in_domain_next_steps": [...],
            ...     "handoff_recommendations": [...],
            ...     "metadata": {},
            ... }
            >>> output = DomainAgentOutput.from_dict(data)
        """
        # Deserialize in-domain steps
        in_domain_steps = tuple(
            InDomainNextStep.from_dict(step_data)
            for step_data in data.get("in_domain_next_steps", [])
        )

        # Deserialize handoff recommendations
        handoff_recs = None
        if data.get("handoff_recommendations") is not None:
            handoff_recs = tuple(
                HandoffRecommendation.from_dict(rec_data)
                for rec_data in data["handoff_recommendations"]
            )

        return cls(
            primary_answer=data["primary_answer"],
            in_domain_next_steps=in_domain_steps,
            handoff_recommendations=handoff_recs,
            metadata=data.get("metadata", {}),
        )
