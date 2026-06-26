# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden/snapshot tests for ClusterMetricsAnalyzer.

These tests use real (anonymized) data and snapshot testing to ensure:
1. Output structure remains consistent (regression detection)
2. Transformations are deterministic
3. Output is valid and complete

Run with: pytest tests/golden/transformers/test_cluster_metrics_golden.py
Update snapshots: pytest --snapshot-update
"""

import json
from pathlib import Path

import pytest
from starboard_server.tools.domain.cluster.cluster_metrics_analyzer import (
    ClusterMetricsAnalyzer,
)

GOLDEN_DIR = Path(__file__).parent / "data"


@pytest.mark.golden
class TestClusterMetricsGolden:
    """Golden tests for ClusterMetricsAnalyzer with real data."""

    def test_snapshot_match(self, snapshot):
        """Test output matches golden snapshot."""
        input_data = json.loads(
            (GOLDEN_DIR / "cluster_metrics_sample.json").read_text()
        )
        analyzer = ClusterMetricsAnalyzer(input_data)
        result = analyzer.analyze()

        # Verify against snapshot
        assert result == snapshot

    def test_deterministic_output(self):
        """Test transformation produces consistent output across multiple runs."""
        input_data = json.loads(
            (GOLDEN_DIR / "cluster_metrics_sample.json").read_text()
        )

        # Run multiple times
        results = []
        for _ in range(5):
            analyzer = ClusterMetricsAnalyzer(input_data)
            result = analyzer.analyze()
            results.append(result)

        # All results should be identical
        for i in range(1, len(results)):
            assert results[i] == results[0], f"Run {i} differs from run 0"

    def test_output_structure_valid(self):
        """Test output structure is valid and complete."""
        input_data = json.loads(
            (GOLDEN_DIR / "cluster_metrics_sample.json").read_text()
        )
        analyzer = ClusterMetricsAnalyzer(input_data)
        result = analyzer.analyze()

        # Should return a list
        assert isinstance(result, list)
        assert len(result) == 1  # One cluster

        cluster = result[0]

        # Check top-level structure
        assert "config" in cluster
        assert "resources" in cluster
        assert "usage" in cluster

        # Check config
        config = cluster["config"]
        assert config["cluster_id"] == "test-cluster-001"
        assert config["cluster_name"] == "Analytics Cluster"
        assert config["node_type"] == "i3.xlarge"
        assert config["dbr_version"] == "11.3.x-scala2.12"

        # Check resources
        resources = cluster["resources"]
        assert "driver" in resources
        assert "worker" in resources

        driver = resources["driver"]
        assert driver["instances"] == 1
        assert driver["cores_total"] == 4.0
        assert driver["memory_total_GB"] == 30.0

        worker = resources["worker"]
        assert worker["instances"] == 3
        assert worker["cores_total"] == 12.0  # 3 workers * 4 cores

        # Check usage
        usage = cluster["usage"]
        assert "compute_utilization" in usage
        assert "network_MB" in usage
        assert "disk_free_bytes_GB" in usage

        # Check compute utilization
        compute = usage["compute_utilization"]
        assert "driver" in compute
        assert "worker" in compute

        for role in ["driver", "worker"]:
            assert "cpu_total_avg" in compute[role]
            assert "cpu_total_min" in compute[role]
            assert "cpu_total_max" in compute[role]
            assert "mem_used_avg" in compute[role]
            assert "mem_used_min" in compute[role]
            assert "mem_used_max" in compute[role]

    def test_deduplication_works(self):
        """Test that duplicate records are properly deduplicated."""
        input_data = json.loads(
            (GOLDEN_DIR / "cluster_metrics_sample.json").read_text()
        )

        # Add duplicate record
        duplicate = input_data[0].copy()
        input_data_with_dup = input_data + [duplicate]

        analyzer = ClusterMetricsAnalyzer(input_data_with_dup)
        result = analyzer.analyze()

        # Should still have same resource counts (deduplication worked)
        cluster = result[0]
        assert cluster["resources"]["driver"]["instances"] == 1
        assert cluster["resources"]["worker"]["instances"] == 3

    def test_role_based_aggregation(self):
        """Test that metrics are correctly aggregated by role."""
        input_data = json.loads(
            (GOLDEN_DIR / "cluster_metrics_sample.json").read_text()
        )
        analyzer = ClusterMetricsAnalyzer(input_data)
        result = analyzer.analyze()

        cluster = result[0]
        resources = cluster["resources"]

        # Driver should have 1 instance with 4 cores
        assert resources["driver"]["instances"] == 1
        assert resources["driver"]["cores_total"] == 4.0
        assert resources["driver"]["gpus_total"] == 0.0

        # Workers should have 3 instances with 4 cores each = 12 total
        assert resources["worker"]["instances"] == 3
        assert resources["worker"]["cores_total"] == 12.0
        assert resources["worker"]["gpus_total"] == 0.0

    def test_compute_metrics_reasonable(self):
        """Test that computed metrics are in reasonable ranges."""
        input_data = json.loads(
            (GOLDEN_DIR / "cluster_metrics_sample.json").read_text()
        )
        analyzer = ClusterMetricsAnalyzer(input_data)
        result = analyzer.analyze()

        cluster = result[0]
        compute = cluster["usage"]["compute_utilization"]

        # CPU percentages should be 0-100
        for role in ["driver", "worker"]:
            assert 0 <= compute[role]["cpu_total_avg"] <= 100
            assert 0 <= compute[role]["cpu_total_min"] <= 100
            assert 0 <= compute[role]["cpu_total_max"] <= 100

            # Memory percentages should be 0-100
            assert 0 <= compute[role]["mem_used_avg"] <= 100
            assert 0 <= compute[role]["mem_used_min"] <= 100
            assert 0 <= compute[role]["mem_used_max"] <= 100

            # Min <= Avg <= Max
            assert compute[role]["cpu_total_min"] <= compute[role]["cpu_total_avg"]
            assert compute[role]["cpu_total_avg"] <= compute[role]["cpu_total_max"]
            assert compute[role]["mem_used_min"] <= compute[role]["mem_used_avg"]
            assert compute[role]["mem_used_avg"] <= compute[role]["mem_used_max"]

    def test_network_metrics_aggregated(self):
        """Test that network metrics are correctly summed."""
        input_data = json.loads(
            (GOLDEN_DIR / "cluster_metrics_sample.json").read_text()
        )
        analyzer = ClusterMetricsAnalyzer(input_data)
        result = analyzer.analyze()

        cluster = result[0]
        network = cluster["usage"]["network_MB"]

        # Should have positive values
        assert network["sent_total"] > 0
        assert network["received_total"] > 0
        assert network["total"] == pytest.approx(
            network["sent_total"] + network["received_total"], abs=0.1
        )

        # Ratio should be reasonable
        assert network["sent_to_recv_ratio"] > 0

    def test_disk_usage_calculated(self):
        """Test that disk usage is calculated from mount points."""
        input_data = json.loads(
            (GOLDEN_DIR / "cluster_metrics_sample.json").read_text()
        )
        analyzer = ClusterMetricsAnalyzer(input_data)
        result = analyzer.analyze()

        cluster = result[0]
        disk = cluster["usage"]["disk_free_bytes_GB"]

        # Should have positive free space
        assert disk["total_free_avg"] > 0
        # Based on sample data: / = 100GB, /tmp = 50GB per instance, averaged
        assert disk["total_free_avg"] == pytest.approx(161.06, abs=1.0)
