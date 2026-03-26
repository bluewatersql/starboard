"""Shared utility functions for domain logic.

This module provides common helper functions used across all domain modules
for safe type conversions, JSON parsing, data cleaning, and calculations.

These utilities are pure functions with no I/O dependencies.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any, Literal

import polars as pl

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

KILOBYTE = 1_024.0
MEGABYTE = 1_000_000.0
GIGABYTE = 1_000_000_000.0
THOUSAND = 1_000.0
KILOBYTE_THRESHOLD = 256 * 1024
ROUNDING_PRECISION = 2


# =============================================================================
# Type Conversion Functions
# =============================================================================


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float, returning default on failure.

    Args:
        value: Value to convert to float
        default: Default value to return if conversion fails

    Returns:
        Float value or default if conversion fails
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int | None = 0) -> int | None:
    """Safely convert value to int, handling NaN and various formats.

    Args:
        value: Value to convert to int
        default: Default value to return if conversion fails (default: 0)

    Returns:
        Integer value or default if conversion fails or value is NaN
    """
    if value is None:
        return default

    try:
        if isinstance(value, int):
            return value

        if isinstance(value, float):
            if math.isnan(value):
                return default
            return int(value)

        string_val = str(value).strip()
        if not string_val or string_val.lower() == "nan":
            return default

        return int(float(string_val))
    except (TypeError, ValueError):
        return default


def round_float(value: Any, precision: int = ROUNDING_PRECISION) -> float:
    """Round a value to specified precision.

    Args:
        value: Value to round
        precision: Number of decimal places

    Returns:
        Rounded float value
    """
    return round(safe_float(value), precision)


# =============================================================================
# NaN Handling
# =============================================================================


def is_nan(value: Any) -> bool:
    """Check if value is NaN.

    Args:
        value: Value to check

    Returns:
        True if value is NaN, False otherwise
    """
    try:
        return isinstance(value, float) and math.isnan(value)
    except (ValueError, TypeError, KeyError):
        return False


def nan_to_none(value: Any) -> Any:
    """Convert NaN to None, otherwise return value unchanged.

    Args:
        value: Value to convert

    Returns:
        None if value is NaN, otherwise the original value
    """
    return None if is_nan(value) else value


# =============================================================================
# Datetime Functions
# =============================================================================


def to_datetime(timestamp: Any | None) -> datetime | None:
    """Convert various timestamp formats to datetime object.

    Handles pandas Timestamp, datetime objects, and ISO strings.

    Args:
        timestamp: Timestamp in various formats (pandas, datetime, string)

    Returns:
        Datetime object or None if conversion fails
    """
    if timestamp is None:
        return None

    if hasattr(timestamp, "to_pydatetime"):
        try:
            return timestamp.to_pydatetime()
        except (ValueError, TypeError, KeyError):
            pass

    if isinstance(timestamp, datetime):
        return timestamp

    if isinstance(timestamp, str):
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except (ValueError, TypeError, KeyError):
            return None

    return None


def to_iso_string(timestamp: Any) -> str | None:
    """Convert timestamp to ISO format string.

    Args:
        timestamp: Timestamp value to convert

    Returns:
        ISO format string or None if timestamp is None/NaN
    """
    if timestamp is None or (isinstance(timestamp, float) and math.isnan(timestamp)):
        return None
    try:
        if hasattr(timestamp, "isoformat"):
            return timestamp.isoformat()
        return str(timestamp)
    except (ValueError, TypeError, KeyError):
        return str(timestamp)


def ts_ms_to_iso(ts_ms: int | None) -> str | None:
    """Convert timestamp in milliseconds to ISO format string.

    Args:
        ts_ms: Timestamp in milliseconds

    Returns:
        ISO format string or None if conversion fails
    """
    if ts_ms is None:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()
    except (ValueError, TypeError, KeyError):
        return None


def ts_ms_to_day_key(ts_ms: int | None) -> str | None:
    """Convert timestamp in milliseconds to day key string (YYYY-MM-DD).

    Args:
        ts_ms: Timestamp in milliseconds

    Returns:
        Day key string or None if conversion fails
    """
    if ts_ms is None:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
    except (ValueError, TypeError, KeyError):
        return None


# =============================================================================
# JSON Parsing Functions
# =============================================================================


def try_json_load(value: Any, return_none: bool = False) -> Any:
    """Best-effort JSON loader.

    If value is a JSON-encoded string, decode it; otherwise return value.
    If return_none is True, return None on failure instead of original value.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError, KeyError):
            return None if return_none else value
    return None if return_none else value


def deep_load_json_strings(obj: Any) -> Any:
    """Recursively decode any JSON-encoded strings in the object.

    Useful for payloads with nested JSON-in-JSON structures.
    """
    if isinstance(obj, dict):
        return {k: deep_load_json_strings(try_json_load(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_load_json_strings(try_json_load(v)) for v in obj]
    return try_json_load(obj)


def parse_json(value: Any, expected_type: type = dict) -> Any:
    """Parse value that may be a JSON-encoded string.

    Args:
        value: Value that may be a JSON string or already parsed object
        expected_type: Expected type (dict or list)

    Returns:
        Parsed object of expected_type, or empty instance if parsing fails
    """
    default = expected_type() if expected_type in (dict, list) else None

    if value is None:
        return default

    if isinstance(value, expected_type):
        return value

    if isinstance(value, str):
        string_val = value.strip()
        try:
            parsed = json.loads(string_val)
            if isinstance(parsed, expected_type):
                return parsed
        except (ValueError, TypeError, KeyError):
            if (
                expected_type is list
                and string_val.startswith("[")
                and string_val.endswith("]")
            ):
                inner = string_val[1:-1].strip()
                if not inner:
                    return []
                return [part.strip().strip("\"'") for part in inner.split(",")]

    return default


def parse_json_list(value: Any) -> list[Any]:
    """Parse value that may be a JSON array string."""
    return parse_json(value, expected_type=list)


def parse_json_dict(value: Any) -> dict[str, Any]:
    """Parse value that may be a JSON object string."""
    return parse_json(value, expected_type=dict)


def pack_dict(data: Any) -> str:
    """Convert data structure to compact JSON string.

    Args:
        data: Dictionary, list, or other JSON-serializable data

    Returns:
        Compact JSON string representation of the data
    """
    if data is None:
        return "{}"

    if isinstance(data, str):
        return data

    try:
        data = strip_nulls(data)
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return str(data)


def first(d: dict[str, Any], *paths: str, default: Any = None) -> Any:
    """Return first non-empty value among dotted key paths.

    Example:
        first(d, "cluster_log_conf.volumes.destination", "spec.cluster_log_conf")
    """
    for path in paths:
        cur = d
        try:
            for p in path.split("."):
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    raise KeyError
            if cur not in (None, "", {}):
                return cur
        except KeyError:
            continue
    return default


# =============================================================================
# Data Cleaning Functions
# =============================================================================


def strip_nulls(data: Any) -> Any:
    """Recursively remove None, empty strings, dicts, and lists from data structure."""
    if isinstance(data, dict):
        cleaned_dict = {}
        for key, value in data.items():
            cleaned_value = strip_nulls(value)
            if cleaned_value not in (None, "", {}, []):
                cleaned_dict[key] = cleaned_value
        return cleaned_dict

    if isinstance(data, list):
        cleaned_list = [
            strip_nulls(item) for item in data if item not in (None, "", {}, [])
        ]
        return [item for item in cleaned_list if item not in (None, "", {}, [])]

    return data


def filter_none_values(data: dict[str, Any]) -> dict[str, Any]:
    """Filter out None values from dictionary."""
    return {k: v for k, v in data.items() if v is not None}


def as_list(value: Any) -> list[str]:
    """Convert value to list of strings.

    Returns empty list for None, converts single values to single-element list.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def split_comma_list(value: str, strip: bool = True) -> list[str]:
    """Split comma-separated string into list of strings.

    Args:
        value: Comma-separated string to split
        strip: Whether to strip whitespace from each element

    Returns:
        List of string elements, empty strings removed
    """
    if not value:
        return []
    items = value.split(",")
    if strip:
        items = [x.strip() for x in items]
    return [x for x in items if x]


# =============================================================================
# Calculation Functions
# =============================================================================


def calculate_ratio(numerator: Any, denominator: Any) -> float:
    """Calculate ratio, returning 0 if denominator is 0 or None.

    Args:
        numerator: Numerator value
        denominator: Denominator value

    Returns:
        Ratio as float, or 0.0 if denominator is 0 or None
    """
    n = safe_float(numerator) if numerator is not None else 0.0
    d = safe_float(denominator) if denominator is not None else 0.0
    return (n / d) if d != 0 else 0.0


def calculate_average(values: list[float]) -> float:
    """Calculate average of list, returning 0.0 if empty."""
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[float], p: float) -> float:
    """Inclusive percentile (0-100). Returns NaN if empty."""
    if not values:
        return float("nan")
    v = sorted(values)
    if p <= 0:
        return v[0]
    if p >= 100:
        return v[-1]
    k = (len(v) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return v[int(k)]
    return v[f] + (v[c] - v[f]) * (k - f)


# =============================================================================
# Extraction and Unification Functions
# =============================================================================


def extract_result_state(obj: dict[str, Any]) -> str:
    """Extract result state from various response structures.

    Checks multiple possible locations for status/result information.
    Returns the result/termination code (SUCCESS/FAILED), not lifecycle state.
    """
    state = (obj.get("state") or {}).get("result_state")
    if state:
        return state

    term = ((obj.get("status") or {}).get("termination_details") or {}).get("code")
    if term:
        return term

    state_message = (obj.get("state") or {}).get("state_message")
    if state_message:
        return state_message

    life_cycle = (obj.get("state") or {}).get("life_cycle_state")
    if life_cycle and life_cycle not in [
        "TERMINATED",
        "TERMINATING",
        "RUNNING",
        "PENDING",
    ]:
        return life_cycle

    status_obj = obj.get("status") or {}
    status_state = status_obj.get("state")
    if status_state and status_state not in [
        "TERMINATED",
        "TERMINATING",
        "RUNNING",
        "PENDING",
    ]:
        return status_state

    return "UNKNOWN"


def unify_field_value(records: list[dict[str, Any]], key: str) -> Any:
    """Get unified value for a field across multiple records.

    Returns the value if all non-None values are the same, otherwise returns first found.
    """
    values = {r.get(key) for r in records if r.get(key) is not None}
    return values.pop() if values else None


# =============================================================================
# Polars DataFrame Functions
# =============================================================================


def polars_df_to_dict(
    df: pl.DataFrame,
    *,
    max_rows: int | None = None,
    orientation: Literal["columns", "records"] = "records",
    datetime_format: str = "%Y-%m-%dT%H:%M:%S%.f",
    date_format: str = "%Y-%m-%d",
    time_format: str = "%H:%M:%S%.f",
    duration_unit: Literal["us"] = "us",
) -> dict[str, Any]:
    """
    Convert a Polars DataFrame into a JSON-serializable payload suitable for LLM context.

    Fix 1 (updated): For tz-aware datetime columns, convert to UTC then drop timezone (tz-naive UTC clock time).
    Fix 2: Convert Decimal columns to Float64.

    Notes:
    - Float NaN/Inf are replaced with None (JSON can't represent them).
    - Date/Datetime/Time are encoded as strings.
    - Duration encoded as integer microseconds.
    """
    if max_rows is not None:
        df = df.head(max_rows)

    row_count = df.height
    normalized_df = df
    datetime_cols_normalized: list[str] = []
    decimal_cols_normalized: list[str] = []

    # Keep original tz per column (optional metadata)
    datetime_tz_original: dict[str, str] = {}

    for col, dtype in normalized_df.schema.items():
        # Fix 1: tz-aware Datetime -> convert to UTC -> drop tz (naive)
        is_datetime = hasattr(dtype, "time_zone") or str(dtype).startswith("Datetime")
        if is_datetime:
            tz = getattr(dtype, "time_zone", None)
            if tz is not None:
                datetime_tz_original[col] = str(tz)
                normalized_df = normalized_df.with_columns(
                    pl.col(col)
                    .dt.convert_time_zone("UTC")
                    .dt.replace_time_zone(None)
                    .alias(col)
                )
                datetime_cols_normalized.append(col)
            continue

        # Fix 2: Decimal -> Float64
        if str(dtype).startswith("Decimal"):
            normalized_df = normalized_df.with_columns(
                pl.col(col).cast(pl.Float64).alias(col)
            )
            decimal_cols_normalized.append(col)

    schema_meta: dict[str, Any] = {}
    exprs: list[pl.Expr] = []

    for col, dt in normalized_df.schema.items():
        meta: dict[str, Any] = {"dtype": str(dt), "encoding": "native"}

        if col in datetime_cols_normalized:
            meta["normalization"] = "tz_to_utc_then_drop"
            meta["original_time_zone"] = datetime_tz_original.get(col)

        if col in decimal_cols_normalized:
            meta["normalization"] = "decimal_to_float64"

        # Floats: replace NaN/Inf with null
        if dt in (pl.Float32, pl.Float64):
            exprs.append(
                pl.when(pl.col(col).is_finite())
                .then(pl.col(col))
                .otherwise(pl.lit(None))
                .alias(col)
            )
            meta["encoding"] = "float_finite_only"

        elif dt == pl.Date:
            exprs.append(pl.col(col).dt.to_string(date_format).alias(col))
            meta.update({"encoding": "date_string", "format": date_format})

        elif dt == pl.Datetime:
            # Now tz-naive UTC clock time if it was originally tz-aware
            exprs.append(pl.col(col).dt.to_string(datetime_format).alias(col))
            meta.update({"encoding": "datetime_string", "format": datetime_format})

        elif dt == pl.Time:
            exprs.append(pl.col(col).dt.to_string(time_format).alias(col))
            meta.update({"encoding": "time_string", "format": time_format})

        elif dt == pl.Duration:
            exprs.append(pl.col(col).dt.total_microseconds().alias(col))
            meta.update({"encoding": "duration_int", "unit": duration_unit})

        # Safety fallback if a Decimal slipped through (shouldn't after Fix 2)
        elif str(dt).startswith("Decimal"):
            exprs.append(pl.col(col).cast(pl.Float64).alias(col))
            meta.update(
                {"encoding": "float_finite_only", "normalization": "decimal_to_float64"}
            )

        else:
            exprs.append(pl.col(col))

        schema_meta[col] = meta

    safe = normalized_df.select(exprs)

    data = (
        safe.to_dict(as_series=False) if orientation == "columns" else safe.to_dicts()
    )

    return {
        "version": 1,
        "orientation": orientation,
        "schema": schema_meta,
        "data": data,
        "row_count": row_count,
    }


def payload_to_polars_df(payload: dict[str, Any]) -> pl.DataFrame:
    """
    Reconstruct a Polars DataFrame from the payload produced by polars_df_to_dict().

    Handles:
    - orientation: "columns" (dict-of-lists) or "records" (list-of-dicts)
    - date/datetime/time strings -> parsed types
    - duration microseconds int -> Duration[us]
    - decimal strings -> Decimal if precision/scale present, else left as Utf8
    """
    orientation = payload.get("orientation", "records")
    schema: dict[str, Any] = payload.get("schema") or {}
    data = payload.get("data")

    # --- Build the base DataFrame safely ---
    if orientation == "columns":
        # Expect dict[str, list]
        df = pl.DataFrame({c: [] for c in schema}) if not data else pl.DataFrame(data)
    else:
        # Expect list[dict]
        df = pl.DataFrame({c: [] for c in schema}) if not data else pl.from_dicts(data)

    if df.is_empty() and not df.columns and schema:
        # Extra guard: some empty constructions can drop columns
        df = pl.DataFrame({c: [] for c in schema})

    # --- Apply dtype restorations based on encoding metadata ---
    exprs: list[pl.Expr] = []

    for col in df.columns:
        meta: dict[str, Any] = schema.get(col, {}) or {}
        enc = meta.get("encoding", "native")

        if enc == "date_string":
            fmt = meta.get("format", "%Y-%m-%d")
            exprs.append(
                pl.col(col)
                .cast(pl.Utf8)
                .str.strptime(pl.Date, format=fmt, strict=False)
                .alias(col)
            )

        elif enc == "datetime_string":
            fmt = meta.get("format", "%Y-%m-%dT%H:%M:%S%.f")
            e = (
                pl.col(col)
                .cast(pl.Utf8)
                .str.strptime(pl.Datetime, format=fmt, strict=False)
            )

            # Best-effort timezone restore (only if you stored one)
            tz = meta.get("time_zone")
            if tz:
                try:
                    e = e.dt.replace_time_zone(tz)  # works on many versions
                except (ValueError, TypeError, KeyError):
                    logger.debug(
                        "failed_to_restore_timezone",
                        col=col,
                        tz=tz,
                    )

            exprs.append(e.alias(col))

        elif enc == "time_string":
            fmt = meta.get("format", "%H:%M:%S%.f")
            exprs.append(
                pl.col(col)
                .cast(pl.Utf8)
                .str.strptime(pl.Time, format=fmt, strict=False)
                .alias(col)
            )

        elif enc == "duration_int":
            # Stored as integer microseconds; build a Duration[us] expression robustly
            exprs.append(
                pl.duration(microseconds=pl.col(col).cast(pl.Int64)).alias(col)
            )

        elif enc == "decimal_string":
            prec = meta.get("precision")
            scale = meta.get("scale")
            if prec is not None and scale is not None:
                exprs.append(
                    pl.col(col)
                    .cast(pl.Utf8)
                    .cast(pl.Decimal(precision=int(prec), scale=int(scale)))
                    .alias(col)
                )
            else:
                exprs.append(pl.col(col).cast(pl.Utf8).alias(col))

        else:
            exprs.append(pl.col(col))

    # with_columns preserves existing cols and updates types/values
    return df.with_columns(exprs)
