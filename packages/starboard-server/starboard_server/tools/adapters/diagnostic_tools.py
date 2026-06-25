# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Diagnostic tools adapter for agent-driven exploration.

Provides tools for the diagnostic agent to explore large uploaded artifacts
with intent-aware extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.adapters.base import BaseToolAdapter
from starboard_server.tools.domain.diagnostic.artifact_exploration_service import (
    ArtifactExplorationService,
)

if TYPE_CHECKING:
    from starboard_server.infra.core import NamespacedCache
    from starboard_server.infra.observability.events import EventEmitter

logger = get_logger(__name__)


class DiagnosticTools(BaseToolAdapter):
    """Async reasoning interface for diagnostic operations.

    Provides intent-aware exploration of large uploaded artifacts
    like query profiles, Spark event logs, and EXPLAIN plans.

    Example:
        >>> tools = DiagnosticTools(cache, events=events)
        >>> result = await tools.explore_artifact(
        ...     attachment_id="att_conv123_abc",
        ...     focus="range join hints, join strategies",
        ... )
        >>> print(result["content"])
    """

    def __init__(
        self,
        attachments_cache: NamespacedCache,
        *,
        events: EventEmitter | None = None,
    ) -> None:
        """Initialize diagnostic tools.

        Args:
            attachments_cache: Namespaced cache for artifact storage
            events: Optional event emitter for status updates
        """
        super().__init__(events=events)
        self._exploration_service = ArtifactExplorationService(attachments_cache)

    async def explore_artifact(
        self,
        attachment_id: str,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"] = "detailed",
    ) -> dict[str, Any]:
        """Explore a large uploaded artifact with intent-aware extraction.

        Use this to extract specific sections from large files (query profiles,
        Spark event logs, etc.) based on the user's question context.

        Args:
            attachment_id: The attachment ID to explore (from available_artifacts)
            focus: Natural language description of what to focus on
            detail_level: How much detail to return (summary/detailed/exhaustive)

        Returns:
            Dict with extracted content and metadata:
            - content: Markdown-formatted focused extraction
            - evidence_count: Number of evidence items found
            - sections_found: List of section types found
            - has_more: Whether more detail is available
            - suggested_followups: Suggested focus queries

        Raises:
            ValueError: If attachment not found in cache
        """
        logger.debug(
            "exploring_artifact",
            extra={
                "attachment_id": attachment_id,
                "focus": focus,
                "detail_level": detail_level,
            },
        )

        try:
            result = await self._exploration_service.explore(
                attachment_id=attachment_id,
                focus=focus,
                detail_level=detail_level,
            )

            return result.to_dict()

        except ValueError as e:
            logger.warning(
                "explore_artifact_failed",
                extra={"attachment_id": attachment_id, "error": str(e)},
            )
            return {
                "content": f"## Exploration Failed\n\nError: {e!s}",
                "evidence_count": 0,
                "sections_found": [],
                "has_more": False,
                "suggested_followups": [],
                "error": str(e),
                "error_code": "tool_error",
            }
