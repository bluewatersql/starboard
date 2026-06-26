# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Performance benchmarks for SparkUIAnalyzer.

Run with: pytest tests/benchmarks/transformers/test_spark_ui_benchmarks.py --benchmark-only

View results: pytest tests/benchmarks/transformers/test_spark_ui_benchmarks.py --benchmark-only --benchmark-compare

Requirements:
- pytest-benchmark
- memory_profiler (optional, for memory benchmarks)
"""

import pytest
from starboard_server.tools.domain.job.spark_ui_analyzer import SparkUIAnalyzer


def generate_spark_ui_data(num_jobs: int, num_stages: int) -> dict:
    """
    Generate synthetic Spark UI data for benchmarking.

    Args:
        num_jobs: Number of jobs to generate
        num_stages: Number of stages to generate

    Returns:
        Dict with jobData and stageData lists
    """
    jobs = []
    stages = []

    for job_id in range(num_jobs):
        sql_id = f"sql_{job_id % 10}"  # Group into 10 SQL IDs
        jobs.append(
            {
                "job_id": job_id,
                "sql_id": sql_id,
                "duration": 1000 + (job_id * 100),
                "stage_ids": list(range(job_id * 5, job_id * 5 + 5)),
            }
        )

    for stage_id in range(num_stages):
        job_id = stage_id // 5
        sql_id = f"sql_{job_id % 10}"
        stages.append(
            {
                "stage_id": stage_id,
                "query_id": sql_id,
                "job_id": job_id,
                "duration": 500 + (stage_id * 50),
                "num_tasks": 10 + (stage_id % 50),
                "input_mb": 100.0 + (stage_id * 10.0),
                "shuffle_mb_written": 50.0 + (stage_id * 5.0),
                "remote_mb_read": 25.0 + (stage_id * 2.5),
                "output_mb": 75.0 + (stage_id * 7.5),
                "memory_bytes_spilled": stage_id * 1024 * 1024,
                "disk_bytes_spilled": stage_id * 512 * 1024,
                "stage_info": {"stage_name": f"Stage_{stage_id}"},
            }
        )

    return {"jobData": jobs, "stageData": stages}


class TestSparkUIAnalyzerBenchmarks:
    """Benchmark tests for SparkUIAnalyzer with various dataset sizes."""

    def test_benchmark_small_dataset(self, benchmark):
        """Benchmark with small dataset: 10 jobs, 50 stages."""
        data = generate_spark_ui_data(num_jobs=10, num_stages=50)

        def run():
            analyzer = SparkUIAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        result_dict = result.to_dict()
        assert "summary" in result_dict
        assert "by_sql_id" in result_dict

    def test_benchmark_medium_dataset(self, benchmark):
        """Benchmark with medium dataset: 100 jobs, 500 stages."""
        data = generate_spark_ui_data(num_jobs=100, num_stages=500)

        def run():
            analyzer = SparkUIAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        result_dict = result.to_dict()
        assert len(result_dict["by_sql_id"]) > 0

    def test_benchmark_large_dataset(self, benchmark):
        """Benchmark with large dataset: 1000 jobs, 5000 stages."""
        data = generate_spark_ui_data(num_jobs=1000, num_stages=5000)

        def run():
            analyzer = SparkUIAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        result_dict = result.to_dict()
        assert "summary" in result_dict

    def test_benchmark_very_large_dataset(self, benchmark):
        """Benchmark with very large dataset: 5000 jobs, 25000 stages."""
        data = generate_spark_ui_data(num_jobs=5000, num_stages=25000)

        def run():
            analyzer = SparkUIAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None

    def test_benchmark_empty_dataset(self, benchmark):
        """Benchmark with empty dataset (edge case)."""
        data = {"jobData": [], "stageData": []}

        def run():
            analyzer = SparkUIAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None

    def test_benchmark_jobs_only(self, benchmark):
        """Benchmark with jobs but no stages."""
        data = generate_spark_ui_data(num_jobs=1000, num_stages=0)

        def run():
            analyzer = SparkUIAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None

    def test_benchmark_stages_only(self, benchmark):
        """Benchmark with stages but no jobs."""
        data = generate_spark_ui_data(num_jobs=0, num_stages=5000)

        def run():
            analyzer = SparkUIAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None


class TestSparkUIAnalyzerScaling:
    """Test how SparkUIAnalyzer scales with increasing dataset sizes."""

    @pytest.mark.parametrize(
        "num_jobs,num_stages",
        [
            (10, 50),
            (50, 250),
            (100, 500),
            (500, 2500),
            (1000, 5000),
        ],
    )
    def test_scaling(self, benchmark, num_jobs, num_stages):
        """Test scaling across different dataset sizes."""
        data = generate_spark_ui_data(num_jobs=num_jobs, num_stages=num_stages)

        def run():
            analyzer = SparkUIAnalyzer(data)
            return analyzer.analyze()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None

        # Store metadata for comparison
        benchmark.extra_info["num_jobs"] = num_jobs
        benchmark.extra_info["num_stages"] = num_stages
        benchmark.extra_info["total_records"] = num_jobs + num_stages


@pytest.mark.memory
class TestSparkUIAnalyzerMemory:
    """Memory usage benchmarks for SparkUIAnalyzer."""

    def test_memory_large_dataset(self, benchmark):
        """Test memory usage with large dataset."""
        data = generate_spark_ui_data(num_jobs=1000, num_stages=5000)

        def run():
            analyzer = SparkUIAnalyzer(data)
            result = analyzer.analyze()
            # Convert to dict to simulate full processing
            return result.to_dict()

        result = benchmark(run)

        # Verify result is valid
        assert result is not None
        assert isinstance(result, dict)
