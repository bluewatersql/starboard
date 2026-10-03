# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for task_sources transformation."""

import pytest
from starboard_core.domain.transformers.job_transformers import transform_task_sources


class TestTransformTaskSources:
    """Test task_sources transformation for LLM-friendly format."""

    @pytest.mark.parametrize(
        "task_key,input_data,expected_type,expected_path",
        [
            (
                "notebook_task",
                {
                    "type": "notebook",
                    "path": "/Workspace/etl/pipeline",
                    "source": "# ETL code\ndf = spark.read.table('source')",
                },
                "notebook",
                "/Workspace/etl/pipeline",
            ),
            (
                "sql_task",
                {
                    "type": "sql",
                    "source": "SELECT * FROM sales WHERE date = current_date()",
                },
                "sql",
                None,
            ),
            (
                "python_task",
                {
                    "type": "python_file",
                    "path": "dbfs:/scripts/process.py",
                    "source": "print('processing')",
                },
                "python_file",
                "dbfs:/scripts/process.py",
            ),
        ],
    )
    def test_transform_individual_task_types(
        self, task_key, input_data, expected_type, expected_path
    ):
        """Test transformation of different task types."""
        result = transform_task_sources({task_key: input_data})

        assert task_key in result
        assert result[task_key]["task_type"] == expected_type
        assert "code" in result[task_key]
        assert "source" not in result[task_key]  # Renamed to "code"

        if expected_path:
            assert result[task_key]["file_path"] == expected_path
        else:
            assert "file_path" not in result[task_key]

    def test_transform_multiple_tasks(self, sample_task_sources):
        """Test transformation of multiple task sources."""
        result = transform_task_sources(sample_task_sources)

        assert len(result) == 3
        assert all(key in result for key in sample_task_sources)
        assert all("code" in result[key] for key in result)
        assert all("task_type" in result[key] for key in result)

    @pytest.mark.parametrize(
        "invalid_input",
        [
            {},  # Empty dict
            None,  # None
            {"task1": "not a dict"},  # Invalid structure
        ],
    )
    def test_transform_handles_invalid_input(self, invalid_input):
        """Test transformation handles invalid inputs gracefully."""
        result = transform_task_sources(invalid_input)
        assert isinstance(result, dict)
        if (
            invalid_input
            and isinstance(invalid_input, dict)
            and "task1" in invalid_input
        ):
            # Invalid entries should be skipped
            assert "task1" not in result

    def test_transform_filters_none_values(self):
        """Test that None values are filtered out."""
        task_sources = {"sql_task": {"type": "sql", "path": None, "source": "SELECT 1"}}
        result = transform_task_sources(task_sources)

        assert "file_path" not in result["sql_task"]  # None filtered out
        assert result["sql_task"]["task_type"] == "sql"
        assert result["sql_task"]["code"] == "SELECT 1"

    def test_field_names_are_llm_friendly(self):
        """Test that transformed field names are clear and LLM-friendly."""
        input_data = {"task1": {"type": "notebook", "path": "/nb", "source": "code"}}
        result = transform_task_sources(input_data)

        # New field names
        assert "task_type" in result["task1"]
        assert "file_path" in result["task1"]
        assert "code" in result["task1"]

        # Old field names should be gone
        assert "type" not in result["task1"]
        assert "path" not in result["task1"]
        assert "source" not in result["task1"]
