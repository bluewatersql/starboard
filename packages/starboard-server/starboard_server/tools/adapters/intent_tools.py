# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Reasoning interface for intent resolution tools.

This module provides LLM-facing tools for intent resolution.
Uses IntentResolver domain logic directly - no intermediate service layer.
"""

from starboard_server.infra.observability.events import EventEmitter
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.adapters.base import BaseToolAdapter
from starboard_server.tools.domain.intent.models import IntentResolutionInput
from starboard_server.tools.domain.intent.resolver import IntentResolver

logger = get_logger(__name__)


class IntentTools(BaseToolAdapter):
    """Reasoning interface for intent resolution operations.

    Provides LLM-facing tools for analyzing user input and classifying intent.
    Calls IntentResolver domain logic directly - service layer was removed as
    it was a trivial pass-through.

    Architecture:
        IntentTools (adapter) → IntentResolver (domain)

    Example:
        >>> tools = IntentTools(events=events)
        >>> result = await tools.resolve_user_intent("Optimize job 12345")
    """

    def __init__(self, *, events: EventEmitter | None = None):
        """Initialize intent tools.

        Args:
            events: Optional event emitter for status updates.
        """
        super().__init__(events=events)

    async def resolve_user_intent(
        self,
        user_input: str,
        conversation_history: list[dict] | None = None,
    ) -> dict:
        """Resolve user intent from natural language input.

        Analyzes user input and conversation history to determine the primary
        optimization intent (query, job, pipeline, etc.) and extract relevant
        parameters.

        Uses a keyword-first, pattern-based approach:
        1. Detect context keywords (job, query, pipeline, etc.)
        2. Extract candidate tokens (IDs, names, etc.)
        3. Classify intent based on keywords + tokens
        4. Generate friendly conversation name

        Args:
            user_input: User's natural language input to analyze.
            conversation_history: Optional conversation context (list of dicts).

        Returns:
            Dict with intent resolution result.

        Example:
            >>> result = await tools.resolve_user_intent("Optimize job 12345")
            >>> # Returns:
            >>> # {
            >>> #   "intent": "optimize_job",
            >>> #   "confidence": 0.9,
            >>> #   "parameters": {"job_id": "12345"},
            >>> #   "reasoning": "Detected 'job' keyword with job ID 12345",
            >>> #   "suggested_friendly_name": "Job Optimization for 12345"
            >>> # }
        """
        logger.debug(
            "resolve_user_intent_called",
            user_input=user_input,
            has_history=conversation_history is not None,
        )

        # Emit start event
        if self.events:
            self.events.emit_info(
                source="intent_tools",
                message="intent_resolution_started",
                data={"user_input": user_input},
            )

        # Prepare input and call domain logic directly
        input_data = IntentResolutionInput(
            user_input=user_input,
            conversation_history=conversation_history,
        )

        result = IntentResolver.resolve_intent(input_data)

        logger.debug(
            "intent_resolved",
            intent=result.intent.value,
            confidence=result.confidence,
            parameters=result.parameters,
            friendly_name=result.suggested_friendly_name,
        )

        # Emit completion event
        if self.events:
            self.events.emit_info(
                source="intent_tools",
                message="intent_resolution_completed",
                data={
                    "intent": result.intent.value,
                    "confidence": result.confidence,
                    "parameters": result.parameters,
                },
            )

        return {
            "intent": result.intent.value,
            "confidence": result.confidence,
            "parameters": result.parameters,
            "reasoning": result.reasoning,
            "suggested_friendly_name": result.suggested_friendly_name,
            "matched_keywords": result.matched_keywords,
        }
