# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Protocol definitions for log parser loader dependencies.

These protocols define the interface contracts that the log_parser requires
from external systems (Databricks API, cloud storage, etc.), allowing
dependency injection and loose coupling.

Using protocols (PEP 544 structural subtyping) allows any object that implements
the required methods to be used, without needing explicit inheritance.

Examples:
    >>> from starboard_log_parser.loaders.protocols import DBFSClient
    >>> from typing import Any
    >>>
    >>> class MyDBFSClient:
    ...     def dbfs_path_exists(self, dbfs_path: str) -> bool:
    ...         return True
    ...
    ...     def list_dbfs_files(
    ...         self, dbfs_path: str, recursive: bool = True
    ...     ) -> list[dict[str, Any]]:
    ...         return []
    ...
    ...     def read_dbfs_chunk(
    ...         self, dbfs_path: str, offset: int, length: int
    ...     ) -> bytes | None:
    ...         return b""
    >>>
    >>> client = MyDBFSClient()
    >>> assert isinstance(client, DBFSClient)  # Structural subtyping!
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DBFSClient(Protocol):
    """
    Protocol for DBFS file system operations.

    This protocol defines the minimal interface required for reading
    files from Databricks DBFS or Unity Catalog Volumes.

    Implementers can provide this interface using:
    - Databricks SDK WorkspaceClient.dbfs methods
    - Mock implementations for testing
    - Alternative DBFS client libraries
    - Custom implementations wrapping the Databricks REST API

    Methods:
        dbfs_path_exists: Check if a path exists
        list_dbfs_files: List files in a directory
        read_dbfs_chunk: Read a chunk of bytes from a file

    Notes:
        This is a Protocol (PEP 544), not an ABC. Classes don't need to
        explicitly inherit from it - they just need to implement the methods.

    Examples:
        >>> # Using with Databricks SDK (via adapter)
        >>> from databricks.sdk import WorkspaceClient
        >>>
        >>> class SDKAdapter:
        ...     def __init__(self, client: WorkspaceClient):
        ...         self._client = client
        ...
        ...     def dbfs_path_exists(self, dbfs_path: str) -> bool:
        ...         try:
        ...             self._client.dbfs.get_status(dbfs_path)
        ...             return True
        ...         except Exception:
        ...             return False
        ...
        ...     def list_dbfs_files(self, dbfs_path: str, recursive: bool = True):
        ...         files = []
        ...         for file_info in self._client.dbfs.list(dbfs_path, recursive=recursive):
        ...             files.append(file_info.as_dict())
        ...         return files
        ...
        ...     def read_dbfs_chunk(self, dbfs_path: str, offset: int, length: int):
        ...         import base64
        ...         response = self._client.dbfs.read(path=dbfs_path, offset=offset, length=length)
        ...         return base64.b64decode(response.data)
        >>>
        >>> sdk_client = WorkspaceClient()
        >>> dbfs_client = SDKAdapter(sdk_client)
        >>> # dbfs_client now implements DBFSClient protocol!
    """

    def dbfs_path_exists(self, dbfs_path: str) -> bool:
        """
        Check if a DBFS or Unity Catalog Volume path exists.

        This method should check both files and directories.

        Args:
            dbfs_path: Path to check (e.g., "/path/to/file" or "/Volumes/catalog/...")

        Returns:
            True if path exists (file or directory), False otherwise

        Notes:
            - Should handle both DBFS paths (/dbfs/..., dbfs://...)
            - Should handle Unity Catalog Volume paths (/Volumes/...)
            - Should not raise exceptions for non-existent paths
            - May raise exceptions for permission/network errors

        Examples:
            >>> client.dbfs_path_exists("/mnt/logs/app.json")  # True
            >>> client.dbfs_path_exists("/nonexistent/path")  # False
            >>> client.dbfs_path_exists("/Volumes/catalog/schema/volume/file.json")  # True
        """
        ...

    def list_dbfs_files(
        self, dbfs_path: str, recursive: bool = True
    ) -> list[dict[str, Any]]:
        """
        List files in a DBFS directory or Unity Catalog Volume.

        Args:
            dbfs_path: Directory path to list
            recursive: Whether to list recursively (default: True)

        Returns:
            List of file info dictionaries with at least:
                - "path": str - Full path to file
                - "is_dir": bool - Whether entry is a directory
                - "file_size": int - Size in bytes (optional)

        Notes:
            - Should only return files, not directories (when is_dir=False)
            - For non-existent paths, should return empty list (not raise)
            - Path should be normalized (no "dbfs:" prefix)
            - Recursive listing should flatten the directory tree

        Examples:
            >>> files = client.list_dbfs_files("/mnt/logs")
            >>> files[0]
            {'path': '/mnt/logs/app.json', 'is_dir': False, 'file_size': 1024}

            >>> # Non-recursive
            >>> files = client.list_dbfs_files("/mnt/logs", recursive=False)
            >>> # Returns only files in /mnt/logs, not subdirectories

            >>> # Empty result for non-existent path
            >>> files = client.list_dbfs_files("/nonexistent")
            >>> files  # []
        """
        ...

    def read_dbfs_chunk(self, dbfs_path: str, offset: int, length: int) -> bytes | None:
        """
        Read a chunk of bytes from a DBFS file.

        This method enables streaming file reads without loading the entire
        file into memory.

        Args:
            dbfs_path: File path to read
            offset: Byte offset to start reading from (0-indexed)
            length: Number of bytes to read

        Returns:
            Chunk data as bytes, or None if:
            - Offset is beyond end of file
            - File doesn't exist
            - Read operation fails

        Raises:
            Exception: May raise exceptions for permission/network errors
                      (specific exception type is implementation-dependent)

        Notes:
            - Should handle partial reads (when remaining bytes < length)
            - Should return actual bytes read, which may be < length
            - Offset beyond file size should return None
            - Empty file should return empty bytes (b"") for offset=0

        Examples:
            >>> # Read first 1MB
            >>> chunk1 = client.read_dbfs_chunk("/mnt/logs/app.json", 0, 1024*1024)
            >>> len(chunk1)  # <= 1048576

            >>> # Read next 1MB
            >>> chunk2 = client.read_dbfs_chunk("/mnt/logs/app.json", 1024*1024, 1024*1024)

            >>> # Offset beyond file returns None
            >>> chunk3 = client.read_dbfs_chunk("/mnt/logs/app.json", 999999999, 1024)
            >>> chunk3  # None
        """
        ...


@runtime_checkable
class CloudStorageClient(Protocol):
    """
    Protocol for cloud storage operations.

    Provides a unified interface across AWS S3, Azure ADLS Gen2, and GCP GCS.
    All implementations support streaming reads for memory efficiency and
    large file handling.

    This protocol enables:
    - Cloud-agnostic storage access
    - Dependency injection for testing
    - Adapter pattern for different cloud SDKs
    - Streaming file reads without loading entire files

    Methods:
        path_exists: Check if a storage path exists
        list_files: List files at a storage path
        read_chunk: Read a chunk of bytes from a file
        get_file_size: Get size of a file in bytes

    Notes:
        This is a Protocol (PEP 544), not an ABC. Classes don't need to
        explicitly inherit from it - they just need to implement the methods.

    Examples:
        >>> # Using with S3
        >>> class S3Client:
        ...     def path_exists(self, path: str) -> bool:
        ...         # Check if S3 object exists
        ...         return True
        ...
        ...     def list_files(self, path: str, recursive: bool = True, pattern: str | None = None):
        ...         # List S3 objects with optional pattern matching
        ...         return [{"path": "s3://bucket/file.json", "size": 1024}]
        ...
        ...     def read_chunk(self, path: str, offset: int, length: int) -> bytes | None:
        ...         # Read byte range from S3 object
        ...         return b"data"
        ...
        ...     def get_file_size(self, path: str) -> int:
        ...         # Get S3 object size
        ...         return 1024
        >>>
        >>> s3_client = S3Client()
        >>> # s3_client now implements CloudStorageClient protocol!
    """

    def path_exists(self, path: str) -> bool:
        """
        Check if a storage path exists.

        Args:
            path: Cloud storage path (e.g., "s3://bucket/key",
                  "abfss://container@account.dfs.core.windows.net/path",
                  "gs://bucket/object")

        Returns:
            True if path exists (file or prefix), False otherwise

        Notes:
            - Should handle both file paths and directory prefixes
            - Should not raise exceptions for non-existent paths
            - May raise exceptions for permission/network errors
            - Case sensitivity depends on cloud provider

        Examples:
            >>> client.path_exists("s3://my-bucket/logs/app.json")  # True
            >>> client.path_exists("s3://my-bucket/nonexistent/")  # False
            >>> client.path_exists("gs://bucket/data/")  # True (prefix exists)
        """
        ...

    def list_files(
        self,
        path: str,
        recursive: bool = True,
        pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List files at a storage path.

        Args:
            path: Cloud storage path to list
            recursive: Whether to list recursively (default: True)
            pattern: Optional glob pattern to filter files (e.g., "*.json")

        Returns:
            List of file info dictionaries with at least:
                - "path": str - Full cloud storage path to file
                - "size": int - Size in bytes
                - "last_modified": str - ISO 8601 timestamp (optional)
                - "etag": str - ETag/version identifier (optional)

        Notes:
            - Should only return files, not directories/prefixes
            - For non-existent paths, should return empty list (not raise)
            - Paths should be fully qualified (include scheme)
            - Recursive listing should flatten the directory tree
            - Pattern matching is optional but recommended

        Examples:
            >>> files = client.list_files("s3://my-bucket/logs/")
            >>> files[0]
            {'path': 's3://my-bucket/logs/app.json', 'size': 1024, 'last_modified': '2024-01-01T00:00:00Z'}

            >>> # Non-recursive
            >>> files = client.list_files("s3://my-bucket/logs/", recursive=False)
            >>> # Returns only files in logs/, not subdirectories

            >>> # With pattern
            >>> files = client.list_files("s3://my-bucket/logs/", pattern="*.json")
            >>> # Returns only JSON files

            >>> # Empty result for non-existent path
            >>> files = client.list_files("s3://my-bucket/nonexistent/")
            >>> files  # []
        """
        ...

    def read_chunk(
        self,
        path: str,
        offset: int,
        length: int,
    ) -> bytes | None:
        """
        Read a chunk of bytes from a file.

        This method enables streaming file reads without loading the entire
        file into memory. Uses byte range requests (HTTP Range header) under
        the hood for efficient partial downloads.

        Args:
            path: Cloud storage path to file
            offset: Byte offset to start reading from (0-indexed)
            length: Number of bytes to read

        Returns:
            Chunk data as bytes, or None if:
            - Offset is beyond end of file
            - File doesn't exist
            - Read operation fails

        Raises:
            Exception: May raise exceptions for permission/network errors
                      (specific exception type is implementation-dependent)

        Notes:
            - Should handle partial reads (when remaining bytes < length)
            - Should return actual bytes read, which may be < length
            - Offset beyond file size should return None
            - Empty file should return empty bytes (b"") for offset=0
            - Uses cloud provider's byte range request feature

        Examples:
            >>> # Read first 1MB
            >>> chunk1 = client.read_chunk("s3://my-bucket/logs/app.json", 0, 1024*1024)
            >>> len(chunk1)  # <= 1048576

            >>> # Read next 1MB (streaming)
            >>> chunk2 = client.read_chunk("s3://my-bucket/logs/app.json", 1024*1024, 1024*1024)

            >>> # Offset beyond file returns None
            >>> chunk3 = client.read_chunk("s3://my-bucket/logs/app.json", 999999999, 1024)
            >>> chunk3  # None
        """
        ...

    def get_file_size(self, path: str) -> int:
        """
        Get size of a file in bytes.

        This method should be efficient and not download the file content.
        Uses HEAD request or metadata API calls under the hood.

        Args:
            path: Cloud storage path to file

        Returns:
            File size in bytes

        Raises:
            Exception: May raise exceptions if file doesn't exist or
                      permission/network errors occur

        Notes:
            - Should use metadata/HEAD request, not download the file
            - Should be fast regardless of file size
            - May raise exception for non-existent files
            - May return 0 for empty files

        Examples:
            >>> size = client.get_file_size("s3://my-bucket/logs/app.json")
            >>> size  # 1024

            >>> # Works efficiently with large files
            >>> size = client.get_file_size("s3://my-bucket/large-file.tar.gz")
            >>> size  # 5368709120 (5GB)
        """
        ...
