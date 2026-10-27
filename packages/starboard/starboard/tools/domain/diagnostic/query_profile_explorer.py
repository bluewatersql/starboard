# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
# ruff: noqa: ARG002 - Extraction methods have consistent signatures for API uniformity

"""
Intent-aware query profile explorer.

Extracts focused content from Databricks query profiles (Liquid format JSON)
based on the user's question/focus. This enables agent-driven exploration
where the agent decides what to extract based on actual user intent.

Supported focus areas:
- Joins: Join operators, algorithms, predicates, hints
- Shuffles: Exchange operators, shuffle bytes, partitions
- Scans: Scan operators, rows/bytes read, files
- Slow operators: Top operators by execution time
- Skew: Task metrics, partition variance
- Memory/Spill: Spill metrics, memory pressure

Parsing is delegated to the stdlib-only
``starboard_x.diagnostic.query_profile.parse_profile`` (D3-22): this class maps its
``QueryProfileSummary`` to focused markdown in an ``ExplorationResult``.

Design reference: changes/large-file-agent-discovery/ARCHITECTURE.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from starboard_x.diagnostic.query_profile import (
    JOIN_TAGS,
    SCAN_TAGS,
    SHUFFLE_TAGS,
    OperatorInfo,
    join_algorithm,
    parse_profile,
)

from starboard.infra.observability.logging import get_logger
from starboard.tools.domain.diagnostic.models import (
    ExplorationResult,
)

logger = get_logger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum content size by detail level
DETAIL_LIMITS = {
    "summary": 2000,
    "detailed": 10000,
    "exhaustive": 50000,
}

# Focus keyword to handler mapping
FOCUS_HANDLERS: dict[str, str] = {
    # Join-related
    "join": "_extract_joins",
    "range_join": "_extract_joins",
    "broadcast": "_extract_joins",
    "hash_join": "_extract_joins",
    "merge_join": "_extract_joins",
    "nested_loop": "_extract_joins",
    # Shuffle-related
    "shuffle": "_extract_shuffles",
    "exchange": "_extract_shuffles",
    "data_movement": "_extract_shuffles",
    "network": "_extract_shuffles",
    # Scan-related
    "scan": "_extract_scans",
    "read": "_extract_scans",
    "data_source": "_extract_scans",
    "table": "_extract_scans",
    "file": "_extract_scans",
    # Performance-related
    "slow": "_extract_by_time",
    "bottleneck": "_extract_by_time",
    "wall_clock": "_extract_by_time",
    "time": "_extract_by_time",
    "duration": "_extract_by_time",
    # Memory-related
    "skew": "_extract_skew_indicators",
    "partition": "_extract_skew_indicators",
    "distribution": "_extract_skew_indicators",
    "spill": "_extract_memory_metrics",
    "memory": "_extract_memory_metrics",
    "disk": "_extract_memory_metrics",
    # Stage-related (NEW)
    "stage": "_extract_stages",
    "task": "_extract_stages",
    "failed": "_extract_stages",
    "execution": "_extract_stages",
    # Performance overview (NEW)
    "overview": "_extract_performance_overview",
    "summary": "_extract_performance_overview",
    "performance": "_extract_performance_overview",
    "metrics": "_extract_performance_overview",
    "timing": "_extract_performance_overview",
    # Cache-related (NEW)
    "cache": "_extract_cache_metrics",
    "io": "_extract_cache_metrics",
    "bytes": "_extract_cache_metrics",
}


# =============================================================================
# HELPER DATA CLASSES
# =============================================================================


@dataclass
class ExtractionSection:
    """A section of extracted content."""

    section_type: str
    content: str
    item_count: int


# =============================================================================
# QUERY PROFILE EXPLORER
# =============================================================================


class QueryProfileExplorer:
    """Intent-aware explorer for Databricks query profiles.

    Extracts focused content from Liquid format query profiles based on
    the user's question context. Supports multiple focus areas including
    joins, shuffles, scans, performance bottlenecks, and data skew.

    Example:
        >>> explorer = QueryProfileExplorer()
        >>> result = explorer.explore(
        ...     profile_json,
        ...     focus="range join hints, join strategies",
        ...     detail_level="detailed"
        ... )
        >>> print(result.content)
        ## Join Operators (12 found)
        ...

    Attributes:
        _parsed_cache: Cache for parsed profile structures
    """

    def __init__(self) -> None:
        """Initialize explorer."""
        self._parsed_cache: dict[str, tuple[list[OperatorInfo], dict[str, Any]]] = {}

    def explore(
        self,
        content: str,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"] = "detailed",
    ) -> ExplorationResult:
        """Extract focused content based on user intent.

        Args:
            content: Query profile JSON content
            focus: Natural language description of what to focus on
            detail_level: How much detail to return

        Returns:
            ExplorationResult with focused extraction

        Raises:
            ValueError: If content cannot be parsed as JSON
        """
        try:
            operators, query_meta = self._parse_profile(content)
        except json.JSONDecodeError as e:
            logger.warning("query_profile_parse_failed: %s", e)
            return ExplorationResult(
                focus_query=focus,
                content="## Query Profile (parse failed)\n\nUnable to parse JSON.",
                evidence_count=0,
                sections_found=(),
                has_more=False,
                suggested_followups=(),
            )

        if not operators:
            return ExplorationResult(
                focus_query=focus,
                content="## Query Profile (empty)\n\nNo operators found in profile.",
                evidence_count=0,
                sections_found=(),
                has_more=False,
                suggested_followups=(),
            )

        # Determine which handlers to apply based on focus keywords
        focus_lower = focus.lower()
        sections: list[ExtractionSection] = []
        handlers_used: set[str] = set()

        for keyword, handler_name in FOCUS_HANDLERS.items():
            if keyword in focus_lower and handler_name not in handlers_used:
                handlers_used.add(handler_name)
                handler = getattr(self, handler_name)
                section = handler(operators, focus, detail_level, query_meta)
                if section and section.item_count > 0:
                    sections.append(section)

        # Fallback: if no handlers matched, use pattern search
        if not sections:
            section = self._search_by_pattern(operators, focus, detail_level)
            if section and section.item_count > 0:
                sections.append(section)

        # If still nothing, extract overview
        if not sections:
            section = self._extract_overview(operators, query_meta, detail_level)
            sections.append(section)

        # Combine sections
        combined_content = self._combine_sections(sections, detail_level, query_meta)
        section_types = tuple(s.section_type for s in sections)
        total_evidence = sum(s.item_count for s in sections)

        # Determine if more detail is available
        max_size = DETAIL_LIMITS.get(detail_level, 10000)
        has_more = detail_level != "exhaustive" and len(combined_content) >= max_size

        # Generate suggested followups
        followups = self._generate_followups(focus, section_types, operators)

        return ExplorationResult(
            focus_query=focus,
            content=combined_content,
            evidence_count=total_evidence,
            sections_found=section_types,
            has_more=has_more,
            suggested_followups=followups,
        )

    def _parse_profile(self, content: str) -> tuple[list[OperatorInfo], dict[str, Any]]:
        """Parse the profile through the stdlib parser (D3-22).

        ``starboard_x.diagnostic.query_profile.parse_profile`` reads the Liquid and
        standard shapes into a ``QueryProfileSummary``; this maps it back to the
        ``(operators, query metadata)`` pair the markdown sections render. Invalid
        JSON raises ``json.JSONDecodeError``.
        """
        content_hash = str(hash(content))
        if content_hash in self._parsed_cache:
            return self._parsed_cache[content_hash]

        summary = parse_profile(content, max_operators=None)
        query_meta: dict[str, Any] = dict(summary.query)
        if summary.format == "liquid":
            query_meta["stages"] = [dict(stage) for stage in summary.stages]
        parsed = (list(summary.operators), query_meta)
        self._parsed_cache[content_hash] = parsed
        return parsed

    def _extract_joins(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract join operators with full join conditions and keys.

        Args:
            operators: Parsed operators
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata

        Returns:
            ExtractionSection with complete join information including conditions
        """
        joins = [op for op in operators if op.tag in JOIN_TAGS]

        if not joins:
            return ExtractionSection(
                section_type="joins",
                content="## Join Operators: NONE FOUND\n\nNo join operators detected in this query plan.",
                item_count=0,
            )

        lines = [f"## Join Operators ({len(joins)} found)\n"]

        # Group by join algorithm
        by_algorithm: dict[str, list[OperatorInfo]] = {}
        for op in joins:
            algo = self._get_join_algorithm(op.tag)
            if algo not in by_algorithm:
                by_algorithm[algo] = []
            by_algorithm[algo].append(op)

        lines.append("### Join Algorithms Used\n")
        for algo, ops in sorted(by_algorithm.items(), key=lambda x: -len(x[1])):
            lines.append(f"- **{algo}**: {len(ops)} occurrence(s)")

        # Check for range join hints AND identify range join candidates
        range_join_found = False
        range_join_candidates: list[OperatorInfo] = []
        range_keywords = ["range_join", "rangejoin", "range join"]
        inequality_patterns = [">=", "<=", ">", "<", "BETWEEN"]

        for op in joins:
            # Check metadata for range join hints
            for _meta_key, meta_val in op.metadata.items():
                if isinstance(meta_val, str) and any(
                    kw in meta_val.lower() for kw in range_keywords
                ):
                    range_join_found = True
                    break
            # Check tag
            if "RANGE" in op.tag.upper():
                range_join_found = True
                break

            # Identify range join CANDIDATES (joins with inequality conditions)
            condition = op.metadata.get("CONDITION", [])
            if isinstance(condition, list):
                condition_str = " ".join(str(c) for c in condition)
            else:
                condition_str = str(condition)

            if condition_str and any(
                pat in condition_str for pat in inequality_patterns
            ):
                range_join_candidates.append(op)

        lines.append("\n### Range Join Analysis")
        if range_join_found:
            lines.append("✅ Range join hint detected in execution plan.")
        else:
            lines.append("❌ No RANGE_JOIN hints currently applied.")

        # Highlight range join candidates
        if range_join_candidates:
            lines.append(
                f"\n⚠️ **{len(range_join_candidates)} joins have inequality conditions "
                "and may benefit from RANGE_JOIN hints:**\n"
            )
            for op in range_join_candidates[:10]:  # Show top 10
                left_keys = op.metadata.get("LEFT_KEYS", [])
                right_keys = op.metadata.get("RIGHT_KEYS", [])
                condition = op.metadata.get("CONDITION", [])
                join_type = op.metadata.get("JOIN_TYPE", op.name)

                lines.append(
                    f"**Join ID {op.id}** ({self._get_join_algorithm(op.tag)})"
                )
                lines.append(f"- Type: {join_type}")
                if left_keys:
                    keys_str = (
                        ", ".join(left_keys)
                        if isinstance(left_keys, list)
                        else str(left_keys)
                    )
                    lines.append(f"- Left Keys: `{keys_str}`")
                if right_keys:
                    keys_str = (
                        ", ".join(right_keys)
                        if isinstance(right_keys, list)
                        else str(right_keys)
                    )
                    lines.append(f"- Right Keys: `{keys_str}`")
                if condition:
                    cond_str = (
                        " AND ".join(condition)
                        if isinstance(condition, list)
                        else str(condition)
                    )
                    lines.append(f"- **Condition (range candidate):** `{cond_str}`")
                lines.append("")

            if len(range_join_candidates) > 10:
                lines.append(
                    f"*...and {len(range_join_candidates) - 10} more range join candidates*\n"
                )

            # Add recommendation
            lines.append("**Recommendation:** Add RANGE_JOIN hints for these joins:")
            lines.append("```sql")
            lines.append("SELECT /*+ RANGE_JOIN(right_table, bin_size_seconds) */ ...")
            lines.append("```")
            lines.append(
                "The `bin_size` should match the typical range width "
                "(e.g., 86400 for daily ranges)."
            )

        # Full join details for detailed/exhaustive levels
        if detail_level in ("detailed", "exhaustive"):
            lines.append("\n### All Join Details\n")

            limit = 30 if detail_level == "detailed" else 200
            for i, op in enumerate(joins[:limit]):
                algo = self._get_join_algorithm(op.tag)
                join_type = op.metadata.get("JOIN_TYPE", op.name)
                left_keys = op.metadata.get("LEFT_KEYS", [])
                right_keys = op.metadata.get("RIGHT_KEYS", [])
                condition = op.metadata.get("CONDITION", [])
                build_side = op.metadata.get("JOIN_BUILD_SIDE", "")

                lines.append(f"#### Join {i + 1}: {op.name} (ID: {op.id})")
                lines.append(f"- **Algorithm:** {algo}")
                lines.append(f"- **Type:** {join_type}")
                if build_side:
                    lines.append(f"- **Build Side:** {build_side}")

                if left_keys:
                    keys_str = (
                        ", ".join(left_keys)
                        if isinstance(left_keys, list)
                        else str(left_keys)
                    )
                    lines.append(f"- **Left Keys:** `{keys_str}`")

                if right_keys:
                    keys_str = (
                        ", ".join(right_keys)
                        if isinstance(right_keys, list)
                        else str(right_keys)
                    )
                    lines.append(f"- **Right Keys:** `{keys_str}`")

                if condition:
                    cond_str = (
                        " AND ".join(condition)
                        if isinstance(condition, list)
                        else str(condition)
                    )
                    lines.append(f"- **Condition:** `{cond_str}`")

                # Add metrics if available
                wall_time = op.metrics.get(
                    "WALL_CLOCK_TIME", op.metrics.get("wallClockTime", 0)
                )
                if wall_time:
                    lines.append(
                        f"- **Wall Clock Time:** {self._format_time(wall_time)}"
                    )

                output_rows = op.metrics.get(
                    "NUMBER_OUTPUT_ROWS", op.metrics.get("numOutputRows", 0)
                )
                if output_rows:
                    lines.append(f"- **Output Rows:** {output_rows:,}")

                lines.append("")

            if len(joins) > limit:
                lines.append(f"\n*...and {len(joins) - limit} more joins*")

        return ExtractionSection(
            section_type="joins",
            content="\n".join(lines),
            item_count=len(joins),
        )

    def _extract_shuffles(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract shuffle/exchange operators.

        Args:
            operators: Parsed operators
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata

        Returns:
            ExtractionSection with shuffle information
        """
        shuffles = [op for op in operators if op.tag in SHUFFLE_TAGS]

        if not shuffles:
            return ExtractionSection(
                section_type="shuffles",
                content="## Shuffle Operations: NONE FOUND\n\nNo shuffle operators detected.",
                item_count=0,
            )

        lines = [f"## Shuffle Operations ({len(shuffles)} found)\n"]

        # Overall network stats from query metadata
        network_bytes = query_meta.get("networkSentBytes", 0)
        if network_bytes > 0:
            lines.append(
                f"**Total Network Transfer:** {self._format_bytes(network_bytes)}"
            )

        lines.append("\n### Shuffle Exchanges\n")

        if detail_level == "summary":
            lines.append(f"Found {len(shuffles)} shuffle operations in the plan.")
        else:
            lines.append("| ID | Name | Type |")
            lines.append("|----|------|------|")

            limit = 15 if detail_level == "detailed" else 100
            for op in shuffles[:limit]:
                shuffle_type = "Reused" if "REUSED" in op.tag else "Exchange"
                lines.append(f"| {op.id} | {op.name} | {shuffle_type} |")

            if len(shuffles) > limit:
                lines.append(f"\n*...and {len(shuffles) - limit} more shuffles*")

        return ExtractionSection(
            section_type="shuffles",
            content="\n".join(lines),
            item_count=len(shuffles),
        )

    def _extract_scans(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract scan/read operators.

        Args:
            operators: Parsed operators
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata

        Returns:
            ExtractionSection with scan information
        """
        scans = [op for op in operators if op.tag in SCAN_TAGS or "Scan" in op.name]

        if not scans:
            return ExtractionSection(
                section_type="scans",
                content="## Data Sources: NONE FOUND\n\nNo scan operators detected.",
                item_count=0,
            )

        lines = [f"## Data Sources ({len(scans)} found)\n"]

        # Overall read stats
        read_bytes = query_meta.get("readBytes", 0)
        rows_read = query_meta.get("rowsReadCount", 0)
        if read_bytes > 0:
            lines.append(f"**Total Data Read:** {self._format_bytes(read_bytes)}")
        if rows_read > 0:
            lines.append(f"**Total Rows Read:** {rows_read:,}")

        lines.append("\n### Scanned Tables\n")

        # Extract unique table names
        tables: dict[str, int] = {}
        for op in scans:
            # Extract table name from scan name (e.g., "Scan catalog.schema.table")
            table_match = re.search(r"Scan\s+(\S+)", op.name)
            if table_match:
                table_name = table_match.group(1)
                tables[table_name] = tables.get(table_name, 0) + 1
            else:
                tables[op.name] = tables.get(op.name, 0) + 1

        for table, count in sorted(tables.items(), key=lambda x: -x[1]):
            lines.append(f"- `{table}` ({count} scan(s))")

        return ExtractionSection(
            section_type="scans",
            content="\n".join(lines),
            item_count=len(scans),
        )

    def _extract_by_time(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract slowest operators by execution time.

        Args:
            operators: Parsed operators
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata

        Returns:
            ExtractionSection with slow operator information
        """
        # Look for timing metrics
        timed_ops: list[tuple[OperatorInfo, float]] = []
        for op in operators:
            # Try various time metric keys
            time_ms = 0.0
            for key in ["wallClockTimeNanos", "WALL_CLOCK_TIME", "totalTimeMs"]:
                if key in op.metrics:
                    val = op.metrics[key]
                    time_ms = val / 1_000_000 if "Nanos" in key else val
                    break

            if time_ms > 0:
                timed_ops.append((op, time_ms))

        if not timed_ops:
            # Use query-level time if no operator-level times
            total_time = query_meta.get("totalTimeMs", 0)
            return ExtractionSection(
                section_type="performance",
                content=f"## Performance\n\n**Total Query Time:** {total_time:,} ms\n\nNo operator-level timing metrics available.",
                item_count=0,
            )

        # Sort by time descending
        timed_ops.sort(key=lambda x: -x[1])

        lines = ["## Slowest Operators\n"]

        total_time = query_meta.get("totalTimeMs", 0)
        if total_time > 0:
            lines.append(f"**Total Query Time:** {total_time:,} ms\n")

        limit = (
            5
            if detail_level == "summary"
            else (10 if detail_level == "detailed" else 20)
        )

        lines.append("| Rank | ID | Name | Time (ms) |")
        lines.append("|------|-----|------|-----------|")

        for i, (op, time_ms) in enumerate(timed_ops[:limit], 1):
            lines.append(f"| {i} | {op.id} | {op.name} | {time_ms:,.0f} |")

        if len(timed_ops) > limit:
            lines.append(
                f"\n*...and {len(timed_ops) - limit} more operators with timing data*"
            )

        return ExtractionSection(
            section_type="performance",
            content="\n".join(lines),
            item_count=len(timed_ops),
        )

    def _extract_skew_indicators(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract data skew indicators.

        Args:
            operators: Parsed operators
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata

        Returns:
            ExtractionSection with skew information
        """
        lines = ["## Data Distribution Analysis\n"]

        # Look for skew-related metrics in operators
        skew_indicators: list[str] = []

        rows_read = query_meta.get("rowsReadCount", 0)
        rows_produced = query_meta.get("rowsProducedCount", 0)

        if rows_read > 0 and rows_produced > 0:
            ratio = rows_read / rows_produced
            lines.append(
                f"**Read/Output Ratio:** {ratio:,.1f}x ({rows_read:,} read → {rows_produced:,} output)"
            )
            if ratio > 1000:
                skew_indicators.append(
                    "Very high read/output ratio suggests potential data skew or inefficient joins"
                )

        # Check for spill (indicator of uneven partitions)
        spill_bytes = query_meta.get("spillToDiskBytes", 0)
        if spill_bytes > 0:
            lines.append(f"**Spill to Disk:** {self._format_bytes(spill_bytes)}")
            skew_indicators.append(
                "Disk spill detected - may indicate memory pressure from skewed partitions"
            )

        if skew_indicators:
            lines.append("\n### Skew Indicators\n")
            for indicator in skew_indicators:
                lines.append(f"⚠️ {indicator}")
        else:
            lines.append("\n✅ No obvious data skew indicators detected.")

        return ExtractionSection(
            section_type="skew",
            content="\n".join(lines),
            item_count=len(skew_indicators),
        )

    def _extract_memory_metrics(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract memory and spill metrics.

        Args:
            operators: Parsed operators
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata

        Returns:
            ExtractionSection with memory information
        """
        lines = ["## Memory Usage\n"]

        spill_bytes = query_meta.get("spillToDiskBytes", 0)
        if spill_bytes > 0:
            lines.append(f"**Spill to Disk:** {self._format_bytes(spill_bytes)}")
            lines.append("\n⚠️ Disk spill detected. Consider:")
            lines.append("- Increasing executor memory")
            lines.append("- Adding more partitions to reduce partition size")
            lines.append("- Optimizing joins to reduce intermediate data")
        else:
            lines.append("✅ **No disk spill** - query fit within memory limits.")

        return ExtractionSection(
            section_type="memory",
            content="\n".join(lines),
            item_count=1 if spill_bytes > 0 else 0,
        )

    def _extract_stages(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract Spark stage execution details.

        Args:
            operators: Parsed operators (unused)
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata containing stages

        Returns:
            ExtractionSection with stage information
        """
        stages = query_meta.get("stages", [])

        if not stages:
            return ExtractionSection(
                section_type="stages",
                content="## Stages: NO DATA\n\nNo stage data found in query profile.",
                item_count=0,
            )

        lines = [f"## Spark Stages ({len(stages)} total)\n"]

        # Aggregate stats
        total_tasks = sum(s.get("numTasks", 0) for s in stages)
        failed_stages = [s for s in stages if s.get("status") == "FAILED"]
        completed_stages = [s for s in stages if s.get("status") == "COMPLETE"]

        lines.append("### Summary")
        lines.append(f"- **Total Stages:** {len(stages)}")
        lines.append(f"- **Completed:** {len(completed_stages)}")
        lines.append(f"- **Failed:** {len(failed_stages)}")
        lines.append(f"- **Total Tasks:** {total_tasks:,}")

        # Show failed stages first (critical for debugging)
        if failed_stages:
            lines.append("\n### ⚠️ Failed Stages\n")
            for stage in failed_stages[:10]:
                lines.append(f"**Stage {stage.get('stageId', '?')}**")
                lines.append("- Status: FAILED")
                lines.append(f"- Tasks: {stage.get('numTasks', 0)}")
                failure = stage.get("failureReason", "Unknown")
                if failure:
                    lines.append(f"- **Failure Reason:** {failure}")
                lines.append("")

        # Show longest stages
        if detail_level in ("detailed", "exhaustive"):
            # Sort by duration
            stages_with_duration = [
                s for s in stages if s.get("keyMetrics", {}).get("durationMs")
            ]
            stages_with_duration.sort(
                key=lambda x: x.get("keyMetrics", {}).get("durationMs", 0), reverse=True
            )

            if stages_with_duration:
                lines.append("\n### Slowest Stages\n")
                limit = 10 if detail_level == "detailed" else 30
                for stage in stages_with_duration[:limit]:
                    duration_ms = stage.get("keyMetrics", {}).get("durationMs", 0)
                    lines.append(
                        f"- **Stage {stage.get('stageId')}**: "
                        f"{duration_ms:,}ms, {stage.get('numTasks', 0)} tasks, "
                        f"{stage.get('numCompleteTasks', 0)} completed"
                    )

        return ExtractionSection(
            section_type="stages",
            content="\n".join(lines),
            item_count=len(stages),
        )

    def _extract_performance_overview(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract comprehensive performance overview.

        Args:
            operators: Parsed operators
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata with full metrics

        Returns:
            ExtractionSection with performance summary
        """
        lines = ["## Performance Overview\n"]

        # BB-08: Make SQL text prominent at the top of performance overview
        query_text = query_meta.get("queryText", "")
        if query_text:
            lines.append("### Original SQL\n")
            lines.append("```sql")
            lines.append(query_text.strip())
            lines.append("```\n")

        # Timing breakdown
        total_ms = query_meta.get("totalTimeMs", 0)
        if total_ms > 0:
            lines.append("### Timing Breakdown")
            lines.append(f"- **Total Time:** {total_ms:,}ms ({total_ms / 1000:.1f}s)")

            compilation_ms = query_meta.get("compilationTimeMs", 0)
            execution_ms = query_meta.get("executionTimeMs", 0)
            fetch_ms = query_meta.get("resultFetchTimeMs", 0)
            planning_ms = query_meta.get("planningTimeMs")
            queued_prov = query_meta.get("queuedProvisioningTimeMs")
            queued_overload = query_meta.get("queuedOverloadTimeMs")

            if compilation_ms:
                pct = compilation_ms / total_ms * 100
                lines.append(f"- Compilation: {compilation_ms:,}ms ({pct:.1f}%)")
            if execution_ms:
                pct = execution_ms / total_ms * 100
                lines.append(f"- Execution: {execution_ms:,}ms ({pct:.1f}%)")
            if fetch_ms:
                pct = fetch_ms / total_ms * 100
                lines.append(f"- Result Fetch: {fetch_ms:,}ms ({pct:.1f}%)")
            if planning_ms:
                pct = planning_ms / total_ms * 100
                lines.append(f"- Planning: {planning_ms:,}ms ({pct:.1f}%)")
            if queued_prov:
                lines.append(f"- Queued (Provisioning): {queued_prov:,}ms")
            if queued_overload:
                lines.append(f"- Queued (Overload): {queued_overload:,}ms")

        # Photon metrics
        photon_ms = query_meta.get("photonTotalTimeMs", 0)
        task_ms = query_meta.get("taskTotalTimeMs", 0)
        if photon_ms > 0 and task_ms > 0:
            photon_pct = photon_ms / task_ms * 100
            lines.append("\n### Photon Usage")
            lines.append(f"- Task Total Time: {task_ms:,}ms")
            lines.append(f"- Photon Time: {photon_ms:,}ms ({photon_pct:.1f}%)")
            if photon_pct > 90:
                lines.append("- ✅ Excellent Photon utilization")
            elif photon_pct > 50:
                lines.append("- ⚠️ Moderate Photon utilization")
            else:
                lines.append(
                    "- ❌ Low Photon utilization - check for non-Photon operators"
                )

        # Data I/O
        lines.append("\n### Data I/O")
        read_bytes = query_meta.get("readBytes", 0)
        read_cache = query_meta.get("readCacheBytes", 0)
        read_remote = query_meta.get("readRemoteBytes", 0)
        spill = query_meta.get("spillToDiskBytes", 0)
        network = query_meta.get("networkSentBytes", 0)

        lines.append(f"- **Total Read:** {self._format_bytes(read_bytes)}")
        if read_cache:
            cache_pct = read_cache / read_bytes * 100 if read_bytes > 0 else 0
            lines.append(
                f"- From Cache: {self._format_bytes(read_cache)} ({cache_pct:.1f}%)"
            )
        if read_remote:
            lines.append(f"- From Remote: {self._format_bytes(read_remote)}")
        if network:
            lines.append(f"- Network Sent: {self._format_bytes(network)}")
        if spill:
            lines.append(f"- ⚠️ **Spill to Disk:** {self._format_bytes(spill)}")

        # Row counts
        rows_read = query_meta.get("rowsReadCount", 0)
        rows_produced = query_meta.get("rowsProducedCount", 0)
        if rows_read > 0:
            lines.append("\n### Row Counts")
            lines.append(f"- Rows Read: {rows_read:,}")
            lines.append(f"- Rows Produced: {rows_produced:,}")
            if rows_read > 0:
                selectivity = rows_produced / rows_read * 100
                lines.append(f"- Selectivity: {selectivity:.4f}%")

        # File/partition pruning
        files_read = query_meta.get("readFilesCount", 0)
        files_pruned = query_meta.get("prunedFilesCount", 0)
        bytes_pruned = query_meta.get("prunedBytes", 0)
        if files_read or files_pruned:
            lines.append("\n### Pruning Efficiency")
            lines.append(f"- Files Read: {files_read:,}")
            if files_pruned:
                lines.append(f"- Files Pruned: {files_pruned:,}")
            if bytes_pruned:
                lines.append(f"- Bytes Pruned: {self._format_bytes(bytes_pruned)}")

        return ExtractionSection(
            section_type="performance",
            content="\n".join(lines),
            item_count=1,
        )

    def _extract_cache_metrics(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> ExtractionSection:
        """Extract cache and I/O metrics.

        Args:
            operators: Parsed operators (unused)
            focus: Original focus query
            detail_level: Level of detail
            query_meta: Query metadata

        Returns:
            ExtractionSection with cache/IO information
        """
        lines = ["## Cache & I/O Analysis\n"]

        read_bytes = query_meta.get("readBytes", 0)
        read_cache = query_meta.get("readCacheBytes", 0)
        read_remote = query_meta.get("readRemoteBytes", 0)
        cache_pct = query_meta.get("bytesReadFromCachePercentage", 0)
        result_from_cache = query_meta.get("resultFromCache", False)

        if result_from_cache:
            lines.append("✅ **Result served from cache** - no execution required")
            return ExtractionSection(
                section_type="cache",
                content="\n".join(lines),
                item_count=1,
            )

        lines.append("### Data Source Breakdown")
        lines.append(f"- **Total Bytes Read:** {self._format_bytes(read_bytes)}")

        if read_bytes > 0:
            if read_cache:
                cache_actual_pct = read_cache / read_bytes * 100
                lines.append(
                    f"- **From Cache:** {self._format_bytes(read_cache)} "
                    f"({cache_actual_pct:.1f}%)"
                )
            if read_remote:
                remote_pct = read_remote / read_bytes * 100
                lines.append(
                    f"- **From Remote Storage:** {self._format_bytes(read_remote)} "
                    f"({remote_pct:.1f}%)"
                )

        # Cache efficiency assessment
        lines.append("\n### Cache Efficiency")
        if cache_pct >= 90:
            lines.append(f"✅ **Excellent:** {cache_pct}% cache hit rate")
        elif cache_pct >= 50:
            lines.append(f"⚠️ **Moderate:** {cache_pct}% cache hit rate")
            lines.append("Consider warming cache for frequently accessed data.")
        else:
            lines.append(f"❌ **Low:** {cache_pct}% cache hit rate")
            lines.append("Most data read from remote storage. Consider:")
            lines.append("- Running queries to warm cache")
            lines.append("- Using Delta caching")
            lines.append("- Checking data locality")

        return ExtractionSection(
            section_type="cache",
            content="\n".join(lines),
            item_count=1,
        )

    def _search_by_pattern(
        self,
        operators: list[OperatorInfo],
        focus: str,
        detail_level: str,
    ) -> ExtractionSection:
        """Fallback: search for focus terms in operator names/metadata.

        Args:
            operators: Parsed operators
            focus: Focus query to search for
            detail_level: Level of detail

        Returns:
            ExtractionSection with matching operators
        """
        focus_lower = focus.lower()
        focus_words = set(re.findall(r"\w+", focus_lower))

        matches: list[OperatorInfo] = []
        for op in operators:
            # Search in name
            if any(word in op.name.lower() for word in focus_words):
                matches.append(op)
                continue

            # Search in tag
            if any(word in op.tag.lower() for word in focus_words):
                matches.append(op)
                continue

            # Search in metadata values
            for val in op.metadata.values():
                if isinstance(val, str) and any(
                    word in val.lower() for word in focus_words
                ):
                    matches.append(op)
                    break

        if not matches:
            return ExtractionSection(
                section_type="search",
                content=f"## Search Results for '{focus}'\n\nNo matching operators found.",
                item_count=0,
            )

        lines = [f"## Search Results for '{focus}' ({len(matches)} matches)\n"]

        limit = 10 if detail_level == "summary" else 20
        for op in matches[:limit]:
            lines.append(f"- **{op.name}** (ID: {op.id}, Tag: {op.tag})")

        if len(matches) > limit:
            lines.append(f"\n*...and {len(matches) - limit} more matches*")

        return ExtractionSection(
            section_type="search",
            content="\n".join(lines),
            item_count=len(matches),
        )

    def _extract_overview(
        self,
        operators: list[OperatorInfo],
        query_meta: dict[str, Any],
        detail_level: str,
    ) -> ExtractionSection:
        """Extract general overview when no specific focus matches.

        Args:
            operators: Parsed operators
            query_meta: Query metadata
            detail_level: Level of detail

        Returns:
            ExtractionSection with overview
        """
        lines = ["## Query Profile Overview\n"]

        # Query metadata
        if query_meta.get("id"):
            lines.append(f"**Query ID:** `{query_meta['id']}`")
        if query_meta.get("status"):
            lines.append(f"**Status:** {query_meta['status']}")
        if query_meta.get("totalTimeMs"):
            lines.append(f"**Total Time:** {query_meta['totalTimeMs']:,} ms")
        if query_meta.get("readBytes"):
            lines.append(
                f"**Data Read:** {self._format_bytes(query_meta['readBytes'])}"
            )
        if query_meta.get("rowsReadCount"):
            lines.append(f"**Rows Read:** {query_meta['rowsReadCount']:,}")

        # BB-08: Make SQL text prominent in the overview
        query_text = query_meta.get("queryText", "")
        if query_text:
            lines.append("\n### Original SQL\n")
            lines.append("```sql")
            lines.append(query_text.strip())
            lines.append("```")

        lines.append(f"\n**Operators:** {len(operators)} total")

        # Count by category
        joins = len([op for op in operators if op.tag in JOIN_TAGS])
        shuffles = len([op for op in operators if op.tag in SHUFFLE_TAGS])
        scans = len(
            [op for op in operators if op.tag in SCAN_TAGS or "Scan" in op.name]
        )

        if joins > 0:
            lines.append(f"- Joins: {joins}")
        if shuffles > 0:
            lines.append(f"- Shuffles: {shuffles}")
        if scans > 0:
            lines.append(f"- Scans: {scans}")

        return ExtractionSection(
            section_type="overview",
            content="\n".join(lines),
            item_count=len(operators),
        )

    def _combine_sections(
        self,
        sections: list[ExtractionSection],
        detail_level: str,
        query_meta: dict[str, Any],
    ) -> str:
        """Combine extraction sections into final content.

        Args:
            sections: List of extraction sections
            detail_level: Level of detail for truncation
            query_meta: Query metadata for header

        Returns:
            Combined markdown content
        """
        max_size = DETAIL_LIMITS.get(detail_level, 10000)

        # Build header
        parts = []
        query_id = query_meta.get("id", "unknown")
        parts.append(f"# Query Profile Analysis\n\n**Query ID:** `{query_id}`\n")

        # BB-08: Include SQL text in header for immediate visibility
        query_text = query_meta.get("queryText", "")
        if query_text and not any(
            s.section_type in ("overview", "performance") for s in sections
        ):
            # Only add SQL here if not already in overview/performance sections
            parts.append("## Original SQL\n")
            parts.append("```sql")
            parts.append(query_text.strip())
            parts.append("```\n")

        # Add sections
        for section in sections:
            parts.append(section.content)
            parts.append("")  # Blank line between sections

        combined = "\n".join(parts)

        # Truncate if needed
        if len(combined) > max_size:
            combined = (
                combined[: max_size - 50] + "\n\n*[Content truncated for detail level]*"
            )

        return combined

    def _generate_followups(
        self,
        focus: str,
        sections_found: tuple[str, ...],
        operators: list[OperatorInfo],
    ) -> tuple[str, ...]:
        """Generate suggested follow-up focus queries.

        Args:
            focus: Original focus query
            sections_found: Section types that were extracted
            operators: All operators

        Returns:
            Tuple of suggested follow-up queries
        """
        suggestions: list[str] = []

        # Suggest based on what wasn't explored
        if "joins" not in sections_found and any(
            op.tag in JOIN_TAGS for op in operators
        ):
            suggestions.append("join algorithms, broadcast vs shuffle")

        if "shuffles" not in sections_found and any(
            op.tag in SHUFFLE_TAGS for op in operators
        ):
            suggestions.append("shuffle bottlenecks, network transfer")

        if "scans" not in sections_found and any("Scan" in op.name for op in operators):
            suggestions.append("data sources, table scans")

        if "performance" not in sections_found:
            suggestions.append("slow operators, execution time")

        if "memory" not in sections_found:
            suggestions.append("memory usage, spill to disk")

        # Limit to 3 suggestions
        return tuple(suggestions[:3])

    def _get_join_algorithm(self, tag: str) -> str:
        """Extract join algorithm from operator tag.

        Args:
            tag: Operator tag

        Returns:
            Human-readable algorithm name
        """
        return join_algorithm(tag)

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        """Format bytes as human-readable string.

        Args:
            num_bytes: Number of bytes

        Returns:
            Formatted string (e.g., "1.5 GB")
        """
        if num_bytes < 1024:
            return f"{num_bytes} B"
        if num_bytes < 1024 * 1024:
            return f"{num_bytes / 1024:.1f} KB"
        if num_bytes < 1024 * 1024 * 1024:
            return f"{num_bytes / (1024 * 1024):.1f} MB"
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def _format_time(nanoseconds: int) -> str:
        """Format nanoseconds as human-readable time.

        Args:
            nanoseconds: Time in nanoseconds

        Returns:
            Formatted string (e.g., "1.5s", "250ms", "50μs")
        """
        if nanoseconds < 1000:
            return f"{nanoseconds}ns"
        if nanoseconds < 1_000_000:
            return f"{nanoseconds / 1000:.1f}μs"
        if nanoseconds < 1_000_000_000:
            return f"{nanoseconds / 1_000_000:.1f}ms"
        return f"{nanoseconds / 1_000_000_000:.2f}s"


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ["QueryProfileExplorer", "ExplorationResult"]
