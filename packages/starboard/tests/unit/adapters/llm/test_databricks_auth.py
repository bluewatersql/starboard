# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for deriving a Databricks serving-endpoint bearer token for the LLM client.

Covers the "pull the token from the auth'd client, fall back to LLM_API_KEY"
contract: when ``LLM_BASE_URL`` targets a Databricks serving endpoint, the LLM
client authenticates with a fresh token from the unified resolver (profile /
OAuth / PAT / ambient); otherwise it falls back to the configured key.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from starboard.adapters.llm import databricks_auth as da
from starboard.infra.core.config import EnvConfig


class TestIsDatabricksServingUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://e2-demo-field-eng.cloud.databricks.com/serving-endpoints",
            "https://adb-123.azuredatabricks.net/serving-endpoints",
            "https://x.gcp.databricks.com/serving-endpoints",
            "https://dbc-1.cloud.databricks.us/serving-endpoints",
            "https://dbc-1.cloud.databricks.mil/serving-endpoints",
            "https://my-app-123.aws.databricksapps.com/v1",
            "https://accounts.cloud.databricks.com",
            "https://databricks.com",
            "HTTPS://ADB-123.AzureDatabricks.NET:443/serving-endpoints",
            "https://adb-123.azuredatabricks.net./serving-endpoints",
        ],
    )
    def test_true_for_databricks_hosts(self, url: str) -> None:
        assert da.is_databricks_serving_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "",
            None,
            "https://api.openai.com/v1",
            # F8b spoofs: the old substring test sent the workspace bearer here.
            "https://databricks.attacker.example/serving-endpoints",
            "https://evil.com/?x=databricks",
            "https://evil.com/databricks/serving-endpoints",
            "https://evil.com#databricks.com",
            "https://databricks.com.evil.net/serving-endpoints",
            "https://notdatabricks.com/serving-endpoints",
            "https://evilazuredatabricks.net/serving-endpoints",
            "https://databricks.com@evil.com/serving-endpoints",
            "http://adb-123.azuredatabricks.net/serving-endpoints",
            "adb-123.azuredatabricks.net/serving-endpoints",
            "ftp://x.cloud.databricks.com",
            "https://",
            "not a url",
        ],
    )
    def test_false_otherwise(self, url: str | None) -> None:
        assert da.is_databricks_serving_url(url) is False


_SERVING = "https://serving-ws.cloud.databricks.com/serving-endpoints"


def _client(host: str, token: str = "tok") -> Mock:
    fake = Mock()
    fake.config.host = host
    fake.config.authenticate.return_value = {"Authorization": f"Bearer {token}"}
    return fake


def _overlay(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setattr(
        EnvConfig, "overlay_enabled", property(lambda self: enabled), raising=True
    )


class TestResolveServingBearerToken:
    @pytest.fixture(autouse=True)
    def _public_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _overlay(monkeypatch, False)

    def _cfg(self, base_url: str, **kw: object) -> EnvConfig:
        return EnvConfig(
            llm_provider="openai",
            llm_api_key="env-fallback-key",
            llm_model="databricks-claude-sonnet-4-5",
            llm_base_url=base_url,
            **kw,  # type: ignore[arg-type]
        )

    def test_returns_none_for_non_databricks_url(self) -> None:
        cfg = self._cfg("https://api.openai.com/v1")
        assert da.resolve_serving_bearer_token(cfg) is None

    def test_extracts_bearer_from_authenticated_client(self) -> None:
        cfg = self._cfg(_SERVING)
        fake_client = _client(
            "https://serving-ws.cloud.databricks.com", "oauth-token-xyz"
        )
        with patch.object(
            da, "resolve_workspace_client", return_value=fake_client
        ) as rwc:
            token = da.resolve_serving_bearer_token(cfg)
        assert token == "oauth-token-xyz"
        rwc.assert_called_once()

    def test_returns_none_when_resolution_raises(self) -> None:
        cfg = self._cfg(_SERVING)
        with patch.object(
            da, "resolve_workspace_client", side_effect=RuntimeError("no auth")
        ):
            assert da.resolve_serving_bearer_token(cfg) is None

    def test_returns_none_when_no_bearer_header(self) -> None:
        cfg = self._cfg(_SERVING)
        fake_client = _client("https://serving-ws.cloud.databricks.com")
        fake_client.config.authenticate.return_value = {}
        with patch.object(da, "resolve_workspace_client", return_value=fake_client):
            assert da.resolve_serving_bearer_token(cfg) is None


class TestServingIdentitySeparation:
    """The data profile's token is never sent to a different serving host."""

    def _cfg(self, **kw: object) -> EnvConfig:
        return EnvConfig(
            llm_provider="openai",
            llm_api_key="env-fallback-key",
            llm_base_url=_SERVING,
            **kw,  # type: ignore[arg-type]
        )

    def test_public_different_host_never_sends_data_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _overlay(monkeypatch, False)
        data = _client("https://customer.cloud.databricks.com", "data-secret")
        with patch.object(da, "resolve_workspace_client", return_value=data):
            assert da.resolve_serving_bearer_token(self._cfg()) is None
        data.config.authenticate.assert_not_called()

    def test_public_same_host_reuses_data_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _overlay(monkeypatch, False)
        # Host comparison is on the normalized host (case, scheme, trailing dot, port).
        data = _client("HTTPS://Serving-WS.cloud.databricks.com.", "data-token")
        with patch.object(da, "resolve_workspace_client", return_value=data):
            assert da.resolve_serving_bearer_token(self._cfg()) == "data-token"

    @pytest.mark.parametrize(
        ("credential_host", "expected"),
        [
            ("https://serving-ws.cloud.databricks.com:443", "data-token"),
            ("https://serving-ws.cloud.databricks.com:8443", None),
        ],
    )
    def test_host_comparison_includes_port(
        self,
        monkeypatch: pytest.MonkeyPatch,
        credential_host: str,
        expected: str | None,
    ) -> None:
        _overlay(monkeypatch, False)
        data = _client(credential_host, "data-token")
        with patch.object(da, "resolve_workspace_client", return_value=data):
            assert da.resolve_serving_bearer_token(self._cfg()) == expected

    def test_overlay_never_uses_data_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _overlay(monkeypatch, True)
        # Even when the data host equals the serving host.
        data = _client("https://serving-ws.cloud.databricks.com", "data-secret")
        with patch.object(da, "resolve_workspace_client", return_value=data) as rwc:
            assert da.resolve_serving_bearer_token(self._cfg()) is None
        rwc.assert_not_called()
        data.config.authenticate.assert_not_called()

    def test_overlay_with_serving_profile_uses_that_profile_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _overlay(monkeypatch, True)
        serving = _client("https://serving-ws.cloud.databricks.com", "serving-token")
        with patch.object(da, "resolve_workspace_client", return_value=serving) as rwc:
            token = da.resolve_serving_bearer_token(
                self._cfg(llm_databricks_profile="serving-prof")
            )
        assert token == "serving-token"
        (target,), _ = rwc.call_args
        assert target.profile == "serving-prof"
        assert target.host is None and target.token is None

    def test_serving_profile_host_mismatch_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _overlay(monkeypatch, False)
        wrong = _client("https://other-ws.cloud.databricks.com", "wrong-token")
        with patch.object(da, "resolve_workspace_client", return_value=wrong):
            token = da.resolve_serving_bearer_token(
                self._cfg(llm_databricks_profile="serving-prof")
            )
        assert token is None
        wrong.config.authenticate.assert_not_called()

    def test_serving_profile_ignores_data_host_and_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _overlay(monkeypatch, False)
        serving = _client("https://serving-ws.cloud.databricks.com", "serving-token")
        cfg = self._cfg(
            llm_databricks_profile="serving-prof",
            databricks_host="https://customer.cloud.databricks.com",
            databricks_token="data-pat",
        )
        with patch.object(da, "resolve_workspace_client", return_value=serving) as rwc:
            assert da.resolve_serving_bearer_token(cfg) == "serving-token"
        (target,), _ = rwc.call_args
        assert target.host is None and target.token is None

    def test_overlay_hint_names_serving_profile_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _overlay(monkeypatch, True)
        log = Mock()
        monkeypatch.setattr(da, "logger", log)
        assert da.resolve_serving_bearer_token(self._cfg()) is None
        assert "LLM_DATABRICKS_PROFILE" in str(log.warning.call_args)

    def test_token_never_logged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _overlay(monkeypatch, False)
        log = Mock()
        monkeypatch.setattr(da, "logger", log)
        data = _client("https://customer.cloud.databricks.com", "data-secret")
        with patch.object(da, "resolve_workspace_client", return_value=data):
            da.resolve_serving_bearer_token(self._cfg())
        assert "data-secret" not in str(log.mock_calls)

    def test_env_wiring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_DATABRICKS_PROFILE", "from-env")
        assert EnvConfig().llm_databricks_profile == "from-env"
