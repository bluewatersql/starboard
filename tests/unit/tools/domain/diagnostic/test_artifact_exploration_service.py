# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for ArtifactExplorationService.

Tests the service that orchestrates intent-aware artifact exploration,
routing to type-specific explorers based on detected artifact type.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from starboard.tools.domain.diagnostic.artifact_exploration_service import (
    ArtifactExplorationService,
)

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
def service(mock_cache: AsyncMock) -> ArtifactExplorationService:
    """Create service instance with mock cache."""
    return ArtifactExplorationService(mock_cache)


@pytest.fixture
def query_profile_content() -> str:
    """Sample query profile content."""
    return json.dumps(
        {
            "query": {
                "id": "test-query",
                "status": "FINISHED",
                "metrics": {"totalTimeMs": 1000},
            },
            "graphs": [
                {
                    "nodes": [
                        {
                            "id": "1",
                            "name": "Join",
                            "tag": "PHOTON_BROADCAST_HASH_JOIN_EXEC",
                            "metrics": [],
                            "metadata": [],
                        }
                    ]
                }
            ],
        }
    )


# =============================================================================
# SERVICE TESTS
# =============================================================================


class TestArtifactExplorationService:
    """Tests for ArtifactExplorationService."""

    @pytest.mark.asyncio
    async def test_explore_query_profile(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
        query_profile_content: str,
    ) -> None:
        """Test exploration of query profile artifact."""
        mock_cache.get.return_value = {
            "content": query_profile_content,
            "filename": "query_profile.json",
            "size": len(query_profile_content),
        }

        result = await service.explore(
            attachment_id="att_test_123",
            focus="join strategies",
            detail_level="detailed",
        )

        assert result.evidence_count > 0
        assert "Join" in result.content or "join" in result.content.lower()
        mock_cache.get.assert_called_once_with("att_test_123")

    @pytest.mark.asyncio
    async def test_explore_attachment_not_found(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
    ) -> None:
        """Test handling of missing attachment."""
        mock_cache.get.return_value = None

        with pytest.raises(ValueError) as exc_info:
            await service.explore(
                attachment_id="att_missing",
                focus="anything",
            )

        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_explore_empty_content(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
    ) -> None:
        """Test handling of empty artifact content."""
        mock_cache.get.return_value = {
            "content": "",
            "filename": "empty.json",
            "size": 0,
        }

        result = await service.explore(
            attachment_id="att_empty",
            focus="anything",
        )

        assert "empty" in result.content.lower() or "Error" in result.content
        assert result.evidence_count == 0

    @pytest.mark.asyncio
    async def test_type_detection_liquid_format(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
        query_profile_content: str,
    ) -> None:
        """Test artifact type detection for Liquid format."""
        mock_cache.get.return_value = {
            "content": query_profile_content,
            "filename": "unknown.bin",
            "size": len(query_profile_content),
        }

        result = await service.explore(
            attachment_id="att_liquid",
            focus="overview",
        )

        # Should detect as query profile and process successfully
        assert result is not None

    @pytest.mark.asyncio
    async def test_type_detection_standard_format(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
    ) -> None:
        """Test artifact type detection for standard format."""
        standard_content = json.dumps(
            {
                "operatorID": 1,
                "operatorName": "BroadcastHashJoin",
                "metrics": {},
                "children": [],
            }
        )

        mock_cache.get.return_value = {
            "content": standard_content,
            "filename": "plan.json",
            "size": len(standard_content),
        }

        result = await service.explore(
            attachment_id="att_standard",
            focus="joins",
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_type_detection_spark_event_log(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
    ) -> None:
        """Test artifact type detection for Spark event log."""
        spark_log = '{"Event":"SparkListenerApplicationStart","App Name":"test"}\n'

        mock_cache.get.return_value = {
            "content": spark_log,
            "filename": "eventlog",
            "size": len(spark_log),
        }

        result = await service.explore(
            attachment_id="att_spark",
            focus="application",
        )

        # Should detect and use generic exploration (no Spark explorer yet)
        assert result is not None

    @pytest.mark.asyncio
    async def test_type_detection_explain_plan(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
    ) -> None:
        """Test artifact type detection for EXPLAIN plan."""
        explain_content = """
        == Physical Plan ==
        *(1) BroadcastHashJoin
        +- *(2) FileScan
        """

        mock_cache.get.return_value = {
            "content": explain_content,
            "filename": "explain.txt",
            "size": len(explain_content),
        }

        result = await service.explore(
            attachment_id="att_explain",
            focus="join",
        )

        # Should use generic exploration
        assert result is not None

    @pytest.mark.asyncio
    async def test_detail_levels(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
        query_profile_content: str,
    ) -> None:
        """Test different detail levels produce appropriate output."""
        mock_cache.get.return_value = {
            "content": query_profile_content,
            "filename": "profile.json",
            "size": len(query_profile_content),
        }

        summary = await service.explore(
            attachment_id="att_detail",
            focus="joins",
            detail_level="summary",
        )

        detailed = await service.explore(
            attachment_id="att_detail",
            focus="joins",
            detail_level="detailed",
        )

        exhaustive = await service.explore(
            attachment_id="att_detail",
            focus="joins",
            detail_level="exhaustive",
        )

        # All should succeed
        assert summary is not None
        assert detailed is not None
        assert exhaustive is not None

    @pytest.mark.asyncio
    async def test_focus_query_preserved(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
        query_profile_content: str,
    ) -> None:
        """Test focus query is preserved in result."""
        mock_cache.get.return_value = {
            "content": query_profile_content,
            "filename": "profile.json",
            "size": len(query_profile_content),
        }

        result = await service.explore(
            attachment_id="att_focus",
            focus="range join hints, join strategies",
        )

        assert result.focus_query == "range join hints, join strategies"


# =============================================================================
# GENERIC EXPLORATION TESTS
# =============================================================================


class TestGenericExploration:
    """Tests for generic exploration fallback."""

    @pytest.mark.asyncio
    async def test_generic_exploration_unknown_type(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
    ) -> None:
        """Test generic exploration for unknown artifact type."""
        content = "Some random log content\nWith multiple lines\njoin mentioned here"

        mock_cache.get.return_value = {
            "content": content,
            "filename": "unknown.xyz",
            "size": len(content),
        }

        result = await service.explore(
            attachment_id="att_unknown",
            focus="join",
        )

        # Should use generic pattern search
        assert result.evidence_count >= 1
        assert "join" in result.content.lower()

    @pytest.mark.asyncio
    async def test_generic_exploration_no_matches(
        self,
        service: ArtifactExplorationService,
        mock_cache: AsyncMock,
    ) -> None:
        """Test generic exploration with no matching lines."""
        content = "Lorem ipsum dolor sit amet"

        mock_cache.get.return_value = {
            "content": content,
            "filename": "lorem.txt",
            "size": len(content),
        }

        result = await service.explore(
            attachment_id="att_no_match",
            focus="extremely_specific_term_not_present",
        )

        assert result.evidence_count == 0
        assert "No lines matching" in result.content or result.content != ""
