"""
Adapters layer for Spark log parser.

This package contains I/O boundaries and external integrations.
Adapters handle loading, parsing, and persistence without business logic.

Architecture:
    loaders/  - Existing data loaders (keep as-is)
    parsers/  - NEW: Event parsers that build domain models
"""

from starboard_log_parser.adapters.parsers.parsed_log import (
    ParsedLogParser,
)

__all__ = [
    "ParsedLogParser",
]
