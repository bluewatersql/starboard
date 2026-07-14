# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Domain models for data visualization.

This module defines models for LLM-driven visualization with query catalog guardrails.
All chart configurations follow Vega-Lite semantics for encoding types and chart types.

Models:
    - Encoding: Single encoding specification (x, y, color, etc.)
    - ChartConfig: Complete chart configuration (Pydantic validated)
    - ChartRecommendation: LLM's reasoning for chart selection
    - VisualizationInput: Input to VisualizationService
    - VisualizationOutput: Output from VisualizationService

Design Principles:
    - Pydantic models at boundaries (external validation)
    - Frozen dataclasses for immutability
    - Type-safe enums for chart/encoding types
    - Schema enforces query catalog constraints
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from starboard_core.domain.models.analytics import QueryMetadata


class EncodingType(StrEnum):
    """Vega-Lite encoding types.

    Maps semantic data types to visual encoding types:
        - QUANTITATIVE: Numeric metrics (cost, count, duration)
        - NOMINAL: Categorical dimensions (job_id, cluster_name)
        - ORDINAL: Ordered categories (priority: low/medium/high)
        - TEMPORAL: Time/date fields (usage_date, timestamp)
    """

    QUANTITATIVE = "quantitative"
    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    TEMPORAL = "temporal"


class ChartType(StrEnum):
    """Supported chart types.

    Aligned with Vega-Lite mark types and query catalog chart_metadata.
    Each type maps to specific encoding requirements:
        - BAR: Compare categorical values (x: nominal, y: quantitative)
        - LINE: Show trends over time (x: temporal, y: quantitative)
        - AREA: Emphasize magnitude trends (x: temporal, y: quantitative)
        - SCATTER: Show correlations (x: quantitative, y: quantitative)
        - HISTOGRAM: Show distribution (x: quantitative)
        - TABLE: Raw data display (no encodings required)
    """

    BAR = "bar"
    LINE = "line"
    AREA = "area"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    TABLE = "table"


class Encoding(BaseModel):
    """Single encoding specification for a visual channel.

    Encodings map data fields to visual properties (x-axis, y-axis, color, etc.).
    Type determines how data is interpreted and scaled.

    Attributes:
        field: Column name from the data
        type: Encoding type (quantitative, nominal, ordinal, temporal)
        title: Human-readable axis/legend label (optional)
        sort: Sort order for the field (optional: "ascending", "descending", or field name)
        aggregate: Aggregation function (optional: "sum", "mean", "count", "min", "max")

    Examples:
        >>> # Quantitative y-axis
        >>> Encoding(field="list_cost", type=EncodingType.QUANTITATIVE, title="Cost ($)")

        >>> # Nominal x-axis with sort
        >>> Encoding(field="job_id", type=EncodingType.NOMINAL, sort="descending")

        >>> # Temporal x-axis
        >>> Encoding(field="usage_date", type=EncodingType.TEMPORAL, title="Date")

        >>> # Y-axis with aggregation
        >>> Encoding(field="total_cost", type=EncodingType.QUANTITATIVE, aggregate="sum")
    """

    field: str = Field(..., description="Column name from the data")
    type: EncodingType = Field(
        ..., description="Encoding type (quantitative, nominal, ordinal, temporal)"
    )
    title: str | None = Field(None, description="Human-readable label for axis/legend")
    sort: str | None = Field(
        None,
        description="Sort order: 'ascending', 'descending', or field name to sort by",
    )
    aggregate: str | None = Field(
        None,
        description="Aggregation function: 'sum', 'mean', 'count', 'min', 'max', etc.",
    )

    model_config = ConfigDict(
        use_enum_values=True,  # Serialize enums as strings
        frozen=False,  # Allow mutation for builder pattern if needed
        extra="ignore",  # Ignore extra fields (allows flexibility from LLM)
    )


class ChartConfig(BaseModel):
    """Complete chart configuration (Vega-Lite-inspired).

    Declarative specification of a chart that can be rendered by ChartRenderer.
    Validated against query catalog constraints (allowed_chart_types).

    Attributes:
        chart_type: Type of chart (bar, line, area, scatter, histogram, table)
        title: Chart title
        encodings: Visual encodings (x, y, color, size, etc.)
        options: Chart-specific options (e.g., interpolation, stacking)

    Validation:
        - No extra fields allowed (forbid mode)
        - Encoding field names must exist in data (validated post-LLM)
        - Encoding types must match semantic types (validated post-LLM)

    Examples:
        >>> # Bar chart comparing costs
        >>> ChartConfig(
        ...     chart_type=ChartType.BAR,
        ...     title="Top 10 Jobs by Cost",
        ...     encodings={
        ...         "x": Encoding(field="job_id", type=EncodingType.NOMINAL),
        ...         "y": Encoding(field="list_cost", type=EncodingType.QUANTITATIVE),
        ...     },
        ... )

        >>> # Line chart with options
        >>> ChartConfig(
        ...     chart_type=ChartType.LINE,
        ...     title="Cost Trend",
        ...     encodings={
        ...         "x": Encoding(field="date", type=EncodingType.TEMPORAL),
        ...         "y": Encoding(field="cost", type=EncodingType.QUANTITATIVE),
        ...     },
        ...     options={"interpolate": "monotone", "point": True},
        ... )
    """

    chart_type: ChartType = Field(..., description="Type of chart to render")
    title: str = Field(..., description="Chart title")
    description: str | None = Field(
        None, description="Chart description (provides context)"
    )
    encodings: dict[str, Encoding] = Field(
        default_factory=dict,
        description="Visual encodings (x, y, color, size, etc.)",
    )
    options: dict[str, Any] | None = Field(
        None,
        description="Chart-specific options (e.g., sort, interpolate, stacking)",
    )

    model_config = ConfigDict(
        use_enum_values=True,
        extra="forbid",  # No extra fields allowed (strict validation)
        frozen=False,
    )

    @field_validator("encodings", mode="before")
    @classmethod
    def validate_encodings_dict(cls, v: Any) -> dict[str, Encoding]:
        """Ensure encodings is a dict with Encoding values."""
        if not isinstance(v, dict):
            raise ValueError("encodings must be a dictionary")

        # Convert dict values to Encoding if they're dicts
        result = {}
        for key, value in v.items():
            if isinstance(value, dict):
                result[key] = Encoding(**value)
            elif isinstance(value, Encoding):
                result[key] = value
            else:
                raise ValueError(
                    f"Invalid encoding value for '{key}': must be dict or Encoding"
                )

        return result


@dataclass(frozen=True)
class ChartRecommendation:
    """LLM's reasoning for chart selection.

    Captures the LLM's decision-making process for transparency and debugging.
    Used for observability and user explanations.

    Attributes:
        chart_type: Recommended chart type
        reasoning: Natural language explanation of why this chart was chosen
        confidence: Confidence score 0.0-1.0 (optional, defaults to 1.0)

    Examples:
        >>> ChartRecommendation(
        ...     chart_type=ChartType.BAR,
        ...     reasoning="Comparing costs across 10 jobs - bar chart effectively shows ranking",
        ...     confidence=0.95,
        ... )
    """

    chart_type: ChartType
    reasoning: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        """Validate confidence is in range [0.0, 1.0]."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")


@dataclass(frozen=True)
class VisualizationInput:
    """Input to VisualizationService.

    Contains all data needed for LLM to generate chart config:
        - Query metadata (guardrails from catalog)
        - Data profile (statistics, samples)
        - Data reference (for caching)

    Attributes:
        query_metadata: Query catalog metadata (name, description, chart_metadata, etc.)
        data_profile: Statistical profile from DataProfiler (numeric_stats, categorical_stats, etc.)
        data_reference: Unique key for cached query results

    Examples:
        >>> VisualizationInput(
        ...     query_metadata=QueryMetadata(...),
        ...     data_profile={
        ...         "row_count": 10,
        ...         "columns": [...],
        ...         "numeric_stats": {"list_cost": {...}},
        ...     },
        ...     data_reference="data_ref_abc123",
        ... )
    """

    query_metadata: QueryMetadata
    data_profile: dict[str, Any]
    data_reference: str


@dataclass(frozen=True)
class VisualizationOutput:
    """Output from VisualizationService.

    Contains LLM-generated natural language summary and validated chart config.
    Includes data_reference for frontend to fetch raw data.

    Attributes:
        summary: Natural language summary of the data (2-3 sentences)
        chart_recommendation: LLM's reasoning for chart selection (may be None if table-only)
        chart_config: Validated chart configuration (may be None if visualization failed)
        data_reference: Unique key for cached query results
        has_visualization: Whether a chart is available (False for table-only)

    Examples:
        >>> # With chart
        >>> VisualizationOutput(
        ...     summary="The top 10 jobs consumed $3,544.21 in total...",
        ...     chart_recommendation=ChartRecommendation(...),
        ...     chart_config=ChartConfig(...),
        ...     data_reference="data_ref_abc",
        ...     has_visualization=True,
        ... )

        >>> # Table only (no chart)
        >>> VisualizationOutput(
        ...     summary="Data retrieved successfully. See table below.",
        ...     chart_recommendation=None,
        ...     chart_config=None,
        ...     data_reference="data_ref_xyz",
        ...     has_visualization=False,
        ... )
    """

    summary: str
    chart_recommendation: ChartRecommendation | None
    chart_config: ChartConfig | None
    data_reference: str
    has_visualization: bool
