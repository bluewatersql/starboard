"""
File-based checkpoint system for vector store build pipeline.

Provides simple, debuggable checkpoints to avoid re-running expensive operations
(metadata extraction, LLM enrichment) when resuming after failures.

Pattern:
    checkpoint = await read_checkpoint("tables_extracted", checkpoint_dir)
    if not checkpoint:
        tables = extractor.extract_tables(schemas=["billing", "compute"])
        await write_checkpoint("tables_extracted", [t.model_dump() for t in tables], checkpoint_dir)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, TypeAdapter, ValidationError

from starboard_server.infra.io import read_json, write_json

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


def is_file_fresh(path: Path, *, max_age_minutes: int = 1200) -> bool:
    """
    Check if file exists and is newer than max_age_minutes.

    Uses filesystem modification time (mtime) compared to current UTC time.

    Args:
        path: Path to checkpoint file
        max_age_minutes: Maximum age in minutes before considering stale.
                        Default is 1200 (20 hours) to cover a typical workday.

    Returns:
        True if file exists and mtime is within max_age_minutes, False otherwise

    Example:
        >>> checkpoint_path = Path("data/checkpoints/tables_extracted.json")
        >>> if is_file_fresh(checkpoint_path, max_age_minutes=60):
        ...     print("Checkpoint is fresh (< 1 hour old)")
    """
    try:
        stat = path.stat()
    except FileNotFoundError:
        logger.debug("checkpoint_not_found", path=str(path))
        return False

    # mtime as UTC-aware datetime
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)

    is_fresh = mtime >= cutoff
    age_minutes = int((datetime.now(UTC) - mtime).total_seconds() / 60)

    logger.debug(
        "checkpoint_freshness_check",
        path=str(path),
        is_fresh=is_fresh,
        age_minutes=age_minutes,
        cutoff_minutes=max_age_minutes,
    )

    return is_fresh


async def read_checkpoint(
    checkpoint_name: str, checkpoint_dir: Path
) -> dict[str, Any] | None:
    """
    Read checkpoint if fresh, otherwise return None.

    Args:
        checkpoint_name: Name of checkpoint (e.g., "tables_extracted")
        checkpoint_dir: Directory containing checkpoints

    Returns:
        Checkpoint data as dict if fresh, None if stale or missing

    Example:
        >>> checkpoint_dir = Path("data/checkpoints")
        >>> data = await read_checkpoint("tables_extracted", checkpoint_dir)
        >>> if data:
        ...     tables = [TableMetadata.model_validate(t) for t in data]
    """
    checkpoint_file = checkpoint_dir / f"{checkpoint_name}.json"

    if not is_file_fresh(checkpoint_file):
        logger.info(
            "checkpoint_stale_or_missing",
            checkpoint_name=checkpoint_name,
            path=str(checkpoint_file),
        )
        return None

    try:
        data = await read_json(checkpoint_file)

        logger.info(
            "checkpoint_loaded",
            checkpoint_name=checkpoint_name,
            path=str(checkpoint_file),
        )
        return data

    except ValueError as e:
        logger.error(
            "checkpoint_invalid_json",
            checkpoint_name=checkpoint_name,
            path=str(checkpoint_file),
            error=str(e),
        )
        return None
    except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
        logger.error(
            "checkpoint_read_error",
            checkpoint_name=checkpoint_name,
            path=str(checkpoint_file),
            error=str(e),
        )
        return None


async def write_checkpoint(
    checkpoint_name: str,
    data: Any,
    checkpoint_dir: Path,
) -> None:
    """
    Write checkpoint to disk.

    Creates checkpoint directory if it doesn't exist.
    Uses JSON with indent=2 for human readability.

    Args:
        checkpoint_name: Name of checkpoint (e.g., "tables_extracted")
        data: Data to serialize (must be JSON-serializable)
        checkpoint_dir: Directory to write checkpoint to

    Raises:
        OSError: If unable to create directory or write file

    Example:
        >>> checkpoint_dir = Path("data/checkpoints")
        >>> tables = [table.model_dump() for table in extracted_tables]
        >>> await write_checkpoint("tables_extracted", tables, checkpoint_dir)
    """
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = checkpoint_dir / f"{checkpoint_name}.json"

    try:
        await write_json(checkpoint_file, data, indent=2, default=str)

        logger.info(
            "checkpoint_saved",
            checkpoint_name=checkpoint_name,
            path=str(checkpoint_file),
        )

    except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
        logger.error(
            "checkpoint_write_error",
            checkpoint_name=checkpoint_name,
            path=str(checkpoint_file),
            error=str(e),
        )
        raise


def validate_checkpoint(  # noqa: UP047
    data: dict[str, Any] | list[dict[str, Any]], model: type[T]
) -> list[T] | None:
    """
    Validate checkpoint data against Pydantic model.

    Handles both single dict and list of dicts.
    Returns None if validation fails.

    Args:
        data: Checkpoint data (dict or list of dicts)
        model: Pydantic model class to validate against

    Returns:
        List of validated model instances, or None if validation fails

    Example:
        >>> checkpoint = read_checkpoint("tables_extracted", checkpoint_dir)
        >>> if checkpoint:
        ...     tables = validate_checkpoint(checkpoint, TableMetadata)
        ...     if tables:
        ...         print(f"Loaded {len(tables)} valid tables")
    """
    try:
        # Handle single dict (wrap in list)
        if isinstance(data, dict):
            data = [data]

        # Validate using TypeAdapter for list of models
        adapter: Any = TypeAdapter(list[model])  # type: ignore[valid-type]
        validated: list[T] = adapter.validate_python(data)

        logger.debug(
            "checkpoint_validated",
            model=model.__name__,
            count=len(validated),
        )
        return validated

    except ValidationError as e:
        logger.error(
            "checkpoint_validation_error",
            model=model.__name__,
            error=str(e),
            errors=e.errors(),
        )
        return None
    except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
        logger.error(
            "checkpoint_validation_unexpected_error",
            model=model.__name__,
            error=str(e),
        )
        return None
