# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Large artifact processor for incremental discovery.

Orchestrates detection, extraction, and summarization of large uploaded files
to fit within LLM context limits while preserving diagnostic value.

This module provides:
- Artifact type detection (logs, Spark event logs, query profiles, EXPLAIN plans)
- Evidence extraction using existing extractors
- Distilled content generation for LLM context

Event emission (progress updates via ThinkingEvents) should be handled
by the calling code (e.g., MultiAgentConversationManager).

Design reference: changes/large_files/DESIGN.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.diagnostic.artifact_detector import ArtifactDetector
from starboard_server.tools.domain.diagnostic.artifact_summarizer import (
    ArtifactSummarizer,
)
from starboard_server.tools.domain.diagnostic.evidence_extractor import (
    EvidenceWindowExtractor,
)
from starboard_server.tools.domain.diagnostic.models import ArtifactType

logger = get_logger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Processing limits
MAX_DISTILLED_SIZE = 8000  # ~2K tokens for distilled content
CHUNK_SIZE = 100_000  # 100KB chunks for processing
LARGE_FILE_THRESHOLD = 50 * 1024  # 50KB threshold for "large" files


# =============================================================================
# PROCESSED ARTIFACT RESULT
# =============================================================================


@dataclass(frozen=True)
class ProcessedArtifact:
    """Result of processing a large artifact.

    Contains the distilled content suitable for LLM context,
    along with metadata about the processing.

    Attributes:
        artifact_type: Detected artifact type
        distilled_content: Compact summary fitting LLM context limits
        evidence_count: Number of evidence windows extracted
        original_size: Original file size in bytes
        compression_ratio: How much content was compressed (0-1)
        inferred_goal: Automatically inferred user goal based on artifact type
        metadata: Additional metadata (IDs extracted, patterns matched, etc.)
    """

    artifact_type: ArtifactType
    distilled_content: str
    evidence_count: int
    original_size: int
    compression_ratio: float
    inferred_goal: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the processed artifact.
        """
        return {
            "artifact_type": self.artifact_type.value,
            "distilled_content": self.distilled_content,
            "evidence_count": self.evidence_count,
            "original_size": self.original_size,
            "compression_ratio": self.compression_ratio,
            "inferred_goal": self.inferred_goal,
            "metadata": self.metadata,
        }


# =============================================================================
# INTERNAL DETECTION RESULT
# =============================================================================


@dataclass
class _DetectionResult:
    """Internal detection result for specialized artifact types."""

    artifact_type: ArtifactType
    confidence: float
    signals: tuple[str, ...] = ()


# =============================================================================
# LARGE ARTIFACT PROCESSOR
# =============================================================================


class LargeArtifactProcessor:
    """Process large artifacts through incremental discovery.

    Orchestrates:
    1. Type detection (logs, traces, event logs, profiles)
    2. Evidence extraction (chunked for memory efficiency)
    3. Summarization (extractive or abstractive)

    The processor uses existing extractors from the diagnostic domain
    and adds specialized handling for Spark event logs and query profiles.

    Event emission (progress updates via ThinkingEvents) should be handled
    by the calling code (e.g., MultiAgentConversationManager).

    Example:
        >>> processor = LargeArtifactProcessor()
        >>> result = await processor.process(
        ...     content=log_content,
        ...     filename="spark_driver.log",
        ...     user_goal="Find OOM errors"
        ... )
        >>> print(result.artifact_type, result.evidence_count)

    Attributes:
        _max_distilled_size: Maximum size of distilled content
        _detector: Artifact type detector
        _evidence_extractor: Evidence window extractor
        _summarizer: Artifact summarizer
    """

    def __init__(
        self,
        *,
        max_distilled_size: int = MAX_DISTILLED_SIZE,
    ) -> None:
        """Initialize the large artifact processor.

        Args:
            max_distilled_size: Maximum characters in distilled output
        """
        self._max_distilled_size = max_distilled_size

        # Initialize extractors
        self._detector = ArtifactDetector()
        self._evidence_extractor = EvidenceWindowExtractor(max_windows=15)
        self._summarizer = ArtifactSummarizer()

        # Lazy-loaded specialized extractors (avoid circular imports)
        self._spark_extractor: Any = None
        self._query_profile_extractor: Any = None

    async def process(
        self,
        content: str,
        filename: str = "",
        user_goal: str | None = None,
    ) -> ProcessedArtifact:
        """Process a large artifact directly.

        Processes content and returns the distilled result.
        Event emission (ThinkingEvents) should be handled by the caller.

        Args:
            content: File content to process
            filename: Original filename (used for type detection)
            user_goal: Optional explicit goal; inferred from artifact type if not provided

        Returns:
            ProcessedArtifact with distilled content

        Example:
            >>> processor = LargeArtifactProcessor()
            >>> result = await processor.process(
            ...     content=log_content,
            ...     filename="spark_event.log",
            ...     user_goal="Find OOM errors"
            ... )
            >>> print(result.artifact_type, result.evidence_count)
        """
        original_size = len(content)

        # Step 1: Detect artifact type
        detection = self._detect_artifact_type(content, filename)
        inferred_goal = user_goal or self._infer_goal(detection.artifact_type)

        logger.debug(
            "artifact_detected: kind=%s confidence=%s filename=%s",
            detection.artifact_type.value,
            detection.confidence,
            filename,
        )

        # Step 2: Extract evidence (type-specific)
        if detection.artifact_type == ArtifactType.SPARK_EVENT_LOG:
            result = await self._process_spark_event_log(content, inferred_goal)
        elif detection.artifact_type == ArtifactType.QUERY_PROFILE:
            result = await self._process_query_profile(content, inferred_goal)
        elif detection.artifact_type == ArtifactType.EXPLAIN_PLAN:
            result = await self._process_explain_text(content, inferred_goal)
        else:
            result = await self._process_general_artifact(
                content, detection, inferred_goal
            )

        logger.info(
            "artifact_processed: kind=%s evidence_count=%d original_size=%d distilled_size=%d compression_ratio=%.2f",
            result.artifact_type.value,
            result.evidence_count,
            original_size,
            len(result.distilled_content),
            result.compression_ratio,
        )

        return result

    # =========================================================================
    # TYPE DETECTION
    # =========================================================================

    def _detect_artifact_type(self, content: str, filename: str) -> _DetectionResult:  # noqa: ARG002
        """Detect artifact type with special handling for structured formats.

        Checks for specialized formats first (Spark event logs, query profiles,
        EXPLAIN plans), then falls back to the general artifact detector.

        Args:
            content: File content
            filename: Original filename

        Returns:
            Detection result with type, confidence, and signals
        """
        # Check for Spark event log (JSON-lines with SparkListener*)
        if self._is_spark_event_log(content):
            return _DetectionResult(
                artifact_type=ArtifactType.SPARK_EVENT_LOG,
                confidence=0.95,
                signals=("spark_listener_event",),
            )

        # Check for query profile (Liquid JSON format)
        if self._is_query_profile(content):
            return _DetectionResult(
                artifact_type=ArtifactType.QUERY_PROFILE,
                confidence=0.95,
                signals=("query_profile_json",),
            )

        # Check for EXPLAIN plan text
        if self._is_explain_text(content):
            return _DetectionResult(
                artifact_type=ArtifactType.EXPLAIN_PLAN,
                confidence=0.90,
                signals=("explain_plan_sections",),
            )

        # Use standard detector for logs, traces, code, errors
        detection = self._detector.detect(content)
        return _DetectionResult(
            artifact_type=detection.artifact_type,
            confidence=detection.confidence,
            signals=detection.signals,
        )

    def _is_spark_event_log(self, content: str) -> bool:
        """Check if content is a Spark event log (JSON-lines format).

        Spark event logs are JSON-lines where each line contains an
        event with an "Event" field starting with "SparkListener".

        Args:
            content: File content to check

        Returns:
            True if content appears to be a Spark event log
        """
        first_line = content.split("\n", 1)[0].strip()
        if not first_line:
            return False
        try:
            event = json.loads(first_line)
            event_type = event.get("Event", "")
            return isinstance(event_type, str) and event_type.startswith(
                "SparkListener"
            )
        except (json.JSONDecodeError, AttributeError, TypeError):
            return False

    def _is_query_profile(self, content: str) -> bool:
        """Check if content is a Databricks query profile (Liquid format).

        Query profiles are JSON with operatorID/operatorName fields.

        Args:
            content: File content to check

        Returns:
            True if content appears to be a query profile
        """
        content = content.strip()
        if not content.startswith("{") and not content.startswith("["):
            return False
        try:
            data = json.loads(content)
            # Liquid format has operatorID, operatorName at root or in array
            if isinstance(data, dict):
                return "operatorID" in data or "operatorName" in data
            if isinstance(data, list) and data:
                first = data[0]
                return isinstance(first, dict) and (
                    "operatorID" in first or "operatorName" in first
                )
            return False
        except json.JSONDecodeError:
            return False

    def _is_explain_text(self, content: str) -> bool:
        """Check if content is EXPLAIN plan text.

        EXPLAIN output contains section headers like "== Physical Plan ==".

        Args:
            content: File content to check

        Returns:
            True if content appears to be EXPLAIN output
        """
        return (
            "== Physical Plan ==" in content or "== Parsed Logical Plan ==" in content
        )

    # =========================================================================
    # GOAL INFERENCE
    # =========================================================================

    def _infer_goal(self, artifact_type: ArtifactType) -> str:
        """Infer user goal from artifact type.

        Provides a sensible default goal based on what the user uploaded.

        Args:
            artifact_type: Detected artifact type

        Returns:
            Human-readable goal string
        """
        goal_map = {
            ArtifactType.STACK_TRACE: "Diagnose the root cause of this error",
            ArtifactType.LOGS: "Identify errors and performance issues in these logs",
            ArtifactType.GC_LOGS: "Analyze memory usage and GC behavior",
            ArtifactType.ERROR_MESSAGE: "Diagnose and resolve this error",
            ArtifactType.CODE: "Review this code for issues and optimization opportunities",
            ArtifactType.SPARK_EVENT_LOG: "Analyze Spark job performance and failures",
            ArtifactType.QUERY_PROFILE: "Analyze query performance and identify bottlenecks",
            ArtifactType.EXPLAIN_PLAN: "Analyze query execution plan and suggest optimizations",
            ArtifactType.MIXED: "Analyze this artifact for diagnostic insights",
        }
        return goal_map.get(artifact_type, "Analyze and provide insights")

    # =========================================================================
    # ARTIFACT PROCESSING
    # =========================================================================

    async def _process_general_artifact(
        self,
        content: str,
        detection: _DetectionResult,
        inferred_goal: str,
    ) -> ProcessedArtifact:
        """Process logs, traces, code, error messages.

        Uses existing extractors for evidence window extraction
        and summarization.

        Args:
            content: Artifact content
            detection: Detection result
            inferred_goal: Inferred or provided goal

        Returns:
            ProcessedArtifact with distilled content
        """
        # Extract evidence windows
        extraction = self._evidence_extractor.extract(content)

        # Summarize
        summary = self._summarizer.summarize(
            content,
            mode="extractive",
            max_length=self._max_distilled_size,
        )

        # Combine evidence + summary
        distilled_parts = []

        if extraction.primary_evidence:
            distilled_parts.append(
                f"## Primary Evidence ({extraction.primary_evidence.evidence_type.value})\n"
                f"Lines {extraction.primary_evidence.line_start}-"
                f"{extraction.primary_evidence.line_end}:\n"
                f"```\n{extraction.primary_evidence.content}\n```"
            )

        if summary.summary:
            distilled_parts.append(f"## Summary\n{summary.summary}")

        distilled_content = "\n\n".join(distilled_parts)

        return ProcessedArtifact(
            artifact_type=detection.artifact_type,
            distilled_content=distilled_content[: self._max_distilled_size],
            evidence_count=extraction.window_count,
            original_size=len(content),
            compression_ratio=summary.compression_ratio,
            inferred_goal=inferred_goal,
            metadata={
                "has_fatal": extraction.has_fatal,
                "detection_signals": list(detection.signals),
            },
        )

    async def _process_spark_event_log(
        self,
        content: str,
        inferred_goal: str,
    ) -> ProcessedArtifact:
        """Process Spark event logs using starboard-log-parser.

        Lazily loads the SparkEventLogExtractor to avoid circular imports.

        Args:
            content: Spark event log content (JSON-lines)
            inferred_goal: Inferred or provided goal

        Returns:
            ProcessedArtifact with distilled Spark analysis
        """
        # Lazy import to avoid circular dependencies
        if self._spark_extractor is None:
            from starboard_server.tools.domain.diagnostic.spark_event_log_extractor import (
                SparkEventLogExtractor,
            )

            self._spark_extractor = SparkEventLogExtractor()

        return await self._spark_extractor.extract(content, inferred_goal)

    async def _process_query_profile(
        self,
        content: str,
        inferred_goal: str,
    ) -> ProcessedArtifact:
        """Process Databricks query profiles (Liquid format).

        Lazily loads the QueryProfileExtractor to avoid circular imports.

        Args:
            content: Query profile JSON content
            inferred_goal: Inferred or provided goal

        Returns:
            ProcessedArtifact with distilled query analysis
        """
        if self._query_profile_extractor is None:
            from starboard_server.tools.domain.diagnostic.query_profile_extractor import (
                QueryProfileExtractor,
            )

            self._query_profile_extractor = QueryProfileExtractor()

        return await self._query_profile_extractor.extract(content, inferred_goal)

    async def _process_explain_text(
        self,
        content: str,
        inferred_goal: str,
    ) -> ProcessedArtifact:
        """Process EXPLAIN plan text.

        Uses existing transformer utilities for plan parsing.

        Args:
            content: EXPLAIN plan text
            inferred_goal: Inferred or provided goal

        Returns:
            ProcessedArtifact with distilled plan analysis
        """
        from starboard_server.tools.domain.query.transformers import (
            split_explain_sections,
        )

        sections = split_explain_sections(content)
        physical_lines = sections.get("physical", [])

        if physical_lines:
            # Create a compact representation by joining the physical lines
            compact = "\n".join(physical_lines[:100])  # Take first 100 lines
            distilled = f"## Physical Plan Summary\n{compact}"
        else:
            # Fallback: just truncate
            distilled = f"## EXPLAIN Output\n{content[: self._max_distilled_size]}"

        return ProcessedArtifact(
            artifact_type=ArtifactType.EXPLAIN_PLAN,
            distilled_content=distilled[: self._max_distilled_size],
            evidence_count=1,
            original_size=len(content),
            compression_ratio=1 - (len(distilled) / len(content)) if content else 0,
            inferred_goal=inferred_goal,
            metadata={"sections_found": list(sections.keys())},
        )

    # =========================================================================
    # UTILITIES
    # =========================================================================

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format byte size for human readability.

        Args:
            size_bytes: Size in bytes

        Returns:
            Human-readable size string (e.g., "1.5MB")
        """
        if size_bytes < 1024:
            return f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f}MB"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_large_file(size_bytes: int) -> bool:
    """Check if a file should be treated as a large file.

    Args:
        size_bytes: File size in bytes

    Returns:
        True if file exceeds the large file threshold
    """
    return size_bytes >= LARGE_FILE_THRESHOLD
