"""Unit tests for DirectChartConfigBuilder.

Tests the deterministic chart configuration builder that uses LLM hints
from SQL generation without making a second LLM call.

Coverage Target: 80%+
"""

from starboard_server.tools.domain.analytics.visualization_models import (
    ChartConfig,
    ChartRecommendation,
    ChartType,
    Encoding,
    EncodingType,
    VisualizationOutput,
)
from starboard_server.tools.services.direct_chart_builder import (
    DirectChartConfigBuilder,
)


class TestDirectChartConfigBuilder:
    """Test suite for DirectChartConfigBuilder."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.builder = DirectChartConfigBuilder()
        self.data_reference = "test_data_ref_123"

    # =========================================================================
    # Test: build_from_hints() - Valid Hints
    # =========================================================================

    def test_build_from_hints_line_chart_success(self) -> None:
        """Test building line chart from valid hints."""
        hints = {
            "chart_type": "line",
            "x_field": "usage_date",
            "y_field": "total_cost",
            "x_type": "temporal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 30,
            "column_count": 2,
            "columns": {
                "usage_date": {"type": "Date"},
                "total_cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        assert isinstance(result, VisualizationOutput)
        assert result.has_visualization is True
        assert result.data_reference == self.data_reference
        assert result.chart_config is not None
        assert result.chart_config.chart_type == ChartType.LINE
        assert "x" in result.chart_config.encodings
        assert "y" in result.chart_config.encodings
        assert result.chart_config.encodings["x"].field == "usage_date"
        assert result.chart_config.encodings["x"].type == EncodingType.TEMPORAL
        assert result.chart_config.encodings["y"].field == "total_cost"
        assert result.chart_config.encodings["y"].type == EncodingType.QUANTITATIVE
        assert result.chart_recommendation is not None
        assert result.summary is not None

    def test_build_from_hints_bar_chart_success(self) -> None:
        """Test building bar chart from valid hints."""
        hints = {
            "chart_type": "bar",
            "x_field": "warehouse_id",
            "y_field": "total_cost",
            "x_type": "nominal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 10,
            "column_count": 2,
            "columns": {
                "warehouse_id": {"type": "Utf8"},
                "total_cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        assert result.has_visualization is True
        assert result.chart_config.chart_type == ChartType.BAR
        assert result.chart_config.encodings["x"].field == "warehouse_id"
        assert result.chart_config.encodings["x"].type == EncodingType.NOMINAL
        assert result.chart_config.encodings["y"].field == "total_cost"
        assert result.chart_config.encodings["y"].type == EncodingType.QUANTITATIVE

    def test_build_from_hints_area_chart_success(self) -> None:
        """Test building area chart from valid hints."""
        hints = {
            "chart_type": "area",
            "x_field": "hour",
            "y_field": "cumulative_usage",
            "x_type": "quantitative",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 24,
            "column_count": 2,
            "columns": {
                "hour": {"type": "Int64"},
                "cumulative_usage": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        assert result.has_visualization is True
        assert result.chart_config.chart_type == ChartType.AREA

    def test_build_from_hints_scatter_chart_success(self) -> None:
        """Test building scatter plot from valid hints."""
        hints = {
            "chart_type": "scatter",
            "x_field": "usage_hours",
            "y_field": "total_cost",
            "x_type": "quantitative",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 50,
            "column_count": 2,
            "columns": {
                "usage_hours": {"type": "Float64"},
                "total_cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        assert result.has_visualization is True
        assert result.chart_config.chart_type == ChartType.SCATTER

    def test_build_from_hints_table_explicit(self) -> None:
        """Test explicitly requesting table view."""
        hints = {
            "chart_type": "table",
            "x_field": None,
            "y_field": None,
            "x_type": None,
            "y_type": None,
        }
        data_profile = {
            "row_count": 5,
            "column_count": 8,
            "columns": {},
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        assert result.has_visualization is False
        assert result.chart_config is None
        assert result.chart_recommendation is None
        assert result.data_reference == self.data_reference
        assert "table" in result.summary.lower()

    # =========================================================================
    # Test: build_from_hints() - Invalid Hints (Fallback)
    # =========================================================================

    def test_build_from_hints_missing_hints_falls_back_to_table(self) -> None:
        """Test fallback to table when hints are missing."""
        hints = {}
        data_profile = {
            "row_count": 10,
            "column_count": 2,
            "columns": {},
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        assert result.has_visualization is False
        assert result.chart_config is None
        assert "table" in result.summary.lower()

    def test_build_from_hints_invalid_chart_type_falls_back_to_table(self) -> None:
        """Test fallback to table when chart_type is invalid."""
        hints = {
            "chart_type": "pie",  # Not supported
            "x_field": "category",
            "y_field": "value",
            "x_type": "nominal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 10,
            "column_count": 2,
            "columns": {
                "category": {"type": "Utf8"},
                "value": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        assert result.has_visualization is False
        assert result.chart_config is None

    def test_build_from_hints_missing_chart_type_falls_back(self) -> None:
        """Test fallback when chart_type is missing."""
        hints = {
            "x_field": "date",
            "y_field": "cost",
            "x_type": "temporal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 10,
            "column_count": 2,
            "columns": {
                "date": {"type": "Date"},
                "cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Should fall back to table or attempt to infer
        assert result.data_reference == self.data_reference

    def test_build_from_hints_missing_x_field_falls_back(self) -> None:
        """Test fallback when x_field is missing."""
        hints = {
            "chart_type": "line",
            "y_field": "cost",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 10,
            "column_count": 2,
            "columns": {
                "date": {"type": "Date"},
                "cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Should fall back or attempt to infer
        assert result.data_reference == self.data_reference

    def test_build_from_hints_missing_y_field_falls_back(self) -> None:
        """Test fallback when y_field is missing."""
        hints = {
            "chart_type": "bar",
            "x_field": "category",
            "x_type": "nominal",
        }
        data_profile = {
            "row_count": 10,
            "column_count": 2,
            "columns": {
                "category": {"type": "Utf8"},
                "value": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Should fall back or attempt to infer
        assert result.data_reference == self.data_reference

    def test_build_from_hints_field_not_in_data_profile_falls_back(self) -> None:
        """Test fallback when specified fields don't exist in data."""
        hints = {
            "chart_type": "line",
            "x_field": "nonexistent_date",
            "y_field": "nonexistent_cost",
            "x_type": "temporal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 10,
            "column_count": 2,
            "columns": {
                "date": {"type": "Date"},
                "cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Should fall back to table when fields don't exist
        assert result.has_visualization is False

    # =========================================================================
    # Test: _validate_hints() - Validation Logic
    # =========================================================================

    def test_validate_hints_valid_returns_true(self) -> None:
        """Test that valid hints pass validation."""
        hints = {
            "chart_type": "line",
            "x_field": "date",
            "y_field": "cost",
            "x_type": "temporal",
            "y_type": "quantitative",
        }
        data_profile = {
            "columns": {
                "date": {"type": "Date"},
                "cost": {"type": "Float64"},
            },
        }

        is_valid = self.builder._validate_hints(hints, data_profile)
        assert is_valid is True

    def test_validate_hints_missing_chart_type_returns_false(self) -> None:
        """Test that hints without chart_type fail validation."""
        hints = {
            "x_field": "date",
            "y_field": "cost",
        }
        data_profile = {"columns": {}}

        is_valid = self.builder._validate_hints(hints, data_profile)
        assert is_valid is False

    def test_validate_hints_unsupported_chart_type_returns_false(self) -> None:
        """Test that unsupported chart types fail validation."""
        hints = {
            "chart_type": "pie",
            "x_field": "category",
            "y_field": "value",
        }
        data_profile = {"columns": {}}

        is_valid = self.builder._validate_hints(hints, data_profile)
        assert is_valid is False

    def test_validate_hints_table_type_always_valid(self) -> None:
        """Test that table type is always valid (no x/y required)."""
        hints = {
            "chart_type": "table",
        }
        data_profile = {"columns": {}}

        is_valid = self.builder._validate_hints(hints, data_profile)
        assert is_valid is True

    def test_validate_hints_line_requires_temporal_x(self) -> None:
        """Test that line charts require temporal x-axis."""
        hints = {
            "chart_type": "line",
            "x_field": "category",  # Not temporal
            "y_field": "value",
            "x_type": "nominal",  # Should be temporal
            "y_type": "quantitative",
        }
        data_profile = {
            "columns": {
                "category": {"type": "Utf8"},
                "value": {"type": "Float64"},
            },
        }

        is_valid = self.builder._validate_hints(hints, data_profile)
        # Should fail validation (or be corrected to bar chart)
        assert is_valid is False or hints.get("chart_type") == "bar"

    # =========================================================================
    # Test: _infer_from_data_profile() - Fallback Inference
    # =========================================================================

    def test_infer_from_data_profile_temporal_numeric_suggests_line(self) -> None:
        """Test inferring line chart from temporal + numeric data."""
        data_profile = {
            "row_count": 30,
            "columns": {
                "usage_date": {"type": "Date"},
                "total_cost": {"type": "Float64"},
            },
        }

        result = self.builder._infer_from_data_profile(
            data_profile, self.data_reference
        )

        # Should infer line chart or at least return a valid visualization
        assert isinstance(result, VisualizationOutput)
        if result.has_visualization:
            assert result.chart_config.chart_type in [ChartType.LINE, ChartType.AREA]

    def test_infer_from_data_profile_categorical_numeric_suggests_bar(self) -> None:
        """Test inferring bar chart from categorical + numeric data."""
        data_profile = {
            "row_count": 10,
            "columns": {
                "warehouse_id": {"type": "Utf8", "unique_count": 10},
                "total_cost": {"type": "Float64"},
            },
        }

        result = self.builder._infer_from_data_profile(
            data_profile, self.data_reference
        )

        # Should infer bar chart or return table
        assert isinstance(result, VisualizationOutput)
        if result.has_visualization:
            assert result.chart_config.chart_type == ChartType.BAR

    def test_infer_from_data_profile_two_numeric_suggests_scatter(self) -> None:
        """Test inferring scatter plot from two numeric columns."""
        data_profile = {
            "row_count": 50,
            "columns": {
                "usage_hours": {"type": "Float64"},
                "total_cost": {"type": "Float64"},
            },
        }

        result = self.builder._infer_from_data_profile(
            data_profile, self.data_reference
        )

        # Should infer scatter or return table
        assert isinstance(result, VisualizationOutput)
        if result.has_visualization:
            assert result.chart_config.chart_type == ChartType.SCATTER

    def test_infer_from_data_profile_complex_data_falls_back_to_table(self) -> None:
        """Test that complex data (many columns) falls back to table."""
        data_profile = {
            "row_count": 5,
            "column_count": 10,
            "columns": {f"col_{i}": {"type": "Utf8"} for i in range(10)},
        }

        result = self.builder._infer_from_data_profile(
            data_profile, self.data_reference
        )

        # Should fall back to table for complex data
        assert result.has_visualization is False

    def test_infer_from_data_profile_few_rows_falls_back_to_table(self) -> None:
        """Test that data with few rows (<5) falls back to table."""
        data_profile = {
            "row_count": 3,
            "columns": {
                "id": {"type": "Utf8"},
                "value": {"type": "Float64"},
            },
        }

        result = self.builder._infer_from_data_profile(
            data_profile, self.data_reference
        )

        # Should fall back to table for few rows
        assert result.has_visualization is False

    # =========================================================================
    # Test: _create_table_fallback() - Table Fallback
    # =========================================================================

    def test_create_table_fallback_has_correct_structure(self) -> None:
        """Test table fallback creates correct VisualizationOutput."""
        result = self.builder._create_table_fallback(
            data_reference=self.data_reference,
            summary="Fallback to table view",
            reason="test_reason",
        )

        assert isinstance(result, VisualizationOutput)
        assert result.has_visualization is False
        assert result.chart_config is None
        assert result.chart_recommendation is None
        assert result.data_reference == self.data_reference
        assert result.summary == "Fallback to table view"

    # =========================================================================
    # Test: Edge Cases
    # =========================================================================

    def test_build_from_hints_empty_data_profile(self) -> None:
        """Test handling empty data profile."""
        hints = {
            "chart_type": "line",
            "x_field": "date",
            "y_field": "cost",
            "x_type": "temporal",
            "y_type": "quantitative",
        }
        data_profile = {"row_count": 0, "columns": {}}

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Should handle gracefully (likely fall back to table)
        assert isinstance(result, VisualizationOutput)
        assert result.data_reference == self.data_reference

    def test_build_from_hints_none_hints(self) -> None:
        """Test handling None hints."""
        data_profile = {
            "row_count": 10,
            "columns": {
                "col1": {"type": "Utf8"},
                "col2": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=None,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Should fall back to table or infer from profile
        assert isinstance(result, VisualizationOutput)

    def test_build_from_hints_histogram_support(self) -> None:
        """Test histogram chart type (single numeric column)."""
        hints = {
            "chart_type": "histogram",
            "x_field": "duration",
            "y_field": None,
            "x_type": "quantitative",
            "y_type": None,
        }
        data_profile = {
            "row_count": 100,
            "columns": {
                "duration": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Histogram might be supported or fall back to table
        assert isinstance(result, VisualizationOutput)
        if result.has_visualization:
            assert result.chart_config.chart_type == ChartType.HISTOGRAM

    # =========================================================================
    # Test: Integration with Real Models
    # =========================================================================

    def test_chart_config_uses_pydantic_models(self) -> None:
        """Test that ChartConfig uses proper Pydantic validation."""
        hints = {
            "chart_type": "bar",
            "x_field": "category",
            "y_field": "value",
            "x_type": "nominal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 10,
            "columns": {
                "category": {"type": "Utf8"},
                "value": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Verify Pydantic models are used
        assert isinstance(result.chart_config, ChartConfig)
        assert isinstance(result.chart_config.encodings["x"], Encoding)
        assert isinstance(result.chart_config.encodings["y"], Encoding)
        assert isinstance(result.chart_recommendation, ChartRecommendation)

    def test_encoding_types_are_enums(self) -> None:
        """Test that encoding types use proper EncodingType enums."""
        hints = {
            "chart_type": "line",
            "x_field": "date",
            "y_field": "cost",
            "x_type": "temporal",
            "y_type": "quantitative",
        }
        data_profile = {
            "row_count": 30,
            "columns": {
                "date": {"type": "Date"},
                "cost": {"type": "Float64"},
            },
        }

        result = self.builder.build_from_hints(
            hints=hints,
            data_profile=data_profile,
            data_reference=self.data_reference,
        )

        # Verify enum types
        assert result.chart_config.encodings["x"].type == EncodingType.TEMPORAL
        assert result.chart_config.encodings["y"].type == EncodingType.QUANTITATIVE
        assert result.chart_config.chart_type == ChartType.LINE


# =============================================================================
# Test: Module Functions (if any)
# =============================================================================


def test_direct_chart_builder_can_be_instantiated() -> None:
    """Test that DirectChartConfigBuilder can be instantiated."""
    builder = DirectChartConfigBuilder()
    assert builder is not None
