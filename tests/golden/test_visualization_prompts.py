# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden tests for visualization prompts.

These tests use syrupy snapshots to detect prompt regressions. When prompts
change (intentionally), run `pytest --snapshot-update` to update snapshots.

Test Coverage:
    - Line chart for time-series data
    - Bar chart for categorical comparison
    - Area chart for cumulative trends
    - Scatter chart for correlation analysis
    - Table fallback for unsuitable data
"""

from __future__ import annotations

from starboard.prompts.visualization.v1 import (
    PROMPT_VERSION,
    build_visualization_prompt,
)
from syrupy.assertion import SnapshotAssertion


class TestVisualizationPromptSnapshots:
    """Golden tests for visualization prompts using syrupy."""

    def test_prompt_version(self, snapshot: SnapshotAssertion) -> None:
        """Ensure prompt version is tracked."""
        assert snapshot == PROMPT_VERSION

    def test_line_chart_prompt_time_series(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Line chart for daily cost time-series."""
        query_meta = {
            "id": "daily_cost_trend",
            "name": "Daily Cost Trend",
            "description": "Daily cost breakdown over time",
            "recommended_chart_types": ["line", "area"],
            "goals": ["Show cost trends over time"],
        }

        data_profile = {
            "row_count": 30,
            "column_count": 2,
            "columns": {
                "date": {
                    "name": "date",
                    "type": "Date",
                    "null_count": 0,
                    "min": "2024-11-01",
                    "max": "2024-11-30",
                    "semantic_type": "time",
                },
                "total_cost": {
                    "name": "total_cost",
                    "type": "Float64",
                    "null_count": 0,
                    "min": 1234.56,
                    "max": 9876.54,
                    "mean": 5000.0,
                    "semantic_type": "metric",
                },
            },
        }

        messages = build_visualization_prompt(query_meta, data_profile)

        # Snapshot the user message (contains query context and data profile)
        assert messages[1]["content"] == snapshot

    def test_bar_chart_prompt_categorical_comparison(
        self, snapshot: SnapshotAssertion
    ) -> None:
        """Golden test: Bar chart for cost by service comparison."""
        query_meta = {
            "id": "cost_by_service",
            "name": "Cost by Service",
            "description": "Total cost grouped by service type",
            "recommended_chart_types": ["bar"],
            "goals": ["Compare costs across different services"],
        }

        data_profile = {
            "row_count": 10,
            "column_count": 2,
            "columns": {
                "service_name": {
                    "name": "service_name",
                    "type": "Utf8",
                    "null_count": 0,
                    "unique_count": 10,
                    "semantic_type": "dimension",
                },
                "total_cost": {
                    "name": "total_cost",
                    "type": "Float64",
                    "null_count": 0,
                    "min": 100.0,
                    "max": 5000.0,
                    "mean": 1500.0,
                    "semantic_type": "metric",
                },
            },
        }

        messages = build_visualization_prompt(query_meta, data_profile)
        assert messages[1]["content"] == snapshot

    def test_area_chart_prompt_cumulative_trend(
        self, snapshot: SnapshotAssertion
    ) -> None:
        """Golden test: Area chart for cumulative usage."""
        query_meta = {
            "id": "cumulative_usage",
            "name": "Cumulative Usage Over Time",
            "description": "Running total of resource usage",
            "recommended_chart_types": ["area", "line"],
            "goals": ["Show accumulation over time"],
        }

        data_profile = {
            "row_count": 24,
            "column_count": 2,
            "columns": {
                "hour": {
                    "name": "hour",
                    "type": "Int64",
                    "null_count": 0,
                    "min": 0,
                    "max": 23,
                    "semantic_type": "time",
                },
                "cumulative_usage": {
                    "name": "cumulative_usage",
                    "type": "Float64",
                    "null_count": 0,
                    "min": 0.0,
                    "max": 1000.0,
                    "mean": 500.0,
                    "semantic_type": "metric",
                },
            },
        }

        messages = build_visualization_prompt(query_meta, data_profile)
        assert messages[1]["content"] == snapshot

    def test_scatter_chart_prompt_correlation(
        self, snapshot: SnapshotAssertion
    ) -> None:
        """Golden test: Scatter plot for cost vs usage correlation."""
        query_meta = {
            "id": "cost_usage_correlation",
            "name": "Cost vs Usage Correlation",
            "description": "Analyze relationship between usage and cost",
            "recommended_chart_types": ["scatter"],
            "goals": ["Explore correlation between two metrics"],
        }

        data_profile = {
            "row_count": 50,
            "column_count": 2,
            "columns": {
                "usage_hours": {
                    "name": "usage_hours",
                    "type": "Float64",
                    "null_count": 0,
                    "min": 10.0,
                    "max": 1000.0,
                    "mean": 300.0,
                    "semantic_type": "metric",
                },
                "total_cost": {
                    "name": "total_cost",
                    "type": "Float64",
                    "null_count": 0,
                    "min": 50.0,
                    "max": 5000.0,
                    "mean": 1500.0,
                    "semantic_type": "metric",
                },
            },
        }

        messages = build_visualization_prompt(query_meta, data_profile)
        assert messages[1]["content"] == snapshot

    def test_table_fallback_prompt_unsuitable_data(
        self, snapshot: SnapshotAssertion
    ) -> None:
        """Golden test: Table fallback for complex configuration data."""
        query_meta = {
            "id": "job_config_details",
            "name": "Job Configuration Details",
            "description": "Detailed job settings and parameters",
            "recommended_chart_types": [],  # No recommended charts
            "goals": ["View detailed configuration"],
        }

        data_profile = {
            "row_count": 3,
            "column_count": 8,
            "columns": {
                "job_id": {
                    "name": "job_id",
                    "type": "Utf8",
                    "null_count": 0,
                    "semantic_type": "id",
                },
                "cluster_size": {
                    "name": "cluster_size",
                    "type": "Utf8",
                    "null_count": 0,
                    "semantic_type": "dimension",
                },
                "driver_type": {
                    "name": "driver_type",
                    "type": "Utf8",
                    "null_count": 0,
                    "semantic_type": "dimension",
                },
                "worker_type": {
                    "name": "worker_type",
                    "type": "Utf8",
                    "null_count": 0,
                    "semantic_type": "dimension",
                },
                "num_workers": {
                    "name": "num_workers",
                    "type": "Int64",
                    "null_count": 0,
                    "semantic_type": "metric",
                },
                "libraries": {
                    "name": "libraries",
                    "type": "Utf8",
                    "null_count": 2,
                    "semantic_type": "dimension",
                },
                "timeout": {
                    "name": "timeout",
                    "type": "Int64",
                    "null_count": 1,
                    "semantic_type": "metric",
                },
                "retry_policy": {
                    "name": "retry_policy",
                    "type": "Utf8",
                    "null_count": 0,
                    "semantic_type": "dimension",
                },
            },
        }

        messages = build_visualization_prompt(query_meta, data_profile)
        assert messages[1]["content"] == snapshot

    def test_prompt_with_no_recommendations(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt when no chart types are recommended."""
        query_meta = {
            "id": "generic_query",
            "name": "Generic Query",
            "description": "A query without specific visualization guidance",
            "recommended_chart_types": [],  # Empty list
            "goals": [],  # No specific goals
        }

        data_profile = {
            "row_count": 15,
            "column_count": 3,
            "columns": {
                "category": {
                    "name": "category",
                    "type": "Utf8",
                    "null_count": 0,
                    "unique_count": 15,
                    "semantic_type": "dimension",
                },
                "value_a": {
                    "name": "value_a",
                    "type": "Float64",
                    "null_count": 0,
                    "min": 1.0,
                    "max": 100.0,
                    "mean": 50.0,
                    "semantic_type": "metric",
                },
                "value_b": {
                    "name": "value_b",
                    "type": "Float64",
                    "null_count": 0,
                    "min": 10.0,
                    "max": 200.0,
                    "mean": 75.0,
                    "semantic_type": "metric",
                },
            },
        }

        messages = build_visualization_prompt(query_meta, data_profile)
        assert messages[1]["content"] == snapshot


# Integration test: Full prompt structure
def test_prompt_structure() -> None:
    """Verify prompt structure (system + user messages)."""
    query_meta = {
        "id": "test_query",
        "name": "Test Query",
        "description": "Test description",
        "recommended_chart_types": ["bar"],
        "goals": ["test goal"],
    }

    data_profile = {
        "row_count": 10,
        "column_count": 2,
        "columns": {
            "x": {
                "name": "x",
                "type": "Utf8",
                "semantic_type": "dimension",
            },
            "y": {
                "name": "y",
                "type": "Float64",
                "semantic_type": "metric",
            },
        },
    }

    messages = build_visualization_prompt(query_meta, data_profile)

    # Verify structure
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    # Verify system prompt contains key sections
    system_content = messages[0]["content"]
    assert "data visualization expert" in system_content.lower()
    assert "available chart types" in system_content.lower()
    assert "encoding types" in system_content.lower()

    # Verify user prompt contains query context and data profile
    user_content = messages[1]["content"]
    assert "Test Query" in user_content
    assert "Test description" in user_content
    assert "bar" in user_content
    assert '"row_count": 10' in user_content
