"""
Tests for S3 loaders.

Following TDD: tests written first, implementation follows.
"""

from __future__ import annotations

import sys
from unittest.mock import Mock, patch

import pytest

# Mock boto3 before imports
sys.modules["boto3"] = Mock()
sys.modules["botocore"] = Mock()
sys.modules["botocore.exceptions"] = Mock()

from starboard_log_parser.adapters.cloud.s3 import S3Adapter  # noqa: E402
from starboard_log_parser.auth.providers import StaticCredentialProvider  # noqa: E402


def create_chunked_mock_s3(test_data: bytes) -> Mock:
    """Create a mock S3 client that properly simulates chunked reads.

    The mock returns data on the first call and empty bytes on subsequent calls,
    simulating reaching EOF and preventing infinite loops in the chunked read logic.

    Args:
        test_data: The data to return on the first read

    Returns:
        Mock S3 client configured for chunked reads
    """
    mock_s3 = Mock()

    # Mock head_object to return file size
    mock_s3.head_object.return_value = {"ContentLength": len(test_data)}

    # Track call count to return empty on subsequent calls (EOF)
    call_count = [0]

    def mock_get_object(**kwargs):
        call_count[0] += 1
        mock_response = {"Body": Mock()}
        if call_count[0] == 1:
            mock_response["Body"].read.return_value = test_data
        else:
            # Past EOF - return empty bytes to terminate the read loop
            mock_response["Body"].read.return_value = b""
        return mock_response

    mock_s3.get_object.side_effect = mock_get_object
    return mock_s3


class TestS3FileLinesDataLoader:
    """Tests for S3FileLinesDataLoader."""

    def test_imports_successfully(self) -> None:
        """Should import without errors."""
        from starboard_log_parser.loaders.s3 import S3FileLinesDataLoader

        assert S3FileLinesDataLoader is not None

    def test_initialization(self) -> None:
        """Should initialize with S3Adapter."""
        from starboard_log_parser.loaders.s3 import S3FileLinesDataLoader

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)
        loader = S3FileLinesDataLoader(s3_adapter=adapter)

        assert loader.s3_adapter is adapter

    @patch("boto3.Session")
    def test_list_items(self, mock_session: Mock) -> None:
        """Should list S3 files."""
        from starboard_log_parser.loaders.s3 import S3FileLinesDataLoader

        # Mock S3 client
        mock_s3 = Mock()
        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "logs/file1.json", "Size": 100},
                {"Key": "logs/file2.json", "Size": 200},
            ]
        }
        mock_session.return_value.client.return_value = mock_s3

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)
        loader = S3FileLinesDataLoader(s3_adapter=adapter)

        items = loader.list_items("s3://bucket/logs/")

        assert len(items) == 2
        assert items[0]["path"] == "s3://bucket/logs/file1.json"
        assert items[1]["path"] == "s3://bucket/logs/file2.json"

    @patch("boto3.Session")
    def test_load_item_streams_lines(self, mock_session: Mock) -> None:
        """Should load and stream file lines."""
        from starboard_log_parser.loaders.s3 import S3FileLinesDataLoader

        test_data = b'{"line": 1}\n{"line": 2}\n{"line": 3}\n'
        mock_s3 = create_chunked_mock_s3(test_data)
        mock_session.return_value.client.return_value = mock_s3

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)
        loader = S3FileLinesDataLoader(s3_adapter=adapter)

        # Load item returns FileChunkStreamWrapper
        file_wrapper = loader.load_item("s3://bucket/file.jsonl")

        # Should be able to iterate lines
        lines = list(file_wrapper.iter_lines())
        assert len(lines) == 3
        assert b'{"line": 1}' in lines[0]


class TestS3FileBlobDataLoader:
    """Tests for S3FileBlobDataLoader."""

    def test_imports_successfully(self) -> None:
        """Should import without errors."""
        from starboard_log_parser.loaders.s3 import S3FileBlobDataLoader

        assert S3FileBlobDataLoader is not None

    def test_initialization(self) -> None:
        """Should initialize with S3Adapter."""
        from starboard_log_parser.loaders.s3 import S3FileBlobDataLoader

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)
        loader = S3FileBlobDataLoader(s3_adapter=adapter)

        assert loader.s3_adapter is adapter

    @patch("boto3.Session")
    def test_load_item_returns_blob(self, mock_session: Mock) -> None:
        """Should load entire file as blob."""
        from starboard_log_parser.loaders.s3 import S3FileBlobDataLoader

        test_data = b'{"key": "value", "data": [1, 2, 3]}'
        mock_s3 = create_chunked_mock_s3(test_data)
        mock_session.return_value.client.return_value = mock_s3

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)
        loader = S3FileBlobDataLoader(s3_adapter=adapter)

        # Load item returns FileChunkStreamWrapper
        file_wrapper = loader.load_item("s3://bucket/data.json")

        # Should be able to read entire blob
        data = file_wrapper.read()
        assert data == test_data


class TestS3LoaderIntegration:
    """Integration tests for S3 loaders."""

    @pytest.mark.skip(
        reason="Automatic gzip decompression in load_item() not yet implemented. "
        "Use extract() method for decompression support."
    )
    @patch("boto3.Session")
    def test_lines_loader_with_gzip(self, mock_session: Mock) -> None:
        """Should handle gzipped files."""
        import gzip

        from starboard_log_parser.loaders.s3 import S3FileLinesDataLoader

        # Create gzipped test data
        test_lines = b'{"line": 1}\n{"line": 2}\n'
        gzipped_data = gzip.compress(test_lines)

        mock_s3 = create_chunked_mock_s3(gzipped_data)
        mock_session.return_value.client.return_value = mock_s3

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)
        loader = S3FileLinesDataLoader(s3_adapter=adapter)

        # Load gzipped file
        file_wrapper = loader.load_item("s3://bucket/file.jsonl.gz")

        # Should automatically decompress
        lines = list(file_wrapper.iter_lines())
        assert len(lines) == 2

    @pytest.mark.skip(
        reason="Automatic gzip decompression in load_item() not yet implemented. "
        "Use extract() method for decompression support."
    )
    @patch("boto3.Session")
    def test_blob_loader_with_compression(self, mock_session: Mock) -> None:
        """Should handle compressed blob files."""
        import gzip

        from starboard_log_parser.loaders.s3 import S3FileBlobDataLoader

        # Create gzipped JSON
        test_data = b'{"key": "value"}'
        gzipped_data = gzip.compress(test_data)

        mock_s3 = create_chunked_mock_s3(gzipped_data)
        mock_session.return_value.client.return_value = mock_s3

        provider = StaticCredentialProvider(access_key="test", secret_key="test")
        adapter = S3Adapter(credential_provider=provider)
        loader = S3FileBlobDataLoader(s3_adapter=adapter)

        # Load compressed blob
        file_wrapper = loader.load_item("s3://bucket/data.json.gz")

        # Should automatically decompress
        data = file_wrapper.read()
        assert data == test_data
