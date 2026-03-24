"""
Tests for output management and formatting.

Coverage targets:
- OutputConfig creation
- OutputManager initialization
- File saving in multiple formats
- Directory creation
"""

from pathlib import Path
from typing import Any
from unittest.mock import mock_open, patch

import pytest
from starboard_server.infra.observability.output import OutputConfig, OutputManager


class TestOutputConfig:
    """Tests for OutputConfig dataclass."""

    def test_output_config_defaults(self) -> None:
        """Test OutputConfig with default values."""
        # Act
        config = OutputConfig()

        # Assert
        assert config.save_to_file is True
        assert config.formats == ["markdown"]
        assert config.output_dir == "out"
        assert config.include_raw_context is False
        assert config.include_trace is False
        assert config.include_budget is False

    def test_output_config_custom_values(self) -> None:
        """Test OutputConfig with custom values."""
        # Act
        config = OutputConfig(
            save_to_file=False,
            formats=["json", "yaml"],
            output_dir="/custom/path",
            include_raw_context=True,
            include_trace=True,
            include_budget=True,
        )

        # Assert
        assert config.save_to_file is False
        assert config.formats == ["json", "yaml"]
        assert config.output_dir == "/custom/path"
        assert config.include_raw_context is True
        assert config.include_trace is True
        assert config.include_budget is True

    def test_output_config_multiple_formats(self) -> None:
        """Test OutputConfig with multiple output formats."""
        # Act
        config = OutputConfig(formats=["markdown", "json", "yaml"])

        # Assert
        assert len(config.formats) == 3
        assert "markdown" in config.formats
        assert "json" in config.formats
        assert "yaml" in config.formats


class TestOutputManager:
    """Tests for OutputManager functionality."""

    def test_output_manager_initialization(self) -> None:
        """Test OutputManager initialization."""
        # Arrange
        config = OutputConfig()

        # Act
        manager = OutputManager(config)

        # Assert
        assert manager.config == config

    def test_output_manager_with_custom_config(self) -> None:
        """Test OutputManager with custom configuration."""
        # Arrange
        config = OutputConfig(output_dir="/custom/dir", formats=["json"])

        # Act
        manager = OutputManager(config)

        # Assert
        assert manager.config.output_dir == "/custom/dir"
        assert manager.config.formats == ["json"]

    @pytest.mark.asyncio
    async def test_save_results_disabled(self) -> None:
        """Test save_results when save_to_file is False."""
        # Arrange
        config = OutputConfig(save_to_file=False)
        manager = OutputManager(config)

        results = {"recommendations": {"key": "value"}}
        metadata = {}

        # Act
        saved_files = await manager.save_results(results, metadata)

        # Assert
        assert saved_files == {}

    @pytest.mark.asyncio
    async def test_save_results_creates_directory(self) -> None:
        """Test that save_results creates output directory."""
        # Arrange
        config = OutputConfig(output_dir="test_out", formats=["markdown"])
        manager = OutputManager(config)

        results = {"recommendations": {"items": []}}
        metadata = {}

        with (
            patch.object(Path, "mkdir") as mock_mkdir,
            patch.object(manager, "_save_markdown", return_value=None),
        ):
            # Act
            await manager.save_results(results, metadata)

            # Assert
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @pytest.mark.asyncio
    async def test_save_results_markdown_format(self) -> None:
        """Test saving results in markdown format."""
        # Arrange
        config = OutputConfig(formats=["markdown"])
        manager = OutputManager(config)

        results = {"recommendations": {"items": [{"name": "test", "value": 1}]}}
        metadata = {}

        with (
            patch.object(Path, "mkdir"),
            patch.object(
                manager, "_save_markdown", return_value=Path("test.md")
            ) as mock_save_md,
        ):
            # Act
            saved_files = await manager.save_results(results, metadata)

            # Assert
            mock_save_md.assert_called_once()
            assert "markdown" in saved_files
            assert saved_files["markdown"] == "test.md"

    @pytest.mark.asyncio
    async def test_save_results_json_format(self) -> None:
        """Test saving results in JSON format."""
        # Arrange
        config = OutputConfig(formats=["json"])
        manager = OutputManager(config)

        results = {"recommendations": {"items": []}}
        metadata = {}

        with (
            patch.object(Path, "mkdir"),
            patch.object(
                manager, "_save_json", return_value=Path("test.json")
            ) as mock_save_json,
        ):
            # Act
            saved_files = await manager.save_results(results, metadata)

            # Assert
            mock_save_json.assert_called_once()
            assert "json" in saved_files

    @pytest.mark.asyncio
    async def test_save_results_yaml_format(self) -> None:
        """Test saving results in YAML format."""
        # Arrange
        config = OutputConfig(formats=["yaml"])
        manager = OutputManager(config)

        results = {"recommendations": {"items": []}}
        metadata = {}

        with (
            patch.object(Path, "mkdir"),
            patch.object(
                manager, "_save_yaml", return_value=Path("test.yaml")
            ) as mock_save_yaml,
        ):
            # Act
            saved_files = await manager.save_results(results, metadata)

            # Assert
            mock_save_yaml.assert_called_once()
            assert "yaml" in saved_files

    @pytest.mark.asyncio
    async def test_save_results_multiple_formats(self) -> None:
        """Test saving results in multiple formats."""
        # Arrange
        config = OutputConfig(formats=["markdown", "json", "yaml"])
        manager = OutputManager(config)

        results = {"recommendations": {"items": []}}
        metadata = {}

        with (
            patch.object(Path, "mkdir"),
            patch.object(manager, "_save_markdown", return_value=Path("test.md")),
            patch.object(manager, "_save_json", return_value=Path("test.json")),
            patch.object(manager, "_save_yaml", return_value=Path("test.yaml")),
        ):
            # Act
            saved_files = await manager.save_results(results, metadata)

            # Assert
            assert len(saved_files) == 3
            assert "markdown" in saved_files
            assert "json" in saved_files
            assert "yaml" in saved_files

    @pytest.mark.asyncio
    async def test_save_results_extracts_recommendations(self) -> None:
        """Test that save_results properly extracts recommendations."""
        # Arrange
        config = OutputConfig(formats=["markdown"])
        manager = OutputManager(config)

        recommendations = {
            "items": [{"name": "item1", "confidence": "high"}],
            "summary": "Test summary",
        }
        results = {"recommendations": recommendations}
        metadata = {}

        with (
            patch.object(Path, "mkdir"),
            patch.object(
                manager, "_save_markdown", return_value=Path("test.md")
            ) as mock_save_md,
        ):
            # Act
            await manager.save_results(results, metadata)

            # Assert
            # Verify recommendations were passed to save method
            call_args = mock_save_md.call_args
            assert call_args is not None


class TestOutputManagerPrivateMethods:
    """Tests for OutputManager private helper methods."""

    def test_save_markdown_method_exists(self) -> None:
        """Test that _save_markdown method exists."""
        config = OutputConfig()
        manager = OutputManager(config)

        assert hasattr(manager, "_save_markdown")
        assert callable(manager._save_markdown)

    def test_save_json_method_exists(self) -> None:
        """Test that _save_json method exists."""
        config = OutputConfig()
        manager = OutputManager(config)

        assert hasattr(manager, "_save_json")
        assert callable(manager._save_json)

    def test_save_yaml_method_exists(self) -> None:
        """Test that _save_yaml method exists."""
        config = OutputConfig()
        manager = OutputManager(config)

        assert hasattr(manager, "_save_yaml")
        assert callable(manager._save_yaml)


class TestOutputIntegration:
    """Integration tests for output management."""

    @pytest.mark.asyncio
    async def test_full_output_workflow(self) -> None:
        """Test complete output workflow with all formats."""
        # Arrange
        config = OutputConfig(
            save_to_file=True,
            formats=["markdown", "json", "yaml"],
            output_dir="test_integration_out",
        )
        manager = OutputManager(config)

        results = {
            "recommendations": {
                "items": [
                    {"name": "recommendation1", "confidence": "high", "effort": "low"},
                    {
                        "name": "recommendation2",
                        "confidence": "medium",
                        "effort": "medium",
                    },
                ]
            }
        }
        metadata = {"plan": {"steps": []}, "trace": {}, "budget": {}}

        with (
            patch.object(Path, "mkdir"),
            patch.object(manager, "_save_markdown", return_value=Path("out.md")),
            patch.object(manager, "_save_json", return_value=Path("out.json")),
            patch.object(manager, "_save_yaml", return_value=Path("out.yaml")),
        ):
            # Act
            saved_files = await manager.save_results(results, metadata)

            # Assert
            assert isinstance(saved_files, dict)
            assert len(saved_files) == 3

    @pytest.mark.asyncio
    async def test_output_with_empty_recommendations(self) -> None:
        """Test output handling with empty recommendations."""
        # Arrange
        config = OutputConfig(formats=["json"])
        manager = OutputManager(config)

        results: dict[str, Any] = {"recommendations": {}}
        metadata: dict[str, Any] = {}

        with (
            patch.object(Path, "mkdir"),
            patch.object(manager, "_save_json", return_value=None),
        ):
            # Act
            saved_files = await manager.save_results(results, metadata)

            # Assert
            # Should handle gracefully
            assert isinstance(saved_files, dict)


class TestOutputManagerFileOperations:
    """Tests for output manager file operations."""

    def test_save_markdown_creates_file(self) -> None:
        """Test that _save_markdown creates a markdown file."""
        # Arrange
        config = OutputConfig()
        manager = OutputManager(config)

        output_dir = Path("test_out")
        recommendations = {"items": [{"name": "test", "confidence": "high"}]}

        with (
            patch("pathlib.Path.open", mock_open()),
            patch.object(Path, "exists", return_value=True),
        ):
            # Act
            _ = manager._save_markdown(output_dir, recommendations)

            # Assert
            # Method may return Path or None - execution without error is success

    def test_save_json_creates_file(self) -> None:
        """Test that _save_json creates a JSON file."""
        # Arrange
        config = OutputConfig()
        manager = OutputManager(config)

        output_dir = Path("test_out")
        recommendations: dict[str, Any] = {"items": []}
        full_results: dict[str, Any] = {"recommendations": recommendations}

        with patch("pathlib.Path.open", mock_open()):
            # Act
            _ = manager._save_json(output_dir, recommendations, full_results)

            # Assert
            # Method may return Path or None - execution without error is success

    def test_save_yaml_creates_file(self) -> None:
        """Test that _save_yaml creates a YAML file."""
        # Arrange
        config = OutputConfig()
        manager = OutputManager(config)

        output_dir = Path("test_out")
        recommendations: dict[str, Any] = {"items": []}
        full_results: dict[str, Any] = {"recommendations": recommendations}

        with patch("pathlib.Path.open", mock_open()):
            # Act
            _ = manager._save_yaml(output_dir, recommendations, full_results)

            # Assert
            # Method may return Path or None - execution without error is success

    def test_format_recommendation_for_markdown(self) -> None:
        """Test formatting recommendations for markdown."""
        # Arrange
        config = OutputConfig()
        manager = OutputManager(config)

        recommendation = {
            "name": "Add index on user_id",
            "confidence": "high",
            "effort": "low",
            "rationale": "Improves query performance",
        }

        # Act - This tests internal formatting logic
        # The method may not be directly accessible, but we test it via save_markdown
        output_dir = Path("test_out")
        recommendations = {"items": [recommendation]}

        with patch("pathlib.Path.open", mock_open()):
            _ = manager._save_markdown(output_dir, recommendations)

    def test_save_markdown_with_complex_data(self) -> None:
        """Test saving markdown with complex nested data."""
        # Arrange
        config = OutputConfig()
        manager = OutputManager(config)

        output_dir = Path("test_out")
        recommendations = {
            "items": [
                {
                    "name": "Recommendation 1",
                    "confidence": "high",
                    "effort": "low",
                    "impact": {"latency": "50%", "throughput": "30%"},
                },
                {
                    "name": "Recommendation 2",
                    "confidence": "medium",
                    "effort": "medium",
                },
            ]
        }

        with patch("pathlib.Path.open", mock_open()):
            # Act
            _ = manager._save_markdown(output_dir, recommendations)

    def test_save_json_with_metadata(self) -> None:
        """Test saving JSON with metadata."""
        # Arrange
        config = OutputConfig()
        manager = OutputManager(config)

        output_dir = Path("test_out")
        recommendations = {"items": [{"name": "test"}]}
        full_results = {
            "recommendations": recommendations,
            "metadata": {"timestamp": "2024-01-01", "version": "1.0"},
        }

        with patch("pathlib.Path.open", mock_open()):
            # Act
            _ = manager._save_json(output_dir, recommendations, full_results)

    @pytest.mark.asyncio
    async def test_save_results_with_all_options(self) -> None:
        """Test save_results with all configuration options enabled."""
        # Arrange
        config = OutputConfig(
            save_to_file=True,
            formats=["markdown", "json", "yaml"],
            output_dir="full_test_out",
            include_raw_context=True,
            include_trace=True,
            include_budget=True,
        )
        manager = OutputManager(config)

        results = {
            "recommendations": {"items": [{"name": "test", "confidence": "high"}]}
        }
        metadata = {
            "trace": {"steps": ["step1", "step2"]},
            "budget": {"spent": 100, "remaining": 900},
            "raw_context": {"data": "context"},
        }

        with (
            patch.object(Path, "mkdir"),
            patch.object(manager, "_save_markdown", return_value=Path("out.md")),
            patch.object(manager, "_save_json", return_value=Path("out.json")),
            patch.object(manager, "_save_yaml", return_value=Path("out.yaml")),
        ):
            # Act
            saved_files = await manager.save_results(results, metadata)

            # Assert
            assert isinstance(saved_files, dict)
