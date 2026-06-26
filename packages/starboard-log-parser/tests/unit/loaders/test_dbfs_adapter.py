# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for DBFS adapter implementations.

Tests the adapters that bridge between the DBFSClient protocol and
the Databricks SDK.

Following TDD: Writing tests first, before implementation.
"""

from __future__ import annotations

import base64
from unittest.mock import Mock

import pytest


class TestDatabricksSDKAdapter:
    """Tests for the DatabricksSDKAdapter class."""

    def test_sdk_adapter_implements_protocol(self):
        """Test that DatabricksSDKAdapter implements DBFSClient protocol."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )
        from starboard_log_parser.loaders.protocols import DBFSClient

        # Create mock SDK client
        mock_client = Mock()
        mock_client.dbfs.get_status.return_value = {}
        mock_client.dbfs.list.return_value = []
        mock_client.dbfs.read.return_value = Mock(data="")

        adapter = DatabricksSDKAdapter(mock_client)

        assert isinstance(adapter, DBFSClient)

    def test_sdk_adapter_path_exists_true(self):
        """Test dbfs_path_exists returns True when path exists."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )

        mock_client = Mock()
        mock_client.dbfs.get_status.return_value = {"path": "/test", "is_dir": False}

        adapter = DatabricksSDKAdapter(mock_client)
        result = adapter.dbfs_path_exists("/test/file.json")

        assert result is True
        mock_client.dbfs.get_status.assert_called_once_with("/test/file.json")

    def test_sdk_adapter_path_exists_false(self):
        """Test dbfs_path_exists returns False when path doesn't exist."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )

        mock_client = Mock()
        mock_client.dbfs.get_status.side_effect = Exception("Not found")

        adapter = DatabricksSDKAdapter(mock_client)
        result = adapter.dbfs_path_exists("/nonexistent")

        assert result is False
        mock_client.dbfs.get_status.assert_called_once_with("/nonexistent")

    def test_sdk_adapter_list_files(self):
        """Test list_dbfs_files returns file list."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )

        mock_client = Mock()

        # Create mock file objects
        mock_file1 = Mock()
        mock_file1.as_dict.return_value = {
            "path": "/test/file1.json",
            "is_dir": False,
            "file_size": 100,
        }

        mock_file2 = Mock()
        mock_file2.as_dict.return_value = {
            "path": "/test/file2.json",
            "is_dir": False,
            "file_size": 50,
        }

        mock_client.dbfs.list.return_value = [mock_file1, mock_file2]

        adapter = DatabricksSDKAdapter(mock_client)
        result = adapter.list_dbfs_files("/test", recursive=True)

        assert len(result) == 2
        assert result[0]["path"] == "/test/file1.json"
        assert result[1]["path"] == "/test/file2.json"
        mock_client.dbfs.list.assert_called_once_with("/test", recursive=True)

    def test_sdk_adapter_list_files_exception(self):
        """Test list_dbfs_files returns empty list on exception."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )

        mock_client = Mock()
        mock_client.dbfs.list.side_effect = Exception("Permission denied")

        adapter = DatabricksSDKAdapter(mock_client)
        result = adapter.list_dbfs_files("/restricted")

        assert result == []

    def test_sdk_adapter_read_chunk(self):
        """Test read_dbfs_chunk returns decoded data."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )

        mock_client = Mock()

        # Base64 encoded "test data"
        test_data = b"test data"
        encoded_data = base64.b64encode(test_data).decode("utf-8")

        mock_response = Mock()
        mock_response.data = encoded_data
        mock_client.dbfs.read.return_value = mock_response

        adapter = DatabricksSDKAdapter(mock_client)
        result = adapter.read_dbfs_chunk("/test/file", 0, 1024)

        assert result == test_data
        mock_client.dbfs.read.assert_called_once_with(
            path="/test/file", offset=0, length=1024
        )

    def test_sdk_adapter_read_chunk_dict_response(self):
        """Test read_dbfs_chunk handles dict response."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )

        mock_client = Mock()

        test_data = b"dict response data"
        encoded_data = base64.b64encode(test_data).decode("utf-8")

        mock_client.dbfs.read.return_value = {"data": encoded_data}

        adapter = DatabricksSDKAdapter(mock_client)
        result = adapter.read_dbfs_chunk("/test/file", 100, 200)

        assert result == test_data

    def test_sdk_adapter_read_chunk_no_data(self):
        """Test read_dbfs_chunk returns None when no data."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )

        mock_client = Mock()
        mock_client.dbfs.read.return_value = Mock(data=None)

        adapter = DatabricksSDKAdapter(mock_client)
        result = adapter.read_dbfs_chunk("/test/file", 0, 1024)

        assert result is None

    def test_sdk_adapter_read_chunk_exception(self):
        """Test read_dbfs_chunk raises on exception."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )

        mock_client = Mock()
        mock_client.dbfs.read.side_effect = Exception("Read failed")

        adapter = DatabricksSDKAdapter(mock_client)

        with pytest.raises(Exception, match="Read failed"):
            adapter.read_dbfs_chunk("/test/file", 0, 1024)


class TestAdapterIntegration:
    """Integration tests for adapter usage patterns."""

    def test_adapter_is_usable_as_dbfs_client(self):
        """Test that SDK adapter can be used as DBFSClient."""
        from starboard_log_parser.loaders.dbfs_adapter import (
            DatabricksSDKAdapter,
        )
        from starboard_log_parser.loaders.protocols import DBFSClient

        # Should be usable as DBFSClient
        def use_dbfs_client(client: DBFSClient) -> bool:
            return client.dbfs_path_exists("/test")

        # Create mock
        mock_sdk = Mock()
        mock_sdk.dbfs.get_status.return_value = {}

        # Adapter works
        adapter = DatabricksSDKAdapter(mock_sdk)
        assert use_dbfs_client(adapter) is True


def test_adapter_module_exports():
    """Test that adapter classes are exported from module."""
    from starboard_log_parser.loaders import dbfs_adapter

    assert hasattr(dbfs_adapter, "DatabricksSDKAdapter")
    cls = dbfs_adapter.DatabricksSDKAdapter
    assert callable(cls)
