"""DirectChartConfigBuilder - Build chart configs deterministically from LLM hints.

This module provides a simplified approach to visualization configuration that
eliminates the need for a second LLM call. It uses hints generated during SQL
creation to build ChartConfig directly, with fallbacks for edge cases.

Design Principles:
    - Trust the SQL generator LLM (it already saw the query structure)
    - Deterministic logic (same inputs → same outputs)
    - Graceful fallback to table view
    - Simple rules over complex prompts

Architecture:
    1. Validate hints from SQL generator
    2. If valid → build ChartConfig deterministically
    3. If invalid → infer from data profile
    4. Ultimate fallback → table view
"""

from __future__ import annotations

from typing import Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.analytics.visualization_models import (
    ChartConfig,
    ChartRecommendation,
    ChartType,
    Encoding,
    EncodingType,
    VisualizationOutput,
)

logger = get_logger(__name__)

# Supported chart types (aligned with ChartType enum)
SUPPORTED_CHART_TYPES = {
    "bar",
    "line",
    "area",
    "scatter",
    "histogram",
    "table",
}

# Chart types that require temporal x-axis
TEMPORAL_CHART_TYPES = {"line", "area"}


class DirectChartConfigBuilder:
    """Build ChartConfig directly from LLM hints without second LLM call.

    This builder eliminates the duplicate LLM call for visualization by using
    the hints generated during SQL creation. It provides deterministic chart
    configuration with graceful fallbacks.
    """

    def build_from_hints(
        self,
        hints: dict[str, Any] | None,
        data_profile: dict[str, Any],
        data_reference: str,
    ) -> VisualizationOutput:
        """Build VisualizationOutput from SQL generator hints.

        Fallback chain:
        1. Use LLM hints if valid
        2. Infer from data profile if hints invalid
        3. Table fallback if uncertain

        Args:
            hints: Simplified visualization hints from SQL generator with fields:
                - chart_type: str (bar|line|area|scatter|histogram|table)
                - x_field: str (column name for x-axis)
                - y_field: str (column name for y-axis)
                - x_type: str (temporal|nominal|ordinal|quantitative)
                - y_type: str (quantitative|nominal|ordinal|temporal)
            data_profile: Data profile with columns, row_count, etc.
            data_reference: Cache key for query results

        Returns:
            VisualizationOutput with chart_config or table fallback
        """
        # Handle None or empty hints
        if not hints:
            logger.warning(
                "visualization_hints_missing",
                data_reference=data_reference,
            )
            return self._infer_from_data_profile(data_profile, data_reference)

        # Validate hints
        if not self._validate_hints(hints, data_profile):
            # Check if hints had chart_type and fields but they were invalid
            # If so, don't infer (LLM gave explicit guidance, just wrong)
            # If hints were incomplete, we can try to infer
            chart_type = hints.get("chart_type")
            has_fields = hints.get("x_field") or hints.get("y_field")

            if chart_type and has_fields:
                # Explicit hints were provided but invalid (wrong fields, wrong types, etc.)
                # Don't infer - this could show wrong data
                logger.warning(
                    "visualization_hints_invalid_explicit",
                    hints=hints,
                    data_reference=data_reference,
                )
                return self._create_table_fallback(
                    data_reference=data_reference,
                    summary="Unable to create requested visualization due to invalid field references. Showing table view.",
                    reason="invalid_field_references",
                )
            else:
                # Hints were incomplete, try to infer
                logger.warning(
                    "visualization_hints_incomplete",
                    hints=hints,
                    data_reference=data_reference,
                )
                return self._infer_from_data_profile(data_profile, data_reference)

        # Extract hint fields
        chart_type = hints.get("chart_type")

        # Handle explicit table request
        if chart_type == "table":
            return self._create_table_fallback(
                data_reference=data_reference,
                summary="Data displayed in table format as requested.",
                reason="explicit_table_request",
            )

        # Build chart config from hints
        try:
            chart_config = self._create_chart_config(hints, data_profile)
            chart_recommendation = self._create_chart_recommendation(hints)
            summary = self._create_summary(hints, data_profile)

            logger.debug(
                "chart_config_built_from_hints",
                chart_type=chart_type,
                data_reference=data_reference,
            )

            return VisualizationOutput(
                summary=summary,
                chart_recommendation=chart_recommendation,
                chart_config=chart_config,
                data_reference=data_reference,
                has_visualization=True,
            )

        except Exception as e:
            logger.error(
                "chart_config_build_error",
                error=str(e),
                hints=hints,
                data_reference=data_reference,
            )
            return self._create_table_fallback(
                data_reference=data_reference,
                summary=f"Unable to create chart: {str(e)}. Showing table view.",
                reason="builder_error",
            )

    def _validate_hints(
        self, hints: dict[str, Any], data_profile: dict[str, Any]
    ) -> bool:
        """Validate hints are sufficient to build a chart.

        Args:
            hints: Hints from SQL generator
            data_profile: Data profile with column information

        Returns:
            True if hints are valid, False otherwise

        Validation rules:
            - chart_type must be present and supported
            - table type always valid (no other fields required)
            - Other types require x_field, y_field (except histogram)
            - Fields must exist in data_profile columns
            - Line/area charts require temporal x-axis
        """
        # Check chart_type presence
        chart_type = hints.get("chart_type")
        if not chart_type:
            return False

        # Check if chart_type is supported
        if chart_type not in SUPPORTED_CHART_TYPES:
            return False

        # Table type is always valid
        if chart_type == "table":
            return True

        # Histogram only needs x_field
        if chart_type == "histogram":
            x_field = hints.get("x_field")
            if not x_field:
                return False
            column_names = self._extract_column_names(data_profile)
            return x_field in column_names

        # Other chart types need both x and y fields
        x_field = hints.get("x_field")
        y_field = hints.get("y_field")
        if not x_field or not y_field:
            return False

        # Check fields exist in data
        column_names = self._extract_column_names(data_profile)
        if x_field not in column_names or y_field not in column_names:
            return False

        # Validate temporal constraint for line/area charts
        if chart_type in TEMPORAL_CHART_TYPES:
            x_type = hints.get("x_type", "")
            # If x_type is not temporal, allow quantitative for area charts
            # (cumulative data over numeric sequence)
            if chart_type == "line" and x_type != "temporal":
                return False
            # Area charts can use temporal or quantitative (for cumulative series)
            if chart_type == "area" and x_type not in ["temporal", "quantitative"]:
                return False

        return True

    def _extract_column_names(self, data_profile: dict[str, Any]) -> set[str]:
        """Extract column names from data profile.

        Handles different profile formats:
        - columns as list of dicts with 'name' key: [{"name": "col1", ...}, ...]
        - columns as dict with column names as keys: {"col1": {...}, ...}
        - columns as simple list: ["col1", "col2", ...]

        Args:
            data_profile: Data profile dictionary

        Returns:
            Set of column names
        """
        columns = data_profile.get("columns", [])

        # Handle list of dicts (e.g., from profile_dataframe)
        if isinstance(columns, list) and columns and isinstance(columns[0], dict):
            return {col.get("name", "") for col in columns if "name" in col}

        # Handle dict (e.g., legacy format)
        if isinstance(columns, dict):
            return set(columns.keys())

        # Handle simple list
        if isinstance(columns, list):
            return set(columns)

        return set()

    def _infer_from_data_profile(
        self, data_profile: dict[str, Any], data_reference: str
    ) -> VisualizationOutput:
        """Infer chart type from data profile characteristics.

        Inference rules:
        1. Few rows (<5) → table
        2. Many columns (>5) → table
        3. 1 temporal + 1 numeric → line chart
        4. 1 categorical + 1 numeric (low cardinality) → bar chart
        5. 2 numeric columns → scatter plot
        6. Default → table

        Args:
            data_profile: Data profile with columns, row_count
            data_reference: Cache key for query results

        Returns:
            VisualizationOutput with inferred chart or table
        """
        row_count = data_profile.get("row_count", 0)
        columns = data_profile.get("columns", [])

        # Get column metadata - columns can be list of dicts or dict
        if isinstance(columns, list) and columns and isinstance(columns[0], dict):
            # Format: [{"name": "col1", "type": "...", ...}, ...]
            column_count = len(columns)
            columns_dict = {col["name"]: col for col in columns if "name" in col}
        elif isinstance(columns, dict):
            # Format: {"col1": {...}, "col2": {...}}
            column_count = len(columns)
            columns_dict = columns
        else:
            # Unknown format - fallback to table
            column_count = len(columns) if isinstance(columns, list) else 0
            columns_dict = {}

        # Rule 1: Few rows → table
        if row_count < 5:
            return self._create_table_fallback(
                data_reference=data_reference,
                summary=f"Dataset has only {row_count} rows. Displaying in table format.",
                reason="few_rows",
            )

        # Rule 2: Many columns → table
        if column_count > 5:
            return self._create_table_fallback(
                data_reference=data_reference,
                summary=f"Dataset has {column_count} columns. Displaying in table format.",
                reason="many_columns",
            )

        # Categorize columns by type
        temporal_cols = []
        numeric_cols = []
        categorical_cols = []

        for col_name, col_meta in columns_dict.items():
            col_type = col_meta.get("type", "") if isinstance(col_meta, dict) else ""
            if col_type in ["Date", "Timestamp", "datetime64[ns]"]:
                temporal_cols.append(col_name)
            elif col_type in [
                "Float64",
                "Int64",
                "float64",
                "int64",
                "Int32",
                "Float32",
                "Decimal",
            ]:
                numeric_cols.append(col_name)
            elif col_type in ["Utf8", "str", "string", "object", "String"]:
                categorical_cols.append(col_name)

        # Rule 3: Temporal + numeric → line chart
        if len(temporal_cols) == 1 and len(numeric_cols) >= 1:
            hints = {
                "chart_type": "line",
                "x_field": temporal_cols[0],
                "y_field": numeric_cols[0],
                "x_type": "temporal",
                "y_type": "quantitative",
            }
            return self.build_from_hints(hints, data_profile, data_reference)

        # Rule 4: Categorical + numeric (low cardinality) → bar chart
        if len(categorical_cols) == 1 and len(numeric_cols) >= 1:
            cat_col = categorical_cols[0]
            unique_count = (
                columns_dict[cat_col].get("unique_count", 999)
                if isinstance(columns_dict[cat_col], dict)
                else 999
            )
            if unique_count <= 20:  # Low cardinality
                hints = {
                    "chart_type": "bar",
                    "x_field": cat_col,
                    "y_field": numeric_cols[0],
                    "x_type": "nominal",
                    "y_type": "quantitative",
                }
                return self.build_from_hints(hints, data_profile, data_reference)

        # Rule 5: Two numeric columns → scatter plot
        if len(numeric_cols) >= 2 and row_count >= 10:
            hints = {
                "chart_type": "scatter",
                "x_field": numeric_cols[0],
                "y_field": numeric_cols[1],
                "x_type": "quantitative",
                "y_type": "quantitative",
            }
            return self.build_from_hints(hints, data_profile, data_reference)

        # Rule 6: Default fallback → table
        return self._create_table_fallback(
            data_reference=data_reference,
            summary="Unable to determine appropriate chart type. Displaying table view.",
            reason="no_pattern_match",
        )

    def _create_chart_config(
        self, hints: dict[str, Any], _data_profile: dict[str, Any]
    ) -> ChartConfig:
        """Create ChartConfig from validated hints.

        Args:
            hints: Validated hints with chart_type, x_field, y_field, etc.
            _data_profile: Data profile (not currently used but retained for future use)

        Returns:
            ChartConfig with proper encodings
        """
        chart_type = hints["chart_type"]

        # Build encodings
        encodings = {}

        # X encoding (if present)
        x_field = hints.get("x_field")
        if x_field:
            x_type = hints.get("x_type", "nominal")
            encodings["x"] = Encoding(
                field=x_field,
                type=EncodingType(x_type),
                title=self._format_field_title(x_field),
            )

        # Y encoding (if present)
        y_field = hints.get("y_field")
        if y_field:
            y_type = hints.get("y_type", "quantitative")
            # Use aggregation if provided (for time series and other multi-row-per-x scenarios)
            aggregate = hints.get("aggregation_type")
            encodings["y"] = Encoding(
                field=y_field,
                type=EncodingType(y_type),
                title=self._format_field_title(y_field),
                aggregate=aggregate,
            )

        # Create chart title
        title = self._create_chart_title(hints)

        return ChartConfig(
            chart_type=ChartType(chart_type),
            title=title,
            encodings=encodings,
            options=None,
        )

    def _create_chart_recommendation(
        self, hints: dict[str, Any]
    ) -> ChartRecommendation:
        """Create ChartRecommendation from hints.

        Args:
            hints: Validated hints

        Returns:
            ChartRecommendation with reasoning
        """
        chart_type = hints["chart_type"]
        reasoning = self._generate_reasoning(hints)

        return ChartRecommendation(
            chart_type=ChartType(chart_type),
            reasoning=reasoning,
            confidence=1.0,  # Deterministic from hints
        )

    def _create_summary(
        self, hints: dict[str, Any], data_profile: dict[str, Any]
    ) -> str:
        """Create natural language summary.

        Args:
            hints: Validated hints
            data_profile: Data profile with row_count

        Returns:
            Summary string
        """
        chart_type = hints["chart_type"]
        row_count = data_profile.get("row_count", 0)
        x_field = hints.get("x_field", "")
        y_field = hints.get("y_field", "")

        summaries = {
            "line": f"Time series showing {y_field} over {x_field} ({row_count} data points).",
            "bar": f"Comparison of {y_field} across {x_field} ({row_count} categories).",
            "area": f"Cumulative trend of {y_field} over {x_field} ({row_count} data points).",
            "scatter": f"Correlation analysis between {x_field} and {y_field} ({row_count} points).",
            "histogram": f"Distribution of {x_field} ({row_count} values).",
        }

        return summaries.get(
            chart_type,
            f"Visualization of {row_count} rows using {chart_type} chart.",
        )

    def _generate_reasoning(self, hints: dict[str, Any]) -> str:
        """Generate reasoning for chart selection.

        Args:
            hints: Validated hints

        Returns:
            Reasoning string
        """
        chart_type = hints["chart_type"]
        x_type = hints.get("x_type", "")

        reasoning_map = {
            "line": f"Line chart selected for temporal data ({x_type} x-axis) to show trends over time.",
            "bar": "Bar chart selected for categorical comparison to easily compare values across groups.",
            "area": f"Area chart selected for cumulative temporal data ({x_type} x-axis) to emphasize magnitude.",
            "scatter": "Scatter plot selected to visualize correlation between two quantitative variables.",
            "histogram": "Histogram selected to show distribution of values in a single quantitative variable.",
        }

        return reasoning_map.get(
            chart_type,
            f"Chart type '{chart_type}' selected based on data characteristics.",
        )

    def _create_chart_title(self, hints: dict[str, Any]) -> str:
        """Create chart title from hints.

        Args:
            hints: Validated hints

        Returns:
            Title string
        """
        chart_type = hints["chart_type"]
        y_field = hints.get("y_field", "")
        x_field = hints.get("x_field", "")

        if y_field and x_field:
            return f"{self._format_field_title(y_field)} by {self._format_field_title(x_field)}"
        elif x_field:
            return f"{self._format_field_title(x_field)} Distribution"
        else:
            return f"{chart_type.capitalize()} Chart"

    def _format_field_title(self, field_name: str) -> str:
        """Format field name as human-readable title.

        Args:
            field_name: Field name from data (e.g., "total_cost")

        Returns:
            Formatted title (e.g., "Total Cost")
        """
        # Replace underscores with spaces and title case
        return field_name.replace("_", " ").title()

    def _create_table_fallback(
        self, data_reference: str, summary: str, reason: str
    ) -> VisualizationOutput:
        """Create table fallback VisualizationOutput.

        Args:
            data_reference: Cache key for query results
            summary: Summary message explaining table fallback
            reason: Reason code for monitoring (e.g., "missing_hints")

        Returns:
            VisualizationOutput with has_visualization=False
        """
        logger.info(
            "visualization_fallback_to_table",
            reason=reason,
            data_reference=data_reference,
        )

        return VisualizationOutput(
            summary=summary,
            chart_recommendation=None,
            chart_config=None,
            data_reference=data_reference,
            has_visualization=False,
        )
