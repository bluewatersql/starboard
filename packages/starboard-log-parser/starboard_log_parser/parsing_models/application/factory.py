# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unified factory for creating SparkApplication instances.

Provides a single entry point for loading Spark applications from all
supported sources: local files, DBFS, Unity Catalog Volumes, S3, and HTTP/HTTPS.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from starboard_log_parser.exceptions import SparkLogPathNotFoundError
from starboard_log_parser.loaders import (
    AbstractFileDataLoader,
    ArchiveExtractionThresholds,
)
from starboard_log_parser.loaders.dbfs import DBFSFileLinesDataLoader
from starboard_log_parser.loaders.https import HTTPFileLinesDataLoader
from starboard_log_parser.loaders.json import JSONLinesDataLoader
from starboard_log_parser.loaders.local_file import (
    LocalFileLinesDataLoader,
)
from starboard_log_parser.parsing_models.application.loaders.ambiguous import (
    AmbiguousLogFormatSparkApplicationLoader,
)
from starboard_log_parser.parsing_models.application.loaders.base import (
    SparkApplicationClass,
)

logger = logging.getLogger(__name__)


def _build_s3_loader(
    thresholds: ArchiveExtractionThresholds,
) -> AbstractFileDataLoader:
    """Construct an S3 lines-data loader with environment credentials.

    Lazy-imports boto3 dependencies so the rest of the factory works
    without boto3 installed.

    Args:
        thresholds: Archive extraction thresholds for the loader.

    Returns:
        An S3FileLinesDataLoader ready to load files.
    """
    from starboard_log_parser.adapters.cloud.s3 import S3Adapter
    from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
    from starboard_log_parser.loaders.s3 import S3FileLinesDataLoader

    credential_provider = EnvironmentCredentialProvider(cloud="aws")
    s3_adapter = S3Adapter(credential_provider=credential_provider)
    return S3FileLinesDataLoader(
        s3_adapter=s3_adapter,
        extraction_thresholds=thresholds,
    )


def create_spark_application(
    *, path: str, thresholds: ArchiveExtractionThresholds | None = None
) -> SparkApplicationClass | None:
    """
    Create a SparkApplication from any supported path type.

    Auto-detects the path scheme and routes to the appropriate loader.
    Also auto-detects whether the file contains pre-parsed JSON or raw
    event logs.

    Args:
        path: Path to the Spark application log. Supported schemes:
            - Local files: ``/path/to/eventlog.gz``
            - DBFS: ``dbfs:/mnt/logs/eventlog``
            - Unity Catalog Volumes: ``/Volumes/catalog/schema/volume/logs/eventlog``
            - S3: ``s3://bucket/path/to/eventlog.json``
            - HTTP/HTTPS: ``https://example.com/eventlog.gz``
        thresholds: Optional extraction thresholds for archive processing.

    Returns:
        SparkApplicationClass instance with parsed log data, or None if
        logs do not exist at the given path.

    Raises:
        ValueError: If *path* is empty.

    Examples:
        >>> app = create_spark_application(path="/path/to/eventlog.gz")

        >>> app = create_spark_application(path="dbfs:/mnt/logs/eventlog")

        >>> app = create_spark_application(path="s3://bucket/logs/app.json")

    Notes:
        Unity Catalog Volume paths (``/Volumes/{catalog}/{schema}/{volume}/...``)
        are served via the DBFS API without requiring a ``dbfs:`` prefix.

        S3 support requires ``boto3``.  Credentials are read from the
        environment (``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
        ``AWS_REGION``).

        Missing logs are logged at DEBUG and ``None`` is returned instead
        of raising exceptions.
    """

    if not path:
        raise ValueError("No provided eventlog location.")

    path = str(path)
    parsed_path = urlparse(path)

    # Check if this is a Unity Catalog Volume path
    # Pattern: /Volumes/{catalog}/{schema}/{volume}/...
    is_volume_path = path.startswith("/Volumes/")

    # Validate path exists before attempting to load
    # For local paths, check filesystem existence (but not Volume paths)
    if not is_volume_path and (not parsed_path.scheme or parsed_path.scheme == "file"):
        local_path = Path(parsed_path.path if parsed_path.path else path)
        if not local_path.exists():
            logger.debug(
                f"Spark application log path does not exist: {path}",
                extra={"path": path, "scheme": "local"},
            )
            return None  # Return None instead of raising exception
    # For remote paths, defer existence validation to the loader
    elif is_volume_path:
        logger.debug(f"Loading Unity Catalog Volume path: {path}")
    elif parsed_path.scheme == "dbfs":
        logger.debug(f"Loading DBFS path (validation deferred to loader): {path}")
    elif parsed_path.scheme == "s3":
        logger.debug(f"Loading S3 path (validation deferred to loader): {path}")
    elif parsed_path.scheme in ("http", "https"):
        logger.debug(f"Loading HTTP(S) path (validation deferred to loader): {path}")

    thresholds = thresholds if thresholds is not None else ArchiveExtractionThresholds()

    file_loader: AbstractFileDataLoader
    if is_volume_path or parsed_path.scheme == "dbfs":
        file_loader = DBFSFileLinesDataLoader(extraction_thresholds=thresholds)
    elif parsed_path.scheme == "s3":
        file_loader = _build_s3_loader(thresholds)
    elif parsed_path.scheme in ("http", "https"):
        file_loader = HTTPFileLinesDataLoader(extraction_thresholds=thresholds)
    else:
        file_loader = LocalFileLinesDataLoader(extraction_thresholds=thresholds)

    json_loader = JSONLinesDataLoader(lines_data_loader=file_loader)
    app_loader = AmbiguousLogFormatSparkApplicationLoader(json_lines_loader=json_loader)

    try:
        result = app_loader.load(path)
        # Check if result is valid (has data)
        if result is None:
            logger.debug(f"No Spark logs found at path: {path}")
            return None
        return result
    except SparkLogPathNotFoundError as e:
        # Log as info instead of error - missing logs are not exceptional
        logger.debug(f"Spark logs not found at path {path}: {e}")
        return None
    except Exception as e:
        # Unexpected errors should still be logged as errors
        error_msg = str(e) if str(e) else repr(e)
        logger.error(
            f"Error loading Spark logs from {path}: {error_msg}",
            exc_info=True,  # Include full traceback in logs
        )
        return None
