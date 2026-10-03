# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for CLI main module."""

import json
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest
import yaml
from starboard.cli.cli.main import (
    load_config_file,
    merge_env_config,
    parse_args,
    save_results,
    setup_cli_logging,
)


class TestArgumentParsing:
    """Tests for CLI argument parsing."""

    def test_parse_args_minimal(self):
        """Test parsing minimal required arguments."""
        args = parse_args(["--goal", "test goal"])

        assert args.goal == "test goal"
        assert args.config is None
        assert args.databricks_host is None
        assert args.mode == "online"

    def test_parse_args_with_all_options(self):
        """Test parsing all CLI options."""
        argv = [
            "--goal",
            "optimize query",
            "--config",
            "config.yaml",
            "--databricks-host",
            "https://test.databricks.com",
            "--databricks-token",
            "test_token",
            "--llm-model",
            "gpt-4o",
            "--llm-api-key",
            "test_key",
            "--llm-base-url",
            "https://api.openai.com/v1",
            "--llm-temperature",
            "0.5",
            "--llm-max-tokens",
            "50000",
            "--input-file",
            "input.txt",
            "--output-path",
            "./results",
            "--plain",
            "--quiet",
            "--log-level",
            "DEBUG",
            "--log-file",
            "test.log",
            "--debug",
            "--mode",
            "offline",
        ]

        args = parse_args(argv)

        assert args.goal == "optimize query"
        assert args.config == "config.yaml"
        assert args.databricks_host == "https://test.databricks.com"
        assert args.databricks_token == "test_token"
        assert args.llm_model == "gpt-4o"
        assert args.llm_api_key == "test_key"
        assert args.llm_base_url == "https://api.openai.com/v1"
        assert args.llm_temperature == 0.5
        assert args.llm_max_tokens == 50000
        assert args.input_file == "input.txt"
        assert args.output_path == "./results"
        assert args.plain is True
        assert args.quiet is True
        assert args.log_level == "DEBUG"
        assert args.log_file == "test.log"
        assert args.debug is True
        assert args.mode == "offline"

    def test_parse_args_mode_choices(self):
        """Test that mode accepts valid choices."""
        # Test each valid mode
        for mode in ["online", "offline", "diagnostic"]:
            args = parse_args(["--goal", "test", "--mode", mode])
            assert args.mode == mode

    def test_parse_args_log_level_choices(self):
        """Test that log_level accepts valid choices."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            args = parse_args(["--goal", "test", "--log-level", level])
            assert args.log_level == level

    def test_parse_args_no_goal_allowed(self):
        """Test that no goal is allowed (optional argument)."""
        args = parse_args([])
        assert args.goal is None

    def test_parse_args_quiet_flag(self):
        """Test that -q short option works."""
        args = parse_args(["-q", "--goal", "test"])
        assert args.quiet is True


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_config_file_success(self, tmp_path):
        """Test loading valid YAML config file."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "databricks": {
                "host": "https://test.databricks.com",
                "token": "test_token",
            },
            "llm": {"model": "gpt-4o", "temperature": 0.5},
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = load_config_file(config_file)

        assert config == config_data

    def test_load_config_file_not_found(self, tmp_path):
        """Test loading non-existent config file."""
        config_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config_file(config_file)

    def test_load_config_file_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML file."""
        config_file = tmp_path / "invalid.yaml"
        with open(config_file, "w") as f:
            f.write("{ invalid yaml: [")

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config_file(config_file)

    def test_load_config_file_empty(self, tmp_path):
        """Test loading empty YAML file."""
        config_file = tmp_path / "empty.yaml"
        config_file.touch()

        config = load_config_file(config_file)

        assert config == {}

    def test_merge_env_config_file_precedence(self):
        """Test that file config has correct precedence."""
        import argparse

        file_config = {
            "databricks": {"host": "https://file.databricks.com"},
            "llm": {"model": "file-model", "temperature": 0.7},
        }

        args = argparse.Namespace(
            databricks_host=None,
            databricks_token=None,
            llm_model=None,
            llm_api_key=None,
            llm_base_url=None,
            llm_temperature=None,
            llm_max_tokens=None,
        )

        with patch("starboard.cli.cli.main.get_config") as mock_get_config:
            base_config = MagicMock()
            base_config.databricks_host = "https://env.databricks.com"
            base_config.llm_model = "env-model"
            mock_get_config.return_value = base_config

            merge_env_config(file_config, args)

            # Check that model_copy was called with file config overrides
            base_config.model_copy.assert_called_once()
            call_kwargs = base_config.model_copy.call_args[1]
            update_dict = call_kwargs["update"]
            assert "databricks_host" in update_dict
            assert update_dict["databricks_host"] == "https://file.databricks.com"

    def test_merge_env_config_cli_precedence(self):
        """Test that CLI args have highest precedence."""
        import argparse

        file_config = {"llm": {"model": "file-model"}}

        args = argparse.Namespace(
            databricks_host="https://cli.databricks.com",
            databricks_token="cli_token",
            llm_model="cli-model",
            llm_api_key=None,
            llm_base_url=None,
            llm_temperature=0.9,
            llm_max_tokens=100000,
        )

        with patch("starboard.cli.cli.main.get_config") as mock_get_config:
            base_config = MagicMock()
            mock_get_config.return_value = base_config

            merge_env_config(file_config, args)

            # Check that CLI args override file config
            call_kwargs = base_config.model_copy.call_args[1]
            update_dict = call_kwargs["update"]
            assert update_dict["databricks_host"] == "https://cli.databricks.com"
            assert update_dict["databricks_token"] == "cli_token"
            assert update_dict["llm_model"] == "cli-model"
            assert update_dict["llm_temperature"] == 0.9
            assert update_dict["llm_max_tokens"] == 100000


class TestOutputSaving:
    """Tests for output saving functionality."""

    @pytest.mark.asyncio
    async def test_save_results_creates_files(self, tmp_path):
        """Test that save_results creates both JSON and Markdown files."""
        output = {
            "user_goal": "test goal",
            "summary": "test summary",
            "tools_used": ["tool1", "tool2"],
            "tokens_used": 1000,
            "cost_usd": 0.05,
            "duration_seconds": 5.5,
        }

        json_path, markdown_path = await save_results(
            output=output, output_path=tmp_path, conversation_id="test_conv"
        )

        assert json_path.exists()
        assert markdown_path.exists()
        assert json_path.suffix == ".json"
        assert markdown_path.suffix == ".md"

    @pytest.mark.asyncio
    async def test_save_results_json_content(self, tmp_path):
        """Test that JSON file contains correct content."""
        output = {"user_goal": "test goal", "summary": "test summary"}

        json_path, _ = await save_results(
            output=output, output_path=tmp_path, conversation_id="test_conv"
        )

        with open(json_path) as f:
            saved_data = json.load(f)

        assert saved_data == output

    @pytest.mark.asyncio
    async def test_save_results_markdown_content(self, tmp_path):
        """Test that Markdown file is generated."""
        output = {
            "user_goal": "test goal",
            "summary": "test summary",
            "recommendations": [
                {
                    "title": "Recommendation 1",
                    "description": "Description 1",
                    "implementation": "Implementation 1",
                }
            ],
            "tools_used": ["tool1"],
            "tokens_used": 1000,
            "cost_usd": 0.05,
            "duration_seconds": 5.5,
            "steps_taken": 3,
        }

        _, markdown_path = await save_results(
            output=output, output_path=tmp_path, conversation_id="test_conv"
        )

        with open(markdown_path) as f:
            content = f.read()

        assert "# Starboard Agent Analysis Report" in content
        assert "## Goal" in content
        assert "test goal" in content
        assert "## Summary" in content
        assert "test summary" in content

    @pytest.mark.asyncio
    async def test_save_results_creates_output_directory(self, tmp_path):
        """Test that save_results creates output directory if it doesn't exist."""
        output_path = tmp_path / "new_dir" / "nested"
        output = {"user_goal": "test"}

        await save_results(
            output=output, output_path=output_path, conversation_id="test_conv"
        )

        assert output_path.exists()
        assert output_path.is_dir()

    @pytest.mark.asyncio
    async def test_save_results_filename_format(self, tmp_path):
        """Test that filename includes timestamp and goal prefix."""
        output = {"user_goal": "optimize query performance"}

        json_path, markdown_path = await save_results(
            output=output, output_path=tmp_path, conversation_id="test_conv"
        )

        # Check that filename contains goal prefix
        assert "optimize" in json_path.stem
        assert "optimize" in markdown_path.stem

        # Check that filenames match (same base name)
        assert json_path.stem == markdown_path.stem


class TestLoggingSetup:
    """Tests for CLI logging setup."""

    def test_setup_cli_logging_debug_mode(self):
        """Test logging setup in debug mode."""
        with patch("starboard.cli.cli.main.logging.basicConfig") as mock_config:
            setup_cli_logging(log_level="DEBUG", quiet=False)

            mock_config.assert_called_once()
            args = mock_config.call_args[1]
            assert args["level"] == 10  # logging.DEBUG
            assert args["force"] is True

    def test_setup_cli_logging_quiet_mode(self):
        """Test logging setup in quiet mode."""
        with patch("starboard.cli.cli.main.logging.basicConfig") as mock_config:
            setup_cli_logging(log_level="INFO", quiet=True)

            mock_config.assert_called_once()
            args = mock_config.call_args[1]
            assert args["level"] == 40  # logging.ERROR
            assert args["force"] is True

    def test_setup_cli_logging_with_log_file(self, tmp_path):
        """Test logging setup with log file."""
        log_file = tmp_path / "test.log"

        with (
            patch("builtins.open", mock_open()) as mock_file,
            patch("starboard.cli.cli.main.logging.basicConfig"),
        ):
            setup_cli_logging(log_level="INFO", log_file=str(log_file))

            mock_file.assert_called_once_with(str(log_file), "a")

    def test_setup_cli_logging_suppresses_noisy_loggers(self):
        """Test that noisy loggers are suppressed."""
        with patch("starboard.cli.cli.main.logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            with patch("starboard.cli.cli.main.logging.basicConfig"):
                setup_cli_logging(log_level="INFO")

            suppressed = {call[0][0] for call in mock_get_logger.call_args_list}
            for name in (
                "httpx",
                "httpcore",
                "openai",
                "opentelemetry",
                "urllib3",
                "asyncio",
                "databricks.sdk",
                "aiosqlite",
            ):
                assert name in suppressed, f"{name} not suppressed"


class TestMainEntryPoint:
    """Tests for main entry point."""

    def test_main_calls_parse_args(self):
        """Test that main calls parse_args and runs async_main."""
        from starboard.cli.cli.main import main

        with (
            patch("starboard.cli.cli.main.parse_args") as mock_parse,
            patch("starboard.cli.cli.main.asyncio.run") as mock_run,
        ):
            mock_args = MagicMock(goal="test", config=None, debug=False)
            mock_parse.return_value = mock_args

            # When asyncio.run completes normally, main() returns normally
            main([])

            mock_parse.assert_called_once_with([])
            mock_run.assert_called_once()

    def test_main_keyboard_interrupt_handling(self):
        """Test that main handles KeyboardInterrupt."""
        from starboard.cli.cli.main import main

        with (
            patch("starboard.cli.cli.main.parse_args"),
            patch("starboard.cli.cli.main.asyncio.run") as mock_run,
        ):
            mock_run.side_effect = KeyboardInterrupt()

            with pytest.raises(SystemExit) as exc_info:
                main([])

            assert exc_info.value.code == 130

    def test_main_unexpected_error_handling(self):
        """Test that main handles unexpected errors."""
        from starboard.cli.cli.main import main

        with (
            patch("starboard.cli.cli.main.parse_args"),
            patch("starboard.cli.cli.main.asyncio.run") as mock_run,
        ):
            mock_run.side_effect = RuntimeError("Unexpected error")

            with pytest.raises(SystemExit) as exc_info:
                main([])

            assert exc_info.value.code == 1
