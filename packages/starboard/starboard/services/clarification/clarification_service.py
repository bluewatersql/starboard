# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Clarification service for managing clarification requests and responses.

Orchestrates clarification request lifecycle, including resolution and enrichment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.repositories.clarification_repository import (
        ClarificationRepository,
    )
    from starboard.repositories.conversation_repository import (
        ConversationRepository,
    )

logger = get_logger(__name__)


class ClarificationService:
    """
    Service for managing clarification requests.

    Handles the lifecycle of clarification requests, including resolution
    and query enrichment after user response.
    """

    def __init__(
        self,
        repository: ClarificationRepository,
        conversation_repository: ConversationRepository,
    ) -> None:
        """
        Initialize clarification service.

        Args:
            repository: Clarification repository
            conversation_repository: Conversation repository
        """
        self.repository = repository
        self.conversation_repository = conversation_repository

    async def resolve_clarification(
        self,
        clarification_id: str,
        response_type: str,
        selected_option_id: str | None = None,
        custom_text: str | None = None,
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> str:
        """
        Resolve a clarification request with user response.

        Args:
            clarification_id: Clarification identifier
            response_type: Type of response ("option_selected" or "custom_text")
            selected_option_id: ID of selected option (if applicable)
            custom_text: Custom text response (if applicable)
            metadata: Additional context

        Returns:
            Enriched query string

        Raises:
            ValueError: If clarification not found or already resolved
        """
        # Retrieve clarification
        clarification = await self.repository.get_by_id(clarification_id)

        if not clarification:
            raise ValueError(f"Clarification not found: {clarification_id}")

        if clarification.resolved_at is not None:
            raise ValueError(f"Clarification already resolved: {clarification_id}")

        # Extract resolution value
        resolution_value = None
        if response_type == "option_selected":
            if not selected_option_id or not clarification.options:
                raise ValueError("selected_option_id required for option_selected")

            # Find the selected option
            selected_option = next(
                (
                    opt
                    for opt in clarification.options
                    if opt.option_id == selected_option_id
                ),
                None,
            )
            if not selected_option:
                raise ValueError(f"Option not found: {selected_option_id}")

            resolution_value = selected_option.value

        elif response_type == "custom_text":
            if not custom_text:
                raise ValueError("custom_text required for custom_text response")

            resolution_value = custom_text

        # Update resolution in database
        await self.repository.update_resolution(
            clarification_id=clarification_id,
            resolution=resolution_value,
        )

        # Enrich the original query
        # TODO(PHASE-07): Use LLM to intelligently enrich query context
        # For MVP, simple string concatenation
        enriched_query = self._enrich_query_simple(
            clarification.question, resolution_value
        )

        logger.debug(
            "clarification_resolved_service",
            clarification_id=clarification_id,
            response_type=response_type,
            enriched_query=enriched_query,
        )

        return enriched_query

    def _enrich_query_simple(self, question: str, resolution_value: Any) -> str:
        """
        Simple query enrichment (MVP implementation).

        TODO(PHASE-07): Replace with LLM-based enrichment.

        Args:
            question: Original clarification question
            resolution_value: User's response value

        Returns:
            Enriched query string
        """
        # For MVP: Just append the resolution value to the original question context
        # Example: "What warehouse size?" + "Medium" -> "warehouse size: Medium"
        return f"{question} Answer: {resolution_value}"
