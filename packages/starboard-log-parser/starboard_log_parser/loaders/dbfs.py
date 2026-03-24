"""
DBFS and Unity Catalog Volumes loader for Spark event logs.

This module provides a loader that can read event logs from:
- Databricks DBFS (dbfs:// or /path)
- Unity Catalog Volumes (/Volumes/{catalog}/{schema}/{volume})

Both use the Databricks REST API for file access.
"""

from __future__ import annotations

import logging
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.parse import ParseResult, urlparse

from databricks.sdk import WorkspaceClient

from starboard_log_parser.loaders import (
    AbstractFileDataLoader,
    BlobFileReaderMixin,
    FileChunkStreamWrapper,
    LinesFileReaderMixin,
)
from starboard_log_parser.loaders.dbfs_adapter import DatabricksSDKAdapter
from starboard_log_parser.loaders.protocols import DBFSClient

logger = logging.getLogger("DBFSLoader")


class ChunkStreamReader:
    """
    A file-like object that wraps a chunk generator for streaming reads.

    This allows treating a generator of byte chunks as a file-like object
    that can be read incrementally without loading the entire file into memory.
    """

    def __init__(self, chunk_generator):
        """
        Args:
            chunk_generator: Generator that yields bytes chunks
        """
        self._generator = chunk_generator
        self._buffer = bytearray()
        self._exhausted = False

    def read(self, size=-1):
        """
        Read up to size bytes from the stream.

        Args:
            size: Number of bytes to read (-1 means read all remaining)

        Returns:
            bytes: Data read from stream
        """
        if size == -1:
            # Read all remaining data
            result = bytes(self._buffer)
            self._buffer.clear()

            if not self._exhausted:
                for chunk in self._generator:
                    result += chunk
                self._exhausted = True

            return result

        # Read exactly 'size' bytes
        while len(self._buffer) < size and not self._exhausted:
            try:
                chunk = next(self._generator)
                self._buffer.extend(chunk)
            except StopIteration:
                self._exhausted = True
                break

        # Return up to 'size' bytes from buffer
        result = bytes(self._buffer[:size])
        self._buffer = self._buffer[size:]
        return result

    def readline(self, size=-1):
        """
        Read a line from the stream.

        Args:
            size: Maximum number of bytes to read

        Returns:
            bytes: Line data (including newline if present)
        """
        line = bytearray()

        while True:
            # Check if we have a newline in buffer
            try:
                newline_pos = self._buffer.index(b"\n")
                # Found newline in buffer
                line.extend(self._buffer[: newline_pos + 1])
                self._buffer = self._buffer[newline_pos + 1 :]
                break
            except ValueError:
                # No newline in buffer, need more data
                if self._exhausted:
                    # No more data, return what we have
                    line.extend(self._buffer)
                    self._buffer.clear()
                    break

                try:
                    chunk = next(self._generator)
                    self._buffer.extend(chunk)
                except StopIteration:
                    self._exhausted = True
                    line.extend(self._buffer)
                    self._buffer.clear()
                    break

            if size > 0 and len(line) >= size:
                break

        return bytes(line)

    def __iter__(self):
        """Iterate over lines in the stream."""
        return self

    def __next__(self):
        """Read the next line from the stream."""
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class AbstractDBFSFileDataLoader(AbstractFileDataLoader):
    """
    Abstract base class for loading files from Databricks File System (DBFS) using the REST API.

    This loader uses the Databricks SDK via DBFSClient protocol to read files from DBFS.
    It supports recursive directory listing and chunked file reading.

    Connection info is loaded from the environment config automatically via WorkspaceClient.
    Supported environment variables:
        - DATABRICKS_HOST
        - DATABRICKS_TOKEN
        - DATABRICKS_CONFIG_FILE
        - And others supported by the Databricks SDK

    Examples:
        dbfs:/databricks/eventlogs/cluster-id/eventlog.json
        dbfs:/FileStore/logs/app.json.gz
        /cluster-logs/eventlog.json (without dbfs: prefix)

    Args:
        dbfs_client: Optional DBFSClient implementation (e.g., DatabricksSDKAdapter).
                    If not provided, creates a default client from environment.
        save_to_disk: If True, saves downloaded files to a local temp directory.
                     If False (default), files are kept in memory only.
        temp_dir: Optional path to a temporary directory for saving files.
                 If not provided, uses system temp directory.
        streaming: If True (default), uses memory-efficient streaming to process files
                  chunk-by-chunk without loading entire file into memory.
                  If False, loads entire file into memory before processing.
    """

    def __init__(
        self,
        dbfs_client: DBFSClient | None = None,
        save_to_disk: bool = False,
        temp_dir: str | Path = None,
        streaming: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._dbfs_client = dbfs_client
        self.save_to_disk = save_to_disk
        self.streaming = streaming
        self.temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir())

        if self.save_to_disk and not self.temp_dir.exists():
            logger.debug(f"Creating temp directory: {self.temp_dir}")
            self.temp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def client(self) -> DBFSClient:
        """
        Lazy initialization of DBFSClient.

        Returns:
            DBFSClient implementation (default: DatabricksSDKAdapter)

        Raises:
            ConfigurationError: If client initialization fails
        """
        if self._dbfs_client is None:
            try:
                # Create WorkspaceClient from environment and wrap with adapter
                workspace_client = WorkspaceClient()
                self._dbfs_client = DatabricksSDKAdapter(workspace_client)
                logger.debug("Initialized DBFSClient from environment config")
            except Exception as e:
                logger.error(f"Failed to initialize Databricks client: {e}")
                raise
        return self._dbfs_client

    def _normalize_dbfs_path(self, filepath: str | ParseResult) -> str:
        """
        Normalize a DBFS or Unity Catalog Volume path to the format expected by the API.

        Args:
            filepath: Either a dbfs:// URI string, Volume path, or ParseResult

        Returns:
            Normalized path string (e.g., "/cluster-logs/..." or "/Volumes/...")

        Examples:
            dbfs:/path/to/file -> /path/to/file
            /dbfs/path/to/file -> /path/to/file
            /path/to/file -> /path/to/file
            /Volumes/catalog/schema/volume/path -> /Volumes/catalog/schema/volume/path (unchanged)
        """
        if isinstance(filepath, str):
            # Unity Catalog Volume paths are already normalized - pass through as-is
            if filepath.startswith("/Volumes/"):
                return filepath

            # Handle dbfs:// prefix
            if filepath.startswith("dbfs:"):
                filepath = filepath[5:]  # Remove "dbfs:"
            # Handle /dbfs/ prefix (old mount-based paths)
            if filepath.startswith("/dbfs/"):
                filepath = filepath[5:]  # Remove "/dbfs"
            # Ensure leading slash
            if not filepath.startswith("/"):
                filepath = "/" + filepath
            return filepath

        # Handle ParseResult
        parsed = (
            filepath if isinstance(filepath, ParseResult) else urlparse(str(filepath))
        )
        path = parsed.path

        # Unity Catalog Volume paths are already normalized - pass through as-is
        if path.startswith("/Volumes/"):
            return path

        # Remove /dbfs prefix if present
        if path.startswith("/dbfs/"):
            path = path[5:]

        # Ensure leading slash
        if not path.startswith("/"):
            path = "/" + path

        return path

    def _list_files(self, dbfs_path: str, recursive: bool = True) -> list[str]:
        """
        List files in a DBFS directory or Unity Catalog Volume.

        Args:
            dbfs_path: Path to list (normalized, starting with / or /Volumes/)
            recursive: Whether to list recursively

        Returns:
            List of file paths (empty list if path doesn't exist)
        """
        try:
            # Check if path exists first
            if not self.client.dbfs_path_exists(dbfs_path):
                logger.debug(f"DBFS path does not exist: {dbfs_path}")
                return []

            # Use DatabricksAPI to list files
            files = self.client.list_dbfs_files(dbfs_path, recursive=recursive)
            file_paths = []

            for file_info in files:
                # Skip directories - we only want files
                if not file_info.get("is_dir", False):
                    # The file_info dict has a 'path' key
                    path = file_info.get("path")
                    if path:
                        # Normalize the path (remove dbfs: prefix if present)
                        if path.startswith("dbfs:"):
                            path = path[5:]
                        file_paths.append(path)
                        logger.debug(f"Found file: {path}")

            if not file_paths:
                logger.debug(f"No files found in DBFS path: {dbfs_path}")
            else:
                logger.debug(f"Found {len(file_paths)} files in {dbfs_path}")

            return file_paths

        except Exception as e:
            logger.warning(f"Error listing DBFS path {dbfs_path}: {e}")
            return []

    def _stream_file_chunks(self, dbfs_path: str):
        """
        Stream a file from DBFS or Unity Catalog Volume in chunks (generator).

        This yields chunks as they're downloaded, allowing for memory-efficient
        processing of large files without loading everything into memory at once.

        Args:
            dbfs_path: Path to read (normalized, starting with / or /Volumes/)

        Yields:
            bytes: Chunks of file data
        """
        chunk_size = 1024 * 1024  # 1 MB chunks
        offset = 0

        logger.debug(f"Streaming file from DBFS: {dbfs_path}")

        try:
            total_bytes = 0
            while True:
                # Read a chunk from DBFS using DatabricksAPI
                chunk_data = self.client.read_dbfs_chunk(
                    dbfs_path=dbfs_path, offset=offset, length=chunk_size
                )

                if not chunk_data:
                    break

                yield chunk_data
                total_bytes += len(chunk_data)
                logger.debug(f"Streamed {len(chunk_data)} bytes from offset {offset}")

                offset += len(chunk_data)

                # Check if we've reached the end of file
                if len(chunk_data) < chunk_size:
                    break

            logger.debug(f"Successfully streamed {total_bytes} bytes from {dbfs_path}")

        except Exception as e:
            logger.error(f"Error streaming file {dbfs_path}: {e}")
            raise

    def _read_file_to_buffer(self, dbfs_path: str) -> bytearray:
        """
        Read a file from DBFS or Unity Catalog Volume into an in-memory buffer.

        Note: This loads the entire file into memory. For large files, consider
        using _stream_file_chunks() instead for memory-efficient streaming.

        Args:
            dbfs_path: Path to read (normalized, starting with / or /Volumes/)

        Returns:
            bytearray containing the file contents
        """
        buffer = bytearray()
        for chunk in self._stream_file_chunks(dbfs_path):
            buffer.extend(chunk)
        return buffer

    def _save_buffer_to_disk(self, buffer: bytearray, original_path: str) -> Path:
        """
        Save a buffer to a local temp file.

        Args:
            buffer: Data to save
            original_path: Original DBFS path (used to derive filename)

        Returns:
            Path to the saved file
        """
        # Extract filename from the original path
        filename = Path(original_path).name

        # Create a unique temp file with the original filename pattern
        local_path = self.temp_dir / filename

        # Handle filename collisions by appending a counter
        counter = 1
        while local_path.exists():
            stem = Path(original_path).stem
            suffix = "".join(Path(original_path).suffixes)
            local_path = self.temp_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        with open(local_path, "wb") as f:
            f.write(buffer)

        logger.debug(f"Saved {len(buffer)} bytes to {local_path}")
        return local_path

    def load_item(self, filepath):
        """
        Load a file or directory from DBFS using the REST API.

        Args:
            filepath: DBFS URI (dbfs://...) or DBFS path (/...)

        Yields:
            Tuples of (Path, file_stream) for each file found
        """
        try:
            dbfs_path = self._normalize_dbfs_path(filepath)
            logger.debug(f"Loading from DBFS path: {dbfs_path}")

            # Check if path exists first
            if not self.client.dbfs_path_exists(dbfs_path):
                logger.debug(f"Spark log path does not exist: {dbfs_path}")
                return  # Return empty generator instead of raising exception

            # Try to determine if this is a file or directory
            # First, try listing it as a directory
            try:
                file_paths = self._list_files(dbfs_path, recursive=True)

                # If no files found, might be a single file
                if not file_paths:
                    # Check if it's a file before trying to read it
                    if self.client.dbfs_path_exists(dbfs_path):
                        file_paths = [dbfs_path]
                    else:
                        logger.debug(f"No files found at path: {dbfs_path}")
                        return
            except Exception:
                # If listing fails, check if single file exists
                if self.client.dbfs_path_exists(dbfs_path):
                    file_paths = [dbfs_path]
                else:
                    logger.debug(
                        f"Path does not exist or is not accessible: {dbfs_path}"
                    )
                    return

            # Process each file
            for file_path in file_paths:
                try:
                    if self.save_to_disk:
                        # Need to buffer to save to disk
                        buffer = self._read_file_to_buffer(file_path)
                        local_path = self._save_buffer_to_disk(buffer, file_path)
                        yield from self.extract(local_path)
                    elif self.streaming:
                        # True streaming - process chunks as they arrive
                        chunk_generator = self._stream_file_chunks(file_path)
                        file_stream = ChunkStreamReader(chunk_generator)
                        wrapped = FileChunkStreamWrapper(file_stream)

                        # Extract filename for Path object
                        file_name = Path(file_path)
                        yield from self.extract(file_name, wrapped)
                    else:
                        # Non-streaming - buffer entire file in memory
                        buffer = self._read_file_to_buffer(file_path)
                        file_stream = BytesIO(buffer)
                        wrapped = FileChunkStreamWrapper(file_stream)

                        # Extract filename for Path object
                        file_name = Path(file_path)
                        yield from self.extract(file_name, wrapped)

                except Exception as e:
                    logger.warning(f"Error processing file {file_path}: {e}")
                    # Continue with next file instead of failing completely
                    continue

        except Exception as e:
            logger.warning(f"Error loading from DBFS path {filepath}: {e}")
            # Return empty generator instead of raising
            return


class DBFSFileBlobDataLoader(BlobFileReaderMixin, AbstractDBFSFileDataLoader):
    """
    DBFS loader that returns files as complete blobs.
    Useful for loading entire JSON files into memory.
    """

    pass


class DBFSFileLinesDataLoader(LinesFileReaderMixin, AbstractDBFSFileDataLoader):
    """
    DBFS loader that returns files as line-by-line streams.
    Useful for loading JSON Lines or large event logs.

    This is the recommended loader for Spark event logs.
    """

    pass
