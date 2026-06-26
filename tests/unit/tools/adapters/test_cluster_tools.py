# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for ClusterTools adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starboard_server.tools.adapters.cluster_tools import ClusterTools


class TestClusterTools:
    """Tests for ClusterTools adapter."""

    @pytest.fixture
    def mock_provider(self) -> MagicMock:
        """Create mock SharedContextProvider."""
        provider = MagicMock()
        provider.get = AsyncMock()
        provider.get_many = AsyncMock()
        return provider

    @pytest.fixture
    def tools(self, mock_provider: MagicMock) -> ClusterTools:
        """Create ClusterTools with mock provider."""
        return ClusterTools(provider=mock_provider)

    # =========================================================================
    # get_cluster_config tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_cluster_config_success(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test successful cluster config retrieval."""
        with patch(
            "starboard_server.tools.adapters.cluster_tools.get_transformed"
        ) as mock_get:
            mock_get.return_value = {
                "id": "cluster-123",
                "name": "test-cluster",
                "spark_version": "13.3.x-scala2.12",
            }

            result = await tools.get_cluster_config("cluster-123")

            assert result["found"] is True
            assert result["cluster_id"] == "cluster-123"
            assert result["config"]["name"] == "test-cluster"

    @pytest.mark.asyncio
    async def test_get_cluster_config_not_found(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test cluster config not found returns error dict."""
        with patch(
            "starboard_server.tools.adapters.cluster_tools.get_transformed"
        ) as mock_get:
            mock_get.return_value = None

            result = await tools.get_cluster_config("cluster-456")

            assert result["found"] is False
            assert result["error_type"] == "cluster_not_found"
            assert result["cluster_id"] == "cluster-456"

    # =========================================================================
    # get_cluster_events tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_cluster_events_success(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test successful cluster events retrieval."""
        with patch(
            "starboard_server.tools.adapters.cluster_tools.get_transformed"
        ) as mock_get:
            mock_get.return_value = {
                "events": [
                    {"type": "STARTING", "timestamp": 1234567890},
                    {"type": "RUNNING", "timestamp": 1234567900},
                ],
                "summary": {"start_count": 1},
            }

            result = await tools.get_cluster_events("cluster-123")

            assert result["found"] is True
            assert result["cluster_id"] == "cluster-123"
            assert len(result["events"]["events"]) == 2

    @pytest.mark.asyncio
    async def test_get_cluster_events_not_found(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test cluster events not found returns error dict."""
        with patch(
            "starboard_server.tools.adapters.cluster_tools.get_transformed"
        ) as mock_get:
            mock_get.return_value = None

            result = await tools.get_cluster_events("cluster-456")

            assert result["found"] is False
            assert result["error_type"] == "cluster_not_found"

    # =========================================================================
    # get_cluster_metrics tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_cluster_metrics_success(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test successful cluster metrics retrieval."""
        with patch(
            "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
        ) as mock_metrics:
            mock_metrics.return_value = [
                {"cpu_utilization": 75.5, "memory_utilization": 60.0}
            ]

            result = await tools.get_cluster_metrics("cluster-123")

            assert result["found"] is True
            assert result["cluster_id"] == "cluster-123"
            assert result["metrics"]["cpu_utilization"] == 75.5

    @pytest.mark.asyncio
    async def test_get_cluster_metrics_unavailable(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test cluster metrics unavailable returns not found dict."""
        with patch(
            "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
        ) as mock_metrics:
            mock_metrics.return_value = []

            result = await tools.get_cluster_metrics("cluster-456")

            assert result["found"] is False
            assert "unavailable" in result["reason"].lower()

    # =========================================================================
    # get_spark_logs tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_spark_logs_success(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test successful spark logs retrieval."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.ComputeResolver"
            ) as mock_resolver,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_spark_logs"
            ) as mock_logs,
        ):
            mock_get.return_value = {"id": "cluster-123", "logs": {"path": "/logs"}}
            mock_resolver.is_logging_configured.return_value = True
            mock_resolver.extract_log_destination.return_value = "/logs"
            mock_logs.return_value = {
                "summary": {"total_duration_ms": 45000},
                "stages": [],
            }

            result = await tools.get_spark_logs(cluster_id="cluster-123")

            assert result["found"] is True
            assert result["cluster_id"] == "cluster-123"
            assert "logs" in result

    @pytest.mark.asyncio
    async def test_get_spark_logs_raw_mode(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test spark logs retrieval in raw mode."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.ComputeResolver"
            ) as mock_resolver,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_spark_logs"
            ) as mock_logs,
        ):
            mock_get.return_value = {"id": "cluster-123", "logs": {"path": "/logs"}}
            mock_resolver.is_logging_configured.return_value = True
            mock_resolver.extract_log_destination.return_value = "/logs"
            mock_logs.return_value = {"appInfo": {"appId": "app-123"}}

            result = await tools.get_spark_logs(cluster_id="cluster-123", raw=True)

            assert result["found"] is True
            mock_logs.assert_called_once()
            call_args = mock_logs.call_args
            assert call_args[1]["raw"] is True

    @pytest.mark.asyncio
    async def test_get_spark_logs_cluster_not_found(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test spark logs cluster not found returns error dict."""
        with patch(
            "starboard_server.tools.adapters.cluster_tools.get_transformed"
        ) as mock_get:
            mock_get.return_value = None

            result = await tools.get_spark_logs(cluster_id="cluster-456")

            assert result["found"] is False
            assert result["error_type"] == "cluster_not_found"

    @pytest.mark.asyncio
    async def test_get_spark_logs_unavailable(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test spark logs unavailable when logging not configured."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.ComputeResolver"
            ) as mock_resolver,
        ):
            mock_get.return_value = {"id": "cluster-789"}
            mock_resolver.is_logging_configured.return_value = False

            result = await tools.get_spark_logs(cluster_id="cluster-789")

            assert result["found"] is False
            assert result["error_type"] == "spark_logs_unavailable"
            assert result["cluster_id"] == "cluster-789"
            assert "not configured" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_get_spark_logs_by_job_id(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test spark logs retrieval by job_id."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_job_metadata"
            ) as mock_job,
            patch(
                "starboard_server.tools.adapters.cluster_tools.extract_job_clusters"
            ) as mock_clusters,
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.ComputeResolver"
            ) as mock_resolver,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_spark_logs"
            ) as mock_logs,
        ):
            mock_job.return_value = {"runs": [{"cluster_id": "cluster-abc"}]}
            mock_clusters.return_value = [{"cluster_id": "cluster-abc"}]
            mock_get.return_value = {"id": "cluster-abc", "logs": {"path": "/logs"}}
            mock_resolver.is_logging_configured.return_value = True
            mock_resolver.extract_log_destination.return_value = "/logs"
            mock_logs.return_value = {"summary": {"total_duration_ms": 45000}}

            result = await tools.get_spark_logs(job_id="12345")

            assert result["found"] is True
            assert result["job_id"] == "12345"


class TestListClusters:
    """Tests for list_clusters discovery tool."""

    @pytest.fixture
    def mock_provider(self) -> MagicMock:
        """Create mock SharedContextProvider."""
        provider = MagicMock()
        provider.get = AsyncMock()
        provider.get_many = AsyncMock()
        return provider

    @pytest.fixture
    def tools(self, mock_provider: MagicMock) -> ClusterTools:
        """Create ClusterTools with mock provider."""
        return ClusterTools(provider=mock_provider)

    def _make_cluster(
        self,
        cluster_id: str,
        state: str = "RUNNING",
        last_activity_time: int | None = None,
        terminated_time: int | None = None,
        cluster_source: str = "UI",
    ) -> dict:
        """Helper to create mock cluster data."""
        return {
            "cluster_id": cluster_id,
            "cluster_name": f"cluster-{cluster_id}",
            "state": state,
            "creator": "user@test.com",
            "driver_node_type_id": "i3.xlarge",
            "node_type_id": "i3.xlarge",
            "num_workers": 4,
            "spark_version": "14.3.x-scala2.12",
            "cluster_source": cluster_source,
            "last_activity_time": last_activity_time,
            "terminated_time": terminated_time,
        }

    @staticmethod
    def _now_ms() -> int:
        """Get current time in milliseconds."""
        return int(datetime.now(UTC).timestamp() * 1000)

    @pytest.mark.asyncio
    async def test_list_clusters_returns_cluster_list(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test successful cluster list retrieval."""
        now_ms = self._now_ms()
        mock_provider.get.return_value = [
            self._make_cluster("c1", "RUNNING", last_activity_time=now_ms),
            self._make_cluster(
                "c2", "TERMINATED", terminated_time=now_ms - 86400000
            ),  # 1 day ago
        ]

        result = await tools.list_clusters()

        assert result["total_count"] == 2
        assert len(result["clusters"]) == 2
        assert result["summary"]["running"] == 1
        assert result["summary"]["terminated"] == 1
        assert result["window_days"] == 30

    @pytest.mark.asyncio
    async def test_list_clusters_includes_terminated_by_default(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test that terminated clusters are included by default."""
        now_ms = self._now_ms()
        mock_provider.get.return_value = [
            self._make_cluster("c1", "TERMINATED", terminated_time=now_ms),
            self._make_cluster(
                "c2", "TERMINATED", terminated_time=now_ms - 86400000
            ),  # 1 day ago
        ]

        result = await tools.list_clusters()

        assert result["total_count"] == 2
        assert result["summary"]["terminated"] == 2
        assert result["summary"]["running"] == 0

    @pytest.mark.asyncio
    async def test_list_clusters_excludes_terminated_when_false(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test excluding terminated clusters."""
        now_ms = self._now_ms()
        mock_provider.get.return_value = [
            self._make_cluster("c1", "RUNNING", last_activity_time=now_ms),
            self._make_cluster("c2", "TERMINATED", terminated_time=now_ms),
        ]

        result = await tools.list_clusters(include_terminated=False)

        assert result["total_count"] == 1
        assert result["clusters"][0]["cluster_id"] == "c1"
        assert result["summary"]["running"] == 1
        assert result["summary"]["terminated"] == 0

    @pytest.mark.asyncio
    async def test_list_clusters_filters_by_activity_window(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test filtering clusters by activity window."""
        now_ms = self._now_ms()
        day_ms = 86400000  # 1 day in ms
        # One cluster with activity 5 days ago, another 45 days ago
        mock_provider.get.return_value = [
            self._make_cluster(
                "recent", "TERMINATED", terminated_time=now_ms - 5 * day_ms
            ),
            self._make_cluster(
                "old", "TERMINATED", terminated_time=now_ms - 45 * day_ms
            ),
        ]

        result = await tools.list_clusters(window_days=30)

        # Only recent cluster should be included
        assert result["total_count"] == 1
        assert result["clusters"][0]["cluster_id"] == "recent"

    @pytest.mark.asyncio
    async def test_list_clusters_includes_running_regardless_of_activity(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test that running clusters are always included regardless of activity timestamp."""
        mock_provider.get.return_value = [
            self._make_cluster("running", "RUNNING", last_activity_time=None),
            self._make_cluster("pending", "PENDING", last_activity_time=None),
            self._make_cluster("starting", "STARTING", last_activity_time=None),
        ]

        result = await tools.list_clusters(window_days=7)

        # All running/pending/starting clusters should be included
        assert result["total_count"] == 3
        assert result["summary"]["running"] == 1
        assert result["summary"]["pending"] == 2

    @pytest.mark.asyncio
    async def test_list_clusters_empty_workspace(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test handling empty cluster list."""
        mock_provider.get.return_value = []

        result = await tools.list_clusters()

        assert result["total_count"] == 0
        assert result["clusters"] == []
        assert result["summary"]["running"] == 0
        assert result["summary"]["terminated"] == 0

    @pytest.mark.asyncio
    async def test_list_clusters_none_response(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test handling None response from provider."""
        mock_provider.get.return_value = None

        result = await tools.list_clusters()

        assert result["total_count"] == 0
        assert result["clusters"] == []

    @pytest.mark.asyncio
    async def test_list_clusters_state_summary_counts(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test accurate state counting."""
        now_ms = self._now_ms()
        mock_provider.get.return_value = [
            self._make_cluster("r1", "RUNNING", last_activity_time=now_ms),
            self._make_cluster("r2", "RUNNING", last_activity_time=now_ms),
            self._make_cluster("t1", "TERMINATED", terminated_time=now_ms),
            self._make_cluster("t2", "TERMINATED", terminated_time=now_ms),
            self._make_cluster("t3", "TERMINATED", terminated_time=now_ms),
            self._make_cluster("p1", "PENDING", last_activity_time=now_ms),
            self._make_cluster("s1", "STARTING", last_activity_time=now_ms),
        ]

        result = await tools.list_clusters()

        assert result["summary"]["running"] == 2
        assert result["summary"]["terminated"] == 3
        assert result["summary"]["pending"] == 2
        assert result["summary"]["other"] == 0

    @pytest.mark.asyncio
    async def test_list_clusters_sorted_by_recent_activity(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test clusters are sorted by most recent activity."""
        now_ms = self._now_ms()
        day_ms = 86400000
        mock_provider.get.return_value = [
            self._make_cluster(
                "oldest", "TERMINATED", terminated_time=now_ms - 5 * day_ms
            ),
            self._make_cluster("newest", "TERMINATED", terminated_time=now_ms),
            self._make_cluster(
                "middle", "TERMINATED", terminated_time=now_ms - 2 * day_ms
            ),
        ]

        result = await tools.list_clusters()

        # Should be sorted: newest, middle, oldest
        assert result["clusters"][0]["cluster_id"] == "newest"
        assert result["clusters"][1]["cluster_id"] == "middle"
        assert result["clusters"][2]["cluster_id"] == "oldest"

    @pytest.mark.asyncio
    async def test_list_clusters_includes_cluster_source(
        self, tools: ClusterTools, mock_provider: MagicMock
    ):
        """Test that cluster_source is included in output."""
        now_ms = self._now_ms()
        mock_provider.get.return_value = [
            self._make_cluster(
                "job", "TERMINATED", terminated_time=now_ms, cluster_source="JOB"
            ),
            self._make_cluster(
                "ui", "RUNNING", last_activity_time=now_ms, cluster_source="UI"
            ),
            self._make_cluster(
                "api", "RUNNING", last_activity_time=now_ms, cluster_source="API"
            ),
        ]

        result = await tools.list_clusters()

        sources = {c["cluster_id"]: c["cluster_source"] for c in result["clusters"]}
        assert sources["job"] == "JOB"
        assert sources["ui"] == "UI"
        assert sources["api"] == "API"


class TestGetClusterHealth:
    """Tests for get_cluster_health health assessment tool."""

    @pytest.fixture
    def mock_provider(self) -> MagicMock:
        """Create mock SharedContextProvider."""
        provider = MagicMock()
        provider.get = AsyncMock()
        provider.get_many = AsyncMock()
        return provider

    @pytest.fixture
    def tools(self, mock_provider: MagicMock) -> ClusterTools:
        """Create ClusterTools with mock provider."""
        return ClusterTools(provider=mock_provider)

    @pytest.fixture
    def sample_cluster_config(self) -> dict:
        """Sample cluster configuration for testing."""
        return {
            "cluster_id": "1215-143705-xrnl36ly",
            "cluster_name": "analytics-cluster",
            "spark_version": "14.3.x-scala2.12-lts",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "state": "RUNNING",
            "data_security_mode": "SINGLE_USER",
            "cluster_source": "UI",
        }

    @pytest.fixture
    def sample_metrics(self) -> dict:
        """Sample cluster metrics for testing."""
        return {
            "cpu_utilization_p50": 45.0,
            "cpu_utilization_p95": 75.0,
            "memory_utilization_p50": 60.0,
            "memory_utilization_p95": 85.0,
            "oom_events_30d": 0,
            "task_failure_rate": 0.01,
        }

    @pytest.mark.asyncio
    async def test_get_cluster_health_success(
        self, tools: ClusterTools, sample_cluster_config: dict
    ):
        """Test successful cluster health retrieval."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = sample_cluster_config
            mock_metrics.return_value = []  # No metrics available

            result = await tools.get_cluster_health("1215-143705-xrnl36ly")

            assert result["found"] is True
            assert result["cluster_id"] == "1215-143705-xrnl36ly"
            assert result["cluster_name"] == "analytics-cluster"
            assert "health" in result
            assert "health_score" in result["health"]
            assert 0 <= result["health"]["health_score"] <= 100

    @pytest.mark.asyncio
    async def test_get_cluster_health_with_metrics(
        self,
        tools: ClusterTools,
        sample_cluster_config: dict,
        sample_metrics: dict,
    ):
        """Test cluster health with metrics available."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = sample_cluster_config
            mock_metrics.return_value = [sample_metrics]

            result = await tools.get_cluster_health("1215-143705-xrnl36ly")

            assert result["found"] is True
            assert "health" in result
            # With good metrics, score should be reasonably high
            assert result["health"]["health_score"] >= 60

    @pytest.mark.asyncio
    async def test_get_cluster_health_returns_metric_scores(
        self, tools: ClusterTools, sample_cluster_config: dict
    ):
        """Test that health response includes metric scores by dimension."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = sample_cluster_config
            mock_metrics.return_value = []

            result = await tools.get_cluster_health("1215-143705-xrnl36ly")

            assert "metric_scores" in result["health"]
            metric_scores = result["health"]["metric_scores"]
            assert "performance" in metric_scores
            assert "cost" in metric_scores
            assert "reliability" in metric_scores
            assert "security" in metric_scores

    @pytest.mark.asyncio
    async def test_get_cluster_health_returns_risks(self, tools: ClusterTools):
        """Test that health response includes risks for deprecated runtime."""
        deprecated_config = {
            "cluster_id": "cluster-deprecated",
            "cluster_name": "deprecated-cluster",
            "spark_version": "10.4.x-scala2.12",  # Old, deprecated version
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "state": "RUNNING",
            "data_security_mode": "NONE",  # No isolation - security risk
            "cluster_source": "UI",
        }

        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = deprecated_config
            mock_metrics.return_value = []

            result = await tools.get_cluster_health("cluster-deprecated")

            assert result["found"] is True
            assert "risks" in result["health"]
            risks = result["health"]["risks"]
            # Should have risks for deprecated runtime and no isolation
            assert len(risks) > 0
            # Each risk should have required fields
            for risk in risks:
                assert "category" in risk
                assert "severity" in risk
                assert "title" in risk
                assert "description" in risk
                assert "recommendation" in risk

    @pytest.mark.asyncio
    async def test_get_cluster_health_returns_health_status(
        self, tools: ClusterTools, sample_cluster_config: dict
    ):
        """Test that health response includes health_status."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = sample_cluster_config
            mock_metrics.return_value = []

            result = await tools.get_cluster_health("1215-143705-xrnl36ly")

            assert "health_status" in result["health"]
            assert result["health"]["health_status"] in [
                "healthy",
                "warning",
                "critical",
            ]

    @pytest.mark.asyncio
    async def test_get_cluster_health_cluster_not_found(self, tools: ClusterTools):
        """Test cluster health returns error when cluster not found."""
        with patch(
            "starboard_server.tools.adapters.cluster_tools.get_transformed"
        ) as mock_get:
            mock_get.return_value = None

            result = await tools.get_cluster_health("cluster-not-found")

            assert result["found"] is False
            assert result["error_type"] == "cluster_not_found"
            assert result["cluster_id"] == "cluster-not-found"

    @pytest.mark.asyncio
    async def test_get_cluster_health_handles_metrics_failure(
        self, tools: ClusterTools, sample_cluster_config: dict
    ):
        """Test that health assessment works even when metrics fail."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = sample_cluster_config
            mock_metrics.side_effect = Exception("Metrics service unavailable")

            result = await tools.get_cluster_health("1215-143705-xrnl36ly")

            # Should still return health based on config
            assert result["found"] is True
            assert "health" in result
            assert result["health"]["health_score"] > 0

    @pytest.mark.asyncio
    async def test_get_cluster_health_returns_risk_counts(self, tools: ClusterTools):
        """Test that health response includes risk counts."""
        risky_config = {
            "cluster_id": "cluster-risky",
            "cluster_name": "risky-cluster",
            "spark_version": "10.4.x-scala2.12",  # Deprecated
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "state": "RUNNING",
            "data_security_mode": "NONE",  # No isolation
            "cluster_source": "UI",
        }

        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = risky_config
            mock_metrics.return_value = []

            result = await tools.get_cluster_health("cluster-risky")

            assert "critical_risks" in result["health"]
            assert "high_priority_risks" in result["health"]
            assert isinstance(result["health"]["critical_risks"], int)
            assert isinstance(result["health"]["high_priority_risks"], int)

    @pytest.mark.asyncio
    async def test_get_cluster_health_returns_summary(
        self, tools: ClusterTools, sample_cluster_config: dict
    ):
        """Test that health response includes summary text."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = sample_cluster_config
            mock_metrics.return_value = []

            result = await tools.get_cluster_health("1215-143705-xrnl36ly")

            assert "summary" in result["health"]
            assert result["health"]["summary"] is not None
            assert len(result["health"]["summary"]) > 0

    @pytest.mark.asyncio
    async def test_get_cluster_health_returns_generated_at(
        self, tools: ClusterTools, sample_cluster_config: dict
    ):
        """Test that health response includes generation timestamp."""
        with (
            patch(
                "starboard_server.tools.adapters.cluster_tools.get_transformed"
            ) as mock_get,
            patch(
                "starboard_server.tools.adapters.cluster_tools.analyze_cluster_metrics"
            ) as mock_metrics,
        ):
            mock_get.return_value = sample_cluster_config
            mock_metrics.return_value = []

            result = await tools.get_cluster_health("1215-143705-xrnl36ly")

            assert "generated_at" in result["health"]
            # Should be ISO format timestamp
            assert "T" in result["health"]["generated_at"]


class TestClusterToolsFactory:
    """Test ClusterTools factory methods."""

    def test_from_provider(self):
        """Test creating ClusterTools from SharedContextProvider."""
        mock_provider = MagicMock()
        mock_provider.get = AsyncMock()
        mock_provider.get_many = AsyncMock()

        tools = ClusterTools.from_provider(mock_provider)

        assert tools is not None
        assert tools.provider is mock_provider
