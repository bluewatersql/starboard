"""Visualization Hints Validator for Analytics SQL.

Validates and sanitizes visualization hints from LLM SQL generation to ensure
they align with VisualizationService capabilities and data characteristics.

Multi-layer validation:
1. Schema enforcement (in LLMSQLGenerator)
2. Structural validation (this module)
3. Data-driven validation (this module)
4. Service-level guardrails (VisualizationService)
"""

from __future__ import annotations

from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Supported chart types (must match VisualizationService and LLMSQLGenerator)
SUPPORTED_CHART_TYPES = {"bar", "line", "area", "scatter", "histogram", "table"}

# Chart type constraints
TEMPORAL_CHART_TYPES = {"line", "area"}
CATEGORICAL_CHART_TYPES = {"bar"}
CORRELATION_CHART_TYPES = {"scatter"}
DISTRIBUTION_CHART_TYPES = {"histogram"}


class VisualizationHintsValidator:
    """Validates and sanitizes visualization hints from LLM.

    Provides defense-in-depth validation:
    - Validates chart types against supported list
    - Checks temporal constraints (line/area require temporal data)
    - Validates metric/dimension field references
    - Corrects TOP N pattern mismatches
    - Provides fallback recommendations when hints are invalid

    Example:
        >>> validator = VisualizationHintsValidator()
        >>> hints = {
        ...     "recommended_chart_types": ["line", "pie"],  # "pie" invalid
        ...     "is_time_series": True,
        ...     "primary_metric": "cost",
        ... }
        >>> validated = validator.validate_and_sanitize(
        ...     hints, sql_normalized, data_profile
        ... )
        >>> validated["recommended_chart_types"]
        ['line']  # "pie" removed
    """

    @classmethod
    def validate_and_sanitize(
        cls,
        hints: dict[str, Any],
        sql: str,
        data_profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate hints and fix common errors.

        Args:
            hints: Raw hints from LLM (from build_sql_query)
            sql: SQL query
            data_profile: Data profile from profiling (numeric_stats, temporal_stats, etc.)

        Returns:
            Sanitized hints with validated chart types and corrected flags

        Example:
            >>> hints = {"recommended_chart_types": ["line"], "is_time_series": True}
            >>> validated = VisualizationHintsValidator.validate_and_sanitize(
            ...     hints, sql, profile
            ... )
        """
        if not hints:
            logger.warning("empty_visualization_hints_from_llm")
            return cls._create_fallback_hints(sql, data_profile)

        sanitized = hints.copy()

        # 1. Validate chart types against supported list
        sanitized = cls._validate_chart_types(sanitized, sql, data_profile)

        # 2. Validate temporal constraints
        sanitized = cls._validate_temporal_constraints(sanitized, data_profile)

        # 3. Validate metric/dimension fields
        sanitized = cls._validate_field_references(sanitized, data_profile)

        # 4. Validate TOP N pattern
        sanitized = cls._validate_top_n_pattern(sanitized, sql)

        # 5. Ensure at least one valid chart type
        if not sanitized.get("recommended_chart_types"):
            logger.warning("no_valid_chart_types_after_validation")
            sanitized["recommended_chart_types"] = ["table"]

        logger.debug(
            "visualization_hints_validated",
            extra={
                "original_types": hints.get("recommended_chart_types", []),
                "validated_types": sanitized.get("recommended_chart_types", []),
                "corrections_made": hints != sanitized,
            },
        )

        return sanitized

    @classmethod
    def _validate_chart_types(
        cls,
        hints: dict[str, Any],
        sql: str,
        data_profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate chart types against supported list.

        Filters out unsupported types and provides fallback if all types invalid.
        """
        recommended = hints.get("recommended_chart_types", [])

        # Filter to supported types only
        valid_types = [ct for ct in recommended if ct in SUPPORTED_CHART_TYPES]

        if not valid_types and recommended:
            # LLM suggested invalid types - log and fallback
            logger.warning(
                "invalid_chart_types_from_llm",
                extra={
                    "original": recommended,
                    "supported": list(SUPPORTED_CHART_TYPES),
                },
            )
            # Fallback: infer from SQL + data profile
            valid_types = cls._infer_from_structure(sql, data_profile)

        hints["recommended_chart_types"] = valid_types
        return hints

    @classmethod
    def _validate_temporal_constraints(
        cls, hints: dict[str, Any], data_profile: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate temporal chart types require temporal data.

        If LLM suggests line/area but no temporal data exists, correct the hints.
        """
        is_time_series = hints.get("is_time_series", False)
        has_temporal_data = bool(data_profile.get("temporal_stats"))
        recommended = hints.get("recommended_chart_types", [])

        # Case 1: LLM says time-series but no temporal data
        if is_time_series and not has_temporal_data:
            logger.warning(
                "temporal_mismatch_corrected",
                extra={
                    "is_time_series": True,
                    "has_temporal_data": False,
                    "action": "removing_temporal_chart_types",
                },
            )
            hints["is_time_series"] = False

            # Remove temporal chart types
            hints["recommended_chart_types"] = [
                ct for ct in recommended if ct not in TEMPORAL_CHART_TYPES
            ]

            # Add bar as fallback if empty
            if not hints["recommended_chart_types"]:
                hints["recommended_chart_types"] = ["bar", "table"]

        # Case 2: LLM suggests line/area but no temporal flag
        has_temporal_types = any(ct in TEMPORAL_CHART_TYPES for ct in recommended)
        if has_temporal_types and not is_time_series and has_temporal_data:
            logger.debug(
                "temporal_flag_corrected",
                extra={"action": "setting_is_time_series_true"},
            )
            hints["is_time_series"] = True

        return hints

    @classmethod
    def _validate_field_references(
        cls, hints: dict[str, Any], data_profile: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate metric/dimension fields exist in data.

        Nullifies field references that don't exist in the data profile.
        """
        primary_metric = hints.get("primary_metric")
        primary_dimension = hints.get("primary_dimension")

        # Get available columns
        numeric_cols = set(data_profile.get("numeric_stats", {}).keys())
        categorical_cols = set(data_profile.get("categorical_stats", {}).keys())
        temporal_cols = set(data_profile.get("temporal_stats", {}).keys())
        all_cols = numeric_cols | categorical_cols | temporal_cols

        # Validate primary_metric (should be numeric)
        if primary_metric and primary_metric not in numeric_cols:
            logger.warning(
                "primary_metric_not_found",
                extra={
                    "metric": primary_metric,
                    "available_numeric": list(numeric_cols),
                },
            )
            hints["primary_metric"] = None

        # Validate primary_dimension (can be any column)
        if primary_dimension and primary_dimension not in all_cols:
            logger.warning(
                "primary_dimension_not_found",
                extra={
                    "dimension": primary_dimension,
                    "available_columns": list(all_cols)[:10],  # Limit for logging
                },
            )
            hints["primary_dimension"] = None

        return hints

    @classmethod
    def _validate_top_n_pattern(cls, hints: dict[str, Any], sql: str) -> dict[str, Any]:
        """Validate TOP N pattern matches SQL structure.

        TOP N queries should have both ORDER BY and LIMIT.
        """
        is_top_n = hints.get("is_top_n", False)
        sql_upper = sql.upper()

        has_limit = "LIMIT" in sql_upper
        has_order = "ORDER BY" in sql_upper

        # If LLM says TOP N but SQL doesn't match pattern
        if is_top_n and not (has_limit and has_order):
            logger.warning(
                "top_n_mismatch_corrected",
                extra={
                    "is_top_n": True,
                    "has_limit": has_limit,
                    "has_order": has_order,
                },
            )
            hints["is_top_n"] = False

        # If SQL has TOP N pattern but LLM didn't flag it
        if not is_top_n and has_limit and has_order:
            logger.debug(
                "top_n_pattern_detected",
                extra={"action": "setting_is_top_n_true"},
            )
            hints["is_top_n"] = True

        return hints

    @classmethod
    def _infer_from_structure(cls, sql: str, data_profile: dict[str, Any]) -> list[str]:
        """Fallback: infer chart types from SQL structure + data profile.

        Used when LLM hints are completely invalid or missing.

        Args:
            sql: SQL query
            data_profile: Data profile with stats

        Returns:
            List of recommended chart types based on heuristics
        """
        sql_upper = sql.upper()

        has_temporal = bool(data_profile.get("temporal_stats"))
        has_grouping = "GROUP BY" in sql_upper
        row_count = data_profile.get("row_count", 0)
        column_count = data_profile.get("column_count", 0)
        numeric_count = len(data_profile.get("numeric_stats", {}))

        # Heuristic decision tree
        if has_temporal and has_grouping:
            # Time-series aggregation → line/area
            return ["line", "area"]
        elif has_grouping and "LIMIT" in sql_upper:
            # TOP N query → bar
            return ["bar"]
        elif numeric_count >= 2 and not has_grouping:
            # Multiple metrics, no grouping → scatter
            return ["scatter"]
        elif row_count < 10:
            # Very few rows → table
            return ["table"]
        elif column_count > 5:
            # Many columns → table
            return ["table"]
        else:
            # Default → bar or table
            return ["bar", "table"]

    @classmethod
    def _create_fallback_hints(
        cls, sql: str, data_profile: dict[str, Any]
    ) -> dict[str, Any]:
        """Create fallback hints when LLM provides none.

        Args:
            sql: SQL query
            data_profile: Data profile with stats

        Returns:
            Minimal valid hints based on heuristics
        """
        recommended_types = cls._infer_from_structure(sql, data_profile)
        has_temporal = bool(data_profile.get("temporal_stats"))
        sql_upper = sql.upper()

        return {
            "query_intent": "Analyze query results",
            "recommended_chart_types": recommended_types,
            "primary_metric": None,
            "primary_dimension": None,
            "is_time_series": has_temporal and "GROUP BY" in sql_upper,
            "is_top_n": "LIMIT" in sql_upper and "ORDER BY" in sql_upper,
            "aggregation_type": "none",
        }
