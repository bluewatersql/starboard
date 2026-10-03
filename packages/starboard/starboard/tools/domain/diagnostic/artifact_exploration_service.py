# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Artifact exploration service for agent-driven discovery.

Orchestrates intent-aware exploration of large uploaded artifacts,
delegating to type-specific explorers based on detected artifact type.

This service:
- Loads artifacts from cache
- Detects artifact type (query profile, spark event log, etc.)
- Routes to appropriate explorer
- Returns focused extraction results

Design reference: changes/large-file-agent-discovery/ARCHITECTURE.md
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Literal, Protocol

from starboard.infra.observability.logging import get_logger
from starboard.tools.domain.diagnostic.models import (
    ArtifactType,
    ExplorationResult,
)
from starboard.tools.domain.diagnostic.query_profile_explorer import (
    QueryProfileExplorer,
)
from starboard.tools.domain.diagnostic.spark_event_log_explorer import (
    SparkEventLogExplorer,
)

if TYPE_CHECKING:
    from starboard.infra.core import NamespacedCache

logger = get_logger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Large file threshold (same as in message_routes.py)
LARGE_FILE_THRESHOLD = 50 * 1024  # 50KB


# =============================================================================
# EXPLORER PROTOCOL
# =============================================================================


class ArtifactExplorer(Protocol):
    """Protocol for type-specific artifact explorers."""

    def explore(
        self,
        content: str,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> ExplorationResult:
        """Explore artifact content with focus-aware extraction.

        Args:
            content: Full artifact content
            focus: Natural language focus query
            detail_level: Level of detail to extract

        Returns:
            ExplorationResult with focused extraction
        """
        ...


# =============================================================================
# ARTIFACT EXPLORATION SERVICE
# =============================================================================


class ArtifactExplorationService:
    """Service for intent-aware artifact exploration.

    Loads artifacts from cache, detects type, and delegates to
    appropriate explorer based on artifact type.

    Example:
        >>> service = ArtifactExplorationService(cache)
        >>> result = await service.explore(
        ...     attachment_id="att_conv123_abc",
        ...     focus="range join hints, join strategies",
        ...     detail_level="detailed"
        ... )
        >>> print(result.content)

    Attributes:
        _cache: Cache for artifact storage
        _explorers: Type-specific explorers
    """

    def __init__(self, cache: NamespacedCache) -> None:
        """Initialize service.

        Args:
            cache: Namespaced cache for artifact storage (typically "attachments")
        """
        self._cache = cache
        self._explorers: dict[ArtifactType, ArtifactExplorer] = {
            ArtifactType.QUERY_PROFILE: QueryProfileExplorer(),
            ArtifactType.SPARK_EVENT_LOG: SparkEventLogExplorer(),
        }

    async def explore(
        self,
        attachment_id: str,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"] = "detailed",
    ) -> ExplorationResult:
        """Explore an artifact with intent-aware extraction.

        Args:
            attachment_id: Cache key for the artifact
            focus: Natural language description of what to focus on
            detail_level: How much detail to return

        Returns:
            ExplorationResult with focused extraction

        Raises:
            ValueError: If attachment not found in cache
        """
        # Load artifact from cache
        cached_data = await self._cache.get(attachment_id)
        if not cached_data:
            logger.warning(
                "artifact_not_found",
                attachment_id=attachment_id,
            )
            raise ValueError(f"Attachment {attachment_id} not found in cache")

        content = cached_data.get("content", "")
        if not content:
            logger.warning(
                "artifact_empty",
                attachment_id=attachment_id,
            )
            return ExplorationResult(
                focus_query=focus,
                content="## Artifact Error\n\nArtifact content is empty.",
                evidence_count=0,
                sections_found=(),
                has_more=False,
                suggested_followups=(),
            )

        filename = cached_data.get("filename", "")

        # Detect artifact type
        artifact_type = self._detect_type(content, filename)

        logger.debug(
            "exploring_artifact",
            attachment_id=attachment_id,
            artifact_type=artifact_type.value,
            focus=focus,
            detail_level=detail_level,
            content_size=len(content),
        )

        # Get explorer for this type
        explorer = self._explorers.get(artifact_type)
        if explorer:
            return await asyncio.to_thread(
                explorer.explore, content, focus, detail_level
            )

        # Fallback: generic exploration
        return self._generic_explore(content, focus, detail_level, artifact_type)

    def _detect_type(self, content: str, filename: str) -> ArtifactType:
        """Detect artifact type from content and filename.

        Args:
            content: Artifact content
            filename: Original filename

        Returns:
            Detected ArtifactType
        """
        # Check filename extension hints
        filename_lower = filename.lower()
        if filename_lower.endswith(".json"):
            # Could be query profile or spark event log
            if self._is_query_profile(content):
                return ArtifactType.QUERY_PROFILE
            if self._is_spark_event_log(content):
                return ArtifactType.SPARK_EVENT_LOG
            # Default JSON to query profile
            return ArtifactType.QUERY_PROFILE

        if filename_lower.endswith((".log", ".txt")):
            if self._is_spark_event_log(content):
                return ArtifactType.SPARK_EVENT_LOG
            return ArtifactType.LOGS

        # Check content patterns
        content_stripped = content.strip()

        # JSON content
        if content_stripped.startswith("{") or content_stripped.startswith("["):
            if self._is_query_profile(content):
                return ArtifactType.QUERY_PROFILE
            if self._is_spark_event_log(content):
                return ArtifactType.SPARK_EVENT_LOG

        # EXPLAIN plan
        if "== Physical Plan ==" in content or "== Parsed Logical Plan ==" in content:
            return ArtifactType.EXPLAIN_PLAN

        # Stack trace
        if "Traceback (most recent call last)" in content or "at org." in content:
            return ArtifactType.STACK_TRACE

        # Default
        return ArtifactType.UNKNOWN

    def _is_query_profile(self, content: str) -> bool:
        """Check if content is a Databricks query profile.

        Supports both Liquid format and standard format.

        Args:
            content: Content to check

        Returns:
            True if content is a query profile
        """
        content_stripped = content.strip()
        if not content_stripped.startswith("{") and not content_stripped.startswith(
            "["
        ):
            return False

        try:
            data = json.loads(content_stripped[:10000])  # Parse just first 10KB

            # Liquid format indicators
            if isinstance(data, dict):
                if "graphs" in data and "query" in data:
                    return True
                if "operatorID" in data or "operatorName" in data:
                    return True

            # Array of operators
            if isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, dict) and (
                    "operatorID" in first or "operatorName" in first
                ):
                    return True

            return False
        except json.JSONDecodeError:
            return False

    def _is_spark_event_log(self, content: str) -> bool:
        """Check if content is a Spark event log.

        Spark event logs are JSON-lines with SparkListener* events.

        Args:
            content: Content to check

        Returns:
            True if content is a Spark event log
        """
        first_line = content.split("\n", 1)[0].strip()
        if not first_line:
            return False

        try:
            event = json.loads(first_line)
            return isinstance(event, dict) and event.get("Event", "").startswith(
                "SparkListener"
            )
        except (json.JSONDecodeError, AttributeError):
            return False

    def _generic_explore(
        self,
        content: str,
        focus: str,
        detail_level: str,
        artifact_type: ArtifactType,
    ) -> ExplorationResult:
        """Generic exploration for unsupported artifact types.

        Args:
            content: Artifact content
            focus: Focus query
            detail_level: Detail level
            artifact_type: Detected artifact type

        Returns:
            ExplorationResult with basic extraction
        """
        # Simple keyword search in content
        focus_lower = focus.lower()
        focus_words = set(focus_lower.split())

        # Find lines containing focus words
        lines = content.split("\n")
        matching_lines: list[tuple[int, str]] = []

        for i, line in enumerate(lines):
            if any(word in line.lower() for word in focus_words):
                matching_lines.append((i + 1, line.strip()))

        # Build content
        parts = [
            f"## Generic Exploration: {artifact_type.value}\n",
            f"**Focus:** {focus}\n",
        ]

        if matching_lines:
            parts.append(f"### Matching Lines ({len(matching_lines)} found)\n")

            limit = (
                10
                if detail_level == "summary"
                else (30 if detail_level == "detailed" else 100)
            )
            for line_no, line_text in matching_lines[:limit]:
                # Truncate long lines
                display = line_text[:200] + "..." if len(line_text) > 200 else line_text
                parts.append(f"- Line {line_no}: `{display}`")

            if len(matching_lines) > limit:
                parts.append(f"\n*...and {len(matching_lines) - limit} more matches*")
        else:
            parts.append(f"No lines matching '{focus}' found in content.")

        return ExplorationResult(
            focus_query=focus,
            content="\n".join(parts),
            evidence_count=len(matching_lines),
            sections_found=("search",),
            has_more=detail_level != "exhaustive" and len(matching_lines) > 30,
            suggested_followups=(),
        )


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ["ArtifactExplorationService"]
