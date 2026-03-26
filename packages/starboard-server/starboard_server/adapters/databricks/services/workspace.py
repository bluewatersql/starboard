"""Async Workspace service implementation.

This module provides async workspace and DBFS operations for Databricks.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from databricks.sdk.errors import NotFound
from databricks.sdk.service.workspace import ExportFormat

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.reliability.exceptions import DatabricksAPIError

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = get_logger(__name__)

class WorkspaceService(BaseService):
    """Async service for Databricks workspace and DBFS operations.

    Provides async methods for:
    - Notebook content retrieval
    - Workspace file export/import
    - DBFS file operations

    Example:
        >>> service = WorkspaceService(workspace_client)
        >>> content = await service.get_notebook_content("/Users/me/notebook")
        >>> exists = await service.dbfs_path_exists("dbfs:/data/file.csv")
    """

    def __init__(self, client: WorkspaceClient) -> None:
        """Initialize workspace service.

        Args:
            client: Authenticated Databricks WorkspaceClient
        """
        super().__init__(client)

    # =========================================================================
    # Workspace File Operations
    # =========================================================================

    async def get_notebook_content(self, notebook_path: str) -> str | None:
        """Get notebook content from workspace path.

        Args:
            notebook_path: Workspace path to notebook

        Returns:
            Notebook content as string, or None if not found

        Example:
            >>> content = await service.get_notebook_content("/Users/me/etl_notebook")
            >>> print(content[:100])
        """
        return await self.export_workspace_file(notebook_path, ExportFormat.SOURCE)

    async def export_workspace_file(
        self,
        path: str,
        format: ExportFormat = ExportFormat.SOURCE,
    ) -> str | None:
        """Export source code from workspace path.

        Args:
            path: Workspace path to export
            format: Export format (SOURCE, HTML, JUPYTER, DBC)

        Returns:
            File content as string, or None if not found
        """
        logger.debug(
            "export_workspace_file", extra={"path": path, "format": format.value}
        )

        def _export() -> str | None:
            try:
                exported = self._client.workspace.export(path=path, format=format)
                content_b64 = (
                    exported.get("content")
                    if isinstance(exported, dict)
                    else getattr(exported, "content", None)
                )
                if content_b64 is None:
                    return None

                try:
                    return base64.b64decode(content_b64).decode(
                        "utf-8", errors="replace"
                    )
                except (DatabricksAPIError, OSError):
                    if isinstance(content_b64, str):
                        return content_b64
                    raise
            except NotFound:
                logger.warning("workspace_path_not_found", extra={"path": path})
                return None

        return await self._run_with_retry(_export, max_retries=3, retry_delay=1.0)

    async def workspace_mkdir(self, path: str) -> None:
        """Create a directory in the workspace.

        Args:
            path: Path to create

        Example:
            >>> await service.workspace_mkdir("/Users/me/new_folder")
        """
        logger.debug("workspace_mkdir", extra={"path": path})
        await self._run_sync(lambda: self._client.workspace.mkdirs(path))

    async def workspace_import(
        self,
        content: str,
        path: str | None = None,
        overwrite: bool = True,
    ) -> None:
        """Import a file into the workspace.

        Args:
            content: Content to import
            path: Path to import to (defaults to user's home directory)
            overwrite: Overwrite existing file
        """
        logger.debug("workspace_import", extra={"path": path, "overwrite": overwrite})

        def _import() -> None:
            target_path = path
            if target_path is None:
                target_path = f"/Users/{self._client.current_user.me().user_name}"

            self._client.workspace.import_file(  # type: ignore[attr-defined]
                content=content,
                path=target_path,
                overwrite=overwrite,
            )

        await self._run_sync(_import)

    # =========================================================================
    # DBFS Operations
    # =========================================================================

    async def dbfs_path_exists(self, dbfs_path: str) -> bool:
        """Check if a DBFS or Volume path exists.

        Args:
            dbfs_path: DBFS path to check (can be file or directory)

        Returns:
            True if path exists, False otherwise

        Example:
            >>> exists = await service.dbfs_path_exists("dbfs:/data/input.csv")
            >>> if exists:
            ...     print("File found")
        """
        logger.debug("dbfs_path_exists", extra={"dbfs_path": dbfs_path})

        def _exists() -> bool:
            try:
                self._client.dbfs.get_status(dbfs_path)
                return True
            except NotFound:
                return False
            except (DatabricksAPIError, OSError) as e:
                logger.debug(
                    "dbfs_path_check_failed",
                    extra={"dbfs_path": dbfs_path, "error": str(e)},
                )
                return False

        return await self._run_sync(_exists)

    async def read_dbfs_file(
        self,
        dbfs_path: str,
        max_bytes: int = 2_000_000,
    ) -> str | None:
        """Read text file from DBFS.

        Args:
            dbfs_path: DBFS path to read
            max_bytes: Maximum bytes to read

        Returns:
            File content as string, or None if read fails

        Example:
            >>> content = await service.read_dbfs_file("dbfs:/data/config.json")
            >>> config = json.loads(content)
        """
        logger.debug(
            "read_dbfs_file", extra={"dbfs_path": dbfs_path, "max_bytes": max_bytes}
        )

        def _read() -> str | None:
            try:
                data = self._client.dbfs.read(dbfs_path, offset=0, length=max_bytes)
                content_b64 = (
                    data.get("data")
                    if isinstance(data, dict)
                    else getattr(data, "data", None)
                )
                if content_b64 is None:
                    return None
                return base64.b64decode(content_b64).decode("utf-8", errors="replace")
            except (DatabricksAPIError, OSError) as e:
                logger.warning(
                    "read_dbfs_file_failed",
                    extra={"dbfs_path": dbfs_path, "error": str(e)},
                )
                return None

        return await self._run_sync(_read)

    async def list_dbfs_files(
        self,
        dbfs_path: str,
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        """List files in a DBFS directory.

        Args:
            dbfs_path: DBFS path to list
            recursive: Whether to list recursively

        Returns:
            List of file info dictionaries

        Example:
            >>> files = await service.list_dbfs_files("dbfs:/data/")
            >>> for f in files:
            ...     print(f"{f['path']}: {f['file_size']} bytes")
        """
        logger.debug(
            "list_dbfs_files",
            extra={"dbfs_path": dbfs_path, "recursive": recursive},
        )

        def _list() -> list[dict[str, Any]]:
            try:
                files = []
                for file_info in self._client.dbfs.list(dbfs_path, recursive=recursive):
                    files.append(file_info.as_dict())
                return files
            except NotFound:
                logger.debug("dbfs_path_not_found", extra={"dbfs_path": dbfs_path})
                return []

        try:
            return await self._run_sync(_list)
        except NotFound:
            return []
        except (DatabricksAPIError, OSError) as e:
            logger.error(
                "list_dbfs_files_failed",
                extra={"dbfs_path": dbfs_path, "error": str(e)},
            )
            raise DatabricksAPIError(
                message=f"Failed to list DBFS path {dbfs_path}",
                details={"dbfs_path": dbfs_path, "error": str(e)},
            ) from e

    async def read_dbfs_chunk(
        self,
        dbfs_path: str,
        offset: int,
        length: int,
    ) -> bytes | None:
        """Read a chunk of bytes from DBFS file.

        Args:
            dbfs_path: DBFS path to read
            offset: Byte offset to start reading from
            length: Number of bytes to read

        Returns:
            Chunk data as bytes, or None if read fails

        Example:
            >>> chunk = await service.read_dbfs_chunk("dbfs:/data/large.bin", 0, 1024)
            >>> len(chunk)
            1024
        """
        logger.debug(
            "read_dbfs_chunk",
            extra={"dbfs_path": dbfs_path, "offset": offset, "length": length},
        )

        def _read_chunk() -> bytes | None:
            try:
                read_response = self._client.dbfs.read(
                    path=dbfs_path,
                    offset=offset,
                    length=length,
                )
                content_b64 = (
                    read_response.get("data")
                    if isinstance(read_response, dict)
                    else getattr(read_response, "data", None)
                )
                if content_b64 is None:
                    return None
                return base64.b64decode(content_b64)
            except (DatabricksAPIError, OSError) as e:
                logger.error(
                    "read_dbfs_chunk_failed",
                    extra={"dbfs_path": dbfs_path, "offset": offset, "error": str(e)},
                )
                raise DatabricksAPIError(
                    message=f"Failed to read DBFS file {dbfs_path}",
                    details={
                        "dbfs_path": dbfs_path,
                        "offset": offset,
                        "length": length,
                        "error": str(e),
                    },
                ) from e

        return await self._run_sync(_read_chunk)
