# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for DefaultWorkspaceRegistry."""

import pytest
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.exceptions import ConfigurationError
from starboard_server.mcp.workspace_registry import DefaultWorkspaceRegistry


def _make_config(**overrides: object) -> MCPServerConfig:
    defaults: dict = {
        "default_workspace_id": "prod",
        "workspaces": {
            "prod": WorkspaceProfile(
                host="https://prod.databricks.com", token_env="PROD_TOKEN"
            ),
            "dev": WorkspaceProfile(
                host="https://dev.databricks.com", token_env="DEV_TOKEN"
            ),
        },
    }
    defaults.update(overrides)
    return MCPServerConfig(**defaults)


class TestResolve:
    """Tests for workspace resolution."""

    def test_resolve_default_workspace(self) -> None:
        registry = DefaultWorkspaceRegistry(_make_config())
        profile = registry.resolve(None)
        assert profile.host == "https://prod.databricks.com"

    def test_resolve_explicit_workspace(self) -> None:
        registry = DefaultWorkspaceRegistry(_make_config())
        profile = registry.resolve("dev")
        assert profile.host == "https://dev.databricks.com"

    def test_resolve_unknown_raises_config_error(self) -> None:
        registry = DefaultWorkspaceRegistry(_make_config())
        with pytest.raises(ConfigurationError) as exc_info:
            registry.resolve("nonexistent")
        assert exc_info.value.code == "CONFIG_UNKNOWN_WORKSPACE"

    def test_resolve_none_uses_default(self) -> None:
        registry = DefaultWorkspaceRegistry(_make_config())
        profile = registry.resolve(None)
        assert profile.token_env == "PROD_TOKEN"


class TestListWorkspaces:
    """Tests for listing workspaces."""

    def test_list_workspaces(self) -> None:
        registry = DefaultWorkspaceRegistry(_make_config())
        workspaces = registry.list_workspaces()
        assert workspaces == ["dev", "prod"]


class TestValidate:
    """Tests for configuration validation."""

    def test_validate_warns_on_missing_token_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PROD_TOKEN", raising=False)
        monkeypatch.delenv("DEV_TOKEN", raising=False)
        registry = DefaultWorkspaceRegistry(_make_config())
        warnings = registry.validate()
        assert len(warnings) == 2
        assert "PROD_TOKEN" in warnings[0] or "PROD_TOKEN" in warnings[1]

    def test_validate_no_warnings_when_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PROD_TOKEN", "secret")
        monkeypatch.setenv("DEV_TOKEN", "secret")
        registry = DefaultWorkspaceRegistry(_make_config())
        warnings = registry.validate()
        assert len(warnings) == 0


class TestInitValidation:
    """Tests for constructor validation."""

    def test_invalid_default_raises_on_init(self) -> None:
        # Use model_construct to bypass Pydantic validation so we can
        # test the registry's own constructor check.
        bad_config = MCPServerConfig.model_construct(
            default_workspace_id="missing",
            workspaces={
                "prod": WorkspaceProfile(
                    host="https://prod.databricks.com", token_env="T"
                )
            },
        )
        with pytest.raises(ConfigurationError) as exc_info:
            DefaultWorkspaceRegistry(bad_config)
        assert exc_info.value.code == "CONFIG_INVALID_DEFAULT"
