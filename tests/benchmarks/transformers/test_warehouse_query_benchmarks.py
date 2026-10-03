# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Performance benchmarks for WarehouseQueryAnalyzer.

Run with: pytest tests/benchmarks/transformers/test_warehouse_query_benchmarks.py --benchmark-only
"""

import pytest
from starboard.tools.domain.query.warehouse_query_analyzer import (
    WarehouseQueryAnalyzer,
)


def generate_warehouse_query_data(
    num_warehouses: int,
    queries_per_warehouse: int,
) -> list[dict]:
    """
    Generate synthetic warehouse query history data for benchmarking.

    Args:
        num_warehouses: Number of warehouses
        queries_per_warehouse: Number of queries per warehouse

    Returns:
        List of query history records
    """
    records = []

    statement_types = ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE"]
    client_apps = ["Tableau", "PowerBI", "Spark SQL", "JDBC", "Python"]

    for wh_idx in range(num_warehouses):
        warehouse_id = f"warehouse-{wh_idx:04d}"

        for query_idx in range(queries_per_warehouse):
            user_id = (query_idx % 100) + 1  # 100 unique users
            statement_type = statement_types[query_idx % len(statement_types)]
            client_app = client_apps[query_idx % len(client_apps)]

            records.append(
                {
                    "warehouse_id": warehouse_id,
                    "user_id": user_id,
                    "statement_type": statement_type,
                    "duration_ms": 1000 + (query_idx * 100),
                    "compilation_time_ms": 50 + (query_idx % 200),
                    "execution_time_ms": 900 + (query_idx * 95),
                    "read_io_cache_ms": 10 + (query_idx % 50),
                    "rows_produced": 1000 + (query_idx * 500),
                    "rows_read": 5000 + (query_idx * 2000),
                    "read_bytes": 1024 * 1024 * (10 + query_idx),
                    "remote_read_bytes": 1024 * 1024 * (5 + query_idx // 2),
                    "cache_read_bytes": 1024 * 1024 * (2 + query_idx // 4),
                    "spilled_bytes": 1024 * 1024 * (query_idx // 10),
                    "network_sent_bytes": 1024 * 1024 * (1 + query_idx // 5),
                    "result_bytes": 1024 * 1024 * (query_idx // 3),
                    "write_remote_bytes": 1024 * 1024 * (query_idx // 8),
                    "files_read": 10 + (query_idx % 100),
                    "partitions_read": 5 + (query_idx % 50),
                    "photon_total_time_ms": (
                        500 + (query_idx * 50) if query_idx % 3 == 0 else None
                    ),
                    "is_from_result_cache": query_idx % 4 == 0,
                    "channel_used": (
                        "CHANNEL_NAME_CURRENT"
                        if query_idx % 2 == 0
                        else "CHANNEL_NAME_PREVIEW"
                    ),
                    "dbsql_version": f"2023.{40 + (query_idx % 10)}",
                    "client_application": client_app,
                }
            )

    return records


class TestWarehouseQueryAnalyzerBenchmarks:
    """Benchmark tests for WarehouseQueryAnalyzer with various dataset sizes."""

    def test_benchmark_small_dataset(self, benchmark):
        """Benchmark with small dataset: 1 warehouse, 100 queries."""
        data = generate_warehouse_query_data(
            num_warehouses=1,
            queries_per_warehouse=100,
        )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert "warehouses" in result
        assert len(result["warehouses"]) == 1

    def test_benchmark_medium_dataset(self, benchmark):
        """Benchmark with medium dataset: 10 warehouses, 1000 queries each."""
        data = generate_warehouse_query_data(
            num_warehouses=10,
            queries_per_warehouse=1000,
        )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result["warehouses"]) == 10

    def test_benchmark_large_dataset(self, benchmark):
        """Benchmark with large dataset: 50 warehouses, 5000 queries each."""
        data = generate_warehouse_query_data(
            num_warehouses=50,
            queries_per_warehouse=5000,
        )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result["warehouses"]) == 50

    def test_benchmark_very_large_dataset(self, benchmark):
        """Benchmark with very large dataset: 100 warehouses, 10000 queries each."""
        data = generate_warehouse_query_data(
            num_warehouses=100,
            queries_per_warehouse=10000,
        )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result["warehouses"]) == 100

    def test_benchmark_empty_dataset(self, benchmark):
        """Benchmark with empty dataset (edge case)."""
        data = []

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert result == {"warehouses": {}}

    def test_benchmark_single_warehouse_many_queries(self, benchmark):
        """Benchmark with single warehouse but many queries."""
        data = generate_warehouse_query_data(
            num_warehouses=1,
            queries_per_warehouse=50000,
        )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result["warehouses"]) == 1


class TestWarehouseQueryAnalyzerScaling:
    """Test how WarehouseQueryAnalyzer scales with increasing dataset sizes."""

    @pytest.mark.parametrize(
        "num_warehouses,queries_per_warehouse",
        [
            (1, 100),
            (5, 500),
            (10, 1000),
            (25, 2500),
            (50, 5000),
        ],
    )
    def test_scaling(
        self,
        benchmark,
        num_warehouses,
        queries_per_warehouse,
    ):
        """Test scaling across different dataset sizes."""
        data = generate_warehouse_query_data(
            num_warehouses=num_warehouses,
            queries_per_warehouse=queries_per_warehouse,
        )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert len(result["warehouses"]) == num_warehouses

        # Store metadata for comparison
        total_queries = num_warehouses * queries_per_warehouse
        benchmark.extra_info["num_warehouses"] = num_warehouses
        benchmark.extra_info["queries_per_warehouse"] = queries_per_warehouse
        benchmark.extra_info["total_queries"] = total_queries


@pytest.mark.memory
class TestWarehouseQueryAnalyzerMemory:
    """Memory usage benchmarks for WarehouseQueryAnalyzer."""

    def test_memory_large_dataset(self, benchmark):
        """Test memory usage with large dataset."""
        data = generate_warehouse_query_data(
            num_warehouses=50,
            queries_per_warehouse=5000,
        )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert isinstance(result, dict)
        assert "warehouses" in result


class TestWarehouseQueryAnalyzerComplexScenarios:
    """Benchmark complex real-world scenarios."""

    def test_benchmark_high_cardinality_users(self, benchmark):
        """Benchmark with many unique users (tests unique counting)."""
        data = []
        for query_idx in range(10000):
            data.append(
                {
                    "warehouse_id": "warehouse-001",
                    "user_id": query_idx,  # Every query from different user
                    "statement_type": "SELECT",
                    "duration_ms": 1000,
                    "rows_produced": 100,
                    "read_bytes": 1024 * 1024,
                }
            )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        warehouse = result["warehouses"]["warehouse-001"]
        assert warehouse["counts"]["users"] == 10000

    def test_benchmark_many_statement_types(self, benchmark):
        """Benchmark with diverse statement types (tests grouping)."""
        data = []
        statement_types = [f"STATEMENT_TYPE_{i}" for i in range(100)]

        for query_idx in range(10000):
            data.append(
                {
                    "warehouse_id": "warehouse-001",
                    "user_id": 1,
                    "statement_type": statement_types[query_idx % len(statement_types)],
                    "duration_ms": 1000 + query_idx,
                    "rows_produced": 100,
                    "read_bytes": 1024 * 1024,
                }
            )

        def run():
            analyzer = WarehouseQueryAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        warehouse = result["warehouses"]["warehouse-001"]
        assert len(warehouse["performance"]["statement_type_mix"]) == 100
