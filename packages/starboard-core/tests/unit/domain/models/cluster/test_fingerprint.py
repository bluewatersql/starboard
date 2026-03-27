"""Tests for cluster fingerprint domain models."""

from datetime import UTC, datetime

import pytest
from starboard_core.domain.models.cluster import (
    AccessMode,
    ClusterFingerprint,
    ClusterMode,
    ClusterType,
    CostProfile,
    FingerprintScope,
    NodeConfig,
    PerformanceProfile,
    RuntimeConfig,
)


class TestClusterType:
    """Tests for ClusterType enum."""

    def test_all_purpose_value(self) -> None:
        """Test ALL_PURPOSE has correct value."""
        assert ClusterType.ALL_PURPOSE.value == "ALL_PURPOSE"

    def test_job_value(self) -> None:
        """Test JOB has correct value."""
        assert ClusterType.JOB.value == "JOB"

    def test_single_node_value(self) -> None:
        """Test SINGLE_NODE has correct value."""
        assert ClusterType.SINGLE_NODE.value == "SINGLE_NODE"

    def test_string_behavior(self) -> None:
        """Test enum is string-compatible."""
        assert str(ClusterType.ALL_PURPOSE) == "ALL_PURPOSE"
        assert ClusterType.ALL_PURPOSE == "ALL_PURPOSE"


class TestClusterMode:
    """Tests for ClusterMode enum."""

    def test_standard_value(self) -> None:
        """Test STANDARD has correct value."""
        assert ClusterMode.STANDARD.value == "STANDARD"

    def test_high_concurrency_value(self) -> None:
        """Test HIGH_CONCURRENCY has correct value."""
        assert ClusterMode.HIGH_CONCURRENCY.value == "HIGH_CONCURRENCY"


class TestAccessMode:
    """Tests for AccessMode enum."""

    def test_all_modes_defined(self) -> None:
        """Test all access modes are defined."""
        modes = {m.value for m in AccessMode}
        expected = {
            "SINGLE_USER",
            "USER_ISOLATION",
            "SHARED",
            "CUSTOM",
            "NO_ISOLATION",
            "UNKNOWN",
        }
        assert modes == expected


class TestFingerprintScope:
    """Tests for FingerprintScope enum."""

    def test_config_only(self) -> None:
        """Test CONFIG_ONLY scope."""
        assert FingerprintScope.CONFIG_ONLY.value == "config_only"

    def test_with_metrics(self) -> None:
        """Test WITH_METRICS scope."""
        assert FingerprintScope.WITH_METRICS.value == "with_metrics"

    def test_with_cost(self) -> None:
        """Test WITH_COST scope."""
        assert FingerprintScope.WITH_COST.value == "with_cost"

    def test_full(self) -> None:
        """Test FULL scope."""
        assert FingerprintScope.FULL.value == "full"


class TestRuntimeConfig:
    """Tests for RuntimeConfig dataclass."""

    def test_minimal_creation(self) -> None:
        """Test creation with minimal required fields."""
        config = RuntimeConfig(dbr_version="14.3.x-scala2.12")
        assert config.dbr_version == "14.3.x-scala2.12"
        assert config.is_lts is False
        assert config.is_ml is False
        assert config.is_gpu is False
        assert config.photon_enabled is False
        assert config.is_deprecated is False
        assert config.deprecation_date is None

    def test_full_creation(self) -> None:
        """Test creation with all fields."""
        config = RuntimeConfig(
            dbr_version="14.3.x-scala2.12",
            is_lts=True,
            is_ml=True,
            is_gpu=True,
            photon_enabled=True,
            is_deprecated=True,
            deprecation_date="2024-06-01",
        )
        assert config.is_lts is True
        assert config.is_ml is True
        assert config.deprecation_date == "2024-06-01"

    def test_frozen(self) -> None:
        """Test dataclass is frozen."""
        config = RuntimeConfig(dbr_version="14.3.x-scala2.12")
        with pytest.raises(AttributeError):
            config.dbr_version = "new_version"  # type: ignore[misc]


class TestNodeConfig:
    """Tests for NodeConfig dataclass."""

    def test_minimal_creation(self) -> None:
        """Test creation with minimal required fields."""
        config = NodeConfig(
            driver_node_type="i3.xlarge",
            worker_node_type="i3.xlarge",
        )
        assert config.driver_node_type == "i3.xlarge"
        assert config.worker_node_type == "i3.xlarge"
        assert config.min_workers is None
        assert config.max_workers is None
        assert config.num_workers is None
        assert config.use_spot_instances is False
        assert config.first_on_demand == 1

    def test_autoscaling_config(self) -> None:
        """Test autoscaling configuration."""
        config = NodeConfig(
            driver_node_type="i3.xlarge",
            worker_node_type="i3.2xlarge",
            min_workers=2,
            max_workers=10,
            use_spot_instances=True,
            first_on_demand=2,
        )
        assert config.min_workers == 2
        assert config.max_workers == 10
        assert config.use_spot_instances is True
        assert config.first_on_demand == 2


class TestPerformanceProfile:
    """Tests for PerformanceProfile dataclass."""

    def test_empty_creation(self) -> None:
        """Test creation with no data."""
        profile = PerformanceProfile()
        assert profile.cpu_utilization_p50 is None
        assert profile.cpu_utilization_p95 is None
        assert profile.memory_utilization_p50 is None
        assert profile.memory_utilization_p95 is None
        assert profile.oom_events_30d is None
        assert profile.task_failure_rate is None

    def test_full_creation(self) -> None:
        """Test creation with all metrics."""
        profile = PerformanceProfile(
            cpu_utilization_p50=45.5,
            cpu_utilization_p95=85.0,
            memory_utilization_p50=60.0,
            memory_utilization_p95=90.0,
            oom_events_30d=3,
            task_failure_rate=0.02,
        )
        assert profile.cpu_utilization_p50 == 45.5
        assert profile.oom_events_30d == 3


class TestCostProfile:
    """Tests for CostProfile dataclass."""

    def test_empty_creation(self) -> None:
        """Test creation with no data."""
        profile = CostProfile()
        assert profile.dbu_total_30d is None
        assert profile.cost_usd_total_30d is None
        assert profile.idle_cost_pct is None
        assert profile.spot_savings_pct is None

    def test_full_creation(self) -> None:
        """Test creation with cost data."""
        profile = CostProfile(
            dbu_total_30d=1500.0,
            cost_usd_total_30d=450.0,
            idle_cost_pct=25.0,
            spot_savings_pct=40.0,
        )
        assert profile.dbu_total_30d == 1500.0
        assert profile.spot_savings_pct == 40.0


class TestClusterFingerprint:
    """Tests for ClusterFingerprint dataclass."""

    @pytest.fixture
    def minimal_fingerprint(self) -> ClusterFingerprint:
        """Create a minimal valid fingerprint."""
        return ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="1201-090640-abc123",
            cluster_name="analytics-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
        )

    def test_minimal_creation(self, minimal_fingerprint: ClusterFingerprint) -> None:
        """Test creation with minimal fields."""
        fp = minimal_fingerprint
        assert fp.fingerprint_version == "v1"
        assert fp.cluster_id == "1201-090640-abc123"
        assert fp.cluster_name == "analytics-cluster"
        assert fp.cluster_type == ClusterType.ALL_PURPOSE
        assert fp.performance is None
        assert fp.cost is None
        assert fp.autoscaling_enabled is False
        assert fp.pool_id is None

    def test_is_job_cluster_property(self) -> None:
        """Test is_job_cluster property."""
        job_fp = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="job-123",
            cluster_name="job-cluster",
            cluster_type=ClusterType.JOB,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
        )
        assert job_fp.is_job_cluster is True

    def test_is_single_node_property(
        self, minimal_fingerprint: ClusterFingerprint
    ) -> None:
        """Test is_single_node property."""
        assert minimal_fingerprint.is_single_node is False

        single_node_fp = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="single-123",
            cluster_name="single-node-cluster",
            cluster_type=ClusterType.SINGLE_NODE,
            cluster_mode=ClusterMode.SINGLE_NODE,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
        )
        assert single_node_fp.is_single_node is True

    def test_uses_spot_property(self) -> None:
        """Test uses_spot property."""
        spot_fp = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="spot-123",
            cluster_name="spot-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
                use_spot_instances=True,
            ),
        )
        assert spot_fp.uses_spot is True

    def test_has_deprecated_runtime_property(
        self, minimal_fingerprint: ClusterFingerprint
    ) -> None:
        """Test has_deprecated_runtime property."""
        assert minimal_fingerprint.has_deprecated_runtime is False

        deprecated_fp = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="deprecated-123",
            cluster_name="deprecated-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(
                dbr_version="10.4.x-scala2.12",
                is_deprecated=True,
                deprecation_date="2023-01-01",
            ),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
        )
        assert deprecated_fp.has_deprecated_runtime is True

    def test_frozen(self, minimal_fingerprint: ClusterFingerprint) -> None:
        """Test dataclass is frozen."""
        with pytest.raises(AttributeError):
            minimal_fingerprint.cluster_id = "new-id"  # type: ignore[misc]

    def test_full_creation_with_metrics_and_cost(self) -> None:
        """Test creation with performance and cost data."""
        fp = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="full-123",
            cluster_name="full-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(
                dbr_version="14.3.x-scala2.12",
                is_lts=True,
                photon_enabled=True,
            ),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.2xlarge",
                min_workers=2,
                max_workers=10,
                use_spot_instances=True,
            ),
            performance=PerformanceProfile(
                cpu_utilization_p50=50.0,
                cpu_utilization_p95=85.0,
            ),
            cost=CostProfile(
                dbu_total_30d=1500.0,
                cost_usd_total_30d=450.0,
            ),
            autoscaling_enabled=True,
            pool_id="pool-123",
            tags={"team": "data-platform", "env": "production"},
        )
        assert fp.performance is not None
        assert fp.performance.cpu_utilization_p50 == 50.0
        assert fp.cost is not None
        assert fp.cost.dbu_total_30d == 1500.0
        assert fp.autoscaling_enabled is True
        assert fp.pool_id == "pool-123"
        assert fp.tags == {"team": "data-platform", "env": "production"}
