# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Specialist context builder for domain agent routing.

Builds context dictionaries for specialist agents by combining
shared context with routing-specific information.

Follows Python AI Agent Engineering Standards:
- Single responsibility (context building only)
- Pure function design
- Type hints on all functions
- Explicit inputs/outputs
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starboard.agents.routing.routing_models import RouteDecision
    from starboard.agents.state.shared_context import SharedAgentContext


class SpecialistContextBuilder:
    """
    Builds context dictionaries for specialist domain agents.

    Combines shared conversation context with routing-specific
    information (domain, extracted IDs, reasoning, confidence).

    Design:
    - Pure function (no side effects)
    - Merges shared context dict with routing metadata
    - Provides specialist agents with full context

    Example:
        ```python
        builder = SpecialistContextBuilder()

        specialist_context = builder.build(
            shared_context=context,
            route_decision=decision,
        )

        # specialist_context includes:
        # - All shared context fields
        # - domain, extracted_ids, route_reasoning, route_confidence
        ```
    """

    def build(
        self,
        shared_context: SharedAgentContext,
        route_decision: RouteDecision,
    ) -> dict[str, Any]:
        """
        Build context dictionary for specialist agent.

        Combines shared context with routing-specific information
        to provide specialist agents with complete context.

        Args:
            shared_context: Shared conversation context
            route_decision: Routing decision from intent classifier

        Returns:
            Dictionary with complete context for specialist agent:
            - All fields from shared_context.to_dict()
            - domain: Routed domain name
            - extracted_ids: IDs extracted during routing
            - route_reasoning: Why this domain was chosen
            - route_confidence: Confidence score (0.0-1.0)

        Example:
            >>> builder = SpecialistContextBuilder()
            >>> context = builder.build(shared_ctx, route_decision)
            >>> print(context.keys())
            dict_keys(['conversation_id', 'user_id', 'conversation_history',
                       'working_memory', 'agent_transitions', 'metadata',
                       'domain', 'extracted_ids', 'route_reasoning',
                       'route_confidence', 'available_artifacts'])
        """
        context = {
            **shared_context.to_dict(),
            "domain": route_decision.domain,
            "extracted_ids": route_decision.extracted_ids,
            "route_reasoning": route_decision.reasoning,
            "route_confidence": route_decision.confidence,
        }

        # Add available artifacts from large file attachments
        large_file_attachments = route_decision.context.get("large_file_attachments")
        if large_file_attachments:
            context["available_artifacts"] = [
                self._build_artifact_metadata(att) for att in large_file_attachments
            ]

        return context

    def _build_artifact_metadata(self, attachment: dict[str, Any]) -> dict[str, Any]:
        """Build lightweight metadata for agent context.

        Args:
            attachment: Attachment dict from route decision

        Returns:
            Artifact metadata dict for agent context
        """
        return {
            "attachment_id": attachment.get("id", ""),
            "filename": attachment.get("filename", "unknown"),
            "size_bytes": attachment.get("size", 0),
            "detected_type": attachment.get("detected_type", "unknown"),
            "preview": attachment.get("content_preview", "")[:500],
        }
