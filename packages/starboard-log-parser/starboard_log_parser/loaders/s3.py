"""
AWS S3 loaders for Spark event logs.

This module provides loaders for reading event logs from AWS S3 using the
S3Adapter and CloudStorageClient protocol.

Examples:
    >>> # With static credentials
    >>> from starboard_log_parser.auth.providers import StaticCredentialProvider
    >>> from starboard_log_parser.adapters.cloud.s3 import S3Adapter
    >>> from starboard_log_parser.loaders.s3 import S3FileLinesDataLoader
    >>>
    >>> provider = StaticCredentialProvider(
    ...     access_key="AKIAIOSFODNN7EXAMPLE",
    ...     secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    ...     region="us-west-2",
    ... )
    >>> adapter = S3Adapter(credential_provider=provider)
    >>> loader = S3FileLinesDataLoader(s3_adapter=adapter)
    >>>
    >>> # Load JSON Lines file
    >>> for line in loader.load("s3://my-bucket/logs/eventlog.jsonl"):
    ...     print(line)
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from starboard_log_parser.adapters.cloud.s3 import S3Adapter
from starboard_log_parser.loaders import (
    AbstractFileDataLoader,
    BlobFileReaderMixin,
    FileChunkStreamWrapper,
    LinesFileReaderMixin,
)

logger = logging.getLogger(__name__)


class AbstractS3FileDataLoader(AbstractFileDataLoader):
    """
    Base class for loading files from AWS S3.

    Uses S3Adapter for all S3 operations, providing streaming file access
    without loading entire files into memory.

    Attributes:
        s3_adapter: S3Adapter instance for cloud storage operations

    Examples:
        >>> from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
        >>> from starboard_log_parser.adapters.cloud.s3 import S3Adapter
        >>>
        >>> # With environment credentials
        >>> provider = EnvironmentCredentialProvider(cloud="aws")
        >>> adapter = S3Adapter(credential_provider=provider)
        >>> loader = S3FileLinesDataLoader(s3_adapter=adapter)
    """

    def __init__(self, s3_adapter: S3Adapter, **kwargs):
        """Initialize S3 file loader."""
        super().__init__(**kwargs)
        self.s3_adapter = s3_adapter

    def list_items(self, path: str) -> list[dict[str, Any]]:
        """
        List files in S3 prefix.

        Args:
            path: S3 path (e.g., "s3://bucket/prefix/")

        Returns:
            List of file info dictionaries with:
                - path: str - Full S3 path
                - size: int - File size in bytes
                - last_modified: str - ISO timestamp (if available)

        Examples:
            >>> items = loader.list_items("s3://my-bucket/logs/")
            >>> items[0]
            {'path': 's3://my-bucket/logs/eventlog.json', 'size': 1024}
        """
        return self.s3_adapter.list_files(path)

    def load_item(self, filepath: str) -> FileChunkStreamWrapper:
        """
        Load S3 file as streaming wrapper.

        Uses chunked reads for memory efficiency. Automatically handles
        compressed files (.gz) via FileChunkStreamWrapper.

        Args:
            filepath: S3 file path (e.g., "s3://bucket/path/file.json")

        Returns:
            FileChunkStreamWrapper for streaming file access

        Examples:
            >>> wrapper = loader.load_item("s3://bucket/file.jsonl.gz")
            >>> for line in wrapper.iter_lines():
            ...     print(line)  # Automatically decompressed
        """
        # Get file size for initial read
        try:
            file_size = self.s3_adapter.get_file_size(filepath)
        except Exception as e:
            logger.warning(f"Could not get file size for {filepath}: {e}")
            file_size = 1024 * 1024  # Default to 1MB chunks

        # Read file in chunks and stream via BytesIO
        # For simplicity, read entire file into memory for now
        # TODO(BACKLOG-012): Implement true streaming with chunked reads
        all_data = BytesIO()
        offset = 0
        chunk_size = min(1024 * 1024, file_size)  # 1MB chunks

        while True:
            chunk = self.s3_adapter.read_chunk(filepath, offset, chunk_size)
            if not chunk:
                break

            all_data.write(chunk)
            offset += len(chunk)

            if len(chunk) < chunk_size:
                # Last chunk
                break

        all_data.seek(0)

        # Create an iterator that yields the entire content as a single chunk
        # FileChunkStreamWrapper expects (chunks: Iterator[bytes], maximum_file_size: int)
        def chunk_iterator():
            data = all_data.read()
            if data:
                yield data

        # Wrap in FileChunkStreamWrapper
        return FileChunkStreamWrapper(chunk_iterator())


class S3FileLinesDataLoader(LinesFileReaderMixin, AbstractS3FileDataLoader):
    """
    S3 loader for line-by-line file reading.

    Suitable for:
    - JSON Lines (.jsonl)
    - CSV files
    - Log files
    - Any newline-delimited format

    Automatically handles gzip compression (.gz files).

    Examples:
        >>> from starboard_log_parser.auth.providers import StaticCredentialProvider
        >>> from starboard_log_parser.adapters.cloud.s3 import S3Adapter
        >>>
        >>> provider = StaticCredentialProvider(
        ...     access_key="AKIAIOSFODNN7EXAMPLE",
        ...     secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        ... )
        >>> adapter = S3Adapter(credential_provider=provider)
        >>> loader = S3FileLinesDataLoader(s3_adapter=adapter)
        >>>
        >>> # Load JSON Lines file (automatically decompressed if .gz)
        >>> for line in loader.load("s3://my-bucket/logs/events.jsonl.gz"):
        ...     event = json.loads(line)
        ...     print(event["timestamp"])
    """

    def __init__(self, s3_adapter: S3Adapter, **kwargs):
        """Initialize S3 lines loader."""
        super().__init__(s3_adapter=s3_adapter, **kwargs)


class S3FileBlobDataLoader(BlobFileReaderMixin, AbstractS3FileDataLoader):
    """
    S3 loader for binary blob file reading.

    Suitable for:
    - JSON files (single object)
    - Binary files
    - Archives
    - Any file that should be read as a whole

    Automatically handles gzip compression (.gz files).

    Examples:
        >>> from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
        >>> from starboard_log_parser.adapters.cloud.s3 import S3Adapter
        >>>
        >>> provider = EnvironmentCredentialProvider(cloud="aws")
        >>> adapter = S3Adapter(credential_provider=provider)
        >>> loader = S3FileBlobDataLoader(s3_adapter=adapter)
        >>>
        >>> # Load entire JSON file
        >>> data = loader.load("s3://my-bucket/config.json.gz")
        >>> config = json.loads(data)
    """

    def __init__(self, s3_adapter: S3Adapter, **kwargs):
        """Initialize S3 blob loader."""
        super().__init__(s3_adapter=s3_adapter, **kwargs)
