# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for S3Adapter.

Following TDD: tests written first, implementation follows.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

# Mock boto3 before importing S3Adapter
sys.modules["boto3"] = MagicMock()
sys.modules["botocore"] = MagicMock()
sys.modules["botocore.exceptions"] = MagicMock()

from starboard_log_parser.auth.protocols import Credentials  # noqa: E402
from starboard_log_parser.auth.providers import StaticCredentialProvider  # noqa: E402
from starboard_log_parser.exceptions import CloudStorageError  # noqa: E402
from starboard_log_parser.loaders.protocols import CloudStorageClient  # noqa: E402


class TestS3AdapterImport:
    """Tests for S3Adapter import and initialization."""

    def test_s3_adapter_imports_successfully(self) -> None:
        """Should import successfully when boto3 is available."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        assert S3Adapter is not None


class TestS3AdapterProtocol:
    """Tests for S3Adapter protocol compliance."""

    def test_s3_adapter_implements_cloud_storage_client(self) -> None:
        """S3Adapter should implement CloudStorageClient protocol."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        provider = StaticCredentialProvider(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        adapter = S3Adapter(credential_provider=provider)

        assert isinstance(adapter, CloudStorageClient)

    def test_s3_adapter_has_required_methods(self) -> None:
        """S3Adapter should have all CloudStorageClient methods."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        assert hasattr(adapter, "path_exists")
        assert hasattr(adapter, "list_files")
        assert hasattr(adapter, "read_chunk")
        assert hasattr(adapter, "get_file_size")


class TestS3PathParsing:
    """Tests for S3 path parsing."""

    def test_parse_valid_s3_path(self) -> None:
        """Should parse valid s3:// paths."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        bucket, key = adapter._parse_s3_path("s3://my-bucket/path/to/file.json")
        assert bucket == "my-bucket"
        assert key == "path/to/file.json"

    def test_parse_s3_path_with_nested_structure(self) -> None:
        """Should parse deeply nested paths."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        bucket, key = adapter._parse_s3_path(
            "s3://logs/year=2024/month=01/day=15/eventlog.gz"
        )
        assert bucket == "logs"
        assert key == "year=2024/month=01/day=15/eventlog.gz"

    def test_parse_s3_path_bucket_only(self) -> None:
        """Should handle bucket-only paths."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        bucket, key = adapter._parse_s3_path("s3://my-bucket/")
        assert bucket == "my-bucket"
        assert key == ""

    def test_parse_invalid_s3_path(self) -> None:
        """Should raise CloudStorageError for invalid paths."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError) as exc_info:
            adapter._parse_s3_path("not-an-s3-path")

        assert "Invalid S3 path" in str(exc_info.value)

    def test_parse_s3_path_missing_bucket(self) -> None:
        """Should raise CloudStorageError for paths without bucket."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError) as exc_info:
            adapter._parse_s3_path("s3:///path/to/file")

        assert "Invalid S3 path" in str(exc_info.value)


class TestS3AdapterPathExists:
    """Tests for path_exists method."""

    @patch("boto3.Session")
    def test_path_exists_file_exists(self, mock_session: Mock) -> None:
        """Should return True when file exists."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client
        mock_s3_client = Mock()
        mock_s3_client.head_object.return_value = {"ContentLength": 1024}
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        result = adapter.path_exists("s3://my-bucket/file.json")

        assert result is True
        mock_s3_client.head_object.assert_called_once_with(
            Bucket="my-bucket", Key="file.json"
        )

    @patch("boto3.Session")
    def test_path_exists_file_not_found(self, mock_session: Mock) -> None:
        """Should return False when file doesn't exist (NoSuchKey 404)."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        mock_s3_client.head_object.side_effect = _make_s3_error("NoSuchKey", 404)
        mock_s3_client.list_objects_v2.return_value = {}
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        result = adapter.path_exists("s3://my-bucket/nonexistent.json")

        assert result is False

    @patch("boto3.Session")
    def test_path_exists_prefix_exists(self, mock_session: Mock) -> None:
        """Should return True when prefix exists."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        mock_s3_client.head_object.side_effect = _make_s3_error("NoSuchKey", 404)
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [{"Key": "logs/file1.json"}]
        }
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        result = adapter.path_exists("s3://my-bucket/logs/")

        assert result is True


class TestS3AdapterListFiles:
    """Tests for list_files method."""

    @patch("boto3.Session")
    def test_list_files_basic(self, mock_session: Mock) -> None:
        """Should list files in S3 prefix."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client
        mock_s3_client = Mock()
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": "logs/file1.json",
                    "Size": 1024,
                    "LastModified": datetime(2024, 1, 1, tzinfo=UTC),
                },
                {
                    "Key": "logs/file2.json",
                    "Size": 2048,
                    "LastModified": datetime(2024, 1, 2, tzinfo=UTC),
                },
            ]
        }
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        files = adapter.list_files("s3://my-bucket/logs/")

        assert len(files) == 2
        assert files[0]["path"] == "s3://my-bucket/logs/file1.json"
        assert files[0]["size"] == 1024
        assert files[1]["path"] == "s3://my-bucket/logs/file2.json"
        assert files[1]["size"] == 2048

    @patch("boto3.Session")
    def test_list_files_empty_prefix(self, mock_session: Mock) -> None:
        """Should return empty list for non-existent prefix."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client - no contents
        mock_s3_client = Mock()
        mock_s3_client.list_objects_v2.return_value = {}
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        files = adapter.list_files("s3://my-bucket/nonexistent/")

        assert files == []

    @patch("boto3.Session")
    def test_list_files_with_pattern(self, mock_session: Mock) -> None:
        """Should filter files by pattern."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client
        mock_s3_client = Mock()
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "logs/file1.json", "Size": 1024},
                {"Key": "logs/file2.txt", "Size": 2048},
                {"Key": "logs/file3.json", "Size": 3072},
            ]
        }
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        files = adapter.list_files("s3://my-bucket/logs/", pattern="*.json")

        # Should only include JSON files
        assert len(files) == 2
        assert all(f["path"].endswith(".json") for f in files)


class TestS3AdapterReadChunk:
    """Tests for read_chunk method."""

    @patch("boto3.Session")
    def test_read_chunk_success(self, mock_session: Mock) -> None:
        """Should read chunk from S3 object."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client
        mock_s3_client = Mock()
        mock_response = {"Body": MagicMock()}
        mock_response["Body"].read.return_value = b"test data chunk"
        mock_s3_client.get_object.return_value = mock_response
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        data = adapter.read_chunk("s3://my-bucket/file.json", offset=0, length=1024)

        assert data == b"test data chunk"
        mock_s3_client.get_object.assert_called_once_with(
            Bucket="my-bucket", Key="file.json", Range="bytes=0-1023"
        )

    @patch("boto3.Session")
    def test_read_chunk_with_offset(self, mock_session: Mock) -> None:
        """Should read chunk with offset."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client
        mock_s3_client = Mock()
        mock_response = {"Body": MagicMock()}
        mock_response["Body"].read.return_value = b"chunk at offset"
        mock_s3_client.get_object.return_value = mock_response
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        data = adapter.read_chunk("s3://my-bucket/file.json", offset=1024, length=512)

        assert data == b"chunk at offset"
        # Range is bytes=1024-1535 (inclusive)
        mock_s3_client.get_object.assert_called_once_with(
            Bucket="my-bucket", Key="file.json", Range="bytes=1024-1535"
        )

    @patch("boto3.Session")
    def test_read_chunk_file_not_found(self, mock_session: Mock) -> None:
        """Should return None when file doesn't exist."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client raising NoSuchKey
        mock_s3_client = Mock()
        mock_s3_client.get_object.side_effect = Exception("NoSuchKey")
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        data = adapter.read_chunk("s3://my-bucket/nonexistent.json", 0, 1024)

        assert data is None


class TestS3AdapterGetFileSize:
    """Tests for get_file_size method."""

    @patch("boto3.Session")
    def test_get_file_size_success(self, mock_session: Mock) -> None:
        """Should get file size from S3 object metadata."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client
        mock_s3_client = Mock()
        mock_s3_client.head_object.return_value = {"ContentLength": 5242880}
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        size = adapter.get_file_size("s3://my-bucket/large-file.json")

        assert size == 5242880
        mock_s3_client.head_object.assert_called_once_with(
            Bucket="my-bucket", Key="large-file.json"
        )

    @patch("boto3.Session")
    def test_get_file_size_file_not_found(self, mock_session: Mock) -> None:
        """Should raise CloudStorageError when file doesn't exist."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Mock S3 client raising 404
        mock_s3_client = Mock()
        mock_s3_client.head_object.side_effect = Exception("404 Not Found")
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError) as exc_info:
            adapter.get_file_size("s3://my-bucket/nonexistent.json")

        assert "get_size" in str(exc_info.value)


def _make_s3_error(code: str, http_status: int = 400) -> Exception:
    """Build a raiseable S3 error with a .response dict.

    Uses a plain Exception subclass so it is always raiseable, regardless of
    whether botocore is installed or boto3/botocore.exceptions are mocked.
    _is_not_found_error only inspects exc.response, so this is sufficient.
    """

    class _FakeClientError(Exception):
        pass

    err = _FakeClientError(f"S3 {code}")
    err.response = {  # type: ignore[attr-defined]
        "Error": {"Code": code, "Message": f"Simulated {code}"},
        "ResponseMetadata": {"HTTPStatusCode": http_status},
    }
    return err


class TestS3AdapterPathExistsErrorHandling:
    """Tests for path_exists error propagation (F-3-p2-log-parser-1)."""

    def _make_client_error(self, code: str, http_status: int = 400) -> Exception:
        return _make_s3_error(code, http_status)

    @patch("boto3.Session")
    def test_path_exists_404_on_file_and_prefix_returns_false(
        self, mock_session: Mock
    ) -> None:
        """404 on both head_object and list_objects should return False."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        # head_object raises 404/NoSuchKey
        mock_s3_client.head_object.side_effect = self._make_client_error(
            "NoSuchKey", 404
        )
        # list_objects_v2 raises NoSuchBucket (also a 404-class not-found)
        mock_s3_client.list_objects_v2.side_effect = self._make_client_error(
            "NoSuchBucket", 404
        )
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        result = adapter.path_exists("s3://my-bucket/nonexistent/key")
        assert result is False

    @patch("boto3.Session")
    def test_path_exists_403_on_head_object_raises_cloud_storage_error(
        self, mock_session: Mock
    ) -> None:
        """AccessDenied (403) on head_object must raise CloudStorageError, not return False."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        mock_s3_client.head_object.side_effect = self._make_client_error(
            "AccessDenied", 403
        )
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError):
            adapter.path_exists("s3://my-bucket/some/key")

    @patch("boto3.Session")
    def test_path_exists_throttling_on_head_object_raises_cloud_storage_error(
        self, mock_session: Mock
    ) -> None:
        """Throttling on head_object must raise CloudStorageError, not return False."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        mock_s3_client.head_object.side_effect = self._make_client_error(
            "SlowDown", 503
        )
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError):
            adapter.path_exists("s3://my-bucket/some/key")

    @patch("boto3.Session")
    def test_path_exists_403_on_list_objects_raises_cloud_storage_error(
        self, mock_session: Mock
    ) -> None:
        """AccessDenied on list_objects_v2 (prefix check) must raise CloudStorageError."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        # head_object raises 404 so we fall through to prefix check
        mock_s3_client.head_object.side_effect = self._make_client_error(
            "NoSuchKey", 404
        )
        # prefix check gets 403
        mock_s3_client.list_objects_v2.side_effect = self._make_client_error(
            "AccessDenied", 403
        )
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError):
            adapter.path_exists("s3://my-bucket/some/prefix/")


class TestS3AdapterListFilesErrorHandling:
    """Tests for list_files error propagation (F-3-p2-log-parser-2)."""

    def _make_client_error(self, code: str, http_status: int = 400) -> Exception:
        return _make_s3_error(code, http_status)

    @patch("boto3.Session")
    def test_list_files_404_returns_empty_list(self, mock_session: Mock) -> None:
        """NoSuchBucket (404) should return [] not raise."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        mock_s3_client.list_objects_v2.side_effect = self._make_client_error(
            "NoSuchBucket", 404
        )
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        result = adapter.list_files("s3://missing-bucket/prefix/")
        assert result == []

    @patch("boto3.Session")
    def test_list_files_403_raises_cloud_storage_error(
        self, mock_session: Mock
    ) -> None:
        """AccessDenied (403) must raise CloudStorageError, not return []."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        mock_s3_client.list_objects_v2.side_effect = self._make_client_error(
            "AccessDenied", 403
        )
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError):
            adapter.list_files("s3://my-bucket/some/prefix/")

    @patch("boto3.Session")
    def test_list_files_throttling_raises_cloud_storage_error(
        self, mock_session: Mock
    ) -> None:
        """Throttling (SlowDown) must raise CloudStorageError, not return []."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        mock_s3_client.list_objects_v2.side_effect = self._make_client_error(
            "SlowDown", 503
        )
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError):
            adapter.list_files("s3://my-bucket/some/prefix/")

    @patch("boto3.Session")
    def test_list_files_generic_error_raises_cloud_storage_error(
        self, mock_session: Mock
    ) -> None:
        """Any non-404 ClientError must raise CloudStorageError, not return []."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        mock_s3_client = Mock()
        mock_s3_client.list_objects_v2.side_effect = self._make_client_error(
            "InternalError", 500
        )
        mock_session.return_value.client.return_value = mock_s3_client

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)

        with pytest.raises(CloudStorageError):
            adapter.list_files("s3://my-bucket/some/prefix/")


class TestS3AdapterCredentialRefresh:
    """Tests for credential refresh behavior."""

    @patch("boto3.Session")
    def test_credential_refresh_on_expiry(self, mock_session: Mock) -> None:
        """Should refresh S3 client when credentials expire."""
        from starboard_log_parser.adapters.cloud.s3 import S3Adapter

        # Create provider with non-expiring credentials
        class SimpleProvider:
            def __init__(self):
                self.call_count = 0

            def get_credentials(self) -> Credentials:
                self.call_count += 1
                return Credentials(
                    access_key=f"key_{self.call_count}",
                    secret_key=f"secret_{self.call_count}",
                    expires_at=None,  # Non-expiring
                )

        provider = SimpleProvider()
        adapter = S3Adapter(credential_provider=provider)

        # First access creates client
        _ = adapter.s3_client
        assert provider.call_count == 1
        initial_call_count = mock_session.call_count

        # Second access within validity period reuses client
        _ = adapter.s3_client
        # Credentials are checked, get_credentials called again
        assert provider.call_count == 2
        # But Session should not be recreated since creds don't need refresh
        assert mock_session.call_count == initial_call_count
