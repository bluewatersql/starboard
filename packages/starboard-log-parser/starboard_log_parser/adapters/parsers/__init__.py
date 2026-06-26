# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Event parsers for building domain models from various log formats.

Parsers are adapters that convert external data formats into domain models.
"""

from starboard_log_parser.adapters.parsers.parsed_log import (
    ParsedLogParser,
)

__all__ = [
    "ParsedLogParser",
]
