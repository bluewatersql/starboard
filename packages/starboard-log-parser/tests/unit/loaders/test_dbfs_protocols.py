# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for log_parser loader protocols.

Tests the DBFSClient protocol definition and mock implementations.
Following TDD: Writing tests first, before implementation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest


def test_dbfs_client_protocol_methods_exist():
    """Test that DBFSClient protocol defines required methods."""
    from starboard_log_parser.loaders.protocols import DBFSClient

    # Verify protocol has required methods
    assert hasattr(DBFSClient, "dbfs_path_exists")
    assert hasattr(DBFSClient, "list_dbfs_files")
    assert hasattr(DBFSClient, "read_dbfs_chunk")


def test_dbfs_client_protocol_can_be_implemented():
    """Test that DBFSClient protocol can be implemented by a concrete class."""
    from starboard_log_parser.loaders.protocols import DBFSClient

    class MockDBFSClient:
        """Mock implementation of DBFSClient protocol."""

        def dbfs_path_exists(self, dbfs_path: str) -> bool:
            return True

        def list_dbfs_files(
            self, dbfs_path: str, recursive: bool = True
        ) -> list[dict[str, Any]]:
            return [
                {
                    "path": "/test/file1.json",
                    "is_dir": False,
                    "file_size": 1024,
                },
                {
                    "path": "/test/file2.json.gz",
                    "is_dir": False,
                    "file_size": 512,
                },
            ]

        def read_dbfs_chunk(
            self, dbfs_path: str, offset: int, length: int
        ) -> bytes | None:
            return b"test data"

    # Create instance
    client = MockDBFSClient()

    # Verify it implements the protocol
    assert isinstance(client, DBFSClient)

    # Test method calls
    assert client.dbfs_path_exists("/test/path") is True
    files = client.list_dbfs_files("/test")
    assert len(files) == 2
    assert files[0]["path"] == "/test/file1.json"

    chunk = client.read_dbfs_chunk("/test/file.json", 0, 1024)
    assert chunk == b"test data"


def test_dbfs_client_protocol_with_mock():
    """Test that DBFSClient protocol works with unittest.mock.Mock."""
    from starboard_log_parser.loaders.protocols import DBFSClient

    # Create a mock that implements the protocol
    mock_client = Mock(spec=DBFSClient)

    # Configure return values
    mock_client.dbfs_path_exists.return_value = True
    mock_client.list_dbfs_files.return_value = [
        {"path": "/test/file.json", "is_dir": False}
    ]
    mock_client.read_dbfs_chunk.return_value = b"chunk data"

    # Use the mock
    assert mock_client.dbfs_path_exists("/test") is True
    assert len(mock_client.list_dbfs_files("/test")) == 1
    assert mock_client.read_dbfs_chunk("/test/file", 0, 1024) == b"chunk data"

    # Verify calls
    mock_client.dbfs_path_exists.assert_called_once_with("/test")
    mock_client.list_dbfs_files.assert_called_once_with("/test")
    mock_client.read_dbfs_chunk.assert_called_once_with("/test/file", 0, 1024)


def test_dbfs_client_path_exists_signature():
    """Test dbfs_path_exists method signature."""

    class TestClient:
        def dbfs_path_exists(self, dbfs_path: str) -> bool:
            return dbfs_path.startswith("/")

        def list_dbfs_files(
            self, dbfs_path: str, recursive: bool = True
        ) -> list[dict[str, Any]]:
            return []

        def read_dbfs_chunk(
            self, dbfs_path: str, offset: int, length: int
        ) -> bytes | None:
            return None

    client = TestClient()

    # Test path exists logic
    assert client.dbfs_path_exists("/valid/path") is True
    assert client.dbfs_path_exists("invalid") is False


def test_dbfs_client_list_files_signature():
    """Test list_dbfs_files method signature and return structure."""

    class TestClient:
        def dbfs_path_exists(self, dbfs_path: str) -> bool:
            return True

        def list_dbfs_files(
            self, dbfs_path: str, recursive: bool = True
        ) -> list[dict[str, Any]]:
            files = [
                {"path": f"{dbfs_path}/file1.json", "is_dir": False, "file_size": 100},
                {
                    "path": f"{dbfs_path}/file2.json.gz",
                    "is_dir": False,
                    "file_size": 50,
                },
            ]

            if recursive:
                files.append(
                    {
                        "path": f"{dbfs_path}/subdir/file3.json",
                        "is_dir": False,
                        "file_size": 75,
                    }
                )

            return files

        def read_dbfs_chunk(
            self, dbfs_path: str, offset: int, length: int
        ) -> bytes | None:
            return None

    client = TestClient()

    # Test non-recursive
    files_non_recursive = client.list_dbfs_files("/test", recursive=False)
    assert len(files_non_recursive) == 2
    assert all(not f.get("is_dir") for f in files_non_recursive)

    # Test recursive
    files_recursive = client.list_dbfs_files("/test", recursive=True)
    assert len(files_recursive) == 3
    assert any("subdir" in f["path"] for f in files_recursive)


def test_dbfs_client_read_chunk_signature():
    """Test read_dbfs_chunk method signature and behavior."""

    class TestClient:
        def dbfs_path_exists(self, dbfs_path: str) -> bool:
            return True

        def list_dbfs_files(
            self, dbfs_path: str, recursive: bool = True
        ) -> list[dict[str, Any]]:
            return []

        def read_dbfs_chunk(
            self, dbfs_path: str, offset: int, length: int
        ) -> bytes | None:
            # Simulate reading a chunk
            full_data = b"0123456789" * 100  # 1000 bytes

            if offset >= len(full_data):
                return None

            end = min(offset + length, len(full_data))
            return full_data[offset:end]

    client = TestClient()

    # Test reading from offset 0
    chunk1 = client.read_dbfs_chunk("/test/file", 0, 100)
    assert chunk1 is not None
    assert len(chunk1) == 100
    assert chunk1.startswith(b"0123456789")

    # Test reading from offset 500
    chunk2 = client.read_dbfs_chunk("/test/file", 500, 100)
    assert chunk2 is not None
    assert len(chunk2) == 100

    # Test reading beyond file
    chunk3 = client.read_dbfs_chunk("/test/file", 10000, 100)
    assert chunk3 is None


def test_dbfs_client_protocol_type_hints():
    """Test that protocol methods have correct type hints."""
    import inspect

    # Get annotations for the protocol methods
    # Note: This test validates the protocol structure
    # The actual Protocol class will be checked at runtime

    class ConcreteClient:
        def dbfs_path_exists(self, dbfs_path: str) -> bool:
            return True

        def list_dbfs_files(
            self, dbfs_path: str, recursive: bool = True
        ) -> list[dict[str, Any]]:
            return []

        def read_dbfs_chunk(
            self, dbfs_path: str, offset: int, length: int
        ) -> bytes | None:
            return b""

    client = ConcreteClient()

    # Verify method exists and callable
    assert callable(client.dbfs_path_exists)
    assert callable(client.list_dbfs_files)
    assert callable(client.read_dbfs_chunk)

    # Verify signatures via inspection
    sig_exists = inspect.signature(client.dbfs_path_exists)
    assert "dbfs_path" in sig_exists.parameters
    # Note: return annotation is a string in some Python versions due to __future__ annotations
    assert sig_exists.return_annotation in (bool, "bool")

    sig_list = inspect.signature(client.list_dbfs_files)
    assert "dbfs_path" in sig_list.parameters
    assert "recursive" in sig_list.parameters

    sig_read = inspect.signature(client.read_dbfs_chunk)
    assert "dbfs_path" in sig_read.parameters
    assert "offset" in sig_read.parameters
    assert "length" in sig_read.parameters


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/Volumes/catalog/schema/volume/file.json", True),
        ("dbfs:/cluster-logs/eventlog", True),
        ("/mnt/logs/app.json.gz", True),
        ("", False),
        ("/nonexistent/path", False),
    ],
)
def test_dbfs_client_path_exists_scenarios(path: str, expected: bool):
    """Test dbfs_path_exists with various path scenarios."""

    class TestClient:
        VALID_PATHS = {
            "/Volumes/catalog/schema/volume/file.json",
            "dbfs:/cluster-logs/eventlog",
            "/mnt/logs/app.json.gz",
        }

        def dbfs_path_exists(self, dbfs_path: str) -> bool:
            return dbfs_path in self.VALID_PATHS

        def list_dbfs_files(
            self, dbfs_path: str, recursive: bool = True
        ) -> list[dict[str, Any]]:
            return []

        def read_dbfs_chunk(
            self, dbfs_path: str, offset: int, length: int
        ) -> bytes | None:
            return None

    client = TestClient()
    assert client.dbfs_path_exists(path) == expected


def test_dbfs_client_protocol_documentation():
    """Test that DBFSClient protocol has proper documentation."""
    from starboard_log_parser.loaders.protocols import DBFSClient

    # Verify protocol class has docstring
    assert DBFSClient.__doc__ is not None
    assert "DBFS" in DBFSClient.__doc__ or "protocol" in DBFSClient.__doc__.lower()
