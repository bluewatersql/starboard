"""Clarification manager service for Phase 7 (MVP - Simplified).

This service orchestrates ambiguity detection and question generation.

MVP Scope (Phase 7.1):
- Request clarification for missing parameters
- Simple response processing (no database persistence yet)
- Basic resolution logic

Future Enhancements (Phase 7.2+):
- Database persistence via repository
- Multi-turn clarification chains
- Complex response parsing
- Entity matching integration
"""

from __future__ import annotations

from starboard_core.domain.models.clarification import (
    ClarificationRequest,
)

from starboard_server.agents.tools import ToolRegistry
from starboard_server.infra.observability.logging import get_logger
from starboard_server.services.clarification.question_generator import QuestionGenerator
from starboard_server.services.intent.ambiguity_detector import AmbiguityDetector

logger = get_logger(__name__)


class ClarificationManager:
    """
    Orchestrate clarification flow (MVP - Simplified).

    Manages ambiguity detection and question generation.
    For MVP, does not include database persistence.

    Args:
        tool_registry: Registry of available tools

    Example:
        >>> manager = ClarificationManager(tool_registry)
        >>> clarification = await manager.request_clarification(
        ...     query="create warehouse",
        ...     target_tool="create_warehouse",
        ...     conversation_id="conv_123",
        ...     message_id="msg_456",
        ... )
        >>> if clarification:
        ...     print(clarification.question)
        'What warehouse name and warehouse size would you like?'
    """

    def __init__(self, tool_registry: ToolRegistry):
        """Initialize clarification manager.

        Args:
            tool_registry: Registry with tool schemas
        """
        self.detector = AmbiguityDetector(tool_registry=tool_registry)
        self.generator = QuestionGenerator()

    def request_clarification(
        self,
        query: str,
        target_tool: str,
        conversation_id: str,
        message_id: str,
    ) -> ClarificationRequest | None:
        """
        Detect ambiguity and generate clarification if needed.

        Args:
            query: User's query string
            target_tool: Tool the query is intended for
            conversation_id: ID of conversation
            message_id: ID of message

        Returns:
            ClarificationRequest if needed, None if query is clear

        Examples:
            >>> # Ambiguous query
            >>> clarification = manager.request_clarification(
            ...     query="create warehouse",
            ...     target_tool="create_warehouse",
            ...     conversation_id="conv_123",
            ...     message_id="msg_456",
            ... )
            >>> clarification is not None
            True

            >>> # Clear query
            >>> clarification = manager.request_clarification(
            ...     query="create warehouse my-wh size Medium",
            ...     target_tool="create_warehouse",
            ...     conversation_id="conv_123",
            ...     message_id="msg_456",
            ... )
            >>> clarification is None
            True
        """
        # Detect ambiguity
        score = self.detector.detect_ambiguity(
            query=query,
            target_tool=target_tool,
        )

        # If no clarification needed, return None
        if not score.requires_clarification:
            logger.debug(
                "clarification_not_needed",
                query=query,
                target_tool=target_tool,
                overall_score=score.overall_score,
            )
            return None

        # Generate clarification question
        clarification = self.generator.generate_clarification_request(
            conversation_id=conversation_id,
            message_id=message_id,
            missing_parameters=list(score.missing_parameters),
            tool_name=target_tool,
        )

        logger.debug(
            "clarification_requested",
            clarification_id=clarification.clarification_id,
            conversation_id=conversation_id,
            target_tool=target_tool,
            missing_params=score.missing_parameters,
        )

        return clarification
