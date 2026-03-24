"""Tests for cluster fingerprint builder."""

from starboard_core.domain.models.cluster import (
    AccessMode,
    ClusterFingerprint,
    ClusterMode,
    ClusterType,
)
from starboard_server.tools.domain.cluster.fingerprint_builder import (
    _build_node_config,
    _build_runtime_config,
    _extract_access_mode,
    _extract_cluster_mode,
    _extract_cluster_type,
    _is_autoscaling_enabled,
    build_cluster_fingerprint,
)


class TestBuildClusterFingerprint:
    """Tests for build_cluster_fingerprint function."""

    def test_minimal_config(self) -> None:
        """Test fingerprint from minimal config."""
        config = {
            "cluster_id": "test-123",
            "cluster_name": "test-cluster",
            "spark_version": "14.3.x-scala2.12",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "data_security_mode": "SINGLE_USER",
        }

        result = build_cluster_fingerprint(config)

        assert isinstance(result, ClusterFingerprint)
        assert result.cluster_id == "test-123"
        assert result.cluster_name == "test-cluster"
        assert result.fingerprint_version == "v1"
        assert result.performance is None
        assert result.cost is None

    def test_with_metrics(self) -> None:
        """Test fingerprint with metrics data."""
        config = {
            "cluster_id": "test-123",
            "cluster_name": "test-cluster",
            "spark_version": "14.3.x-scala2.12",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "data_security_mode": "SINGLE_USER",
        }
        metrics = {
            "cpu_utilization_p50": 45.0,
            "cpu_utilization_p95": 85.0,
            "memory_utilization_p50": 60.0,
        }

        result = build_cluster_fingerprint(config, metrics=metrics)

        assert result.performance is not None
        assert result.performance.cpu_utilization_p50 == 45.0
        assert result.performance.cpu_utilization_p95 == 85.0

    def test_with_cost_data(self) -> None:
        """Test fingerprint with cost data."""
        config = {
            "cluster_id": "test-123",
            "cluster_name": "test-cluster",
            "spark_version": "14.3.x-scala2.12",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "data_security_mode": "SINGLE_USER",
        }
        cost_data = {
            "dbu_total_30d": 1500.0,
            "cost_usd_total_30d": 450.0,
            "idle_cost_pct": 25.0,
        }

        result = build_cluster_fingerprint(config, cost_data=cost_data)

        assert result.cost is not None
        assert result.cost.dbu_total_30d == 1500.0
        assert result.cost.cost_usd_total_30d == 450.0

    def test_extracts_custom_tags(self) -> None:
        """Test custom tags extraction."""
        config = {
            "cluster_id": "test-123",
            "cluster_name": "test-cluster",
            "spark_version": "14.3.x-scala2.12",
            "node_type_id": "i3.xlarge",
            "driver_node_type_id": "i3.xlarge",
            "num_workers": 4,
            "data_security_mode": "SINGLE_USER",
            "custom_tags": {"team": "data", "env": "prod"},
        }

        result = build_cluster_fingerprint(config)

        assert result.tags == {"team": "data", "env": "prod"}


class TestExtractClusterType:
    """Tests for _extract_cluster_type function."""

    def test_job_cluster(self) -> None:
        """Test job cluster detection."""
        config = {"cluster_source": "JOB", "num_workers": 4}
        assert _extract_cluster_type(config) == ClusterType.JOB

    def test_single_node_cluster(self) -> None:
        """Test single node cluster detection."""
        config = {"cluster_source": "UI", "num_workers": 0}
        assert _extract_cluster_type(config) == ClusterType.SINGLE_NODE

    def test_all_purpose_cluster(self) -> None:
        """Test all-purpose cluster detection."""
        config = {"cluster_source": "UI", "num_workers": 4}
        assert _extract_cluster_type(config) == ClusterType.ALL_PURPOSE

    def test_autoscaling_cluster_is_not_single_node(self) -> None:
        """Test autoscaling cluster is not detected as single node."""
        config = {
            "cluster_source": "UI",
            "num_workers": 0,
            "autoscale": {"min_workers": 2, "max_workers": 10},
        }
        assert _extract_cluster_type(config) == ClusterType.ALL_PURPOSE


class TestExtractClusterMode:
    """Tests for _extract_cluster_mode function."""

    def test_standard_mode(self) -> None:
        """Test standard mode detection."""
        config = {"data_security_mode": "SINGLE_USER", "num_workers": 4}
        assert _extract_cluster_mode(config) == ClusterMode.STANDARD

    def test_high_concurrency_mode(self) -> None:
        """Test high concurrency mode detection."""
        config = {"cluster_mode": "HIGH_CONCURRENCY"}
        assert _extract_cluster_mode(config) == ClusterMode.HIGH_CONCURRENCY

    def test_single_node_mode(self) -> None:
        """Test single node mode detection."""
        config = {"num_workers": 0}
        assert _extract_cluster_mode(config) == ClusterMode.SINGLE_NODE


class TestExtractAccessMode:
    """Tests for _extract_access_mode function."""

    def test_single_user(self) -> None:
        """Test single user mode."""
        config = {"data_security_mode": "SINGLE_USER"}
        assert _extract_access_mode(config) == AccessMode.SINGLE_USER

    def test_user_isolation(self) -> None:
        """Test user isolation mode."""
        config = {"data_security_mode": "USER_ISOLATION"}
        assert _extract_access_mode(config) == AccessMode.USER_ISOLATION

    def test_shared(self) -> None:
        """Test shared mode."""
        config = {"data_security_mode": "SHARED"}
        assert _extract_access_mode(config) == AccessMode.SHARED

    def test_no_isolation(self) -> None:
        """Test no isolation mode."""
        config = {"data_security_mode": "NONE"}
        assert _extract_access_mode(config) == AccessMode.NO_ISOLATION

    def test_unknown(self) -> None:
        """Test unknown mode."""
        config = {"data_security_mode": "SOMETHING_NEW"}
        assert _extract_access_mode(config) == AccessMode.UNKNOWN


class TestBuildRuntimeConfig:
    """Tests for _build_runtime_config function."""

    def test_basic_runtime(self) -> None:
        """Test basic runtime extraction."""
        config = {"spark_version": "14.3.x-scala2.12"}
        result = _build_runtime_config(config)
        assert result.dbr_version == "14.3.x-scala2.12"
        assert result.is_lts is False
        assert result.is_ml is False

    def test_lts_runtime(self) -> None:
        """Test LTS runtime detection."""
        config = {"spark_version": "14.3.x-scala2.12-lts"}
        result = _build_runtime_config(config)
        assert result.is_lts is True

    def test_ml_runtime(self) -> None:
        """Test ML runtime detection."""
        config = {"spark_version": "14.3.x-ml-scala2.12"}
        result = _build_runtime_config(config)
        assert result.is_ml is True

    def test_gpu_runtime(self) -> None:
        """Test GPU runtime detection."""
        config = {"spark_version": "14.3.x-gpu-scala2.12"}
        result = _build_runtime_config(config)
        assert result.is_gpu is True

    def test_photon_from_runtime_engine(self) -> None:
        """Test Photon detection from runtime_engine."""
        config = {"spark_version": "14.3.x-scala2.12", "runtime_engine": "PHOTON"}
        result = _build_runtime_config(config)
        assert result.photon_enabled is True

    def test_deprecated_runtime(self) -> None:
        """Test deprecated runtime detection."""
        config = {"spark_version": "10.4.x-scala2.12"}
        result = _build_runtime_config(config)
        assert result.is_deprecated is True


class TestBuildNodeConfig:
    """Tests for _build_node_config function."""

    def test_fixed_size_cluster(self) -> None:
        """Test fixed size cluster node config."""
        config = {
            "driver_node_type_id": "i3.xlarge",
            "node_type_id": "i3.2xlarge",
            "num_workers": 4,
        }
        result = _build_node_config(config)
        assert result.driver_node_type == "i3.xlarge"
        assert result.worker_node_type == "i3.2xlarge"
        assert result.num_workers == 4
        assert result.min_workers is None
        assert result.max_workers is None

    def test_autoscaling_cluster(self) -> None:
        """Test autoscaling cluster node config."""
        config = {
            "driver_node_type_id": "i3.xlarge",
            "node_type_id": "i3.2xlarge",
            "autoscale": {"min_workers": 2, "max_workers": 10},
        }
        result = _build_node_config(config)
        assert result.min_workers == 2
        assert result.max_workers == 10
        assert result.num_workers is None

    def test_spot_instances_aws(self) -> None:
        """Test spot instance detection for AWS."""
        config = {
            "driver_node_type_id": "i3.xlarge",
            "node_type_id": "i3.xlarge",
            "num_workers": 4,
            "aws_attributes": {
                "availability": "SPOT_WITH_FALLBACK",
                "first_on_demand": 2,
            },
        }
        result = _build_node_config(config)
        assert result.use_spot_instances is True
        assert result.first_on_demand == 2

    def test_spot_instances_gcp(self) -> None:
        """Test preemptible detection for GCP."""
        config = {
            "driver_node_type_id": "n1-standard-4",
            "node_type_id": "n1-standard-4",
            "num_workers": 4,
            "gcp_attributes": {
                "use_preemptible_executors": True,
            },
        }
        result = _build_node_config(config)
        assert result.use_spot_instances is True


class TestIsAutoscalingEnabled:
    """Tests for _is_autoscaling_enabled function."""

    def test_autoscaling_enabled(self) -> None:
        """Test autoscaling is detected when present."""
        config = {"autoscale": {"min_workers": 2, "max_workers": 10}}
        assert _is_autoscaling_enabled(config) is True

    def test_autoscaling_disabled(self) -> None:
        """Test autoscaling not detected when absent."""
        config = {"num_workers": 4}
        assert _is_autoscaling_enabled(config) is False

    def test_empty_autoscale(self) -> None:
        """Test autoscaling not detected with empty config."""
        config = {"autoscale": {}}
        assert _is_autoscaling_enabled(config) is False
