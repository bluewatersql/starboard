# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared datetime serialization utilities."""

from datetime import UTC, datetime


def to_iso(dt: datetime) -> str:
    """Serialize datetime to ISO 8601 string with UTC timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def from_iso(s: str) -> datetime:
    """Deserialize ISO 8601 string to timezone-aware datetime."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def utc_now() -> datetime:
    """Current UTC datetime (replaces datetime.now(UTC) scattered throughout)."""
    return datetime.now(UTC)
