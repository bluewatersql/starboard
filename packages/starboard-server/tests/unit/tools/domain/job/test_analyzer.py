"""Tests for job domain analyzer."""

from starboard_server.tools.domain.job.analyzer import JobAnalyzer


class TestJobAnalyzer:
    """Tests for JobAnalyzer."""

    def test_analyze_job_history(self):
        """Test job history analysis."""
        runs = [
            {"status": "SUCCESS"},
            {"status": "SUCCESS"},
            {"status": "FAILED"},
        ]
        runtime_meta = {
            "success_rate": 0.67,
            "avg_duration_seconds": 120.5,
            "failed_runs": 1,
        }

        result = JobAnalyzer.analyze_job_history(runs, runtime_meta)

        assert result.total_runs == 3
        assert result.success_rate == 0.67
        assert result.avg_duration_seconds == 120.5
        assert result.has_failures is True
        # New optional fields default to None
        assert result.spark_logs is None
        assert result.cluster_id is None

    def test_analyze_task_dependencies(self):
        """Test task dependency analysis."""
        tasks = [
            {"task_key": "task1", "depends_on": []},
            {"task_key": "task2", "depends_on": ["task1"]},
            {"task_key": "task3", "depends_on": ["task1", "task2"]},
        ]

        result = JobAnalyzer.analyze_task_dependencies(tasks)

        assert result.dependencies == {
            "task1": [],
            "task2": ["task1"],
            "task3": ["task1", "task2"],
        }
        assert result.critical_path == ["task1"]

    def test_analyze_task_dependencies_empty(self):
        """Test task dependency analysis with empty list."""
        result = JobAnalyzer.analyze_task_dependencies([])

        assert result.dependencies == {}
        assert result.critical_path == []


class TestJobHistoryResultWithSparkLogs:
    """Tests for JobHistoryResult with Spark logs."""

    def test_job_history_result_with_spark_logs(self):
        """Test creating JobHistoryResult with Spark logs."""
        from starboard_core.domain.models.job import JobHistoryResult

        spark_logs = {
            "summary": {"total_jobs": 10, "total_stages": 50},
            "by_sql_id": {"sql_123": {"total_stages": 5}},
        }

        result = JobHistoryResult(
            total_runs=5,
            success_rate=0.8,
            avg_duration_seconds=300.0,
            has_failures=True,
            spark_logs=spark_logs,
            cluster_id="cluster-123",
        )

        assert result.total_runs == 5
        assert result.success_rate == 0.8
        assert result.avg_duration_seconds == 300.0
        assert result.has_failures is True
        assert result.spark_logs == spark_logs
        assert result.cluster_id == "cluster-123"

    def test_job_history_result_without_spark_logs(self):
        """Test creating JobHistoryResult without Spark logs (backward compatible)."""
        from starboard_core.domain.models.job import JobHistoryResult

        result = JobHistoryResult(
            total_runs=3,
            success_rate=1.0,
            avg_duration_seconds=120.0,
            has_failures=False,
        )

        assert result.total_runs == 3
        assert result.spark_logs is None
        assert result.cluster_id is None
