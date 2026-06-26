# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for visualization models.

Following TDD: These tests define the expected behavior of visualization models
before implementation. Tests should cover:
- Model creation and validation
- Pydantic schema validation
- Field constraints and types
- Serialization/deserialization
- Edge cases and error handling

Target Coverage: ≥80%
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from starboard_server.tools.domain.analytics.visualization_models import (
    ChartConfig,
    ChartRecommendation,
    ChartType,
    Encoding,
    EncodingType,
    VisualizationInput,
    VisualizationOutput,
)


class TestEncoding:
    """Test suite for Encoding model."""

    def test_encoding_creation_valid(self):
        """Test creating a valid Encoding."""
        encoding = Encoding(
            field="job_id",
            type=EncodingType.NOMINAL,
            title="Job ID",
            sort="ascending",
        )

        assert encoding.field == "job_id"
        assert encoding.type == EncodingType.NOMINAL
        assert encoding.title == "Job ID"
        assert encoding.sort == "ascending"

    def test_encoding_minimal_fields(self):
        """Test Encoding with only required fields."""
        encoding = Encoding(
            field="cost",
            type=EncodingType.QUANTITATIVE,
        )

        assert encoding.field == "cost"
        assert encoding.type == EncodingType.QUANTITATIVE
        assert encoding.title is None
        assert encoding.sort is None

    def test_encoding_invalid_type(self):
        """Test Encoding rejects invalid encoding type."""
        with pytest.raises(ValidationError) as exc_info:
            Encoding(field="test", type="invalid_type")  # type: ignore

        assert "type" in str(exc_info.value).lower()

    def test_encoding_serialization(self):
        """Test Encoding can be serialized to dict."""
        encoding = Encoding(
            field="list_cost",
            type=EncodingType.QUANTITATIVE,
            title="List Cost ($)",
        )

        data = encoding.model_dump()
        assert data["field"] == "list_cost"
        assert data["type"] == "quantitative"
        assert data["title"] == "List Cost ($)"

    def test_encoding_deserialization(self):
        """Test Encoding can be deserialized from dict."""
        data = {
            "field": "job_name",
            "type": "nominal",
            "title": "Job Name",
            "sort": "descending",
        }

        encoding = Encoding(**data)
        assert encoding.field == "job_name"
        assert encoding.type == EncodingType.NOMINAL


class TestChartConfig:
    """Test suite for ChartConfig model."""

    def test_chartconfig_creation_valid(self):
        """Test creating a valid ChartConfig."""
        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Top 10 Jobs by Cost",
            encodings={
                "x": Encoding(field="job_id", type=EncodingType.NOMINAL),
                "y": Encoding(field="list_cost", type=EncodingType.QUANTITATIVE),
            },
        )

        assert config.chart_type == ChartType.BAR
        assert config.title == "Top 10 Jobs by Cost"
        assert "x" in config.encodings
        assert "y" in config.encodings
        assert config.options is None

    def test_chartconfig_with_options(self):
        """Test ChartConfig with chart-specific options."""
        config = ChartConfig(
            chart_type=ChartType.LINE,
            title="Cost Trend",
            encodings={
                "x": Encoding(field="date", type=EncodingType.TEMPORAL),
                "y": Encoding(field="cost", type=EncodingType.QUANTITATIVE),
            },
            options={
                "interpolate": "monotone",
                "point": True,
            },
        )

        assert config.options == {"interpolate": "monotone", "point": True}

    def test_chartconfig_invalid_chart_type(self):
        """Test ChartConfig rejects invalid chart type."""
        with pytest.raises(ValidationError) as exc_info:
            ChartConfig(
                chart_type="invalid",  # type: ignore
                title="Test",
                encodings={},
            )

        assert "chart_type" in str(exc_info.value).lower()

    def test_chartconfig_empty_encodings(self):
        """Test ChartConfig allows empty encodings (for table type)."""
        config = ChartConfig(
            chart_type=ChartType.TABLE,
            title="Data Table",
            encodings={},
        )

        assert config.chart_type == ChartType.TABLE
        assert config.encodings == {}

    def test_chartconfig_no_extra_fields(self):
        """Test ChartConfig rejects extra fields (Pydantic forbid)."""
        with pytest.raises(ValidationError) as exc_info:
            ChartConfig(
                chart_type=ChartType.BAR,
                title="Test",
                encodings={},
                invalid_field="should_fail",  # type: ignore
            )

        # Pydantic v2 uses "extra inputs are not permitted"
        assert (
            "extra" in str(exc_info.value).lower()
            and "not permitted" in str(exc_info.value).lower()
        )

    def test_chartconfig_serialization(self):
        """Test ChartConfig serialization preserves nested Encoding."""
        config = ChartConfig(
            chart_type=ChartType.SCATTER,
            title="Job Cost vs Runtime",
            encodings={
                "x": Encoding(field="runtime", type=EncodingType.QUANTITATIVE),
                "y": Encoding(field="cost", type=EncodingType.QUANTITATIVE),
                "color": Encoding(field="cluster", type=EncodingType.NOMINAL),
            },
        )

        data = config.model_dump()
        assert data["chart_type"] == "scatter"
        assert len(data["encodings"]) == 3
        assert data["encodings"]["x"]["field"] == "runtime"


class TestChartRecommendation:
    """Test suite for ChartRecommendation model."""

    def test_chartrecommendation_creation(self):
        """Test creating a ChartRecommendation."""
        rec = ChartRecommendation(
            chart_type=ChartType.BAR,
            reasoning="Comparing costs across 10 jobs - bar chart shows ranking effectively",
            confidence=0.95,
        )

        assert rec.chart_type == ChartType.BAR
        assert "ranking" in rec.reasoning
        assert rec.confidence == 0.95

    def test_chartrecommendation_default_confidence(self):
        """Test ChartRecommendation defaults confidence to 1.0."""
        rec = ChartRecommendation(
            chart_type=ChartType.LINE,
            reasoning="Time series data",
        )

        assert rec.confidence == 1.0

    def test_chartrecommendation_confidence_bounds(self):
        """Test ChartRecommendation validates confidence bounds."""
        # Valid: 0.0 to 1.0
        rec1 = ChartRecommendation(
            chart_type=ChartType.BAR,
            reasoning="Test",
            confidence=0.0,
        )
        assert rec1.confidence == 0.0

        rec2 = ChartRecommendation(
            chart_type=ChartType.BAR,
            reasoning="Test",
            confidence=1.0,
        )
        assert rec2.confidence == 1.0

        # Invalid: outside bounds (dataclass raises ValueError from __post_init__)
        with pytest.raises(ValueError) as exc_info:
            ChartRecommendation(
                chart_type=ChartType.BAR,
                reasoning="Test",
                confidence=1.5,  # type: ignore
            )
        assert "confidence" in str(exc_info.value).lower()


class TestVisualizationInput:
    """Test suite for VisualizationInput model."""

    def test_visualizationinput_creation(self):
        """Test creating a VisualizationInput."""
        from starboard_core.domain.models.analytics import QueryMetadata

        query_metadata = QueryMetadata(
            id="test-123",
            name="Test Query",
            description="Test description",
            long_description="Long description",
            descriptive_name="Descriptive name",
            domains=["FinOps"],
            scenarios=["test"],
            constraints=[],
            parameters=[],
            dependencies=[],
            tables=["system.billing.usage"],
            query="SELECT 1",
            required_parameters={},
            result_columns=[],
            chart_metadata={
                "allowed_chart_types": ["bar"],
                "primary_metric": "cost",
            },
        )

        data_profile = {
            "row_count": 10,
            "columns": [],
            "numeric_stats": {},
        }

        viz_input = VisualizationInput(
            query_metadata=query_metadata,
            data_profile=data_profile,
            data_reference="data_ref_abc123",
        )

        assert viz_input.query_metadata.id == "test-123"
        assert viz_input.data_profile["row_count"] == 10
        assert viz_input.data_reference == "data_ref_abc123"

    def test_visualizationinput_immutable(self):
        """Test VisualizationInput is immutable (frozen)."""
        from starboard_core.domain.models.analytics import QueryMetadata

        query_metadata = QueryMetadata(
            id="test-123",
            name="Test",
            description="Test",
            long_description="Test",
            descriptive_name="Test",
            domains=[],
            scenarios=[],
            constraints=[],
            parameters=[],
            dependencies=[],
            tables=[],
            query="SELECT 1",
            required_parameters={},
            result_columns=[],
            chart_metadata={},
        )

        viz_input = VisualizationInput(
            query_metadata=query_metadata,
            data_profile={},
            data_reference="ref123",
        )

        with pytest.raises(AttributeError):
            viz_input.data_reference = "new_ref"  # type: ignore


class TestVisualizationOutput:
    """Test suite for VisualizationOutput model."""

    def test_visualizationoutput_with_chart(self):
        """Test VisualizationOutput with chart config."""
        recommendation = ChartRecommendation(
            chart_type=ChartType.BAR,
            reasoning="Test reasoning",
        )

        chart_config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Test Chart",
            encodings={
                "x": Encoding(field="x", type=EncodingType.NOMINAL),
                "y": Encoding(field="y", type=EncodingType.QUANTITATIVE),
            },
        )

        output = VisualizationOutput(
            summary="Test summary of the data",
            chart_recommendation=recommendation,
            chart_config=chart_config,
            data_reference="data_ref_xyz",
            has_visualization=True,
        )

        assert output.summary == "Test summary of the data"
        assert output.chart_recommendation is not None
        assert output.chart_config is not None
        assert output.data_reference == "data_ref_xyz"
        assert output.has_visualization is True

    def test_visualizationoutput_without_chart(self):
        """Test VisualizationOutput without chart (table only)."""
        output = VisualizationOutput(
            summary="Data retrieved successfully. See table below.",
            chart_recommendation=None,
            chart_config=None,
            data_reference="data_ref_table",
            has_visualization=False,
        )

        assert output.chart_recommendation is None
        assert output.chart_config is None
        assert output.has_visualization is False

    def test_visualizationoutput_immutable(self):
        """Test VisualizationOutput is immutable (frozen)."""
        output = VisualizationOutput(
            summary="Test",
            chart_recommendation=None,
            chart_config=None,
            data_reference="ref",
            has_visualization=False,
        )

        with pytest.raises(AttributeError):
            output.summary = "New summary"  # type: ignore


class TestEncodingType:
    """Test suite for EncodingType enum."""

    def test_encodingtype_values(self):
        """Test all EncodingType enum values exist."""
        assert EncodingType.QUANTITATIVE == "quantitative"
        assert EncodingType.NOMINAL == "nominal"
        assert EncodingType.ORDINAL == "ordinal"
        assert EncodingType.TEMPORAL == "temporal"

    def test_encodingtype_membership(self):
        """Test EncodingType membership checks."""
        assert "quantitative" in [e.value for e in EncodingType]
        assert "nominal" in [e.value for e in EncodingType]
        assert "invalid" not in [e.value for e in EncodingType]


class TestChartType:
    """Test suite for ChartType enum."""

    def test_charttype_values(self):
        """Test all ChartType enum values exist."""
        assert ChartType.BAR == "bar"
        assert ChartType.LINE == "line"
        assert ChartType.AREA == "area"
        assert ChartType.SCATTER == "scatter"
        assert ChartType.HISTOGRAM == "histogram"
        assert ChartType.TABLE == "table"

    def test_charttype_membership(self):
        """Test ChartType membership checks."""
        chart_types = [e.value for e in ChartType]
        assert "bar" in chart_types
        assert "line" in chart_types
        assert "table" in chart_types
        assert "pie" not in chart_types  # Not supported


class TestIntegration:
    """Integration tests for visualization models working together."""

    def test_complete_visualization_flow(self):
        """Test complete flow from input to output."""
        from starboard_core.domain.models.analytics import QueryMetadata

        # 1. Create input
        query_metadata = QueryMetadata(
            id="b733352d-a70c-452b-9890-16488d4a8ca6",
            name="Top 10 Most Expensive Jobs",
            description="Identify highest cost jobs",
            long_description="Detailed cost analysis",
            descriptive_name="Cost Analysis",
            domains=["FinOps", "Job"],
            scenarios=["cost optimization"],
            constraints=[],
            parameters=["start_date", "end_date"],
            dependencies=[],
            tables=["system.billing.usage"],
            query="SELECT job_id, SUM(list_cost) as total_cost FROM ...",
            required_parameters={
                "start_date": {"type": "date", "description": "Start date"},
                "end_date": {"type": "date", "description": "End date"},
            },
            result_columns=[
                {"name": "job_id", "type": "string", "semantic_type": "dimension"},
                {"name": "total_cost", "type": "float", "semantic_type": "metric"},
            ],
            chart_metadata={
                "allowed_chart_types": ["bar", "table"],
                "primary_metric": "total_cost",
                "primary_dimension": "job_id",
                "suggested_encodings": {
                    "x": {"field": "job_id", "type": "nominal"},
                    "y": {"field": "total_cost", "type": "quantitative"},
                },
            },
        )

        data_profile = {
            "row_count": 10,
            "columns": [
                {"name": "job_id", "dtype": "Utf8", "semantic_type": "dimension"},
                {"name": "total_cost", "dtype": "Float64", "semantic_type": "metric"},
            ],
            "numeric_stats": {
                "total_cost": {
                    "sum": 3544.21,
                    "mean": 354.42,
                    "min": 45.67,
                    "max": 1234.56,
                }
            },
        }

        viz_input = VisualizationInput(
            query_metadata=query_metadata,
            data_profile=data_profile,
            data_reference="data_ref_test123",
        )

        # 2. Create recommendation
        recommendation = ChartRecommendation(
            chart_type=ChartType.BAR,
            reasoning="Comparing costs across 10 jobs - bar chart shows ranking",
            confidence=0.95,
        )

        # 3. Create chart config
        chart_config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Top 10 Most Expensive Jobs",
            encodings={
                "x": Encoding(field="job_id", type=EncodingType.NOMINAL),
                "y": Encoding(
                    field="total_cost",
                    type=EncodingType.QUANTITATIVE,
                    title="Total Cost ($)",
                ),
            },
            options={"sort": {"field": "total_cost", "order": "descending"}},
        )

        # 4. Create output
        output = VisualizationOutput(
            summary="The top 10 jobs consumed $3,544.21 in total DBU costs.",
            chart_recommendation=recommendation,
            chart_config=chart_config,
            data_reference="data_ref_test123",
            has_visualization=True,
        )

        # Verify complete flow
        assert viz_input.query_metadata.id == query_metadata.id
        assert viz_input.data_reference == output.data_reference
        assert output.chart_config.chart_type == recommendation.chart_type
        assert output.has_visualization is True

    def test_chart_config_json_serialization(self):
        """Test ChartConfig can be serialized to JSON for API responses."""
        import json

        config = ChartConfig(
            chart_type=ChartType.LINE,
            title="Cost Trend Over Time",
            encodings={
                "x": Encoding(field="date", type=EncodingType.TEMPORAL),
                "y": Encoding(field="cost", type=EncodingType.QUANTITATIVE),
            },
        )

        # Serialize to JSON
        json_str = config.model_dump_json()
        data = json.loads(json_str)

        assert data["chart_type"] == "line"
        assert data["encodings"]["x"]["field"] == "date"
        assert data["encodings"]["x"]["type"] == "temporal"

        # Deserialize from JSON
        config_restored = ChartConfig.model_validate_json(json_str)
        assert config_restored.chart_type == ChartType.LINE
        assert config_restored.encodings["x"].field == "date"
