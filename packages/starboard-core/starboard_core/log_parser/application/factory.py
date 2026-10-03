# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Factory functions for creating SparkApplication from in-memory data.

Provides helpers for building SparkApplication domain models from
JSON files, dictionaries, and raw string/bytes content.

For path-based loading (local, DBFS, S3, HTTP) use the unified
``create_spark_application`` in
``starboard_core.log_parser.parsing_models.application.factory``.
"""

from __future__ import annotations

import gzip
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import orjson
import polars as pl

from starboard_core.log_parser.adapters.parsers.parsed_log import (
    ParsedLogParser,
)
from starboard_core.log_parser.domain.models.application import (
    SparkApplication,
)
from starboard_core.log_parser.domain.models.info import SparkApplicationInfo
from starboard_core.log_parser.domain.models.metadata import SparkApplicationMetadata

logger = logging.getLogger(__name__)


def _convert_application_model_to_domain(
    app_model: Any,
) -> SparkApplication:
    """
    Convert a mutable ApplicationModel to an immutable SparkApplication domain model.

    This helper uses the ComputerRegistry to compute all required DataFrames
    from the parsed ApplicationModel, then builds the immutable domain model.

    Args:
        app_model: Parsed ApplicationModel from event_log_parser

    Returns:
        Immutable SparkApplication domain model

    Raises:
        ValueError: If conversion fails due to missing data
    """
    from starboard_core.log_parser.parsing_models.computers.registry import (
        ComputerRegistry,
    )

    computers = ComputerRegistry.create_default()

    # Compute all DataFrames using the computer registry
    sql_df = computers.sql_computer.compute(app_model)
    executor_df = computers.executor_computer.compute(app_model)
    job_df = computers.job_computer.compute(app_model, sql_data=sql_df)
    task_df = computers.task_computer.compute(app_model)
    stage_df = computers.stage_computer.compute(
        app_model,
        task_data=task_df if task_df is not None else pl.DataFrame(),
        sql_data=sql_df if sql_df is not None else pl.DataFrame(),
    )
    accum_df = computers.accum_computer.compute(app_model, sql_data=sql_df)

    # Build application info
    app_info = SparkApplicationInfo(
        timestamp_start_ms=int(app_model.start_time * 1000)
        if app_model.start_time
        else 0,
        timestamp_end_ms=int(app_model.finish_time * 1000)
        if app_model.finish_time
        else 0,
        runtime_sec=(
            app_model.finish_time - app_model.start_time
            if app_model.finish_time and app_model.start_time
            else 0.0
        ),
        name=getattr(app_model, "app_name", ""),
        id=getattr(app_model, "app_id", ""),
        spark_version=app_model.spark_version or "",
        emr_version_tag=app_model.emr_version_tag or "",
        cloud_platform=app_model.cloud_platform or "",
        cloud_provider=app_model.cloud_provider or "",
        cluster_id=app_model.cluster_id or "",
    )

    # Build metadata
    has_sql = sql_df is not None and len(sql_df) > 0
    has_executors = executor_df is not None and len(executor_df) > 0

    metadata = SparkApplicationMetadata(
        application_info=app_info,
        spark_params=getattr(app_model, "spark_metadata", {}),
        exists_sql=has_sql,
        exists_executors=has_executors,
    )

    # Build immutable domain model
    return SparkApplication(
        metadata=metadata,
        job_data=job_df if job_df is not None else pl.DataFrame(),
        stage_data=stage_df if stage_df is not None else pl.DataFrame(),
        task_data=task_df if task_df is not None else pl.DataFrame(),
        accum_data=accum_df if accum_df is not None else pl.DataFrame(),
        sql_data=sql_df if has_sql else None,
        executor_data=executor_df if has_executors else None,
    )


def _is_event_log_content(content: str) -> bool:
    """
    Detect if content is a raw Spark event log (JSON lines) vs pre-parsed JSON.

    Event logs are JSON-lines format with one event per line.
    Pre-parsed logs are a single JSON object with "jobData" key.

    Args:
        content: Raw string content

    Returns:
        True if content appears to be event log lines, False if pre-parsed
    """
    # First, try to parse the entire content as a single JSON object
    # This handles pretty-printed (multi-line) pre-parsed JSON
    try:
        full_obj = orjson.loads(content)
        if isinstance(full_obj, dict) and "jobData" in full_obj:
            return False
        if isinstance(full_obj, dict) and "metadata" in full_obj:
            return False
    except orjson.JSONDecodeError:
        # Try cleaning NaN/Infinity before giving up on full parse
        try:
            cleaned = re.sub(r"\bNaN\b", "null", content)
            cleaned = re.sub(r"\bInfinity\b", "null", cleaned)
            cleaned = re.sub(r"\b-Infinity\b", "null", cleaned)
            full_obj = orjson.loads(cleaned)
            if isinstance(full_obj, dict) and "jobData" in full_obj:
                return False
            if isinstance(full_obj, dict) and "metadata" in full_obj:
                return False
        except orjson.JSONDecodeError:
            pass

    # Check first non-empty line (for JSON lines format)
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            first_obj = orjson.loads(line)
            # Pre-parsed applications have "jobData"
            if isinstance(first_obj, dict) and "jobData" in first_obj:
                return False
            # Event logs have "Event" field
            if isinstance(first_obj, dict) and "Event" in first_obj:
                return True
            # If it's a single line with metadata, check further
            if isinstance(first_obj, dict) and "metadata" in first_obj:
                return False
        except orjson.JSONDecodeError:
            # First line not valid JSON - could be multi-line JSON or invalid
            pass
        break

    # Default to treating as event log if we can't determine
    return True


def _parse_event_log_content(content: str) -> Iterator[dict[str, Any]]:
    """
    Parse event log content (JSON lines) into an iterator of event dicts.

    Handles:
    - Standard JSON lines (one event per line)
    - Lines with leading/trailing whitespace
    - Empty lines and comments
    - Lines with NaN/Infinity values

    Args:
        content: Event log content as string

    Yields:
        Parsed event dictionaries
    """
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip lines that don't look like JSON
        if not line.startswith("{"):
            continue

        try:
            yield orjson.loads(line)
        except orjson.JSONDecodeError:
            # Try cleaning NaN/Infinity values
            try:
                cleaned = re.sub(r"\bNaN\b", "null", line)
                cleaned = re.sub(r"\bInfinity\b", "null", cleaned)
                cleaned = re.sub(r"\b-Infinity\b", "null", cleaned)
                yield orjson.loads(cleaned)
            except orjson.JSONDecodeError:
                logger.debug(f"Skipping unparseable line: {line[:100]}...")
                continue


def create_spark_application_from_json(
    filepath: str | Path,
) -> SparkApplication:
    """
    Create a SparkApplication from a pre-parsed JSON file.

    This function loads a previously saved Spark application analysis
    (in JSON format) and rehydrates it into an immutable SparkApplication
    domain model. It handles both compressed (.json.gz) and uncompressed
    (.json) files.

    Args:
        filepath: Path to the JSON file containing parsed application data.
                  Can be a string or Path object.
                  Supports both .json and .json.gz files.

    Returns:
        Immutable SparkApplication domain model

    Raises:
        FileNotFoundError: If the file doesn't exist
        orjson.JSONDecodeError: If the JSON is malformed
        KeyError: If required fields are missing from the JSON
        ValueError: If the data is inconsistent (e.g., metadata flags don't match data)

    Examples:
        >>> # Load uncompressed JSON
        >>> app = create_spark_application_from_json("my_spark_app.json")
        >>> app.metadata.application_info.name
        'MySparkApp'

        >>> # Load compressed JSON
        >>> app = create_spark_application_from_json("my_spark_app.json.gz")
        >>> len(app.job_data)
        42

    Notes:
        - This function is for rehydrating previously parsed applications
        - For parsing raw Spark event logs, use other factory functions
        - The JSON must follow the expected SparkApplication format
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Spark application JSON file not found: {filepath}")

    logger.debug(
        "loading_spark_application_from_json",
        extra={"filepath": str(filepath), "compressed": filepath.suffix == ".gz"},
    )

    # Load JSON data
    if filepath.suffix == ".gz":
        with gzip.open(filepath, "rb") as f:
            raw_data: dict[str, Any] = orjson.loads(f.read())
    else:
        with open(filepath, "rb") as f:
            raw_data = orjson.loads(f.read())

    # Parse into domain model
    parser = ParsedLogParser()
    app = parser.parse(raw_data)

    logger.debug(
        "loaded_spark_application_from_json",
        extra={
            "filepath": str(filepath),
            "app_id": app.metadata.application_info.id,
            "app_name": app.metadata.application_info.name,
            "num_jobs": len(app.job_data),
            "num_stages": len(app.stage_data),
            "num_tasks": len(app.task_data),
            "has_sql": app.has_sql_data(),
            "has_executors": app.has_executor_data(),
        },
    )

    return app


def create_spark_application_from_dict(
    data: dict[str, Any],
) -> SparkApplication:
    """
    Create a SparkApplication from a dictionary (already loaded JSON).

    Useful for testing, API responses, or when you already have the
    data loaded in memory.

    Args:
        data: Dictionary containing parsed application data

    Returns:
        Immutable SparkApplication domain model

    Raises:
        KeyError: If required fields are missing
        ValueError: If the data is inconsistent

    Examples:
        >>> data = {
        ...     "metadata": {...},
        ...     "jobData": {...},
        ...     # ... other data
        ... }
        >>> app = create_spark_application_from_dict(data)
        >>> app.metadata.exists_sql
        True
    """
    parser = ParsedLogParser()
    return parser.parse(data)


def create_spark_application_from_content(
    content: str | bytes,
    *,
    debug: bool = False,
    enable_streaming_validation: bool = False,
) -> SparkApplication:
    """
    Create a SparkApplication from string or bytes content.

    This factory function handles content provided directly (e.g., from user uploads)
    without requiring a file path. It auto-detects whether the content is:
    - Pre-parsed JSON (a single JSON object with "jobData")
    - Raw Spark event log (JSON lines format)

    For raw event logs, this function uses the full parsing pipeline including
    ApplicationModel and ComputerRegistry to build the immutable domain model.

    Args:
        content: Spark application data as string or bytes.
                 Can be pre-parsed JSON or raw event log lines.
        debug: If True, skip validation checks that would raise exceptions.
               Useful for partially complete logs.
        enable_streaming_validation: If True, validate events during parsing
                                     for fail-fast error detection.

    Returns:
        Immutable SparkApplication domain model

    Raises:
        orjson.JSONDecodeError: If content is not valid JSON
        KeyError: If required fields are missing (pre-parsed format)
        ValueError: If data is inconsistent
        UrgentEventValidationException: If critical event data is missing
        LogSubmissionException: If rollover logs are incomplete

    Examples:
        >>> # From pre-parsed JSON content
        >>> content = '{"metadata": {...}, "jobData": {...}, ...}'
        >>> app = create_spark_application_from_content(content)
        >>> len(app.job_data)
        42

        >>> # From raw event log content
        >>> event_log = '''
        ... {"Event": "SparkListenerApplicationStart", "Timestamp": 1234567890}
        ... {"Event": "SparkListenerJobStart", "Job ID": 0, "Stage IDs": [0]}
        ... '''
        >>> app = create_spark_application_from_content(event_log)
        >>> len(app.job_data)
        1

        >>> # From bytes (e.g., file upload)
        >>> with open("eventlog.json", "rb") as f:
        ...     app = create_spark_application_from_content(f.read())

    Notes:
        - Automatically detects pre-parsed vs raw event log format
        - Uses full parsing pipeline with ComputerRegistry for raw logs
        - Handles NaN/Infinity values in legacy logs
        - Thread-safe (no shared mutable state)
    """
    # Convert bytes to string if needed
    if isinstance(content, bytes):
        content = content.decode("utf-8")

    content_size = len(content)
    logger.debug(
        "parsing_spark_application_from_content",
        extra={"content_size": content_size},
    )

    # Detect format
    if not _is_event_log_content(content):
        # Pre-parsed JSON format
        logger.debug("detected_preparsed_json_format")

        # Handle multi-line JSON (pretty printed)
        try:
            raw_data: dict[str, Any] = orjson.loads(content)
        except orjson.JSONDecodeError:
            # Try with NaN/Infinity cleanup
            cleaned = re.sub(r"\bNaN\b", "null", content)
            cleaned = re.sub(r"\bInfinity\b", "null", cleaned)
            cleaned = re.sub(r"\b-Infinity\b", "null", cleaned)
            raw_data = orjson.loads(cleaned)

        parser = ParsedLogParser()
        app = parser.parse(raw_data)

        logger.debug(
            "parsed_preparsed_json_content",
            extra={
                "content_size": content_size,
                "app_id": app.metadata.application_info.id,
                "num_jobs": len(app.job_data),
                "num_stages": len(app.stage_data),
                "num_tasks": len(app.task_data),
            },
        )

        return app

    # Raw event log format (JSON lines)
    logger.debug("detected_event_log_format")

    from starboard_core.log_parser.parsing_models.event_log_parser import (
        ApplicationModel,
    )

    # Parse using ApplicationModel
    lines_iterator = _parse_event_log_content(content)
    app_model = ApplicationModel(
        log_lines=lines_iterator,
        debug=debug,
        enable_streaming_validation=enable_streaming_validation,
    )

    # Convert to immutable domain model
    app = _convert_application_model_to_domain(app_model)

    logger.debug(
        "parsed_event_log_content",
        extra={
            "content_size": content_size,
            "app_id": app.metadata.application_info.id,
            "num_jobs": len(app.job_data),
            "num_stages": len(app.stage_data),
            "num_tasks": len(app.task_data),
            "has_sql": app.has_sql_data(),
            "has_executors": app.has_executor_data(),
        },
    )

    return app
