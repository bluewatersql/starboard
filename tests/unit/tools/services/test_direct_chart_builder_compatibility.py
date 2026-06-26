# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Compatibility tests for DirectChartConfigBuilder output format.

Ensures the output from DirectChartConfigBuilder matches what frontend expects
and is compatible with the previous VisualizationService output format.
"""

from starboard_server.tools.services.direct_chart_builder import (
    DirectChartConfigBuilder,
)


class TestDirectChartConfigBuilderCompatibility:
    """Test compatibility with frontend expectations."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.builder = DirectChartConfigBuilder()

    def test_output_has_all_required_frontend_fields(self) -> None:
        """Test that output contains all fields expected by frontend."""
        hints = {
            "chart_type": "line",
            "x_field": "usage_date",
            "y_field": "total_cost",
            "x_type": "temporal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 30,
            "columns": {
                "usage_date": {"type": "Date"},
                "total_cost": {"type": "Float64"},
            },
        }
        data_reference = "test_ref_123"

        # Build visualization output
        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=data_reference,
        )

        # Convert to dict (like analytics_v2_sql_tools does)
        output_dict = {
            "summary": result.summary,
            "chart_recommendation": (
                {
                    "chart_type": result.chart_recommendation.chart_type.value,
                    "reasoning": result.chart_recommendation.reasoning,
                    "confidence": result.chart_recommendation.confidence,
                }
                if result.chart_recommendation
                else None
            ),
            "chart_config": (
                result.chart_config.model_dump() if result.chart_config else None
            ),
            "data_reference": result.data_reference,
            "has_visualization": result.has_visualization,
        }

        # Frontend expects these exact fields
        assert "summary" in output_dict
        assert "chart_recommendation" in output_dict
        assert "chart_config" in output_dict
        assert "data_reference" in output_dict
        assert "has_visualization" in output_dict

        # Verify types
        assert isinstance(output_dict["summary"], str)
        assert isinstance(output_dict["data_reference"], str)
        assert isinstance(output_dict["has_visualization"], bool)

    def test_chart_config_has_required_fields_for_api(self) -> None:
        """Test that chart_config has all fields needed by /api/visualization/render."""
        hints = {
            "chart_type": "bar",
            "x_field": "warehouse_id",
            "y_field": "total_cost",
            "x_type": "nominal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 10,
            "columns": {
                "warehouse_id": {"type": "Utf8"},
                "total_cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference="test_ref",
        )

        # API endpoint expects these ChartConfig fields
        chart_config = result.chart_config
        assert chart_config is not None
        assert hasattr(chart_config, "chart_type")
        assert hasattr(chart_config, "title")
        assert hasattr(chart_config, "encodings")
        assert hasattr(chart_config, "options")

        # Verify chart_config can be serialized (model_dump)
        serialized = chart_config.model_dump()
        assert "chart_type" in serialized
        assert "title" in serialized
        assert "encodings" in serialized

    def test_table_fallback_output_compatible(self) -> None:
        """Test that table fallback output is compatible with frontend."""
        # Empty hints should fall back to table
        result = self.builder.build_from_hints(
            hints={},
            data_profile={"row_count": 10, "columns": {}},
            data_reference="test_ref",
        )

        # Frontend expects has_visualization=False for tables
        assert result.has_visualization is False
        assert result.chart_config is None
        assert result.chart_recommendation is None
        assert result.data_reference == "test_ref"
        assert result.summary is not None

    def test_data_reference_preserved(self) -> None:
        """Test that data_reference is preserved for frontend data fetching."""
        data_ref = "data_ref_abc123def456"
        hints = {
            "chart_type": "scatter",
            "x_field": "usage_hours",
            "y_field": "total_cost",
            "x_type": "quantitative",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 50,
            "columns": {
                "usage_hours": {"type": "Float64"},
                "total_cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=data_ref,
        )

        # Frontend needs exact data_reference to fetch cached data
        assert result.data_reference == data_ref

    def test_has_visualization_flag_accuracy(self) -> None:
        """Test that has_visualization flag accurately reflects chart availability."""
        # Case 1: Valid chart → has_visualization=True
        hints_chart = {
            "chart_type": "line",
            "x_field": "date",
            "y_field": "cost",
            "x_type": "temporal",
            "y_type": "quantitative",
        }
        profile = {
            "row_count": 30,
            "columns": {"date": {"type": "Date"}, "cost": {"type": "Float64"}},
        }

        result_chart = self.builder.build_from_hints(
            hints=hints_chart, data_profile=profile, data_reference="ref1"
        )
        assert result_chart.has_visualization is True
        assert result_chart.chart_config is not None

        # Case 2: Table fallback → has_visualization=False
        hints_table = {"chart_type": "table"}
        result_table = self.builder.build_from_hints(
            hints=hints_table, data_profile=profile, data_reference="ref2"
        )
        assert result_table.has_visualization is False
        assert result_table.chart_config is None

    def test_chart_recommendation_optional(self) -> None:
        """Test that chart_recommendation can be None (frontend handles this)."""
        # Table fallback has no chart_recommendation
        result = self.builder.build_from_hints(
            hints={"chart_type": "table"},
            data_profile={"row_count": 5, "columns": {}},
            data_reference="test_ref",
        )

        # Frontend checks if chart_recommendation exists before using
        assert result.chart_recommendation is None
        assert result.has_visualization is False

    def test_encodings_serialization(self) -> None:
        """Test that encodings serialize correctly for API/frontend."""
        hints = {
            "chart_type": "area",
            "x_field": "hour",
            "y_field": "cumulative_usage",
            "x_type": "quantitative",
            "y_type": "quantitative",
        }
        profile = {
            "row_count": 24,
            "columns": {
                "hour": {"type": "Int64"},
                "cumulative_usage": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints, data_profile=profile, data_reference="ref"
        )

        # Serialize chart_config
        serialized = result.chart_config.model_dump()

        # Frontend expects encodings as dict with x/y keys
        assert "encodings" in serialized
        assert isinstance(serialized["encodings"], dict)
        assert "x" in serialized["encodings"]
        assert "y" in serialized["encodings"]

        # Each encoding should have field, type, title
        x_encoding = serialized["encodings"]["x"]
        assert "field" in x_encoding
        assert "type" in x_encoding
        assert x_encoding["field"] == "hour"
        assert x_encoding["type"] == "quantitative"
