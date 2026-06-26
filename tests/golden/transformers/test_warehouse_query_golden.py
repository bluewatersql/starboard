# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden/snapshot tests for WarehouseQueryAnalyzer.

These tests use real (anonymized) data and snapshot testing to ensure:
1. Output structure remains consistent (regression detection)
2. Transformations are deterministic
3. Output is valid and complete

Run with: pytest tests/golden/transformers/test_warehouse_query_golden.py
Update snapshots: pytest --snapshot-update
"""

import json
from pathlib import Path

import pytest
from starboard_server.tools.domain.query.warehouse_query_analyzer import (
    WarehouseQueryAnalyzer,
)

GOLDEN_DIR = Path(__file__).parent / "data"


@pytest.mark.golden
class TestWarehouseQueryGolden:
    """Golden tests for WarehouseQueryAnalyzer with real data."""

    def test_snapshot_match(self, snapshot):
        """Test output matches golden snapshot."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        # Verify against snapshot
        assert result == snapshot

    def test_deterministic_output(self):
        """Test transformation produces consistent output across multiple runs."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )

        # Run multiple times
        results = []
        for _ in range(5):
            analyzer = WarehouseQueryAnalyzer(input_data)
            result = analyzer.analyze()
            results.append(result)

        # All results should be identical
        for i in range(1, len(results)):
            assert results[i] == results[0], f"Run {i} differs from run 0"

    def test_output_structure_valid(self):
        """Test output structure is valid and complete."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        # Check top-level structure
        assert "warehouses" in result
        assert isinstance(result["warehouses"], dict)

        # Should have 2 warehouses
        assert len(result["warehouses"]) == 2
        assert "warehouse-001" in result["warehouses"]
        assert "warehouse-002" in result["warehouses"]

        # Check each warehouse structure
        for wid, warehouse in result["warehouses"].items():
            assert "counts" in warehouse
            assert "config" in warehouse
            assert "performance" in warehouse

            # Check counts
            counts = warehouse["counts"]
            assert "queries" in counts
            assert "users" in counts
            assert counts["queries"] > 0

            # Check config
            config = warehouse["config"]
            assert config["warehouse_id"] == wid
            assert "dbsql_versions" in config
            assert "channels" in config
            assert "client_app_mix" in config

            # Check performance
            perf = warehouse["performance"]
            assert "duration_ms" in perf
            assert "times_ms_avg" in perf
            assert "photon" in perf
            assert "bytes" in perf
            assert "rows" in perf
            assert "scan" in perf
            assert "cache" in perf
            assert "statement_type_mix" in perf

            # Check duration stats
            duration = perf["duration_ms"]
            assert "avg" in duration
            assert "p50" in duration
            assert "p95" in duration
            assert "p99" in duration
            assert "max" in duration

    def test_query_aggregation_by_warehouse(self):
        """Test that queries are correctly aggregated by warehouse."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        warehouses = result["warehouses"]

        # warehouse-001 should have 4 queries
        assert warehouses["warehouse-001"]["counts"]["queries"] == 4

        # warehouse-002 should have 1 query
        assert warehouses["warehouse-002"]["counts"]["queries"] == 1

    def test_duration_percentiles_reasonable(self):
        """Test that duration percentiles are in reasonable order."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        for _wid, warehouse in result["warehouses"].items():
            duration = warehouse["performance"]["duration_ms"]

            # Percentiles should be ordered: p50 <= p95 <= p99 <= max
            # Note: avg might not follow this order
            assert duration["p50"] <= duration["p95"]
            assert duration["p95"] <= duration["p99"]
            assert duration["p99"] <= duration["max"]

    def test_photon_metrics_calculated(self):
        """Test that Photon metrics are correctly calculated."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        wh001 = result["warehouses"]["warehouse-001"]
        photon = wh001["performance"]["photon"]

        # Should have 3 observations (3 queries with photon metrics)
        assert photon["observations"] == 3

        # Total photon time should be positive
        assert photon["total_time_ms"] > 0

        # Usage share should be 0-1
        assert 0 <= photon["usage_share_of_total_time"] <= 1

    def test_cache_hit_rate_calculated(self):
        """Test that cache hit rate is correctly calculated."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        wh001 = result["warehouses"]["warehouse-001"]
        cache = wh001["performance"]["cache"]

        # Should have 1 cache hit out of 4 queries = 0.25
        assert cache["hits"] == 1
        assert cache["hit_rate"] == pytest.approx(0.25, abs=0.01)

    def test_statement_type_mix_calculated(self):
        """Test that statement type mix is correctly calculated."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        wh001 = result["warehouses"]["warehouse-001"]
        stmt_mix = wh001["performance"]["statement_type_mix"]

        # Should have SELECT and INSERT
        assert "SELECT" in stmt_mix
        assert "INSERT" in stmt_mix

        # SELECT should have 3 queries
        assert stmt_mix["SELECT"]["count"] == 3

        # INSERT should have 1 query
        assert stmt_mix["INSERT"]["count"] == 1

        # Avg durations should be positive
        assert stmt_mix["SELECT"]["avg_duration_ms"] > 0
        assert stmt_mix["INSERT"]["avg_duration_ms"] > 0

    def test_byte_metrics_aggregated(self):
        """Test that byte metrics are correctly summed."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        wh001 = result["warehouses"]["warehouse-001"]
        bytes_metrics = wh001["performance"]["bytes"]

        # All byte metrics should be positive
        assert bytes_metrics["read_total"] > 0
        assert bytes_metrics["remote_read_total"] > 0
        assert bytes_metrics["cache_read_total"] > 0
        # Some might be 0
        assert bytes_metrics["spill_total"] >= 0
        assert bytes_metrics["network_sent_total"] > 0
        assert bytes_metrics["write_remote_total"] > 0

    def test_rows_and_scan_metrics_aggregated(self):
        """Test that row and scan metrics are correctly summed."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        wh001 = result["warehouses"]["warehouse-001"]

        # Row metrics
        rows = wh001["performance"]["rows"]
        assert rows["read_total"] > 0
        assert rows["produced_total"] > 0

        # Scan metrics
        scan = wh001["performance"]["scan"]
        assert scan["files_read_total"] > 0
        assert scan["partitions_read_total"] > 0

    def test_config_extraction_correct(self):
        """Test that config is correctly extracted."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        wh001 = result["warehouses"]["warehouse-001"]
        config = wh001["config"]

        # Should have both DBSQL versions
        assert set(config["dbsql_versions"]) == {"2023.40", "2023.45"}

        # Should have both channels
        assert set(config["channels"]) == {
            "CHANNEL_NAME_CURRENT",
            "CHANNEL_NAME_PREVIEW",
        }

        # Should have client app mix
        assert "Tableau" in config["client_app_mix"]
        assert "PowerBI" in config["client_app_mix"]
        assert "Spark SQL" in config["client_app_mix"]

    def test_unique_user_counting(self):
        """Test that unique users are correctly counted."""
        input_data = json.loads(
            (GOLDEN_DIR / "warehouse_query_sample.json").read_text()
        )
        analyzer = WarehouseQueryAnalyzer(input_data)
        result = analyzer.analyze()

        wh001 = result["warehouses"]["warehouse-001"]

        # Should have 2 unique users (12345 and 67890)
        assert wh001["counts"]["users"] == 2
