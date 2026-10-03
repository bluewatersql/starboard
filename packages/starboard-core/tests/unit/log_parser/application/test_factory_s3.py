# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for S3 path handling in the unified create_spark_application factory.

Verifies that s3:// paths are routed to the S3 loader and that the
full loader pipeline (S3FileLinesDataLoader -> JSONLinesDataLoader ->
AmbiguousLogFormatSparkApplicationLoader) is constructed correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestFactoryS3PathRouting:
    """Tests for S3 path detection and loader construction."""

    @patch("starboard_core.log_parser.parsing_models.application.factory._build_s3_loader")
    def test_s3_path_routes_to_s3_loader(self, mock_build_s3: MagicMock) -> None:
        """s3:// paths should use the S3 loader builder."""
        from starboard_core.log_parser import create_spark_application

        mock_loader = MagicMock()
        mock_loader.load_item.return_value = iter([])
        mock_build_s3.return_value = mock_loader

        result = create_spark_application(path="s3://bucket/logs/app.json")

        mock_build_s3.assert_called_once()
        assert result is None  # empty loader -> None

    def test_local_path_does_not_use_s3(self, tmp_path) -> None:
        """Local paths should not trigger S3 loader construction."""
        from starboard_core.log_parser import create_spark_application

        test_file = tmp_path / "app.json"
        test_file.write_text(
            '{"metadata": {"application_info": '
            '{"id": "local-1", "name": "LocalApp", '
            '"timestamp_start_ms": 1000, "timestamp_end_ms": 2000, '
            '"runtime_sec": 1, "spark_version": "3.0.0"}, '
            '"existsSQL": false, "existsExecutors": false}, '
            '"jobData": [], "stageData": [], "taskData": [], "accumData": []}'
        )

        with patch(
            "starboard_core.log_parser.parsing_models.application.factory._build_s3_loader"
        ) as mock_build_s3:
            app = create_spark_application(path=str(test_file))

        mock_build_s3.assert_not_called()
        assert app is not None
        assert app.metadata["application_info"]["id"] == "local-1"

    def test_empty_path_raises_value_error(self) -> None:
        """Empty path should raise ValueError."""
        from starboard_core.log_parser import create_spark_application

        with pytest.raises(ValueError, match="No provided eventlog"):
            create_spark_application(path="")

    def test_nonexistent_local_path_returns_none(self) -> None:
        """Nonexistent local path should return None, not raise."""
        from starboard_core.log_parser import create_spark_application

        result = create_spark_application(path="/nonexistent/path/app.json")
        assert result is None


class TestBuildS3Loader:
    """Tests for the _build_s3_loader helper."""

    @patch("starboard_core.log_parser.adapters.cloud.s3.S3Adapter.__post_init__")
    @patch("starboard_core.log_parser.adapters.cloud.s3.boto3", create=True)
    def test_build_s3_loader_creates_lines_loader(
        self, mock_boto3: MagicMock, mock_post_init: MagicMock
    ) -> None:
        """Should return an S3FileLinesDataLoader with env credentials."""
        from starboard_core.log_parser.loaders import ArchiveExtractionThresholds
        from starboard_core.log_parser.loaders.s3 import S3FileLinesDataLoader
        from starboard_core.log_parser.parsing_models.application.factory import (
            _build_s3_loader,
        )

        thresholds = ArchiveExtractionThresholds()
        loader = _build_s3_loader(thresholds)

        assert isinstance(loader, S3FileLinesDataLoader)

    @patch("starboard_core.log_parser.adapters.cloud.s3.S3Adapter.__post_init__")
    @patch("starboard_core.log_parser.adapters.cloud.s3.boto3", create=True)
    def test_build_s3_loader_passes_thresholds(
        self, mock_boto3: MagicMock, mock_post_init: MagicMock
    ) -> None:
        """Should forward extraction thresholds to the loader."""
        from starboard_core.log_parser.loaders import ArchiveExtractionThresholds
        from starboard_core.log_parser.parsing_models.application.factory import (
            _build_s3_loader,
        )

        thresholds = ArchiveExtractionThresholds(entries=42, size=9999)
        loader = _build_s3_loader(thresholds)

        assert loader._extraction_thresholds.entries == 42
        assert loader._extraction_thresholds.size == 9999
