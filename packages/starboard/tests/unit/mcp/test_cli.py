# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP CLI entry point."""

import pytest
from starboard.mcp.cli import main, parse_args


class TestParseArgs:
    """Tests for CLI argument parsing."""

    def test_default_transport_is_stdio(self) -> None:
        args = parse_args([])
        assert args.transport == "stdio"
        assert args.port == 8100
        assert args.config is None

    def test_http_transport(self) -> None:
        args = parse_args(["--transport", "http", "--port", "9000"])
        assert args.transport == "http"
        assert args.port == 9000

    def test_config_flag(self) -> None:
        args = parse_args(["--config", "/path/to/config.json"])
        assert args.config == "/path/to/config.json"

    def test_host_flag(self) -> None:
        args = parse_args(["--host", "0.0.0.0"])
        assert args.host == "0.0.0.0"


class TestMainExitsOnNoConfig:
    """Tests for main() error handling."""

    def test_exits_when_no_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STARBOARD_MCP_CONFIG", raising=False)
        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_exits_on_invalid_config_file(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--config", "/nonexistent/file.json"])
        assert exc_info.value.code == 1

    def test_exits_on_invalid_env_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STARBOARD_MCP_CONFIG", "not-json{{{")
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1
