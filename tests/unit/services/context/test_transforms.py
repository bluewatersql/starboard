# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for context transforms module.

Tests the transform utilities that replace the facade pattern.
These functions provide direct transformation without facade indirection.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class MockProvider:
    """Mock SharedContextProvider for testing."""

    def __init__(self):
        self.data: dict[str, Any] = {}

    async def get(self, resource_type: str, resource_id: str, **kwargs) -> Any:
        key = f"{resource_type}::{resource_id}"
        return self.data.get(key)

    async def get_many(
        self, resource_type: str, resource_ids: list[str], **kwargs
    ) -> dict[str, Any]:
        result = {}
        for resource_id in resource_ids:
            key = f"{resource_type}::{resource_id}"
            if key in self.data:
                result[resource_id] = self.data[key]
        return result


class TestGetTransformed:
    """Tests for get_transformed helper function."""

    @pytest.fixture
    def mock_provider(self) -> MockProvider:
        """Create mock provider."""
        return MockProvider()

    @pytest.mark.asyncio
    async def test_get_transformed_with_transform_fn(self, mock_provider: MockProvider):
        """Test getting and transforming data."""
        from starboard_server.services.context.transforms import get_transformed

        mock_provider.data["cluster_config::cluster-123"] = {
            "cluster_id": "cluster-123",
            "cluster_name": "test-cluster",
        }

        def mock_transform(data):
            return {"id": data["cluster_id"], "name": data["cluster_name"]}

        result = await get_transformed(
            mock_provider,
            "cluster_config",
            "cluster-123",
            transform_fn=mock_transform,
        )

        assert result is not None
        assert result["id"] == "cluster-123"
        assert result["name"] == "test-cluster"

    @pytest.mark.asyncio
    async def test_get_transformed_without_transform_fn(
        self, mock_provider: MockProvider
    ):
        """Test getting data without transformation."""
        from starboard_server.services.context.transforms import get_transformed

        mock_provider.data["cluster_config::cluster-123"] = {
            "cluster_id": "cluster-123",
        }

        result = await get_transformed(
            mock_provider,
            "cluster_config",
            "cluster-123",
            transform_fn=None,
        )

        assert result is not None
        assert result["cluster_id"] == "cluster-123"

    @pytest.mark.asyncio
    async def test_get_transformed_not_found(self, mock_provider: MockProvider):
        """Test getting data when resource not found."""
        from starboard_server.services.context.transforms import get_transformed

        result = await get_transformed(
            mock_provider,
            "cluster_config",
            "nonexistent",
            transform_fn=lambda x: x,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_transformed_with_kwargs(self, mock_provider: MockProvider):
        """Test that kwargs are passed to provider."""
        from starboard_server.services.context.transforms import get_transformed

        # Create a mock that captures kwargs
        captured_kwargs = {}

        async def mock_get(resource_type, resource_id, **kwargs):
            captured_kwargs.update(kwargs)
            return {"data": "test"}

        mock_provider.get = mock_get

        await get_transformed(
            mock_provider,
            "warehouse_metrics",
            "wh-123",
            transform_fn=None,
            days_history=30,
        )

        assert captured_kwargs.get("days_history") == 30


class TestAnalyzeClusterMetrics:
    """Tests for analyze_cluster_metrics helper function."""

    @pytest.fixture
    def mock_provider(self) -> MockProvider:
        """Create mock provider."""
        return MockProvider()

    @pytest.mark.asyncio
    async def test_analyze_cluster_metrics_with_data(self, mock_provider: MockProvider):
        """Test analyzing cluster metrics when data exists."""
        from starboard_server.services.context.transforms import analyze_cluster_metrics

        mock_provider.data["cluster_metrics::cluster-123"] = {
            "metrics": {"cpu_utilization": 75.5}
        }

        with patch(
            "starboard_server.services.context.transforms.ClusterMetricsAnalyzer"
        ) as mock_analyzer_class:
            mock_analyzer = MagicMock()
            mock_analyzer.analyze.return_value = [{"id": "cluster-123", "metrics": {}}]
            mock_analyzer_class.return_value = mock_analyzer

            result = await analyze_cluster_metrics(mock_provider, ["cluster-123"])

            assert result is not None
            assert len(result) == 1
            mock_analyzer_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_cluster_metrics_empty_list(
        self, mock_provider: MockProvider
    ):
        """Test analyzing cluster metrics with empty cluster list."""
        from starboard_server.services.context.transforms import analyze_cluster_metrics

        result = await analyze_cluster_metrics(mock_provider, [])
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_cluster_metrics_not_found(self, mock_provider: MockProvider):
        """Test analyzing cluster metrics when data not found."""
        from starboard_server.services.context.transforms import analyze_cluster_metrics

        result = await analyze_cluster_metrics(mock_provider, ["nonexistent"])
        assert result is None


class TestAnalyzeWarehouseQueries:
    """Tests for analyze_warehouse_queries helper function."""

    @pytest.fixture
    def mock_provider(self) -> MockProvider:
        """Create mock provider."""
        return MockProvider()

    @pytest.mark.asyncio
    async def test_analyze_warehouse_queries_with_data(
        self, mock_provider: MockProvider
    ):
        """Test analyzing warehouse queries when data exists."""
        from starboard_server.services.context.transforms import (
            analyze_warehouse_queries,
        )

        mock_provider.data["warehouse_query_history::wh-123"] = {
            "queries": [{"id": "q1"}, {"id": "q2"}]
        }

        with patch(
            "starboard_server.services.context.transforms.WarehouseQueryAnalyzer"
        ) as mock_analyzer_class:
            mock_analyzer = MagicMock()
            mock_analyzer.analyze.return_value = {
                "summary": {},
                "patterns": [],
            }
            mock_analyzer_class.return_value = mock_analyzer

            result = await analyze_warehouse_queries(mock_provider, "wh-123")

            assert result is not None
            mock_analyzer_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_warehouse_queries_with_days(
        self, mock_provider: MockProvider
    ):
        """Test analyzing warehouse queries with custom days parameter."""
        from starboard_server.services.context.transforms import (
            analyze_warehouse_queries,
        )

        # Track the call parameters
        captured_kwargs = {}

        async def mock_get(resource_type, resource_id, **kwargs):
            captured_kwargs.update(kwargs)
            return None

        mock_provider.get = mock_get

        await analyze_warehouse_queries(mock_provider, "wh-123", days_history=14)

        assert captured_kwargs.get("days_history") == 14

    @pytest.mark.asyncio
    async def test_analyze_warehouse_queries_not_found(
        self, mock_provider: MockProvider
    ):
        """Test analyzing warehouse queries when data not found."""
        from starboard_server.services.context.transforms import (
            analyze_warehouse_queries,
        )

        result = await analyze_warehouse_queries(mock_provider, "nonexistent")
        assert result is None


class TestAnalyzeSparkLogs:
    """Tests for analyze_spark_logs helper function."""

    def test_analyze_spark_logs_found(self):
        """Test analyzing spark logs when found."""
        from starboard_server.services.context.transforms import analyze_spark_logs

        with patch(
            "starboard_server.services.context.transforms.create_spark_application"
        ) as mock_create:
            mock_app = MagicMock()
            mock_app.to_dict.return_value = {
                "appInfo": {"appId": "app-123"},
                "accumData": [],
            }
            mock_create.return_value = mock_app

            with patch(
                "starboard_server.services.context.transforms.SparkUIAnalyzer"
            ) as mock_analyzer_class:
                mock_analyzer = MagicMock()
                mock_result = MagicMock()
                mock_result.to_dict.return_value = {"summary": {}}
                mock_analyzer.analyze.return_value = mock_result
                mock_analyzer_class.return_value = mock_analyzer

                result = analyze_spark_logs("cluster-123", "dbfs:/logs")

                assert result is not None
                mock_create.assert_called_once_with(
                    path="dbfs:/logs/cluster-123/eventlog/"
                )

    def test_analyze_spark_logs_raw_mode(self):
        """Test analyzing spark logs in raw mode."""
        from starboard_server.services.context.transforms import analyze_spark_logs

        with patch(
            "starboard_server.services.context.transforms.create_spark_application"
        ) as mock_create:
            mock_app = MagicMock()
            mock_app.to_dict.return_value = {
                "appInfo": {"appId": "app-123"},
                "accumData": [],
            }
            mock_create.return_value = mock_app

            result = analyze_spark_logs("cluster-123", "dbfs:/logs", raw=True)

            assert result is not None
            assert "appInfo" in result
            assert "accumData" not in result  # Should be deleted

    def test_analyze_spark_logs_not_found(self):
        """Test analyzing spark logs when not found."""
        from starboard_server.services.context.transforms import analyze_spark_logs

        with patch(
            "starboard_server.services.context.transforms.create_spark_application"
        ) as mock_create:
            mock_create.return_value = None

            result = analyze_spark_logs("cluster-123", "dbfs:/logs")
            assert result is None

    def test_analyze_spark_logs_path_not_found_error(self):
        """Test analyzing spark logs when path not found."""
        from starboard_log_parser import SparkLogPathNotFoundError
        from starboard_server.services.context.transforms import analyze_spark_logs

        with patch(
            "starboard_server.services.context.transforms.create_spark_application"
        ) as mock_create:
            mock_create.side_effect = SparkLogPathNotFoundError("path not found")

            result = analyze_spark_logs("cluster-123", "dbfs:/logs")
            assert result is None

    def test_analyze_spark_logs_parse_error_raises(self):
        """Test that parse errors are raised."""
        from starboard_server.services.context.transforms import analyze_spark_logs

        with patch(
            "starboard_server.services.context.transforms.create_spark_application"
        ) as mock_create:
            mock_create.side_effect = ValueError("Parse error")

            with pytest.raises(ValueError, match="Parse error"):
                analyze_spark_logs("cluster-123", "dbfs:/logs")

    def test_analyze_spark_logs_dbfs_path_passes_to_factory(self):
        """Test that DBFS paths are passed through to create_spark_application."""
        from starboard_server.services.context.transforms import analyze_spark_logs

        with patch(
            "starboard_server.services.context.transforms.create_spark_application"
        ) as mock_create:
            mock_create.return_value = None

            result = analyze_spark_logs("cluster-123", "dbfs:/cluster-logs")
            assert result is None
            mock_create.assert_called_once_with(
                path="dbfs:/cluster-logs/cluster-123/eventlog/"
            )


class TestTransformExports:
    """Test that all expected transforms are exported."""

    def test_cluster_transforms_exported(self):
        """Verify cluster transform functions are exported."""
        from starboard_server.services.context.transforms import (
            ClusterMetricsAnalyzer,
            SparkUIAnalyzer,
            transform_cluster_config,
            transform_cluster_events,
        )

        assert callable(transform_cluster_config)
        assert callable(transform_cluster_events)
        assert ClusterMetricsAnalyzer is not None
        assert SparkUIAnalyzer is not None

    def test_warehouse_transforms_exported(self):
        """Verify warehouse transform functions are exported."""
        from starboard_server.services.context.transforms import (
            WarehouseQueryAnalyzer,
            transform_query_history,
            transform_warehouse_configuration,
        )

        assert callable(transform_warehouse_configuration)
        assert callable(transform_query_history)
        assert WarehouseQueryAnalyzer is not None

    def test_table_transforms_exported(self):
        """Verify table transform functions are exported."""
        from starboard_server.services.context.transforms import (
            transform_delta_history,
            transform_table_lineage,
            transform_table_metadata,
        )

        assert callable(transform_table_metadata)
        assert callable(transform_table_lineage)
        assert callable(transform_delta_history)

    def test_job_transforms_exported(self):
        """Verify job transform functions are exported."""
        from starboard_server.services.context.transforms import (
            transform_job_config,
            transform_job_runs,
            transform_system_tables_job_detail,
        )

        assert callable(transform_job_config)
        assert callable(transform_job_runs)
        assert callable(transform_system_tables_job_detail)

    def test_helper_functions_exported(self):
        """Verify helper functions are exported."""
        from starboard_server.services.context.transforms import (
            analyze_cluster_metrics,
            analyze_spark_logs,
            analyze_warehouse_queries,
            get_job_metadata,
            get_jobs_list,
            get_transformed,
            search_jobs_by_name,
        )

        assert callable(get_transformed)
        assert callable(analyze_cluster_metrics)
        assert callable(analyze_spark_logs)
        assert callable(analyze_warehouse_queries)
        assert callable(get_job_metadata)
        assert callable(search_jobs_by_name)
        assert callable(get_jobs_list)


class TestGetJobMetadata:
    """Tests for get_job_metadata helper function."""

    @pytest.fixture
    def mock_provider(self) -> MockProvider:
        """Create mock provider."""
        return MockProvider()

    @pytest.mark.asyncio
    async def test_get_job_metadata_found(self, mock_provider: MockProvider):
        """Test getting job metadata when job exists."""
        from starboard_server.services.context.transforms import get_job_metadata

        mock_provider.data["job_metadata::12345"] = {
            "job_settings": {
                "name": "test-job",
                "tasks": [{"task_key": "main"}],
            },
            "runs": [
                {"run_id": 1, "state": {"result_state": "SUCCESS"}},
            ],
        }

        with (
            patch(
                "starboard_server.services.context.transforms.transform_job_config"
            ) as mock_config,
            patch(
                "starboard_server.services.context.transforms.transform_job_runs"
            ) as mock_runs,
        ):
            mock_config.return_value = {"job": {"name": "test-job"}}
            mock_runs.return_value = {"total_runs": 1, "success_rate": 1.0}

            result = await get_job_metadata(mock_provider, "12345")

            assert result is not None
            assert "job_settings" in result
            assert "parsed_settings" in result
            assert "runtime_meta" in result
            assert "runs" in result
            mock_config.assert_called_once()
            mock_runs.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_job_metadata_not_found(self, mock_provider: MockProvider):
        """Test getting job metadata when job not found."""
        from starboard_server.services.context.transforms import get_job_metadata

        result = await get_job_metadata(mock_provider, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_metadata_with_max_runs(self, mock_provider: MockProvider):
        """Test that max_runs parameter is passed correctly."""
        from starboard_server.services.context.transforms import get_job_metadata

        captured_kwargs = {}

        async def mock_get(resource_type, resource_id, **kwargs):
            captured_kwargs.update(kwargs)
            return None

        mock_provider.get = mock_get

        await get_job_metadata(mock_provider, "12345", max_runs=10)

        assert captured_kwargs.get("max_runs") == 10


class TestSearchJobsByName:
    """Tests for search_jobs_by_name helper function."""

    @pytest.fixture
    def mock_provider(self) -> MockProvider:
        """Create mock provider."""
        return MockProvider()

    @pytest.mark.asyncio
    async def test_search_jobs_by_name_exact_match(self, mock_provider: MockProvider):
        """Test searching for jobs with exact match."""
        from starboard_server.services.context.transforms import search_jobs_by_name

        mock_provider.data["jobs_by_name::my-job"] = {
            "exact_match": True,
            "job_id": "12345",
            "matches": [{"job_id": "12345", "settings": {"name": "my-job"}}],
        }

        result = await search_jobs_by_name(mock_provider, "my-job")

        assert result is not None
        assert result["exact_match"] is True
        assert result["job_id"] == "12345"

    @pytest.mark.asyncio
    async def test_search_jobs_by_name_partial_match(self, mock_provider: MockProvider):
        """Test searching for jobs with partial match."""
        from starboard_server.services.context.transforms import search_jobs_by_name

        mock_provider.data["jobs_by_name::my"] = {
            "exact_match": False,
            "matches": [
                {"job_id": "12345", "settings": {"name": "my-job-1"}},
                {"job_id": "12346", "settings": {"name": "my-job-2"}},
            ],
        }

        result = await search_jobs_by_name(mock_provider, "my")

        assert result is not None
        assert result["exact_match"] is False
        assert len(result["matches"]) == 2

    @pytest.mark.asyncio
    async def test_search_jobs_by_name_not_found(self, mock_provider: MockProvider):
        """Test searching for jobs when none found."""
        from starboard_server.services.context.transforms import search_jobs_by_name

        result = await search_jobs_by_name(mock_provider, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_search_jobs_by_name_with_params(self, mock_provider: MockProvider):
        """Test that exact_match and limit parameters are passed."""
        from starboard_server.services.context.transforms import search_jobs_by_name

        captured_kwargs = {}

        async def mock_get(resource_type, resource_id, **kwargs):
            captured_kwargs.update(kwargs)
            return None

        mock_provider.get = mock_get

        await search_jobs_by_name(mock_provider, "my-job", exact_match=False, limit=10)

        assert captured_kwargs.get("exact_match") is False
        assert captured_kwargs.get("limit") == 10


class TestGetJobsList:
    """Tests for get_jobs_list helper function."""

    @pytest.fixture
    def mock_provider(self) -> MockProvider:
        """Create mock provider."""
        return MockProvider()

    @pytest.mark.asyncio
    async def test_get_jobs_list_found(self, mock_provider: MockProvider):
        """Test getting jobs list when jobs exist."""
        from starboard_server.services.context.transforms import get_jobs_list

        mock_provider.data["jobs_list::all"] = [
            {"job_id": "12345", "settings": {"name": "job-1"}},
            {"job_id": "12346", "settings": {"name": "job-2"}},
        ]

        result = await get_jobs_list(mock_provider)

        assert result is not None
        assert len(result) == 2
        assert result[0]["job_id"] == "12345"

    @pytest.mark.asyncio
    async def test_get_jobs_list_empty(self, mock_provider: MockProvider):
        """Test getting jobs list when none found."""
        from starboard_server.services.context.transforms import get_jobs_list

        result = await get_jobs_list(mock_provider)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_jobs_list_with_limit(self, mock_provider: MockProvider):
        """Test that limit parameter is passed correctly."""
        from starboard_server.services.context.transforms import get_jobs_list

        captured_kwargs = {}

        async def mock_get(resource_type, resource_id, **kwargs):
            captured_kwargs.update(kwargs)
            return None

        mock_provider.get = mock_get

        await get_jobs_list(mock_provider, limit=50)

        assert captured_kwargs.get("limit") == 50


class TestGetExplainPlan:
    """Tests for get_explain_plan helper function."""

    @pytest.fixture
    def mock_provider(self) -> MockProvider:
        """Create mock provider."""
        return MockProvider()

    @pytest.mark.asyncio
    async def test_get_explain_plan_found(self, mock_provider: MockProvider):
        """Test getting explain plan when available."""
        from starboard_server.services.context.transforms import get_explain_plan

        mock_provider.data["explain_plan::SELECT * FROM t"] = (
            "== Physical Plan ==\nScan..."
        )

        result = await get_explain_plan(mock_provider, "SELECT * FROM t")

        assert result is not None
        assert "Physical Plan" in result

    @pytest.mark.asyncio
    async def test_get_explain_plan_not_found(self, mock_provider: MockProvider):
        """Test getting explain plan when not available."""
        from starboard_server.services.context.transforms import get_explain_plan

        result = await get_explain_plan(mock_provider, "SELECT * FROM nonexistent")
        assert result is None
