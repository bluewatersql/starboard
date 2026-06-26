# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden/snapshot tests for SparkUIAnalyzer.

These tests use real (anonymized) data and snapshot testing to ensure:
1. Output structure remains consistent (regression detection)
2. Transformations are deterministic
3. Output is valid and complete

Run with: pytest tests/golden/transformers/test_spark_ui_golden.py
Update snapshots: pytest --snapshot-update
"""

import json
from pathlib import Path

import pytest
from starboard_server.tools.domain.job.spark_ui_analyzer import SparkUIAnalyzer

GOLDEN_DIR = Path(__file__).parent / "data"


@pytest.mark.golden
class TestSparkUIGolden:
    """Golden tests for SparkUIAnalyzer with real data."""

    def test_snapshot_match(self, snapshot):
        """Test output matches golden snapshot."""
        input_data = json.loads((GOLDEN_DIR / "spark_ui_sample.json").read_text())
        analyzer = SparkUIAnalyzer(input_data)
        result = analyzer.analyze()

        # Convert to dict for snapshot
        result_dict = result.to_dict()

        # Verify against snapshot
        assert result_dict == snapshot

    def test_deterministic_output(self):
        """Test transformation produces consistent output across multiple runs."""
        input_data = json.loads((GOLDEN_DIR / "spark_ui_sample.json").read_text())

        # Run multiple times
        results = []
        for _ in range(5):
            analyzer = SparkUIAnalyzer(input_data)
            result = analyzer.analyze()
            results.append(result.to_dict())

        # All results should be identical
        for i in range(1, len(results)):
            assert results[i] == results[0], f"Run {i} differs from run 0"

    def test_output_structure_valid(self):
        """Test output structure is valid and complete."""
        input_data = json.loads((GOLDEN_DIR / "spark_ui_sample.json").read_text())
        analyzer = SparkUIAnalyzer(input_data)
        result = analyzer.analyze()
        result_dict = result.to_dict()

        # Check top-level structure
        assert "summary" in result_dict
        assert "by_sql_id" in result_dict
        assert "top_slowest_jobs" in result_dict
        assert "top_heaviest_stages" in result_dict

        # Check summary
        summary = result_dict["summary"]
        assert "total_jobs" in summary
        assert "total_stages" in summary
        assert "distinct_sql_ids" in summary
        assert summary["total_jobs"] == 3
        assert summary["total_stages"] == 9

        # Check by_sql_id entries
        for _sql_id, sql_data in result_dict["by_sql_id"].items():
            assert "sql_id" in sql_data
            assert "job_count" in sql_data
            assert "total_job_duration_s" in sql_data
            assert "total_stages" in sql_data
            assert "io" in sql_data
            assert "long_stages" in sql_data
            assert "job_ids" in sql_data

            # Check I/O structure
            io = sql_data["io"]
            assert "input_mb" in io
            assert "shuffle_written_mb" in io
            assert "remote_read_mb" in io
            assert "output_mb" in io
            assert "memory_spilled_mb" in io
            assert "disk_spilled_mb" in io

        # Check top jobs
        for job in result_dict["top_slowest_jobs"]:
            assert "job_id" in job
            assert "sql_id" in job
            assert "duration_s" in job
            assert "stage_ids" in job

        # Check top stages
        for stage in result_dict["top_heaviest_stages"]:
            assert "stage_id" in stage
            assert "query_id" in stage
            assert "duration_s" in stage
            assert "num_tasks" in stage

    def test_no_unexpected_none_values(self):
        """Test critical fields don't contain unexpected None values."""
        input_data = json.loads((GOLDEN_DIR / "spark_ui_sample.json").read_text())
        analyzer = SparkUIAnalyzer(input_data)
        result = analyzer.analyze()
        result_dict = result.to_dict()

        # Summary shouldn't have None
        assert result_dict["summary"]["total_jobs"] is not None
        assert result_dict["summary"]["total_stages"] is not None

        # SQL aggregates shouldn't have None in critical fields
        for _sql_id, sql_data in result_dict["by_sql_id"].items():
            assert sql_data["sql_id"] is not None
            assert sql_data["job_count"] is not None
            assert sql_data["total_stages"] is not None

    def test_metrics_aggregation_correct(self):
        """Test that metrics are correctly aggregated."""
        input_data = json.loads((GOLDEN_DIR / "spark_ui_sample.json").read_text())
        analyzer = SparkUIAnalyzer(input_data)
        result = analyzer.analyze()
        result_dict = result.to_dict()

        # Verify sql_001 metrics (jobs 1 and 2, stages 1-5)
        sql_001 = result_dict["by_sql_id"]["sql_001"]
        assert sql_001["job_count"] == 2
        assert sql_001["total_stages"] == 5

        # Total job duration should be 5432 + 3210 = 8642 ms
        assert sql_001["total_job_duration_s"] == 8642.0

        # I/O should aggregate all 5 stages
        # input: 1024.5 + 2048 + 500 + 1500 + 800 = 5872.5
        assert sql_001["io"]["input_mb"] == 5872.5

        # Verify sql_002 metrics (job 3, stages 6-9)
        sql_002 = result_dict["by_sql_id"]["sql_002"]
        assert sql_002["job_count"] == 1
        assert sql_002["total_stages"] == 4
        assert sql_002["total_job_duration_s"] == 8765.0

    def test_heavy_stages_identified(self):
        """Test that heavy stages are correctly identified."""
        input_data = json.loads((GOLDEN_DIR / "spark_ui_sample.json").read_text())
        analyzer = SparkUIAnalyzer(input_data)
        result = analyzer.analyze()
        result_dict = result.to_dict()

        # Stage 6 has 150 tasks (> 100 threshold), should be marked as heavy
        sql_002 = result_dict["by_sql_id"]["sql_002"]
        heavy_stage_ids = [s["stage_id"] for s in sql_002["long_stages"]]
        assert 6 in heavy_stage_ids, "Stage 6 should be marked as heavy (150 tasks)"

    def test_top_n_sorting(self):
        """Test that top-N lists are correctly sorted."""
        input_data = json.loads((GOLDEN_DIR / "spark_ui_sample.json").read_text())
        analyzer = SparkUIAnalyzer(input_data)
        result = analyzer.analyze()
        result_dict = result.to_dict()

        # Top slowest jobs should be sorted by duration (descending)
        top_jobs = result_dict["top_slowest_jobs"]
        for i in range(len(top_jobs) - 1):
            assert top_jobs[i]["duration_s"] >= top_jobs[i + 1]["duration_s"]

        # Top heaviest stages should be sorted by duration (descending)
        top_stages = result_dict["top_heaviest_stages"]
        for i in range(len(top_stages) - 1):
            assert top_stages[i]["duration_s"] >= top_stages[i + 1]["duration_s"]
