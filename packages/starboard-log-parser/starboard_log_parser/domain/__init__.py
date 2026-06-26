# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Domain layer for Spark log parser.

This package contains pure business logic with no I/O dependencies.
All models are immutable (frozen dataclasses) and all services are pure functions.

Architecture:
    models/     - Immutable domain entities
    services/   - Pure business logic functions
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
