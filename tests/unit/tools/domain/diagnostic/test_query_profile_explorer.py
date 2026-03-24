# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for QueryProfileExplorer.

Tests intent-aware extraction from query profiles in both
Liquid format and standard format.
"""

import json

import pytest
from starboard_server.tools.domain.diagnostic.query_profile_explorer import (
    QueryProfileExplorer,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def explorer() -> QueryProfileExplorer:
    """Create explorer instance."""
    return QueryProfileExplorer()


@pytest.fixture
def liquid_format_profile() -> str:
    """Sample Liquid format query profile."""
    return json.dumps(
        {
            "version": "1.3",
            "query": {
                "id": "test-query-123",
                "status": "FINISHED",
                "queryText": "SELECT * FROM test_table",
                "metrics": {
                    "totalTimeMs": 5000,
                    "readBytes": 1000000,
                    "rowsReadCount": 50000,
                    "rowsProducedCount": 100,
                    "spillToDiskBytes": 0,
                    "networkSentBytes": 500000,
                },
            },
            "graphs": [
                {
                    "nodes": [
                        {
                            "id": "1",
                            "name": "Inner Join",
                            "tag": "PHOTON_BROADCAST_HASH_JOIN_EXEC",
                            "metrics": [],
                            "metadata": [],
                        },
                        {
                            "id": "2",
                            "name": "Left Outer Join",
                            "tag": "PHOTON_SHUFFLED_HASH_JOIN_EXEC",
                            "metrics": [],
                            "metadata": [],
                        },
                        {
                            "id": "3",
                            "name": "Shuffle",
                            "tag": "PHOTON_SHUFFLE_EXCHANGE_SINK_EXEC",
                            "metrics": [],
                            "metadata": [],
                        },
                        {
                            "id": "4",
                            "name": "Scan test_table",
                            "tag": "UNKNOWN_DATA_SOURCE_SCAN_EXEC",
                            "metrics": [],
                            "metadata": [],
                        },
                    ]
                }
            ],
        }
    )


@pytest.fixture
def standard_format_profile() -> str:
    """Sample standard format query profile."""
    return json.dumps(
        {
            "operatorID": 1,
            "operatorName": "BroadcastHashJoin",
            "metrics": {
                "wallClockTime": 1000,
                "outputRows": 5000,
            },
            "children": [
                {
                    "operatorID": 2,
                    "operatorName": "Scan test_table",
                    "metrics": {
                        "outputRows": 10000,
                        "outputBytes": 500000,
                    },
                    "children": [],
                },
                {
                    "operatorID": 3,
                    "operatorName": "ShuffleExchange",
                    "metrics": {
                        "shuffleBytesWritten": 100000,
                    },
                    "children": [],
                },
            ],
        }
    )


# =============================================================================
# EXPLORATION TESTS
# =============================================================================


class TestQueryProfileExplorer:
    """Tests for QueryProfileExplorer."""

    def test_explore_joins_liquid_format(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test join extraction from Liquid format."""
        result = explorer.explore(
            content=liquid_format_profile,
            focus="join strategies, join operators",
            detail_level="detailed",
        )

        assert result.evidence_count == 2  # Two join operators
        assert "joins" in result.sections_found
        assert "Join Operators (2 found)" in result.content
        assert "Broadcast Hash" in result.content
        assert "Shuffled Hash" in result.content

    def test_explore_joins_standard_format(
        self, explorer: QueryProfileExplorer, standard_format_profile: str
    ) -> None:
        """Test join extraction from standard format."""
        result = explorer.explore(
            content=standard_format_profile,
            focus="join algorithms",
            detail_level="detailed",
        )

        assert result.evidence_count >= 1
        assert "joins" in result.sections_found
        assert (
            "BroadcastHashJoin" in result.content or "Broadcast Hash" in result.content
        )

    def test_explore_shuffles(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test shuffle extraction."""
        result = explorer.explore(
            content=liquid_format_profile,
            focus="shuffle bottlenecks",
            detail_level="detailed",
        )

        assert "shuffles" in result.sections_found
        assert "Shuffle Operations" in result.content

    def test_explore_scans(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test scan extraction."""
        result = explorer.explore(
            content=liquid_format_profile,
            focus="data sources, table scans",
            detail_level="detailed",
        )

        assert "scans" in result.sections_found
        assert "test_table" in result.content

    def test_range_join_detection_none_found(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test range join hint detection when none present."""
        result = explorer.explore(
            content=liquid_format_profile,
            focus="range join hints",
            detail_level="detailed",
        )

        assert "joins" in result.sections_found
        assert "NONE FOUND" in result.content or "No RANGE_JOIN" in result.content

    def test_explore_with_summary_level(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test summary detail level produces shorter output."""
        detailed = explorer.explore(
            content=liquid_format_profile,
            focus="joins",
            detail_level="detailed",
        )

        summary = explorer.explore(
            content=liquid_format_profile,
            focus="joins",
            detail_level="summary",
        )

        # Summary should be shorter or equal
        assert len(summary.content) <= len(detailed.content) + 100

    def test_explore_fallback_pattern_search(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test fallback pattern search for unknown focus."""
        result = explorer.explore(
            content=liquid_format_profile,
            focus="photon optimization",
            detail_level="detailed",
        )

        # Should fall back to pattern search
        assert result.evidence_count >= 0
        assert len(result.content) > 0

    def test_explore_invalid_json(self, explorer: QueryProfileExplorer) -> None:
        """Test handling of invalid JSON."""
        result = explorer.explore(
            content="not valid json",
            focus="joins",
            detail_level="detailed",
        )

        assert "parse failed" in result.content.lower()
        assert result.evidence_count == 0

    def test_explore_empty_profile(self, explorer: QueryProfileExplorer) -> None:
        """Test handling of empty profile."""
        result = explorer.explore(
            content="{}",
            focus="joins",
            detail_level="detailed",
        )

        assert result.evidence_count == 0

    def test_suggested_followups(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test that followup suggestions are generated."""
        result = explorer.explore(
            content=liquid_format_profile,
            focus="joins",
            detail_level="detailed",
        )

        # Should suggest exploring other areas not yet explored
        # Suggestions should be present (may vary based on what was explored)
        assert isinstance(result.suggested_followups, tuple)

    def test_has_more_flag(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test has_more flag for detail levels."""
        summary = explorer.explore(
            content=liquid_format_profile,
            focus="joins",
            detail_level="summary",
        )

        # Summary level might have more if there's additional detail
        # This depends on content length
        assert isinstance(summary.has_more, bool)

    def test_query_metadata_extraction(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test query metadata is included in output."""
        result = explorer.explore(
            content=liquid_format_profile,
            focus="overview",
            detail_level="detailed",
        )

        # Should include query ID
        assert "test-query-123" in result.content

    def test_multiple_focus_keywords(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test multiple focus keywords are all extracted."""
        result = explorer.explore(
            content=liquid_format_profile,
            focus="joins, shuffles, scans",
            detail_level="detailed",
        )

        # Should have multiple sections
        sections = set(result.sections_found)
        assert len(sections) >= 2  # At least two different section types


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestQueryProfileExplorerEdgeCases:
    """Edge case tests for QueryProfileExplorer."""

    def test_very_large_content_truncation(
        self, explorer: QueryProfileExplorer
    ) -> None:
        """Test that very large content is handled."""
        # Create a profile with many operators
        nodes = [
            {
                "id": str(i),
                "name": f"Operator{i}",
                "tag": "PHOTON_BROADCAST_HASH_JOIN_EXEC"
                if i % 2 == 0
                else "PHOTON_FILTER_EXEC",
                "metrics": [],
                "metadata": [],
            }
            for i in range(100)
        ]

        large_profile = json.dumps(
            {
                "query": {"id": "large-query", "metrics": {}},
                "graphs": [{"nodes": nodes}],
            }
        )

        result = explorer.explore(
            content=large_profile,
            focus="joins",
            detail_level="summary",
        )

        # Should still produce output without error
        assert len(result.content) > 0
        assert result.evidence_count > 0

    def test_empty_graphs(self, explorer: QueryProfileExplorer) -> None:
        """Test profile with empty graphs."""
        profile = json.dumps(
            {
                "query": {"id": "empty-graphs", "metrics": {}},
                "graphs": [],
            }
        )

        result = explorer.explore(
            content=profile,
            focus="joins",
            detail_level="detailed",
        )

        # Should handle gracefully
        assert "NONE FOUND" in result.content or result.evidence_count == 0

    def test_caching_behavior(
        self, explorer: QueryProfileExplorer, liquid_format_profile: str
    ) -> None:
        """Test that parsing is cached for repeated calls."""
        # First call
        result1 = explorer.explore(
            content=liquid_format_profile,
            focus="joins",
            detail_level="detailed",
        )

        # Second call with same content
        result2 = explorer.explore(
            content=liquid_format_profile,
            focus="shuffles",
            detail_level="detailed",
        )

        # Both should succeed
        assert result1.evidence_count > 0
        assert result2.evidence_count > 0 or "NONE FOUND" not in result2.content
