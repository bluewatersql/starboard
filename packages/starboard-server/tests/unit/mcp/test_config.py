# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP configuration models and loading."""

import json
from pathlib import Path

import pytest
from starboard_server.mcp.config import (
    MCPServerConfig,
    WorkspaceProfile,
    load_mcp_config,
)
from starboard_server.mcp.exceptions import ConfigurationError


class TestWorkspaceProfile:
    """Tests for WorkspaceProfile model."""

    def test_valid_profile(self) -> None:
        profile = WorkspaceProfile(
            host="https://my-workspace.cloud.databricks.com",
            token_env="DATABRICKS_TOKEN",
        )
        assert profile.host == "https://my-workspace.cloud.databricks.com"
        assert profile.token_env == "DATABRICKS_TOKEN"
        assert profile.warehouse_id is None

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid workspace host URL"):
            WorkspaceProfile(host="not-a-url", token_env="TOK")

    def test_frozen_is_immutable(self) -> None:
        profile = WorkspaceProfile(
            host="https://x.databricks.com",
            token_env="TOK",
        )
        with pytest.raises(Exception):
            profile.host = "https://other.com"  # type: ignore[misc]


class TestMCPServerConfig:
    """Tests for MCPServerConfig model."""

    def _make_config(self, **overrides) -> MCPServerConfig:
        defaults = {
            "default_workspace_id": "prod",
            "workspaces": {
                "prod": WorkspaceProfile(
                    host="https://prod.databricks.com",
                    token_env="PROD_TOKEN",
                ),
            },
        }
        defaults.update(overrides)
        return MCPServerConfig(**defaults)

    def test_valid_config_parses(self) -> None:
        config = self._make_config()
        assert config.default_workspace_id == "prod"
        assert len(config.workspaces) == 1
        assert config.rate_limit_per_minute == 60
        assert config.max_response_size_bytes == 32_768
        assert config.safe_mode is False

    def test_missing_default_workspace_raises(self) -> None:
        with pytest.raises(ValueError, match="not found in workspaces"):
            MCPServerConfig(
                default_workspace_id="missing",
                workspaces={
                    "prod": WorkspaceProfile(
                        host="https://prod.databricks.com",
                        token_env="TOK",
                    )
                },
            )

    def test_empty_workspaces_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one workspace"):
            MCPServerConfig(
                default_workspace_id="x",
                workspaces={},
            )

    def test_frozen_config_is_immutable(self) -> None:
        config = self._make_config()
        with pytest.raises(Exception):
            config.safe_mode = True  # type: ignore[misc]


class TestLoadMCPConfig:
    """Tests for load_mcp_config function."""

    def test_config_from_file(self, tmp_path: Path) -> None:
        config_data = {
            "default_workspace_id": "dev",
            "workspaces": {
                "dev": {
                    "host": "https://dev.databricks.com",
                    "token_env": "DEV_TOKEN",
                }
            },
        }
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config_data))

        result = load_mcp_config(config_path=config_file)
        assert result is not None
        assert result.default_workspace_id == "dev"

    def test_config_from_json_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config_data = {
            "default_workspace_id": "staging",
            "workspaces": {
                "staging": {
                    "host": "https://staging.databricks.com",
                    "token_env": "STAGING_TOKEN",
                }
            },
        }
        monkeypatch.setenv("STARBOARD_MCP_CONFIG", json.dumps(config_data))

        result = load_mcp_config()
        assert result is not None
        assert result.default_workspace_id == "staging"

    def test_single_workspace_fallback_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABRICKS_HOST", "https://fallback.databricks.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", "secret-token-value")
        # Ensure higher-priority source is not set
        monkeypatch.delenv("STARBOARD_MCP_CONFIG", raising=False)

        result = load_mcp_config()
        assert result is not None
        assert result.default_workspace_id == "default"
        assert "default" in result.workspaces
        assert result.workspaces["default"].host == "https://fallback.databricks.com"

    def test_returns_none_when_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("STARBOARD_MCP_CONFIG", raising=False)
        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)

        result = load_mcp_config()
        assert result is None

    def test_invalid_json_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STARBOARD_MCP_CONFIG", "not-json{{{")
        with pytest.raises(ConfigurationError, match="Invalid JSON"):
            load_mcp_config()

    def test_missing_config_file_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Config file not found"):
            load_mcp_config(config_path="/nonexistent/path.json")
