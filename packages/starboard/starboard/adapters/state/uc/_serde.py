# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Value (de)serialization helpers for UC-native state adapters.

The Statement Execution API returns every column as a string in
``result.data_array`` (see :class:`UCStorageAdapter`). These helpers convert
those string values back into Python types, and JSON-encode structured values on
the write path. They are pure and dependency-free.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def dumps(value: Any) -> str | None:
    """JSON-encode a structured value for a ``STRING`` column (``None`` passthrough)."""
    if value is None:
        return None
    return json.dumps(value)


def loads(value: Any, default: Any) -> Any:
    """Decode a JSON string column, tolerating already-parsed values / NULLs."""
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    """Parse a boolean from a SQL string/typed value (``"true"``/``True``/1)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("true", "1", "t", "yes")


def parse_dt(value: Any) -> datetime:
    """Parse a timestamp column into a :class:`datetime`.

    Accepts ISO-8601 strings (with or without a trailing ``Z``) and passthrough
    ``datetime`` values.
    """
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Databricks renders TIMESTAMP as "YYYY-MM-DD HH:MM:SS[.ffffff]"; normalize
    # the space separator to the ISO 'T' so fromisoformat accepts it.
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    return datetime.fromisoformat(text)


def parse_dt_opt(value: Any) -> datetime | None:
    """Parse an optional timestamp column (``None``/empty → ``None``)."""
    if value is None or value == "":
        return None
    return parse_dt(value)


def parse_int(value: Any, default: int = 0) -> int:
    """Parse an integer column, tolerating strings and ``None``."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value: Any, default: float = 0.0) -> float:
    """Parse a float column, tolerating strings and ``None``."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
