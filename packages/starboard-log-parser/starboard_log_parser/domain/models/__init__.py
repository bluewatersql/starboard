# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Immutable domain models for Spark log parser.

All models are frozen dataclasses for thread safety and immutability.
"""

from starboard_log_parser.domain.models.application import SparkApplication
from starboard_log_parser.domain.models.info import SparkApplicationInfo
from starboard_log_parser.domain.models.metadata import (
    SparkApplicationMetadata,
)

__all__ = [
    "SparkApplication",
    "SparkApplicationInfo",
    "SparkApplicationMetadata",
]
