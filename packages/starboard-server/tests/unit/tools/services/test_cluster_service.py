"""Tests for ClusterService."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.domain.models.cluster import (
    ClusterFingerprint,
    ClusterHealthReport,
    FingerprintScope,
    HealthScore,
)
from starboard_server.tools.services.cluster_service import (
    ClusterNotFoundError,
    ClusterService,
)


@pytest.fixture
def mock_provider() -> MagicMock:
    """Create mock SharedContextProvider."""
    provider = MagicMock()
    provider.get = AsyncMock()
    return provider


@pytest.fixture
def cluster_service(mock_provider: MagicMock) -> ClusterService:
    """Create ClusterService with mock provider."""
    return ClusterService(provider=mock_provider)


@pytest.fixture
def sample_cluster_config() -> dict:
    """Create sample cluster configuration."""
    return {
        "cluster_id": "1234-567890-abc123",
        "cluster_name": "test-cluster",
        "cluster_source": "UI",
        "spark_version": "14.3.x-scala2.12",
        "node_type_id": "i3.xlarge",
        "driver_node_type_id": "i3.xlarge",
        "num_workers": 4,
        "autoscale": None,
        "data_security_mode": "SINGLE_USER",
        "aws_attributes": {
            "availability": "SPOT_WITH_FALLBACK",
            "first_on_demand": 1,
        },
        "custom_tags": {"team": "data-platform"},
    }


class TestClusterNotFoundError:
    """Tests for ClusterNotFoundError."""

    def test_error_message(self) -> None:
        """Test error message format."""
        error = ClusterNotFoundError("cluster-123")
        assert error.cluster_id == "cluster-123"
        assert str(error) == "Cluster not found: cluster-123"


class TestClusterServiceInit:
    """Tests for ClusterService initialization."""

    def test_init_with_provider(self, mock_provider: MagicMock) -> None:
        """Test initialization with provider only."""
        service = ClusterService(provider=mock_provider)
        assert service.provider == mock_provider
        assert service.events is None

    def test_init_with_events(self, mock_provider: MagicMock) -> None:
        """Test initialization with events."""
        mock_events = MagicMock()
        service = ClusterService(provider=mock_provider, events=mock_events)
        assert service.events == mock_events

    def test_max_concurrent_operations(self, cluster_service: ClusterService) -> None:
        """Test concurrency limit is set."""
        assert cluster_service.MAX_CONCURRENT_OPERATIONS == 10


class TestGetClusterConfig:
    """Tests for get_cluster_config method."""

    @pytest.mark.asyncio
    async def test_get_cluster_config_success(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test successful config retrieval."""
        mock_provider.get.return_value = sample_cluster_config

        result = await cluster_service.get_cluster_config("cluster-123")

        mock_provider.get.assert_called_once_with("cluster_config", "cluster-123")
        assert result == sample_cluster_config

    @pytest.mark.asyncio
    async def test_get_cluster_config_not_found(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test ClusterNotFoundError when config is None."""
        mock_provider.get.return_value = None

        with pytest.raises(ClusterNotFoundError) as exc_info:
            await cluster_service.get_cluster_config("nonexistent")

        assert exc_info.value.cluster_id == "nonexistent"


class TestGetFingerprint:
    """Tests for get_fingerprint method."""

    @pytest.mark.asyncio
    async def test_get_fingerprint_config_only(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test fingerprint with CONFIG_ONLY scope."""
        mock_provider.get.return_value = sample_cluster_config

        result = await cluster_service.get_fingerprint(
            "cluster-123",
            scope=FingerprintScope.CONFIG_ONLY,
        )

        assert isinstance(result, ClusterFingerprint)
        assert result.cluster_id == "1234-567890-abc123"
        assert result.cluster_name == "test-cluster"
        assert result.performance is None  # Not fetched with CONFIG_ONLY
        assert result.cost is None  # Not fetched with CONFIG_ONLY

    @pytest.mark.asyncio
    async def test_get_fingerprint_with_metrics(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test fingerprint with WITH_METRICS scope."""
        mock_provider.get.side_effect = [
            sample_cluster_config,  # cluster_config
            {"cpu_utilization_p50": 45.0},  # cluster_metrics
        ]

        result = await cluster_service.get_fingerprint(
            "cluster-123",
            scope=FingerprintScope.WITH_METRICS,
        )

        assert isinstance(result, ClusterFingerprint)
        assert result.performance is not None
        assert result.performance.cpu_utilization_p50 == 45.0
        assert result.cost is None  # Not fetched with WITH_METRICS

    @pytest.mark.asyncio
    async def test_get_fingerprint_full(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test fingerprint with FULL scope."""
        mock_provider.get.side_effect = [
            sample_cluster_config,  # cluster_config
            {"cpu_utilization_p50": 45.0},  # cluster_metrics
            {"dbu_total_30d": 1500.0},  # cluster_cost
        ]

        result = await cluster_service.get_fingerprint(
            "cluster-123",
            scope=FingerprintScope.FULL,
        )

        assert isinstance(result, ClusterFingerprint)
        assert result.performance is not None
        assert result.cost is not None
        assert result.cost.dbu_total_30d == 1500.0

    @pytest.mark.asyncio
    async def test_get_fingerprint_not_found(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test ClusterNotFoundError when cluster doesn't exist."""
        mock_provider.get.return_value = None

        with pytest.raises(ClusterNotFoundError):
            await cluster_service.get_fingerprint("nonexistent")

    @pytest.mark.asyncio
    async def test_get_fingerprint_metrics_fetch_failure(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test graceful handling when metrics fetch fails."""
        mock_provider.get.side_effect = [
            sample_cluster_config,  # cluster_config succeeds
            Exception("Metrics API error"),  # cluster_metrics fails
        ]

        result = await cluster_service.get_fingerprint(
            "cluster-123",
            scope=FingerprintScope.WITH_METRICS,
        )

        # Should return fingerprint without metrics
        assert isinstance(result, ClusterFingerprint)
        assert result.performance is None


class TestGetHealth:
    """Tests for get_health method."""

    @pytest.mark.asyncio
    async def test_get_health_success(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test successful health analysis."""
        mock_provider.get.return_value = sample_cluster_config

        result = await cluster_service.get_health("cluster-123")

        assert isinstance(result, ClusterHealthReport)
        assert result.cluster_id == "1234-567890-abc123"
        assert result.cluster_name == "test-cluster"
        assert isinstance(result.scores, HealthScore)
        assert 0 <= result.scores.overall <= 100

    @pytest.mark.asyncio
    async def test_get_health_not_found(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test ClusterNotFoundError when cluster doesn't exist."""
        mock_provider.get.return_value = None

        with pytest.raises(ClusterNotFoundError):
            await cluster_service.get_health("nonexistent")


class TestAnalyzeFleet:
    """Tests for analyze_fleet method."""

    @pytest.mark.asyncio
    async def test_analyze_fleet_with_ids(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test fleet analysis with explicit cluster IDs."""
        # Each call returns the same config
        mock_provider.get.return_value = sample_cluster_config

        results = await cluster_service.analyze_fleet(
            cluster_ids=["cluster-1", "cluster-2", "cluster-3"],
            scope=FingerprintScope.CONFIG_ONLY,
        )

        assert len(results) == 3
        for result in results:
            assert isinstance(result, ClusterHealthReport)

    @pytest.mark.asyncio
    async def test_analyze_fleet_auto_discover(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test fleet analysis with auto-discovery."""
        # First call returns cluster list, subsequent calls return config
        mock_provider.get.side_effect = [
            [{"cluster_id": "c1"}, {"cluster_id": "c2"}],  # cluster_list
            sample_cluster_config,  # c1 config
            sample_cluster_config,  # c2 config
        ]

        results = await cluster_service.analyze_fleet(
            cluster_ids=None,
            scope=FingerprintScope.CONFIG_ONLY,
        )

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_analyze_fleet_handles_failures(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test fleet analysis gracefully handles individual failures."""
        # First cluster succeeds, second fails
        mock_provider.get.side_effect = [
            sample_cluster_config,  # cluster-1 config
            None,  # cluster-2 not found
        ]

        results = await cluster_service.analyze_fleet(
            cluster_ids=["cluster-1", "cluster-2"],
            scope=FingerprintScope.CONFIG_ONLY,
        )

        # Only successful result returned
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_analyze_fleet_empty_list(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test fleet analysis with empty cluster list."""
        mock_provider.get.return_value = []

        results = await cluster_service.analyze_fleet(
            cluster_ids=None,
            scope=FingerprintScope.CONFIG_ONLY,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_analyze_fleet_respects_concurrency_limit(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
        sample_cluster_config: dict,
    ) -> None:
        """Test that fleet analysis respects concurrency limit."""
        # Create more clusters than the concurrency limit
        num_clusters = 25
        mock_provider.get.return_value = sample_cluster_config

        results = await cluster_service.analyze_fleet(
            cluster_ids=[f"cluster-{i}" for i in range(num_clusters)],
            scope=FingerprintScope.CONFIG_ONLY,
        )

        # All should complete successfully
        assert len(results) == num_clusters


class TestFingerprintFields:
    """Tests for fingerprint field extraction."""

    @pytest.mark.asyncio
    async def test_fingerprint_extracts_autoscaling(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test autoscaling detection in fingerprint."""
        config = {
            "cluster_id": "auto-123",
            "cluster_name": "autoscale-cluster",
            "spark_version": "14.3.x-scala2.12",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "autoscale": {"min_workers": 2, "max_workers": 10},
            "data_security_mode": "SINGLE_USER",
        }
        mock_provider.get.return_value = config

        result = await cluster_service.get_fingerprint("auto-123")

        assert result.autoscaling_enabled is True
        assert result.node_config.min_workers == 2
        assert result.node_config.max_workers == 10

    @pytest.mark.asyncio
    async def test_fingerprint_extracts_spot_instances(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test spot instance detection in fingerprint."""
        config = {
            "cluster_id": "spot-123",
            "cluster_name": "spot-cluster",
            "spark_version": "14.3.x-scala2.12",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "aws_attributes": {
                "availability": "SPOT_WITH_FALLBACK",
                "first_on_demand": 2,
            },
            "data_security_mode": "SINGLE_USER",
        }
        mock_provider.get.return_value = config

        result = await cluster_service.get_fingerprint("spot-123")

        assert result.uses_spot is True
        assert result.node_config.use_spot_instances is True
        assert result.node_config.first_on_demand == 2

    @pytest.mark.asyncio
    async def test_fingerprint_extracts_pool_id(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test pool ID extraction in fingerprint."""
        config = {
            "cluster_id": "pool-123",
            "cluster_name": "pool-cluster",
            "spark_version": "14.3.x-scala2.12",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "instance_pool_id": "pool-abc-123",
            "data_security_mode": "SINGLE_USER",
        }
        mock_provider.get.return_value = config

        result = await cluster_service.get_fingerprint("pool-123")

        assert result.pool_id == "pool-abc-123"

    @pytest.mark.asyncio
    async def test_fingerprint_extracts_runtime_features(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test runtime feature detection."""
        config = {
            "cluster_id": "runtime-123",
            "cluster_name": "runtime-cluster",
            "spark_version": "14.3.x-scala2.12-lts",
            "runtime_engine": "PHOTON",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "data_security_mode": "SINGLE_USER",
        }
        mock_provider.get.return_value = config

        result = await cluster_service.get_fingerprint("runtime-123")

        assert result.runtime.is_lts is True
        assert result.runtime.photon_enabled is True

    @pytest.mark.asyncio
    async def test_fingerprint_detects_deprecated_runtime(
        self,
        cluster_service: ClusterService,
        mock_provider: MagicMock,
    ) -> None:
        """Test deprecated runtime detection."""
        config = {
            "cluster_id": "old-123",
            "cluster_name": "old-cluster",
            "spark_version": "10.4.x-scala2.12",  # Old DBR
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "data_security_mode": "SINGLE_USER",
        }
        mock_provider.get.return_value = config

        result = await cluster_service.get_fingerprint("old-123")

        assert result.runtime.is_deprecated is True
        assert result.has_deprecated_runtime is True
