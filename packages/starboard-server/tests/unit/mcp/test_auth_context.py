# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for EnvTokenAuthProvider."""

import pytest
from starboard_server.mcp.auth_context import EnvTokenAuthProvider
from starboard_server.mcp.config import WorkspaceProfile
from starboard_server.mcp.exceptions import AuthenticationError


@pytest.fixture()
def provider() -> EnvTokenAuthProvider:
    return EnvTokenAuthProvider()


@pytest.fixture()
def profile() -> WorkspaceProfile:
    return WorkspaceProfile(
        host="https://test.databricks.com",
        token_env="TEST_MCP_TOKEN",
    )


class TestGetCredentials:
    """Tests for credential resolution."""

    def test_get_credentials_success(
        self,
        provider: EnvTokenAuthProvider,
        profile: WorkspaceProfile,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TEST_MCP_TOKEN", "dapi12345abcdef")
        creds = provider.get_credentials(profile)
        assert creds.host == "https://test.databricks.com"
        assert creds.token == "dapi12345abcdef"

    def test_missing_token_env_raises_auth_error(
        self,
        provider: EnvTokenAuthProvider,
        profile: WorkspaceProfile,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("TEST_MCP_TOKEN", raising=False)
        with pytest.raises(AuthenticationError) as exc_info:
            provider.get_credentials(profile)
        assert exc_info.value.code == "AUTH_MISSING_TOKEN"

    def test_empty_token_value_raises_auth_error(
        self,
        provider: EnvTokenAuthProvider,
        profile: WorkspaceProfile,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TEST_MCP_TOKEN", "")
        with pytest.raises(AuthenticationError) as exc_info:
            provider.get_credentials(profile)
        assert exc_info.value.code == "AUTH_MISSING_TOKEN"

    def test_credentials_contain_host_and_token(
        self,
        provider: EnvTokenAuthProvider,
        profile: WorkspaceProfile,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TEST_MCP_TOKEN", "token-value")
        creds = provider.get_credentials(profile)
        assert creds.host == profile.host
        assert creds.token == "token-value"

    def test_error_message_does_not_contain_token(
        self,
        provider: EnvTokenAuthProvider,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SECRET_TOK", "super-secret-dapi-value")
        profile = WorkspaceProfile(
            host="https://x.databricks.com", token_env="MISSING_TOK"
        )
        monkeypatch.delenv("MISSING_TOK", raising=False)
        with pytest.raises(AuthenticationError) as exc_info:
            provider.get_credentials(profile)
        assert "super-secret" not in str(exc_info.value)
        assert "dapi" not in exc_info.value.message
