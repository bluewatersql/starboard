# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for QueryProfileExtractor."""

from __future__ import annotations

import json

import pytest
from starboard_server.tools.domain.diagnostic.models import ArtifactType
from starboard_server.tools.domain.diagnostic.query_profile_extractor import (
    QueryProfileExtractor,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def extractor() -> QueryProfileExtractor:
    """Create a QueryProfileExtractor."""
    return QueryProfileExtractor(top_operators=5)


def create_query_profile(
    *,
    num_operators: int = 5,
    include_scan: bool = True,
    include_shuffle: bool = True,
) -> str:
    """Create a minimal query profile JSON."""
    operators = []

    if include_scan:
        operators.append(
            {
                "operatorID": 0,
                "operatorName": "FileScan parquet",
                "metrics": {
                    "outputRows": 1000000,
                    "outputBytes": 50000000,
                    "wallClockTime": 500,
                    "filesRead": 10,
                },
                "children": [],
            }
        )

    if include_shuffle:
        operators.append(
            {
                "operatorID": 1,
                "operatorName": "ShuffleExchange",
                "metrics": {
                    "shuffleBytesWritten": 10000000,
                    "shuffleRecordsWritten": 50000,
                    "wallClockTime": 2000,
                },
                "children": [],
            }
        )

    # Add some filter/project operators
    for i in range(2, num_operators):
        operators.append(
            {
                "operatorID": i,
                "operatorName": f"Filter_{i}",
                "metrics": {
                    "outputRows": 1000000 // (i + 1),
                    "wallClockTime": 100 * i,
                },
                "children": [],
            }
        )

    # Build tree structure
    root = {
        "operatorID": 100,
        "operatorName": "LocalLimit",
        "metrics": {"wallClockTime": 50},
        "children": operators,
    }

    return json.dumps(root)


def create_flat_profile() -> str:
    """Create a flat array-style profile."""
    return json.dumps(
        [
            {
                "operatorID": 0,
                "operatorName": "Scan",
                "metrics": {"wallClockTime": 100},
            },
            {
                "operatorID": 1,
                "operatorName": "Filter",
                "metrics": {"wallClockTime": 50},
            },
        ]
    )


# =============================================================================
# EXTRACTION TESTS
# =============================================================================


class TestExtraction:
    """Tests for extract() method."""

    @pytest.mark.asyncio
    async def test_extract_basic_profile(
        self, extractor: QueryProfileExtractor
    ) -> None:
        """Should extract from basic query profile."""
        content = create_query_profile()
        result = await extractor.extract(content, "Analyze query")

        assert result.artifact_type == ArtifactType.QUERY_PROFILE
        assert result.evidence_count > 0
        assert "Query Profile Analysis" in result.distilled_content

    @pytest.mark.asyncio
    async def test_extract_finds_slowest_operators(
        self, extractor: QueryProfileExtractor
    ) -> None:
        """Should identify slowest operators."""
        content = create_query_profile()
        result = await extractor.extract(content, "Optimize query")

        assert "Slowest Operators" in result.distilled_content
        # ShuffleExchange has highest wall clock time
        assert (
            "Shuffle" in result.distilled_content
            or "shuffle" in result.distilled_content.lower()
        )

    @pytest.mark.asyncio
    async def test_extract_finds_scans(self, extractor: QueryProfileExtractor) -> None:
        """Should identify scan operators."""
        content = create_query_profile(include_scan=True)
        result = await extractor.extract(content, "Analyze I/O")

        assert result.metadata.get("scan_count", 0) > 0
        assert (
            "Scan" in result.distilled_content
            or "Data Sources" in result.distilled_content
        )

    @pytest.mark.asyncio
    async def test_extract_finds_shuffles(
        self, extractor: QueryProfileExtractor
    ) -> None:
        """Should identify shuffle operators."""
        content = create_query_profile(include_shuffle=True)
        result = await extractor.extract(content, "Analyze shuffles")

        assert result.metadata.get("shuffle_count", 0) > 0
        assert "Shuffle" in result.distilled_content

    @pytest.mark.asyncio
    async def test_extract_compression(self, extractor: QueryProfileExtractor) -> None:
        """Should compress large profiles."""
        content = create_query_profile(num_operators=20)
        result = await extractor.extract(content, "Analyze")

        assert result.original_size == len(content)
        assert result.compression_ratio > 0
        assert len(result.distilled_content) < result.original_size

    @pytest.mark.asyncio
    async def test_extract_invalid_json(self, extractor: QueryProfileExtractor) -> None:
        """Should fallback gracefully for invalid JSON."""
        content = "not valid json"
        result = await extractor.extract(content, "Analyze")

        assert result.artifact_type == ArtifactType.QUERY_PROFILE
        assert result.metadata.get("parse_failed") is True
        assert "parse failed" in result.distilled_content.lower()


# =============================================================================
# OPERATOR FLATTENING TESTS
# =============================================================================


class TestOperatorFlattening:
    """Tests for _flatten_operators() method."""

    def test_flatten_nested_tree(self, extractor: QueryProfileExtractor) -> None:
        """Should flatten nested operator tree."""
        profile = json.loads(create_query_profile(num_operators=3))
        operators = extractor._flatten_operators(profile)

        # Should find root + children
        assert len(operators) >= 4  # LocalLimit + Scan + Shuffle + Filter

    def test_flatten_array(self, extractor: QueryProfileExtractor) -> None:
        """Should flatten array-style profile."""
        profile = json.loads(create_flat_profile())
        operators = extractor._flatten_operators(profile)

        assert len(operators) == 2

    def test_flatten_empty(self, extractor: QueryProfileExtractor) -> None:
        """Should handle empty profile."""
        operators = extractor._flatten_operators({})
        assert len(operators) == 0


# =============================================================================
# OPERATOR FINDING TESTS
# =============================================================================


class TestFindOperators:
    """Tests for operator finding methods."""

    def test_find_slowest_operators(self, extractor: QueryProfileExtractor) -> None:
        """Should find operators sorted by wall clock time."""
        operators = [
            {"operatorID": 0, "operatorName": "A", "metrics": {"wallClockTime": 100}},
            {"operatorID": 1, "operatorName": "B", "metrics": {"wallClockTime": 500}},
            {"operatorID": 2, "operatorName": "C", "metrics": {"wallClockTime": 200}},
        ]

        slowest = extractor._find_slowest_operators(operators)

        assert len(slowest) == 3
        assert slowest[0]["name"] == "B"  # Highest wall clock time
        assert slowest[0]["wall_clock_ms"] == 500

    def test_find_scan_operators(self, extractor: QueryProfileExtractor) -> None:
        """Should find scan operators."""
        operators = [
            {"operatorID": 0, "operatorName": "FileScan parquet", "metrics": {}},
            {"operatorID": 1, "operatorName": "Filter", "metrics": {}},
            {"operatorID": 2, "operatorName": "BatchScan delta", "metrics": {}},
        ]

        scans = extractor._find_scan_operators(operators)

        assert len(scans) == 2
        assert all("Scan" in s["name"] for s in scans)

    def test_find_shuffle_operators(self, extractor: QueryProfileExtractor) -> None:
        """Should find shuffle operators."""
        operators = [
            {"operatorID": 0, "operatorName": "ShuffleExchange", "metrics": {}},
            {"operatorID": 1, "operatorName": "Filter", "metrics": {}},
            {"operatorID": 2, "operatorName": "BroadcastExchange", "metrics": {}},
        ]

        shuffles = extractor._find_shuffle_operators(operators)

        assert len(shuffles) == 2
        assert all("Exchange" in s["name"] for s in shuffles)


# =============================================================================
# DISTILLED CONTENT TESTS
# =============================================================================


class TestDistilledContent:
    """Tests for distilled content generation."""

    def test_build_distilled_with_all_sections(
        self, extractor: QueryProfileExtractor
    ) -> None:
        """Should include all sections when data is present."""
        slowest = [{"id": 0, "name": "SlowOp", "wall_clock_ms": 1000, "rows_out": 100}]
        scans = [{"id": 1, "name": "Scan", "rows_read": 1000, "bytes_read": 5000}]
        shuffles = [{"id": 2, "name": "Shuffle", "shuffle_bytes": 10000}]
        all_ops = [{}, {}, {}]

        distilled = extractor._build_distilled(slowest, scans, shuffles, all_ops)

        assert "Slowest Operators" in distilled
        assert "Data Sources" in distilled
        assert "Shuffle Operations" in distilled
        assert "SlowOp" in distilled

    def test_build_distilled_empty(self, extractor: QueryProfileExtractor) -> None:
        """Should handle empty operator lists."""
        distilled = extractor._build_distilled([], [], [], [])

        assert "Query Profile Analysis" in distilled
        assert "0 operators" in distilled


# =============================================================================
# METADATA TESTS
# =============================================================================


class TestMetadata:
    """Tests for extracted metadata."""

    @pytest.mark.asyncio
    async def test_metadata_includes_counts(
        self, extractor: QueryProfileExtractor
    ) -> None:
        """Should include operator counts in metadata."""
        content = create_query_profile(
            num_operators=5, include_scan=True, include_shuffle=True
        )
        result = await extractor.extract(content, "Analyze")

        assert "total_operators" in result.metadata
        assert "scan_count" in result.metadata
        assert "shuffle_count" in result.metadata
        assert result.metadata["total_operators"] > 0

    @pytest.mark.asyncio
    async def test_metadata_includes_slowest(
        self, extractor: QueryProfileExtractor
    ) -> None:
        """Should include slowest operator name in metadata."""
        content = create_query_profile()
        result = await extractor.extract(content, "Analyze")

        assert "slowest_operator" in result.metadata
        # ShuffleExchange has highest wall clock time in our test data
        assert result.metadata["slowest_operator"] is not None
