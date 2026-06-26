# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for source transformer domain logic."""

from starboard_server.tools.domain.source.models import CodeQualityIssue
from starboard_server.tools.domain.source.transformer import SourceTransformer


class TestSourceTransformer:
    """Test suite for SourceTransformer pure functions."""

    def test_transform_hotspot_to_issue(self):
        """Test transformation of LLM hotspot to CodeQualityIssue."""
        # Arrange
        hotspot = {
            "artifact": "task1",
            "risk": "high",
            "issue": "SQL injection risk",
            "evidence": "Unparameterized SQL query",
            "fix": {
                "strategy": "Use parameterized queries",
                "snippet_before": "query = f'SELECT * FROM {table}'",
                "snippet_after": "query = 'SELECT * FROM ?', params=[table]",
            },
            "line_range": "10-12",
            "signal": ["security", "sql"],
        }

        # Act
        result = SourceTransformer.transform_hotspot_to_issue(hotspot, "task1")

        # Assert
        assert isinstance(result, CodeQualityIssue)
        assert result.context == "task1"
        assert result.severity == "high"
        assert result.issue == "SQL injection risk"
        assert result.description == "Unparameterized SQL query"
        assert result.recommendation == "Use parameterized queries"
        assert result.line_range == "10-12"
        assert result.signals == ["security", "sql"]

    def test_transform_hotspot_to_issue_defaults(self):
        """Test transformation with minimal hotspot data (uses defaults)."""
        # Arrange
        hotspot = {}

        # Act
        result = SourceTransformer.transform_hotspot_to_issue(hotspot, "unknown")

        # Assert
        assert result.context == "unknown"
        assert result.severity == "medium"  # Default
        assert result.issue == ""
        assert result.signals == []

    def test_issue_to_dict(self):
        """Test conversion of CodeQualityIssue to dictionary."""
        # Arrange
        issue = CodeQualityIssue(
            context="task1",
            severity="high",
            issue="Performance issue",
            description="Inefficient query",
            recommendation="Add indexes",
            code_snippet="SELECT * FROM huge_table",
            fix_snippet="SELECT id, name FROM huge_table WHERE indexed_col = ?",
            line_range="5-10",
            signals=["performance"],
        )

        # Act
        result = SourceTransformer.issue_to_dict(issue)

        # Assert
        assert result["context"] == "task1"
        assert result["severity"] == "high"
        assert result["issue"] == "Performance issue"
        assert result["recommendation"] == "Add indexes"
        assert result["line_range"] == "5-10"
        assert result["signals"] == ["performance"]

    def test_get_task_source_type_notebook(self):
        """Test task source type detection for notebook tasks."""
        # Arrange
        task = {"task_key": "task1", "notebook_task": {"notebook_path": "/path"}}

        # Act
        result = SourceTransformer.get_task_source_type(task)

        # Assert
        assert result == "notebook"

    def test_get_task_source_type_python_file(self):
        """Test task source type detection for Python file tasks."""
        # Arrange
        task = {"task_key": "task1", "spark_python_task": {"python_file": "main.py"}}

        # Act
        result = SourceTransformer.get_task_source_type(task)

        # Assert
        assert result == "python_file"

    def test_get_task_source_type_sql(self):
        """Test task source type detection for SQL tasks."""
        # Arrange
        task = {"task_key": "task1", "sql_task": {"query": {"query": "SELECT 1"}}}

        # Act
        result = SourceTransformer.get_task_source_type(task)

        # Assert
        assert result == "sql"

    def test_get_task_source_type_unknown(self):
        """Test task source type detection for unknown task type."""
        # Arrange
        task = {"task_key": "task1"}

        # Act
        result = SourceTransformer.get_task_source_type(task)

        # Assert
        assert result is None

    def test_build_source_result(self):
        """Test building source result structure."""
        # Arrange
        sources = {"task1": {"type": "notebook", "source": "code"}}

        # Act
        result = SourceTransformer.build_source_result(sources)

        # Assert
        assert result["has_source_code"] is True
        assert result["task_sources"] == sources
        assert result["results"]["has_source_code"] is True

    def test_build_empty_source_result(self):
        """Test building empty source result."""
        # Act
        result = SourceTransformer.build_empty_source_result()

        # Assert
        assert result["has_source_code"] is False
        assert result["task_sources"] == {}

    def test_build_empty_source_result_with_error(self):
        """Test building empty source result with error message."""
        # Act
        result = SourceTransformer.build_empty_source_result("Not found")

        # Assert
        assert result["has_source_code"] is False
        assert result["error"] == "Not found"
        assert result["results"]["error"] == "Not found"

    def test_build_analysis_result(self):
        """Test building analysis result structure."""
        # Arrange
        issues = [
            CodeQualityIssue(
                context="task1",
                severity="high",
                issue="Issue",
                description="Desc",
                recommendation="Fix",
            )
        ]
        notes = ["Note 1"]

        # Act
        result = SourceTransformer.build_analysis_result(issues, notes)

        # Assert
        assert len(result["code_quality_issues"]) == 1
        assert result["code_quality_notes"] == ["Note 1"]
        assert result["results"]["code_quality_issues"][0]["context"] == "task1"

    def test_build_empty_analysis_result(self):
        """Test building empty analysis result."""
        # Act
        result = SourceTransformer.build_empty_analysis_result()

        # Assert
        assert result["code_quality_issues"] == []
        assert result["code_quality_notes"] == []
