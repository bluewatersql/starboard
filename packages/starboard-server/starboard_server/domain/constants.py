"""Named constants for domain logic. No magic numbers in business code."""

from enum import IntEnum


class WindowDays(IntEnum):
    """Standard lookback windows for time-series analysis."""

    WEEK = 7
    MONTH = 30
    QUARTER = 90


# Aliases for readability in non-enum contexts
DEFAULT_LOOKBACK_DAYS = WindowDays.MONTH
SHORT_LOOKBACK_DAYS = WindowDays.WEEK
LONG_LOOKBACK_DAYS = WindowDays.QUARTER

# Byte-size constants (binary, IEC standard)
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024
BYTES_PER_GB = 1024 * 1024 * 1024
BYTES_PER_TB = 1024 * 1024 * 1024 * 1024

# Analytics defaults
DEFAULT_STUB_INTENT_CONFIDENCE = 1.0
DEFAULT_ANALYTICS_DOMAIN = "BILLING"

# Timeout constants
REQUEST_USER_INPUT_TIMEOUT_SECONDS = 300.0


def bytes_to_human(n: int | float, binary: bool = True) -> str:
    """Format byte count to human-readable string.

    Args:
        n: Number of bytes.
        binary: If True, use 1024-based (KiB/MiB/GiB). If False, use 1000-based (KB/MB/GB).

    Returns:
        Human-readable string representation of the byte count.
    """
    base = 1024 if binary else 1000
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < base:
            return f"{n:.1f} {unit}"
        n /= base
    return f"{n:.1f} PB"
