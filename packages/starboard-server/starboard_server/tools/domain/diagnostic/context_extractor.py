# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Databricks context extractor for ID detection in artifacts.

This module provides:
- Regex-based detection of Databricks IDs (cluster, job, run, etc.)
- Confidence scoring per extracted ID
- Mode determination (ONLINE vs OFFLINE)

Design reference:
- changes/diagnostic_agent/UNIFIED_DESIGN.md Section 3.3
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ContextMode(str, Enum):
    """Operational mode based on available context."""

    ONLINE = "online"
    """Databricks IDs detected - can fetch additional context via API."""

    OFFLINE = "offline"
    """No Databricks IDs - must work with provided artifact only."""

    HYBRID = "hybrid"
    """Some IDs detected - can partially fetch context."""


class IdType(str, Enum):
    """Types of Databricks IDs that can be extracted."""

    CLUSTER_ID = "cluster_id"
    JOB_ID = "job_id"
    RUN_ID = "run_id"
    TASK_RUN_ID = "task_run_id"
    QUERY_ID = "query_id"
    WAREHOUSE_ID = "warehouse_id"
    NOTEBOOK_ID = "notebook_id"
    PIPELINE_ID = "pipeline_id"


@dataclass(frozen=True)
class ExtractedId:
    """A Databricks ID extracted from text.

    Attributes:
        id_type: Type of ID (cluster, job, run, etc.).
        value: The extracted ID value.
        confidence: Confidence in extraction accuracy (0.0-1.0).
        source_context: Text around the extracted ID for verification.
        line_number: Line number where ID was found (1-indexed).
    """

    id_type: IdType
    value: str
    confidence: float
    source_context: str = ""
    line_number: int = 0


@dataclass(frozen=True)
class ContextExtractionResult:
    """Result of context extraction from an artifact.

    Attributes:
        mode: Operational mode (ONLINE, OFFLINE, HYBRID).
        extracted_ids: All IDs extracted from the artifact.
        primary_cluster_id: Most likely cluster ID (if any).
        primary_job_id: Most likely job ID (if any).
        primary_run_id: Most likely run ID (if any).
        has_online_capability: True if at least one ID enables API lookup.
    """

    mode: ContextMode
    extracted_ids: tuple[ExtractedId, ...]
    primary_cluster_id: str | None = None
    primary_job_id: str | None = None
    primary_run_id: str | None = None
    has_online_capability: bool = False

    @property
    def all_cluster_ids(self) -> list[str]:
        """All extracted cluster IDs."""
        return [
            eid.value for eid in self.extracted_ids if eid.id_type == IdType.CLUSTER_ID
        ]

    @property
    def all_job_ids(self) -> list[str]:
        """All extracted job IDs."""
        return [eid.value for eid in self.extracted_ids if eid.id_type == IdType.JOB_ID]

    @property
    def all_run_ids(self) -> list[str]:
        """All extracted run IDs."""
        return [eid.value for eid in self.extracted_ids if eid.id_type == IdType.RUN_ID]


# Regex patterns for Databricks ID extraction
_ID_PATTERNS: dict[IdType, list[tuple[re.Pattern[str], float]]] = {
    IdType.CLUSTER_ID: [
        # Standard cluster ID formats
        (re.compile(r"cluster[_\s]?id[:\s=]+([0-9]{4}-[0-9]{6}-\w+)", re.I), 0.95),
        (re.compile(r"cluster[_\s]?id[:\s=]+(\d{4}-\d{6}-[a-z0-9]+)", re.I), 0.95),
        # Cluster ID in URL
        (re.compile(r"/clusters?/(\d{4}-\d{6}-[a-z0-9]+)", re.I), 0.9),
        # Standalone cluster ID pattern (lower confidence)
        (re.compile(r"\b(\d{4}-\d{6}-[a-z0-9]{5,})\b", re.I), 0.6),
    ],
    IdType.JOB_ID: [
        # Standard job ID formats
        (re.compile(r"job[_\s]?id[:\s=]+(\d+)", re.I), 0.95),
        # Job ID in URL
        (re.compile(r"/jobs/(\d+)", re.I), 0.9),
        # Run context
        (re.compile(r"run[_\s]for[_\s]job[_\s](\d+)", re.I), 0.85),
    ],
    IdType.RUN_ID: [
        # Standard run ID formats
        (re.compile(r"run[_\s]?id[:\s=]+(\d+)", re.I), 0.95),
        # Run ID in URL
        (re.compile(r"/runs/(\d+)", re.I), 0.9),
        # Run ID in log context
        (re.compile(r"run[_\s](\d{10,})", re.I), 0.7),
    ],
    IdType.TASK_RUN_ID: [
        (re.compile(r"task[_\s]?run[_\s]?id[:\s=]+(\d+)", re.I), 0.95),
    ],
    IdType.QUERY_ID: [
        # Query ID in various formats
        (re.compile(r"query[_\s]?id[:\s=]+([a-f0-9-]{36})", re.I), 0.95),
        (re.compile(r"query[_\s]?id[:\s=]+(\d+)", re.I), 0.9),
        # Query ID in URL
        (re.compile(r"/queries/([a-f0-9-]{36}|\d+)", re.I), 0.9),
    ],
    IdType.WAREHOUSE_ID: [
        # Warehouse ID formats
        (re.compile(r"warehouse[_\s]?id[:\s=]+([a-f0-9]+)", re.I), 0.95),
        (re.compile(r"warehouse/([a-f0-9]{16,})", re.I), 0.9),
    ],
    IdType.NOTEBOOK_ID: [
        (re.compile(r"notebook[_\s]?id[:\s=]+(\d+)", re.I), 0.95),
        (re.compile(r"/notebooks/(\d+)", re.I), 0.9),
    ],
    IdType.PIPELINE_ID: [
        (re.compile(r"pipeline[_\s]?id[:\s=]+([a-f0-9-]{36})", re.I), 0.95),
        (re.compile(r"/pipelines/([a-f0-9-]{36})", re.I), 0.9),
    ],
}


class DatabricksContextExtractor:
    """Extracts Databricks context (IDs, mode) from artifacts.

    Scans text for Databricks-specific identifiers that can be used
    to fetch additional context via the Databricks API.

    Example:
        >>> extractor = DatabricksContextExtractor()
        >>> result = extractor.extract("cluster_id=1234-567890-abc12")
        >>> print(result.mode)
        ContextMode.ONLINE
        >>> print(result.primary_cluster_id)
        '1234-567890-abc12'
    """

    def __init__(self, *, min_confidence: float = 0.5) -> None:
        """Initialize extractor.

        Args:
            min_confidence: Minimum confidence to include an ID.
        """
        self._min_confidence = min_confidence

    def extract(self, text: str) -> ContextExtractionResult:
        """Extract Databricks context from text.

        Args:
            text: Log or error text to extract IDs from.

        Returns:
            ContextExtractionResult with extracted IDs and mode.
        """
        extracted_ids: list[ExtractedId] = []
        lines = text.split("\n")

        for line_num, line in enumerate(lines, start=1):
            for id_type, patterns in _ID_PATTERNS.items():
                for pattern, base_confidence in patterns:
                    for match in pattern.finditer(line):
                        value = match.group(1)
                        # Adjust confidence based on context
                        confidence = self._adjust_confidence(
                            base_confidence, value, id_type, line
                        )

                        if confidence >= self._min_confidence:
                            # Get surrounding context
                            start = max(0, match.start() - 20)
                            end = min(len(line), match.end() + 20)
                            context = line[start:end]

                            extracted_ids.append(
                                ExtractedId(
                                    id_type=id_type,
                                    value=value,
                                    confidence=confidence,
                                    source_context=context,
                                    line_number=line_num,
                                )
                            )

        # Deduplicate by (id_type, value), keeping highest confidence
        unique_ids = self._deduplicate_ids(extracted_ids)

        # Determine mode and primary IDs
        mode = self._determine_mode(unique_ids)
        primary_cluster = self._get_primary_id(unique_ids, IdType.CLUSTER_ID)
        primary_job = self._get_primary_id(unique_ids, IdType.JOB_ID)
        primary_run = self._get_primary_id(unique_ids, IdType.RUN_ID)

        has_online = any(
            eid.id_type
            in (
                IdType.CLUSTER_ID,
                IdType.JOB_ID,
                IdType.RUN_ID,
                IdType.QUERY_ID,
            )
            for eid in unique_ids
        )

        return ContextExtractionResult(
            mode=mode,
            extracted_ids=tuple(unique_ids),
            primary_cluster_id=primary_cluster,
            primary_job_id=primary_job,
            primary_run_id=primary_run,
            has_online_capability=has_online,
        )

    def _adjust_confidence(
        self,
        base_confidence: float,
        value: str,
        id_type: IdType,
        line: str,
    ) -> float:
        """Adjust confidence based on context and value characteristics."""
        confidence = base_confidence

        # Boost for explicit label
        if (
            id_type == IdType.CLUSTER_ID
            and "cluster" in line.lower()
            or id_type == IdType.JOB_ID
            and "job" in line.lower()
            or id_type == IdType.RUN_ID
            and "run" in line.lower()
        ):
            confidence = min(1.0, confidence + 0.05)

        # Penalize very short values (likely false positives)
        if len(value) < 5:
            confidence -= 0.1

        # Penalize if value looks like a timestamp or version
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):  # Date format
            confidence -= 0.3

        return max(0.0, min(1.0, confidence))

    def _deduplicate_ids(self, ids: list[ExtractedId]) -> list[ExtractedId]:
        """Deduplicate IDs, keeping highest confidence per (type, value)."""
        best: dict[tuple[IdType, str], ExtractedId] = {}

        for eid in ids:
            key = (eid.id_type, eid.value)
            if key not in best or eid.confidence > best[key].confidence:
                best[key] = eid

        # Sort by confidence descending
        return sorted(best.values(), key=lambda x: -x.confidence)

    def _determine_mode(self, ids: list[ExtractedId]) -> ContextMode:
        """Determine operational mode based on extracted IDs."""
        if not ids:
            return ContextMode.OFFLINE

        # Check for high-confidence IDs that enable API lookups
        high_confidence_online_ids = [
            eid
            for eid in ids
            if eid.confidence >= 0.8
            and eid.id_type
            in (
                IdType.CLUSTER_ID,
                IdType.JOB_ID,
                IdType.RUN_ID,
            )
        ]

        if len(high_confidence_online_ids) >= 2:
            return ContextMode.ONLINE
        elif high_confidence_online_ids or ids:
            return ContextMode.HYBRID

        return ContextMode.OFFLINE

    def _get_primary_id(self, ids: list[ExtractedId], id_type: IdType) -> str | None:
        """Get the highest-confidence ID of the given type."""
        for eid in ids:  # Already sorted by confidence
            if eid.id_type == id_type:
                return eid.value
        return None

    def has_online_context(self, text: str) -> bool:
        """Quick check if text contains IDs enabling online mode.

        Args:
            text: Text to check.

        Returns:
            True if at least one online-capable ID is present.
        """
        result = self.extract(text)
        return result.has_online_capability
