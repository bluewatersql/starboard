"""
Adapters to make Databricks SDK clients compatible with DBFSClient protocol.

This adapter module allows using the Databricks SDK WorkspaceClient directly
with the log_parser's DBFS loaders, without creating hard dependencies.

Examples:
    >>> # Using with Databricks SDK directly
    >>> from databricks.sdk import WorkspaceClient
    >>> from starboard_log_parser.loaders.dbfs_adapter import DatabricksSDKAdapter
    >>>
    >>> sdk_client = WorkspaceClient(host="...", token="...")
    >>> dbfs_client = DatabricksSDKAdapter(sdk_client)
    >>> loader = DBFSFileLinesDataLoader(dbfs_client=dbfs_client)
"""

from __future__ import annotations

import base64
import logging
from typing import Any

logger = logging.getLogger("DBFSAdapter")


class DatabricksSDKAdapter:
    """
    Adapter to use Databricks SDK WorkspaceClient directly with DBFSClient protocol.

    This is a lightweight adapter for cases where you only need DBFS access.
    It directly wraps the databricks-sdk WorkspaceClient and implements the
    DBFSClient protocol.

    Args:
        workspace_client: Instance of databricks.sdk.WorkspaceClient

    Examples:
        >>> from databricks.sdk import WorkspaceClient
        >>> from starboard_log_parser.loaders.dbfs_adapter import DatabricksSDKAdapter
        >>> from starboard_log_parser.loaders.dbfs import DBFSFileLinesDataLoader
        >>>
        >>> sdk_client = WorkspaceClient(host="https://dbc-xxx.cloud.databricks.com", token="...")
        >>> dbfs_client = DatabricksSDKAdapter(sdk_client)
        >>> loader = DBFSFileLinesDataLoader(dbfs_client=dbfs_client)
        >>>
        >>> # Load from Unity Catalog Volume
        >>> app = loader.load("/Volumes/catalog/schema/volume/logs/eventlog.json.gz")
    """

    def __init__(self, workspace_client):
        """
        Initialize adapter with Databricks SDK client.

        Args:
            workspace_client: databricks.sdk.WorkspaceClient instance
        """
        self._client = workspace_client

    def dbfs_path_exists(self, dbfs_path: str) -> bool:
        """
        Check if a DBFS or Volume path exists.

        Uses the SDK's dbfs.get_status() method. Returns False on any exception
        (e.g., path not found, permission denied) to match protocol expectations.

        Args:
            dbfs_path: Path to check

        Returns:
            True if path exists and is accessible, False otherwise
        """
        try:
            self._client.dbfs.get_status(dbfs_path)
            return True
        except Exception:
            # Any exception (NotFound, PermissionDenied, etc.) means path doesn't exist
            # or isn't accessible, which we treat as "doesn't exist" for our purposes
            return False

    def list_dbfs_files(
        self, dbfs_path: str, recursive: bool = True
    ) -> list[dict[str, Any]]:
        """
        List files in a DBFS directory.

        Uses the SDK's dbfs.list() method and converts file info objects to dicts.

        Args:
            dbfs_path: Directory path to list
            recursive: Whether to list recursively

        Returns:
            List of file info dictionaries, or empty list on error
        """
        try:
            files = []
            for file_info in self._client.dbfs.list(dbfs_path, recursive=recursive):
                # Convert SDK object to dict
                files.append(file_info.as_dict())
            return files
        except Exception:
            # Log and return empty list (path doesn't exist or permission denied)
            logger.debug(f"DBFS path does not exist or is inaccessible: {dbfs_path}")
            return []

    def read_dbfs_chunk(self, dbfs_path: str, offset: int, length: int) -> bytes | None:
        """
        Read a chunk of bytes from DBFS file.

        Uses the SDK's dbfs.read() method and decodes base64 response data.

        Args:
            dbfs_path: File path to read
            offset: Byte offset to start reading from
            length: Number of bytes to read

        Returns:
            Chunk data as bytes, or None if no data

        Raises:
            Exception: If read operation fails (permission, network errors, etc.)
        """
        try:
            read_response = self._client.dbfs.read(
                path=dbfs_path, offset=offset, length=length
            )

            # Handle both dict and object responses
            content_b64 = (
                read_response.get("data")
                if isinstance(read_response, dict)
                else getattr(read_response, "data", None)
            )

            if content_b64 is None:
                return None

            # Decode base64-encoded data
            return base64.b64decode(content_b64)

        except Exception as e:
            logger.error(f"Error reading DBFS file {dbfs_path} at offset {offset}: {e}")
            raise
