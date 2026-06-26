# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Performance benchmarks for ClusterMetricsAnalyzer.

Run with: pytest tests/benchmarks/transformers/test_cluster_metrics_benchmarks.py --benchmark-only
"""

import json

import pytest
from starboard_server.tools.domain.cluster.cluster_metrics_analyzer import (
    ClusterMetricsAnalyzer,
)


def generate_cluster_metrics_data(
    num_clusters: int,
    instances_per_cluster: int,
    samples_per_instance: int,
) -> list[dict]:
    """
    Generate synthetic cluster metrics data for benchmarking.

    Args:
        num_clusters: Number of clusters
        instances_per_cluster: Number of instances per cluster (driver + workers)
        samples_per_instance: Number of metric samples per instance

    Returns:
        List of cluster metric records
    """
    records = []

    for cluster_idx in range(num_clusters):
        cluster_id = f"cluster-{cluster_idx:04d}"
        cluster_name = f"Cluster {cluster_idx}"

        # Generate driver metrics
        for sample in range(samples_per_instance):
            records.append(
                {
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                    "instance_id": f"{cluster_id}-driver",
                    "driver": True,
                    "node_type": "m5.4xlarge",
                    "core_count": 16,
                    "gpu_count": 0,
                    "memory_mb": 65536,
                    "dbr_version": "11.3.x-scala2.12",
                    "cpu_user_percent": 30.0 + (sample * 5.0 % 40.0),
                    "cpu_system_percent": 10.0 + (sample * 2.0 % 15.0),
                    "cpu_wait_percent": 2.0 + (sample % 5.0),
                    "mem_used_percent": 50.0 + (sample * 3.0 % 30.0),
                    "network_sent_bytes": 1024 * 1024 * (100 + sample * 10),
                    "network_received_bytes": 1024 * 1024 * (200 + sample * 20),
                    "disk_free_bytes_per_mount_point": json.dumps(
                        {
                            "/": 107374182400 - (sample * 1073741824),
                            "/tmp": 53687091200 - (sample * 536870912),
                        }
                    ),
                }
            )

        # Generate worker metrics
        for worker_idx in range(instances_per_cluster - 1):  # -1 for driver
            instance_id = f"{cluster_id}-worker-{worker_idx:02d}"
            for sample in range(samples_per_instance):
                records.append(
                    {
                        "cluster_id": cluster_id,
                        "cluster_name": cluster_name,
                        "instance_id": instance_id,
                        "driver": False,
                        "node_type": "m5.4xlarge",
                        "core_count": 16,
                        "gpu_count": 0,
                        "memory_mb": 65536,
                        "dbr_version": "11.3.x-scala2.12",
                        "cpu_user_percent": 60.0 + (sample * 4.0 % 30.0),
                        "cpu_system_percent": 15.0 + (sample * 2.0 % 10.0),
                        "cpu_wait_percent": 3.0 + (sample % 7.0),
                        "mem_used_percent": 70.0 + (sample * 2.0 % 20.0),
                        "network_sent_bytes": 1024 * 1024 * (500 + sample * 50),
                        "network_received_bytes": 1024 * 1024 * (1000 + sample * 100),
                        "disk_free_bytes_per_mount_point": json.dumps(
                            {
                                "/": 107374182400 - (sample * 2147483648),
                                "/tmp": 53687091200 - (sample * 1073741824),
                            }
                        ),
                    }
                )

    return records


class TestClusterMetricsAnalyzerBenchmarks:
    """Benchmark tests for ClusterMetricsAnalyzer with various dataset sizes."""

    def test_benchmark_small_dataset(self, benchmark):
        """Benchmark with small dataset: 1 cluster, 4 instances, 10 samples."""
        data = generate_cluster_metrics_data(
            num_clusters=1,
            instances_per_cluster=4,
            samples_per_instance=10,
        )

        def run():
            analyzer = ClusterMetricsAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result) == 1  # 1 cluster

    def test_benchmark_medium_dataset(self, benchmark):
        """Benchmark with medium dataset: 10 clusters, 8 instances, 50 samples."""
        data = generate_cluster_metrics_data(
            num_clusters=10,
            instances_per_cluster=8,
            samples_per_instance=50,
        )

        def run():
            analyzer = ClusterMetricsAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result) == 10  # 10 clusters

    def test_benchmark_large_dataset(self, benchmark):
        """Benchmark with large dataset: 50 clusters, 16 instances, 100 samples."""
        data = generate_cluster_metrics_data(
            num_clusters=50,
            instances_per_cluster=16,
            samples_per_instance=100,
        )

        def run():
            analyzer = ClusterMetricsAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result) == 50  # 50 clusters

    def test_benchmark_very_large_dataset(self, benchmark):
        """Benchmark with very large dataset: 100 clusters, 32 instances, 200 samples."""
        data = generate_cluster_metrics_data(
            num_clusters=100,
            instances_per_cluster=32,
            samples_per_instance=200,
        )

        def run():
            analyzer = ClusterMetricsAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result) == 100  # 100 clusters

    def test_benchmark_empty_dataset(self, benchmark):
        """Benchmark with empty dataset (edge case)."""
        data = []

        def run():
            analyzer = ClusterMetricsAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result) == 0

    def test_benchmark_single_cluster_many_samples(self, benchmark):
        """Benchmark with single cluster but many samples."""
        data = generate_cluster_metrics_data(
            num_clusters=1,
            instances_per_cluster=64,
            samples_per_instance=500,
        )

        def run():
            analyzer = ClusterMetricsAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result) == 1


class TestClusterMetricsAnalyzerScaling:
    """Test how ClusterMetricsAnalyzer scales with increasing dataset sizes."""

    @pytest.mark.parametrize(
        "num_clusters,instances_per_cluster,samples_per_instance",
        [
            (1, 4, 10),
            (5, 8, 25),
            (10, 8, 50),
            (25, 16, 100),
            (50, 16, 100),
        ],
    )
    def test_scaling(
        self,
        benchmark,
        num_clusters,
        instances_per_cluster,
        samples_per_instance,
    ):
        """Test scaling across different dataset sizes."""
        data = generate_cluster_metrics_data(
            num_clusters=num_clusters,
            instances_per_cluster=instances_per_cluster,
            samples_per_instance=samples_per_instance,
        )

        def run():
            analyzer = ClusterMetricsAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result) == num_clusters

        # Store metadata for comparison
        total_records = num_clusters * instances_per_cluster * samples_per_instance
        benchmark.extra_info["num_clusters"] = num_clusters
        benchmark.extra_info["instances_per_cluster"] = instances_per_cluster
        benchmark.extra_info["samples_per_instance"] = samples_per_instance
        benchmark.extra_info["total_records"] = total_records


@pytest.mark.memory
class TestClusterMetricsAnalyzerMemory:
    """Memory usage benchmarks for ClusterMetricsAnalyzer."""

    def test_memory_large_dataset(self, benchmark):
        """Test memory usage with large dataset."""
        data = generate_cluster_metrics_data(
            num_clusters=50,
            instances_per_cluster=16,
            samples_per_instance=100,
        )

        def run():
            analyzer = ClusterMetricsAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert isinstance(result, list)
