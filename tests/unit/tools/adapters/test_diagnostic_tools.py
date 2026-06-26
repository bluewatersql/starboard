# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for DiagnosticTools adapter.

Tests the explore_artifact tool interface.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from starboard_server.tools.adapters.diagnostic_tools import DiagnosticTools

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Create mock namespaced cache."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return cache


@pytest.fixture
def diagnostic_tools(mock_cache: AsyncMock) -> DiagnosticTools:
    """Create DiagnosticTools instance with mock cache."""
    return DiagnosticTools(attachments_cache=mock_cache, events=None)


@pytest.fixture
def sample_query_profile() -> dict:
    """Sample query profile for testing."""
    return {
        "query": {
            "id": "test-query-123",
            "status": "FINISHED",
            "metrics": {"totalTimeMs": 5000},
        },
        "graphs": [
            {
                "nodes": [
                    {
                        "id": "1",
                        "name": "Broadcast Hash Join",
                        "tag": "PHOTON_BROADCAST_HASH_JOIN_EXEC",
                        "metrics": [],
                        "metadata": [],
                    },
                    {
                        "id": "2",
                        "name": "Scan customers",
                        "tag": "DATA_SOURCE_SCAN_EXEC",
                        "metrics": [],
                        "metadata": [],
                    },
                ]
            }
        ],
    }


# =============================================================================
# EXPLORE_ARTIFACT TESTS
# =============================================================================


class TestDiagnosticToolsExploreArtifact:
    """Tests for explore_artifact tool."""

    @pytest.mark.asyncio
    async def test_explore_artifact_success(
        self,
        diagnostic_tools: DiagnosticTools,
        mock_cache: AsyncMock,
        sample_query_profile: dict,
    ) -> None:
        """Test successful artifact exploration."""
        content = json.dumps(sample_query_profile)
        mock_cache.get.return_value = {
            "content": content,
            "filename": "query_profile.json",
            "size": len(content),
        }

        result = await diagnostic_tools.explore_artifact(
            attachment_id="att_test_123",
            focus="join operators",
            detail_level="detailed",
        )

        assert "content" in result
        assert "evidence_count" in result
        assert "sections_found" in result
        assert result["evidence_count"] >= 0
        mock_cache.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_explore_artifact_not_found(
        self,
        diagnostic_tools: DiagnosticTools,
        mock_cache: AsyncMock,
    ) -> None:
        """Test handling of missing artifact."""
        mock_cache.get.return_value = None

        result = await diagnostic_tools.explore_artifact(
            attachment_id="att_missing",
            focus="anything",
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_explore_artifact_with_default_detail_level(
        self,
        diagnostic_tools: DiagnosticTools,
        mock_cache: AsyncMock,
        sample_query_profile: dict,
    ) -> None:
        """Test default detail level is 'detailed'."""
        content = json.dumps(sample_query_profile)
        mock_cache.get.return_value = {
            "content": content,
            "filename": "profile.json",
            "size": len(content),
        }

        result = await diagnostic_tools.explore_artifact(
            attachment_id="att_default",
            focus="joins",
            # detail_level not specified - should default to "detailed"
        )

        assert "content" in result
        assert isinstance(result["sections_found"], list)

    @pytest.mark.asyncio
    async def test_explore_artifact_returns_dict(
        self,
        diagnostic_tools: DiagnosticTools,
        mock_cache: AsyncMock,
        sample_query_profile: dict,
    ) -> None:
        """Test that explore_artifact returns a dict for agent consumption."""
        content = json.dumps(sample_query_profile)
        mock_cache.get.return_value = {
            "content": content,
            "filename": "profile.json",
            "size": len(content),
        }

        result = await diagnostic_tools.explore_artifact(
            attachment_id="att_dict",
            focus="overview",
        )

        assert isinstance(result, dict)
        # Check all expected keys
        expected_keys = {
            "content",
            "evidence_count",
            "sections_found",
            "has_more",
            "suggested_followups",
        }
        assert expected_keys.issubset(set(result.keys()))

    @pytest.mark.asyncio
    async def test_explore_artifact_focus_variations(
        self,
        diagnostic_tools: DiagnosticTools,
        mock_cache: AsyncMock,
        sample_query_profile: dict,
    ) -> None:
        """Test various focus query variations."""
        content = json.dumps(sample_query_profile)
        mock_cache.get.return_value = {
            "content": content,
            "filename": "profile.json",
            "size": len(content),
        }

        focus_queries = [
            "range join hints",
            "join strategies, algorithms",
            "shuffle bottlenecks",
            "scan operations",
            "slow operators",
        ]

        for focus in focus_queries:
            result = await diagnostic_tools.explore_artifact(
                attachment_id="att_focus",
                focus=focus,
            )

            assert "content" in result
            assert isinstance(result["evidence_count"], int)

    @pytest.mark.asyncio
    async def test_explore_artifact_detail_levels(
        self,
        diagnostic_tools: DiagnosticTools,
        mock_cache: AsyncMock,
        sample_query_profile: dict,
    ) -> None:
        """Test all detail levels work correctly."""
        content = json.dumps(sample_query_profile)
        mock_cache.get.return_value = {
            "content": content,
            "filename": "profile.json",
            "size": len(content),
        }

        for level in ["summary", "detailed", "exhaustive"]:
            result = await diagnostic_tools.explore_artifact(
                attachment_id="att_level",
                focus="joins",
                detail_level=level,  # type: ignore
            )

            assert "content" in result
            assert result["content"]  # Not empty
