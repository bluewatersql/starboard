"""
Simple checkpoint system matching POC's API.

Uses a default checkpoint directory: data/checkpoints/

Pattern:
    checkpoint = await read_checkpoint("tables_extracted")
    if not checkpoint:
        tables = extractor.extract_tables(schemas=["billing", "compute"])
        await write_checkpoint("tables_extracted", [t.model_dump() for t in tables])
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from starboard_server.infra.io import read_json, write_json

logger = structlog.get_logger(__name__)

# Default checkpoint directory (matches POC pattern)
DEFAULT_CHECKPOINT_DIR = Path("data/checkpoints")


def is_file_fresh(path: str | Path, *, max_age_minutes: int = 1200) -> bool:
    """
    Return True iff `path` exists and its mtime is newer than `max_age_minutes`.
    Otherwise return False (missing or expired).

    Args:
        path: Path to checkpoint file
        max_age_minutes: Maximum age in minutes (default: 1200 = 20 hours)

    Returns:
        True if file exists and is fresh, False otherwise
    """
    p = Path(path)

    try:
        stat = p.stat()
    except FileNotFoundError:
        return False

    # mtime as UTC-aware datetime
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)

    return mtime >= cutoff


async def read_checkpoint(checkpoint_name: str) -> Any | None:
    """
    Read checkpoint if fresh, otherwise return None.

    Uses DEFAULT_CHECKPOINT_DIR (data/checkpoints/) as the checkpoint directory.

    Args:
        checkpoint_name: Name of checkpoint (e.g., "tables_extracted")

    Returns:
        Checkpoint data if fresh, None if stale or missing
    """
    checkpoint_file = DEFAULT_CHECKPOINT_DIR / f"{checkpoint_name}.json"

    if is_file_fresh(checkpoint_file):
        return await read_json(checkpoint_file)
    return None


async def write_checkpoint(checkpoint_name: str, data: Any) -> None:
    """
    Write checkpoint to disk.

    Uses DEFAULT_CHECKPOINT_DIR (data/checkpoints/) as the checkpoint directory.
    Creates directory if it doesn't exist.

    Args:
        checkpoint_name: Name of checkpoint (e.g., "tables_extracted")
        data: Data to serialize (must be JSON-serializable)
    """
    DEFAULT_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_file = DEFAULT_CHECKPOINT_DIR / f"{checkpoint_name}.json"

    await write_json(checkpoint_file, data, indent=2, default=str)

    logger.info(
        "Checkpoint saved",
        checkpoint_name=checkpoint_name,
        checkpoint_file=str(checkpoint_file),
    )
