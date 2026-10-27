# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for CloudStorageClient protocol.

Following TDD: tests written first, implementation follows.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from starboard_core.log_parser.loaders.protocols import CloudStorageClient


class TestCloudStorageClientProtocol:
    """Tests for CloudStorageClient protocol definition."""

    def test_protocol_structural_subtyping(self) -> None:
        """Any class with required methods should satisfy protocol."""

        class SimpleStorageClient:
            def path_exists(self, path: str) -> bool:
                return True

            def list_files(
                self,
                path: str,
                recursive: bool = True,
                pattern: str | None = None,
            ) -> list[dict[str, Any]]:
                return []

            def read_chunk(
                self,
                path: str,
                offset: int,
                length: int,
            ) -> bytes | None:
                return b""

            def get_file_size(self, path: str) -> int:
                return 0

        client = SimpleStorageClient()
        assert isinstance(client, CloudStorageClient)

    def test_protocol_requires_path_exists(self) -> None:
        """Protocol must have path_exists method."""

        class IncompleteClient:
            def list_files(self, path: str) -> list[dict[str, Any]]:
                return []

        client = IncompleteClient()
        assert not isinstance(client, CloudStorageClient)

    def test_protocol_requires_list_files(self) -> None:
        """Protocol must have list_files method."""

        class IncompleteClient:
            def path_exists(self, path: str) -> bool:
                return True

        client = IncompleteClient()
        assert not isinstance(client, CloudStorageClient)

    def test_protocol_requires_read_chunk(self) -> None:
        """Protocol must have read_chunk method."""

        class IncompleteClient:
            def path_exists(self, path: str) -> bool:
                return True

            def list_files(self, path: str) -> list[dict[str, Any]]:
                return []

        client = IncompleteClient()
        assert not isinstance(client, CloudStorageClient)

    def test_protocol_requires_get_file_size(self) -> None:
        """Protocol must have get_file_size method."""

        class IncompleteClient:
            def path_exists(self, path: str) -> bool:
                return True

            def list_files(self, path: str) -> list[dict[str, Any]]:
                return []

            def read_chunk(self, path: str, offset: int, length: int) -> bytes | None:
                return b""

        client = IncompleteClient()
        assert not isinstance(client, CloudStorageClient)

    def test_mock_cloud_storage_client(self) -> None:
        """Should be able to mock CloudStorageClient."""
        mock_client = Mock(spec=CloudStorageClient)
        mock_client.path_exists.return_value = True
        mock_client.list_files.return_value = []
        mock_client.read_chunk.return_value = b"data"
        mock_client.get_file_size.return_value = 1024

        assert isinstance(mock_client, CloudStorageClient)
        assert mock_client.path_exists("s3://bucket/key")
        assert mock_client.list_files("s3://bucket/") == []
        assert mock_client.read_chunk("s3://bucket/key", 0, 100) == b"data"
        assert mock_client.get_file_size("s3://bucket/key") == 1024

    def test_protocol_type_checking(self) -> None:
        """Protocol should enable type checking."""

        def use_storage(client: CloudStorageClient, path: str) -> bool:
            """Function that accepts any CloudStorageClient."""
            return client.path_exists(path)

        class MyStorageClient:
            def path_exists(self, path: str) -> bool:
                return True

            def list_files(
                self, path: str, recursive: bool = True, pattern: str | None = None
            ) -> list[dict[str, Any]]:
                return []

            def read_chunk(self, path: str, offset: int, length: int) -> bytes | None:
                return b""

            def get_file_size(self, path: str) -> int:
                return 0

        client = MyStorageClient()
        assert use_storage(client, "s3://bucket/key")

    def test_list_files_with_pattern(self) -> None:
        """list_files should support optional pattern parameter."""

        class PatternClient:
            def path_exists(self, path: str) -> bool:
                return True

            def list_files(
                self, path: str, recursive: bool = True, pattern: str | None = None
            ) -> list[dict[str, Any]]:
                # Should filter by pattern if provided
                if pattern == "*.json":
                    return [{"path": "s3://bucket/file.json", "size": 100}]
                return []

            def read_chunk(self, path: str, offset: int, length: int) -> bytes | None:
                return b""

            def get_file_size(self, path: str) -> int:
                return 0

        client = PatternClient()
        assert isinstance(client, CloudStorageClient)

        # Without pattern
        files = client.list_files("s3://bucket/")
        assert files == []

        # With pattern
        files = client.list_files("s3://bucket/", pattern="*.json")
        assert len(files) == 1
        assert files[0]["path"] == "s3://bucket/file.json"

    def test_protocol_documentation(self) -> None:
        """CloudStorageClient protocol should have proper documentation."""
        assert CloudStorageClient.__doc__ is not None
        assert "cloud storage" in CloudStorageClient.__doc__.lower()
