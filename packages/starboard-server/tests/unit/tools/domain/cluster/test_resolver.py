# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for compute resolver domain logic."""

from starboard_server.tools.domain.cluster.resolver import ComputeResolver


class TestComputeResolver:
    """Test suite for ComputeResolver pure functions."""

    def test_resolve_cluster_from_job_clusters_success(self):
        """Test successful cluster resolution from job clusters."""
        # Arrange - newer date has higher epoch timestamp
        clusters = [
            {"cluster_id": "cluster-123", "run_date": 1704067200000},  # 2024-01-01
            {
                "cluster_id": "cluster-456",
                "run_date": 1704153600000,
            },  # 2024-01-02 (newer)
        ]

        # Act
        result = ComputeResolver.resolve_cluster_from_job_clusters(clusters)

        # Assert - should return newest cluster
        assert result == "cluster-456"

    def test_resolve_cluster_from_job_clusters_empty_list(self):
        """Test cluster resolution with empty list."""
        # Arrange
        clusters = []

        # Act
        result = ComputeResolver.resolve_cluster_from_job_clusters(clusters)

        # Assert
        assert result is None

    def test_resolve_cluster_from_job_clusters_none_input(self):
        """Test cluster resolution with None input."""
        # Act
        result = ComputeResolver.resolve_cluster_from_job_clusters(None)

        # Assert
        assert result is None

    def test_resolve_cluster_from_job_clusters_missing_id(self):
        """Test cluster resolution with missing cluster_id in newest entry."""
        # Arrange - newest entry is missing cluster_id
        clusters = [
            {"run_date": 1704067200000, "cluster_id": "cluster-123"},  # 2024-01-01
            {"run_date": 1704153600000},  # 2024-01-02 (newer, but missing cluster_id)
        ]

        # Act
        result = ComputeResolver.resolve_cluster_from_job_clusters(clusters)

        # Assert - should return None since newest cluster has no ID
        assert result is None

    def test_resolve_cluster_from_job_clusters_sorts_correctly(self):
        """Test that clusters are sorted by run_date descending."""
        # Arrange - provide clusters in wrong order (oldest first)
        clusters = [
            {
                "cluster_id": "cluster-old",
                "run_date": 1704067200000,
            },  # 2024-01-01 (oldest)
            {"cluster_id": "cluster-middle", "run_date": 1704153600000},  # 2024-01-02
            {
                "cluster_id": "cluster-new",
                "run_date": 1704240000000,
            },  # 2024-01-03 (newest)
        ]

        # Act
        result = ComputeResolver.resolve_cluster_from_job_clusters(clusters)

        # Assert - should return newest cluster despite input order
        assert result == "cluster-new"

    def test_resolve_cluster_from_job_clusters_handles_missing_run_date(self):
        """Test that clusters with missing run_date are treated as oldest."""
        # Arrange
        clusters = [
            {
                "cluster_id": "cluster-no-date"
            },  # Missing run_date (should be treated as 0)
            {
                "cluster_id": "cluster-with-date",
                "run_date": 1704067200000,
            },  # 2024-01-01
        ]

        # Act
        result = ComputeResolver.resolve_cluster_from_job_clusters(clusters)

        # Assert - should return cluster with date (treated as newer)
        assert result == "cluster-with-date"

    def test_extract_log_destination_success(self):
        """Test successful log destination extraction."""
        # Arrange
        config = {
            "id": "cluster-123",
            "logs": {"destination": "dbfs:/logs/cluster-123"},
        }

        # Act
        result = ComputeResolver.extract_log_destination(config)

        # Assert
        assert result == "dbfs:/logs/cluster-123"

    def test_extract_log_destination_no_logs(self):
        """Test log destination extraction with no logs configured."""
        # Arrange
        config = {"id": "cluster-123"}

        # Act
        result = ComputeResolver.extract_log_destination(config)

        # Assert
        assert result is None

    def test_extract_log_destination_no_destination(self):
        """Test log destination extraction with logs but no destination."""
        # Arrange
        config = {"id": "cluster-123", "logs": {}}

        # Act
        result = ComputeResolver.extract_log_destination(config)

        # Assert
        assert result is None

    def test_extract_log_destination_none_config(self):
        """Test log destination extraction with None config."""
        # Act
        result = ComputeResolver.extract_log_destination(None)

        # Assert
        assert result is None

    def test_is_logging_configured_true(self):
        """Test is_logging_configured returns True when configured."""
        # Arrange
        config = {"logs": {"destination": "dbfs:/logs/cluster-123"}}

        # Act
        result = ComputeResolver.is_logging_configured(config)

        # Assert
        assert result is True

    def test_is_logging_configured_false(self):
        """Test is_logging_configured returns False when not configured."""
        # Arrange
        config = {"id": "cluster-123"}

        # Act
        result = ComputeResolver.is_logging_configured(config)

        # Assert
        assert result is False
