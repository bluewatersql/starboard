# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Query profile evidence extractor.

Extracts diagnostic evidence from Databricks query profiles (Liquid format JSON).

This extractor handles:
- Slowest operators (by wall clock time)
- Data volume metrics (rows/bytes in/out)
- Shuffle statistics
- I/O bottlenecks (scans, writes)
- Data skew indicators

Design reference: changes/large_files/DESIGN.md Section 4.6
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.diagnostic.models import ArtifactType

logger = get_logger(__name__)

MAX_DISTILLED_SIZE = 8000


# =============================================================================
# PROCESSED ARTIFACT (local copy to avoid circular import)
# =============================================================================


@dataclass(frozen=True)
class ProcessedArtifact:
    """Result of processing a large artifact.

    Note: This is a local copy to avoid circular imports.
    The canonical definition is in large_artifact_processor.py.
    """

    artifact_type: ArtifactType
    distilled_content: str
    evidence_count: int
    original_size: int
    compression_ratio: float
    inferred_goal: str
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# QUERY PROFILE EXTRACTOR
# =============================================================================


class QueryProfileExtractor:
    """Extract diagnostic evidence from Databricks query profiles.

    Handles Liquid query profile format and extracts:
    - Slowest operators (by wall clock time)
    - Data volume metrics (rows/bytes in/out)
    - Shuffle statistics
    - I/O bottlenecks (scans, writes)
    - Data skew indicators

    Example:
        >>> extractor = QueryProfileExtractor()
        >>> result = await extractor.extract(profile_json, "Optimize query")
        >>> print(result.distilled_content)

    Attributes:
        _top_n: Number of top operators to include in analysis
    """

    def __init__(self, top_operators: int = 10) -> None:
        """Initialize extractor.

        Args:
            top_operators: Number of top operators to analyze
        """
        self._top_n = top_operators

    async def extract(
        self,
        content: str,
        inferred_goal: str,
    ) -> ProcessedArtifact:
        """Extract diagnostic evidence from query profile JSON.

        Args:
            content: Query profile JSON content
            inferred_goal: User's goal for analysis

        Returns:
            ProcessedArtifact with distilled query analysis
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("query_profile_json_parse_failed", error=str(e))
            return self._fallback(content, inferred_goal)

        # Flatten operator tree
        operators = self._flatten_operators(data)

        # Extract metrics
        slowest = self._find_slowest_operators(operators)
        scan_ops = self._find_scan_operators(operators)
        shuffle_ops = self._find_shuffle_operators(operators)

        # Build distilled content
        distilled = self._build_distilled(slowest, scan_ops, shuffle_ops, operators)

        return ProcessedArtifact(
            artifact_type=ArtifactType.QUERY_PROFILE,
            distilled_content=distilled[:MAX_DISTILLED_SIZE],
            evidence_count=len(slowest) + len(scan_ops),
            original_size=len(content),
            compression_ratio=1 - (len(distilled) / len(content)) if content else 0,
            inferred_goal=inferred_goal,
            metadata={
                "total_operators": len(operators),
                "slowest_operator": slowest[0]["name"] if slowest else None,
                "scan_count": len(scan_ops),
                "shuffle_count": len(shuffle_ops),
            },
        )

    def _flatten_operators(
        self,
        data: dict[str, Any] | list[Any],
        operators: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Recursively flatten operator tree.

        Args:
            data: Query profile data (dict or list)
            operators: Accumulator for flattened operators

        Returns:
            List of all operators in the tree
        """
        if operators is None:
            operators = []

        if isinstance(data, list):
            for item in data:
                self._flatten_operators(item, operators)
        elif isinstance(data, dict):
            if "operatorID" in data or "operatorName" in data:
                operators.append(data)
            if "children" in data and isinstance(data["children"], list):
                for child in data["children"]:
                    self._flatten_operators(child, operators)

        return operators

    def _find_slowest_operators(
        self,
        operators: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Find operators with highest wall clock time.

        Args:
            operators: Flattened list of operators

        Returns:
            Top N slowest operators sorted by wall clock time
        """
        timed_ops = []
        for op in operators:
            metrics = op.get("metrics", {})
            # Try various metric names
            wall_time = (
                metrics.get("wallClockTime")
                or metrics.get("wallClockTimeNanos", 0) / 1_000_000
                or metrics.get("totalTimeMs", 0)
                or 0
            )
            if wall_time > 0:
                timed_ops.append(
                    {
                        "id": op.get("operatorID", op.get("id", "?")),
                        "name": op.get("operatorName", op.get("name", "unknown")),
                        "wall_clock_ms": wall_time,
                        "rows_out": metrics.get(
                            "outputRows", metrics.get("numOutputRows", 0)
                        ),
                        "bytes_out": metrics.get(
                            "outputBytes", metrics.get("numOutputBytes", 0)
                        ),
                    }
                )

        return sorted(timed_ops, key=lambda x: -x["wall_clock_ms"])[: self._top_n]

    def _find_scan_operators(
        self,
        operators: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Find scan/read operators.

        Args:
            operators: Flattened list of operators

        Returns:
            List of scan operators with metrics
        """
        scans = []
        scan_names = {
            "Scan",
            "BatchScan",
            "FileScan",
            "DataSourceScan",
            "Read",
            "TableScan",
        }

        for op in operators:
            name = op.get("operatorName", op.get("name", ""))
            if any(s in name for s in scan_names):
                metrics = op.get("metrics", {})
                scans.append(
                    {
                        "id": op.get("operatorID", op.get("id", "?")),
                        "name": name,
                        "rows_read": metrics.get(
                            "outputRows", metrics.get("numOutputRows", 0)
                        ),
                        "bytes_read": metrics.get(
                            "outputBytes", metrics.get("numOutputBytes", 0)
                        ),
                        "files_read": metrics.get(
                            "filesRead", metrics.get("numFiles", 0)
                        ),
                    }
                )

        return scans

    def _find_shuffle_operators(
        self,
        operators: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Find shuffle/exchange operators.

        Args:
            operators: Flattened list of operators

        Returns:
            List of shuffle operators with metrics
        """
        shuffles = []
        shuffle_names = {"Exchange", "Shuffle", "ShuffleExchange", "BroadcastExchange"}

        for op in operators:
            name = op.get("operatorName", op.get("name", ""))
            if any(s in name for s in shuffle_names):
                metrics = op.get("metrics", {})
                shuffles.append(
                    {
                        "id": op.get("operatorID", op.get("id", "?")),
                        "name": name,
                        "shuffle_bytes": metrics.get(
                            "shuffleBytesWritten", metrics.get("dataSize", 0)
                        ),
                        "shuffle_records": metrics.get(
                            "shuffleRecordsWritten", metrics.get("numPartitions", 0)
                        ),
                    }
                )

        return shuffles

    def _build_distilled(
        self,
        slowest: list[dict[str, Any]],
        scans: list[dict[str, Any]],
        shuffles: list[dict[str, Any]],
        all_operators: list[dict[str, Any]],
    ) -> str:
        """Build distilled content for LLM.

        Args:
            slowest: Slowest operators
            scans: Scan operators
            shuffles: Shuffle operators
            all_operators: All operators

        Returns:
            Markdown-formatted distilled content
        """
        sections = [
            f"## Query Profile Analysis\n\n{len(all_operators)} operators analyzed"
        ]

        if slowest:
            sections.append("### Slowest Operators")
            for op in slowest[:5]:
                sections.append(
                    f"- {op['name']} (#{op['id']}): {op['wall_clock_ms']:.0f}ms, "
                    f"{op['rows_out']:,} rows"
                )

        if scans:
            sections.append("### Data Sources (Scans)")
            for scan in scans[:5]:
                sections.append(
                    f"- {scan['name']} (#{scan['id']}): "
                    f"{scan['rows_read']:,} rows, {scan['bytes_read']:,} bytes"
                )

        if shuffles:
            total_shuffle_bytes = sum(s.get("shuffle_bytes", 0) for s in shuffles)
            sections.append(
                f"### Shuffle Operations\n"
                f"{len(shuffles)} shuffle(s), total: {total_shuffle_bytes:,} bytes"
            )

        return "\n\n".join(sections)

    def _fallback(
        self,
        content: str,
        inferred_goal: str,
    ) -> ProcessedArtifact:
        """Fallback when parsing fails.

        Args:
            content: Original content
            inferred_goal: User's goal

        Returns:
            ProcessedArtifact with fallback content
        """
        return ProcessedArtifact(
            artifact_type=ArtifactType.QUERY_PROFILE,
            distilled_content="## Query Profile (parse failed)\n\nUnable to parse JSON.",
            evidence_count=0,
            original_size=len(content),
            compression_ratio=0.9,
            inferred_goal=inferred_goal,
            metadata={"parse_failed": True},
        )
