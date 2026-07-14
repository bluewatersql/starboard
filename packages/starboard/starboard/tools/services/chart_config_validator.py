# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Validation and sanitization for LLM-generated chart configurations.

This module provides defensive validation to handle common LLM output issues:
- Null/undefined encoding values
- Missing required fields
- Invalid enum values
- Malformed nested structures
"""

from __future__ import annotations

from typing import Any

from starboard.infra.observability.logging import get_logger
from starboard.tools.domain.analytics.visualization_models import ChartConfig

logger = get_logger(__name__)


class ChartConfigValidator:
    """
    Validator for LLM-generated chart configurations.

    Handles common issues:
    - Removes null/undefined encoding values
    - Validates required fields
    - Normalizes enum values
    - Provides helpful error messages
    """

    @staticmethod
    def sanitize_encodings(encodings: dict[str, Any] | None) -> dict[str, Any]:
        """
        Remove null/undefined values from encodings dict.

        LLMs sometimes generate: {"x": {...}, "color": null}
        This removes the null values to prevent validation errors.

        Args:
            encodings: Raw encodings dict from LLM

        Returns:
            Sanitized encodings dict (null values removed)

        Examples:
            >>> encodings = {"x": {"field": "job_name"}, "color": None}
            >>> sanitized = ChartConfigValidator.sanitize_encodings(encodings)
            >>> sanitized
            {'x': {'field': 'job_name'}}
        """
        if not encodings:
            return {}

        sanitized = {}
        removed_keys = []

        for key, value in encodings.items():
            if value is not None and value != {}:
                sanitized[key] = value
            else:
                removed_keys.append(key)

        if removed_keys:
            logger.debug(
                "sanitized_chart_encodings",
                removed_keys=removed_keys,
                note="Removed null/empty encoding values from LLM output",
            )

        return sanitized

    @staticmethod
    def validate_and_fix(config_dict: dict[str, Any]) -> ChartConfig:
        """
        Validate and fix common LLM chart config issues.

        Applies defensive fixes:
        1. Sanitize encodings (remove nulls)
        2. Ensure required fields exist
        3. Validate against Pydantic model
        4. Log warnings for issues found

        Args:
            config_dict: Raw config dict from LLM

        Returns:
            Validated ChartConfig instance

        Raises:
            ValueError: If config is invalid even after fixes

        Examples:
            >>> config_dict = {
            ...     "chart_type": "bar",
            ...     "title": "Cost by Job",
            ...     "encodings": {"x": {...}, "color": None},
            ... }
            >>> config = ChartConfigValidator.validate_and_fix(config_dict)
        """
        # Defensive copy
        fixed_config = dict(config_dict)

        # Fix 1: Sanitize encodings
        if "encodings" in fixed_config:
            original_count = len(fixed_config["encodings"])
            fixed_config["encodings"] = ChartConfigValidator.sanitize_encodings(
                fixed_config["encodings"]
            )
            new_count = len(fixed_config["encodings"])

            if original_count != new_count:
                logger.warning(
                    "llm_chart_config_sanitized",
                    removed_encoding_count=original_count - new_count,
                    note="LLM generated invalid encoding values",
                )

        # Fix 2: Ensure minimum required fields
        required_fields = ["chart_type", "title"]
        missing = [f for f in required_fields if f not in fixed_config]
        if missing:
            raise ValueError(f"Missing required chart config fields: {missing}")

        # Fix 3: Validate with Pydantic
        try:
            validated = ChartConfig(**fixed_config)
            logger.debug(
                "chart_config_validated",
                chart_type=validated.chart_type,
                encoding_count=len(validated.encodings),
            )
            return validated
        except (ValueError, TypeError, KeyError) as e:
            logger.error(
                "chart_config_validation_failed",
                error=str(e),
                config_keys=list(fixed_config.keys()),
            )
            raise ValueError(f"Invalid chart configuration: {str(e)}") from e
