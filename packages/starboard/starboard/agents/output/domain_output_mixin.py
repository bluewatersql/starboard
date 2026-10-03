# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Base mixin for domain agents to generate structured outputs.

This mixin provides a standard interface for domain agents to build
DomainAgentOutput with in-domain steps and cross-domain handoff recommendations.

Part of Phase 9: Service Catalog & Next-Step Suggestions integration.

Usage:
    >>> class QueryAgent(DomainAgentOutputMixin):
    ...     async def execute(self, query: str) -> DomainAgentOutput:
    ...         # ... agent logic ...
    ...         handoffs = self._suggest_handoffs(analysis)
    ...         return self.build_domain_output(
    ...             primary_answer=response_text,
    ...             handoff_recommendations=handoffs
    ...         )
"""

from __future__ import annotations

from typing import Any

from starboard.domain.models.agent_output import (
    DomainAgentOutput,
    InDomainNextStep,
)
from starboard.domain.models.handoff_recommendation import (
    HandoffConfidence,
    HandoffRecommendation,
)
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


class DomainAgentOutputMixin:
    """
    Mixin providing structured output generation for domain agents.

    This mixin standardizes how domain agents create DomainAgentOutput,
    ensuring consistent structure and reducing code duplication.

    Methods:
        build_domain_output: Create standardized DomainAgentOutput
        suggest_compute_handoff: Helper for compute resource handoffs
        suggest_diagnostic_handoff: Helper for diagnostic handoffs
        suggest_table_handoff: Helper for table-related handoffs

    Example:
        >>> class MyAgent(DomainAgentOutputMixin):
        ...     async def execute(self, query: str) -> DomainAgentOutput:
        ...         analysis = self.analyze(query)
        ...
        ...         # Suggest handoffs if needed
        ...         handoffs = []
        ...         if analysis.is_slow:
        ...             handoffs.append(
        ...                 self.suggest_compute_handoff(
        ...                     "Query performance may improve with compute optimization",
        ...                     HandoffConfidence.MEDIUM,
        ...                     {"query_type": "aggregation"}
        ...                 )
        ...             )
        ...
        ...         return self.build_domain_output(
        ...             primary_answer="Query analysis complete",
        ...             handoff_recommendations=handoffs
        ...         )
    """

    def build_domain_output(
        self,
        primary_answer: str,
        in_domain_steps: list[InDomainNextStep] | None = None,
        handoff_recommendations: list[HandoffRecommendation] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DomainAgentOutput:
        """
        Build standardized DomainAgentOutput.

        Args:
            primary_answer: Main response text for the user
            in_domain_steps: Optional list of in-domain next-step suggestions
            handoff_recommendations: Optional list of cross-domain handoff suggestions
            metadata: Optional metadata about the response

        Returns:
            DomainAgentOutput with structured data

        Example:
            >>> output = self.build_domain_output(
            ...     primary_answer="Query optimized successfully",
            ...     in_domain_steps=[
            ...         InDomainNextStep(
            ...             id="explain_plan",
            ...             title="Explain query plan",
            ...             description="See detailed execution plan"
            ...         )
            ...     ],
            ...     handoff_recommendations=[
            ...         HandoffRecommendation(
            ...             target_domain="compute",
            ...             confidence=HandoffConfidence.MEDIUM,
            ...             reason="Cluster configuration may improve performance"
            ...         )
            ...     ]
            ... )
        """
        # Convert lists to tuples (immutable)
        in_domain_tuple = tuple(in_domain_steps) if in_domain_steps else None
        handoff_tuple = (
            tuple(handoff_recommendations) if handoff_recommendations else None
        )

        output = DomainAgentOutput(
            primary_answer=primary_answer,
            in_domain_next_steps=in_domain_tuple,
            handoff_recommendations=handoff_tuple,
            metadata=metadata or {},
        )

        # Log output structure for observability
        logger.debug(
            "domain_output_built",
            agent=self.__class__.__name__,
            in_domain_count=len(in_domain_steps or []),
            handoff_count=len(handoff_recommendations or []),
            has_metadata=bool(metadata),
        )

        return output

    def suggest_compute_handoff(
        self,
        reason: str,
        confidence: HandoffConfidence = HandoffConfidence.MEDIUM,
        context: dict[str, Any] | None = None,
    ) -> HandoffRecommendation:
        """
        Create handoff recommendation for cluster domain.

        Args:
            reason: Why this handoff is suggested
            confidence: Confidence level (LOW, MEDIUM, HIGH)
            context: Optional context to pass to cluster agent

        Returns:
            HandoffRecommendation for cluster domain

        Example:
            >>> handoff = self.suggest_compute_handoff(
            ...     "Cluster may be under-provisioned for this workload",
            ...     HandoffConfidence.HIGH,
            ...     {"cluster_id": "cluster-123", "workload_type": "batch"}
            ... )
        """
        return HandoffRecommendation(
            target_domain="cluster",
            confidence=confidence,
            reason=reason,
            context_to_pass=context or {},
        )

    def suggest_diagnostic_handoff(
        self,
        reason: str,
        confidence: HandoffConfidence = HandoffConfidence.MEDIUM,
        context: dict[str, Any] | None = None,
    ) -> HandoffRecommendation:
        """
        Create handoff recommendation for diagnostic domain.

        Args:
            reason: Why this handoff is suggested
            confidence: Confidence level (LOW, MEDIUM, HIGH)
            context: Optional context to pass to diagnostic agent

        Returns:
            HandoffRecommendation for diagnostic domain

        Example:
            >>> handoff = self.suggest_diagnostic_handoff(
            ...     "Query failure requires deeper investigation",
            ...     HandoffConfidence.HIGH,
            ...     {"error_code": "TIMEOUT", "statement_id": "stmt-456"}
            ... )
        """
        return HandoffRecommendation(
            target_domain="diagnostic",
            confidence=confidence,
            reason=reason,
            context_to_pass=context or {},
        )

    def suggest_table_handoff(
        self,
        reason: str,
        confidence: HandoffConfidence = HandoffConfidence.MEDIUM,
        context: dict[str, Any] | None = None,
    ) -> HandoffRecommendation:
        """
        Create handoff recommendation for table domain.

        Args:
            reason: Why this handoff is suggested
            confidence: Confidence level (LOW, MEDIUM, HIGH)
            context: Optional context to pass to table agent

        Returns:
            HandoffRecommendation for table domain

        Example:
            >>> handoff = self.suggest_table_handoff(
            ...     "Table statistics may be outdated",
            ...     HandoffConfidence.MEDIUM,
            ...     {"table_name": "main.users", "last_analyzed": "2023-01-01"}
            ... )
        """
        return HandoffRecommendation(
            target_domain="tables",
            confidence=confidence,
            reason=reason,
            context_to_pass=context or {},
        )

    def suggest_query_handoff(
        self,
        reason: str,
        confidence: HandoffConfidence = HandoffConfidence.MEDIUM,
        context: dict[str, Any] | None = None,
    ) -> HandoffRecommendation:
        """
        Create handoff recommendation for query optimization domain.

        Args:
            reason: Why this handoff is suggested
            confidence: Confidence level (LOW, MEDIUM, HIGH)
            context: Optional context to pass to query agent

        Returns:
            HandoffRecommendation for query domain

        Example:
            >>> handoff = self.suggest_query_handoff(
            ...     "SQL query may benefit from optimization",
            ...     HandoffConfidence.HIGH,
            ...     {"query_pattern": "full_table_scan"}
            ... )
        """
        return HandoffRecommendation(
            target_domain="query",
            confidence=confidence,
            reason=reason,
            context_to_pass=context or {},
        )

    def suggest_job_handoff(
        self,
        reason: str,
        confidence: HandoffConfidence = HandoffConfidence.MEDIUM,
        context: dict[str, Any] | None = None,
    ) -> HandoffRecommendation:
        """
        Create handoff recommendation for job domain.

        Args:
            reason: Why this handoff is suggested
            confidence: Confidence level (LOW, MEDIUM, HIGH)
            context: Optional context to pass to job agent

        Returns:
            HandoffRecommendation for job domain

        Example:
            >>> handoff = self.suggest_job_handoff(
            ...     "Job configuration may be inefficient",
            ...     HandoffConfidence.MEDIUM,
            ...     {"job_id": "job-789", "job_type": "scheduled"}
            ... )
        """
        return HandoffRecommendation(
            target_domain="jobs",
            confidence=confidence,
            reason=reason,
            context_to_pass=context or {},
        )
