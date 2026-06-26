# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for message API models."""

from starboard_server.api.models.messages import FileAttachment, SendMessageRequest


class TestFileAttachment:
    """Tests for FileAttachment model."""

    def test_parse_snake_case(self) -> None:
        """Test parsing with snake_case field names (Python convention)."""
        data = {
            "filename": "test.log",
            "size": 100000,
            "content": "test content",
            "content_preview": "test...",
            "is_large_file": True,
        }
        attachment = FileAttachment(**data)

        assert attachment.filename == "test.log"
        assert attachment.size == 100000
        assert attachment.is_large_file is True
        assert attachment.content_preview == "test..."

    def test_parse_camel_case(self) -> None:
        """Test parsing with camelCase field names (frontend convention)."""
        data = {
            "filename": "test.log",
            "size": 100000,
            "content": "test content",
            "contentPreview": "test...",  # camelCase
            "isLargeFile": True,  # camelCase
        }
        attachment = FileAttachment(**data)

        assert attachment.filename == "test.log"
        assert attachment.size == 100000
        assert attachment.is_large_file is True  # Parsed from isLargeFile
        assert attachment.content_preview == "test..."  # Parsed from contentPreview

    def test_parse_mixed_case(self) -> None:
        """Test parsing with mixed case field names (both work)."""
        data = {
            "filename": "test.log",
            "size": 100000,
            "is_large_file": True,  # snake_case takes precedence
            "contentPreview": "preview...",  # camelCase
        }
        attachment = FileAttachment(**data)

        assert attachment.is_large_file is True
        assert attachment.content_preview == "preview..."

    def test_default_is_large_file_false(self) -> None:
        """Test that is_large_file defaults to False."""
        data = {"filename": "small.txt", "size": 100}
        attachment = FileAttachment(**data)

        assert attachment.is_large_file is False

    def test_model_dump_uses_snake_case(self) -> None:
        """Test that model_dump() outputs snake_case by default."""
        data = {
            "filename": "test.log",
            "size": 100000,
            "isLargeFile": True,
            "contentPreview": "preview...",
        }
        attachment = FileAttachment(**data)
        dumped = attachment.model_dump()

        # Should use snake_case keys
        assert "is_large_file" in dumped
        assert "content_preview" in dumped
        assert dumped["is_large_file"] is True
        assert dumped["content_preview"] == "preview..."


class TestSendMessageRequest:
    """Tests for SendMessageRequest model."""

    def test_minimal_request(self) -> None:
        """Test minimal request with required fields only."""
        request = SendMessageRequest(content="Hello")

        assert request.content == "Hello"
        assert request.attachments is None
        assert request.metadata is None

    def test_request_with_attachments(self) -> None:
        """Test request with attachments using camelCase fields."""
        request = SendMessageRequest(
            content="Analyze this file",
            attachments=[
                {
                    "filename": "error.log",
                    "size": 100000,
                    "content": "error content",
                    "isLargeFile": True,  # camelCase from frontend
                    "contentPreview": "Error at...",  # camelCase from frontend
                }
            ],
        )

        assert request.content == "Analyze this file"
        assert request.attachments is not None
        assert len(request.attachments) == 1

        attachment = request.attachments[0]
        assert attachment.filename == "error.log"
        assert attachment.is_large_file is True  # Parsed from isLargeFile
        assert attachment.content_preview == "Error at..."  # Parsed from contentPreview
