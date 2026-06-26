# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for DatabricksContextExtractor.

Tests cover:
- ID extraction (cluster, job, run, query, warehouse)
- Confidence scoring
- Mode determination (ONLINE/OFFLINE/HYBRID)
"""

from textwrap import dedent

import pytest
from starboard_server.tools.domain.diagnostic.context_extractor import (
    ContextMode,
    DatabricksContextExtractor,
    IdType,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def extractor() -> DatabricksContextExtractor:
    """Create extractor instance."""
    return DatabricksContextExtractor()


# =============================================================================
# CLUSTER ID EXTRACTION
# =============================================================================


class TestClusterIdExtraction:
    """Tests for cluster ID extraction."""

    def test_standard_cluster_id(self, extractor: DatabricksContextExtractor) -> None:
        """Extract standard cluster ID format."""
        text = "cluster_id=1234-567890-abc12"
        result = extractor.extract(text)

        assert result.primary_cluster_id == "1234-567890-abc12"
        assert any(
            eid.id_type == IdType.CLUSTER_ID and eid.value == "1234-567890-abc12"
            for eid in result.extracted_ids
        )

    def test_cluster_id_in_url(self, extractor: DatabricksContextExtractor) -> None:
        """Extract cluster ID from URL."""
        text = "https://databricks.com/clusters/1234-567890-abc12/metrics"
        result = extractor.extract(text)

        assert result.primary_cluster_id == "1234-567890-abc12"

    def test_cluster_id_with_colon(self, extractor: DatabricksContextExtractor) -> None:
        """Extract cluster ID with colon separator."""
        text = "cluster_id: 1234-567890-xyz99"
        result = extractor.extract(text)

        assert result.primary_cluster_id == "1234-567890-xyz99"


# =============================================================================
# JOB ID EXTRACTION
# =============================================================================


class TestJobIdExtraction:
    """Tests for job ID extraction."""

    def test_standard_job_id(self, extractor: DatabricksContextExtractor) -> None:
        """Extract standard job ID."""
        text = "job_id=12345678"
        result = extractor.extract(text)

        assert result.primary_job_id == "12345678"

    def test_job_id_in_url(self, extractor: DatabricksContextExtractor) -> None:
        """Extract job ID from URL."""
        text = "https://databricks.com/jobs/12345678/runs"
        result = extractor.extract(text)

        assert result.primary_job_id == "12345678"


# =============================================================================
# RUN ID EXTRACTION
# =============================================================================


class TestRunIdExtraction:
    """Tests for run ID extraction."""

    def test_standard_run_id(self, extractor: DatabricksContextExtractor) -> None:
        """Extract standard run ID."""
        text = "run_id=9876543210"
        result = extractor.extract(text)

        assert result.primary_run_id == "9876543210"

    def test_run_id_in_url(self, extractor: DatabricksContextExtractor) -> None:
        """Extract run ID from URL."""
        text = "https://databricks.com/runs/9876543210"
        result = extractor.extract(text)

        assert result.primary_run_id == "9876543210"


# =============================================================================
# MULTI-ID EXTRACTION
# =============================================================================


class TestMultiIdExtraction:
    """Tests for extracting multiple IDs."""

    def test_extract_all_ids(self, extractor: DatabricksContextExtractor) -> None:
        """Extract multiple ID types from same text."""
        text = dedent("""
            Job failed:
            cluster_id: 1234-567890-abc12
            job_id: 12345678
            run_id: 9876543210
            """)
        result = extractor.extract(text)

        assert result.primary_cluster_id == "1234-567890-abc12"
        assert result.primary_job_id == "12345678"
        assert result.primary_run_id == "9876543210"

    def test_multiple_cluster_ids(self, extractor: DatabricksContextExtractor) -> None:
        """Multiple cluster IDs - highest confidence wins."""
        text = dedent("""
            cluster_id=1234-567890-abc12
            Old cluster: 0000-111111-xyz99
            """)
        result = extractor.extract(text)

        # First one has explicit label, higher confidence
        assert result.primary_cluster_id == "1234-567890-abc12"
        assert len(result.all_cluster_ids) >= 1


# =============================================================================
# MODE DETERMINATION
# =============================================================================


class TestModeDetermination:
    """Tests for mode determination."""

    def test_online_mode_with_high_confidence_ids(
        self, extractor: DatabricksContextExtractor
    ) -> None:
        """ONLINE mode when multiple high-confidence IDs present."""
        text = dedent("""
            cluster_id: 1234-567890-abc12
            job_id: 12345678
            run_id: 9876543210
            """)
        result = extractor.extract(text)

        assert result.mode == ContextMode.ONLINE
        assert result.has_online_capability

    def test_offline_mode_no_ids(self, extractor: DatabricksContextExtractor) -> None:
        """OFFLINE mode when no IDs found."""
        text = "java.lang.OutOfMemoryError: Java heap space"
        result = extractor.extract(text)

        assert result.mode == ContextMode.OFFLINE
        assert not result.has_online_capability

    def test_hybrid_mode_partial_ids(
        self, extractor: DatabricksContextExtractor
    ) -> None:
        """HYBRID mode with single ID."""
        text = "cluster_id: 1234-567890-abc12"
        result = extractor.extract(text)

        assert result.mode in (ContextMode.ONLINE, ContextMode.HYBRID)


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_text(self, extractor: DatabricksContextExtractor) -> None:
        """Empty text returns OFFLINE mode."""
        result = extractor.extract("")

        assert result.mode == ContextMode.OFFLINE
        assert len(result.extracted_ids) == 0

    def test_false_positive_date(self, extractor: DatabricksContextExtractor) -> None:
        """Date format should not be extracted as cluster ID."""
        text = "Date: 2024-12-17"
        result = extractor.extract(text)

        # Should not extract the date as a cluster ID
        # Low confidence should filter it out
        assert (
            result.primary_cluster_id is None
            or result.primary_cluster_id != "2024-12-17"
        )

    def test_has_online_context(self, extractor: DatabricksContextExtractor) -> None:
        """Quick check method works."""
        text_with_ids = "cluster_id: 1234-567890-abc12"
        text_without = "Just some error text"

        assert extractor.has_online_context(text_with_ids)
        assert not extractor.has_online_context(text_without)


# =============================================================================
# CONFIDENCE SCORING
# =============================================================================


class TestConfidenceScoring:
    """Tests for confidence scoring."""

    def test_explicit_label_high_confidence(
        self, extractor: DatabricksContextExtractor
    ) -> None:
        """Explicit label increases confidence."""
        text = "cluster_id: 1234-567890-abc12"
        result = extractor.extract(text)

        cluster_id = next(
            (eid for eid in result.extracted_ids if eid.id_type == IdType.CLUSTER_ID),
            None,
        )
        assert cluster_id is not None
        assert cluster_id.confidence >= 0.9

    def test_url_medium_confidence(self, extractor: DatabricksContextExtractor) -> None:
        """URL extraction has good confidence."""
        text = "/clusters/1234-567890-abc12"
        result = extractor.extract(text)

        cluster_id = next(
            (eid for eid in result.extracted_ids if eid.id_type == IdType.CLUSTER_ID),
            None,
        )
        assert cluster_id is not None
        assert cluster_id.confidence >= 0.8
