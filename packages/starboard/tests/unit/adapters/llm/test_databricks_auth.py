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
        ],
    )
    def test_true_for_databricks_hosts(self, url: str) -> None:
        assert da.is_databricks_serving_url(url) is True

    @pytest.mark.parametrize("url", ["", None, "https://api.openai.com/v1"])
    def test_false_otherwise(self, url: str | None) -> None:
        assert da.is_databricks_serving_url(url) is False


class TestResolveServingBearerToken:
    def _cfg(self, base_url: str) -> EnvConfig:
        return EnvConfig(
            llm_provider="openai",
            llm_api_key="env-fallback-key",
            llm_model="databricks-claude-sonnet-4-5",
            llm_base_url=base_url,
        )

    def test_returns_none_for_non_databricks_url(self) -> None:
        cfg = self._cfg("https://api.openai.com/v1")
        assert da.resolve_serving_bearer_token(cfg) is None

    def test_extracts_bearer_from_authenticated_client(self) -> None:
        cfg = self._cfg(
            "https://e2-demo-field-eng.cloud.databricks.com/serving-endpoints"
        )
        fake_client = Mock()
        fake_client.config.authenticate.return_value = {
            "Authorization": "Bearer oauth-token-xyz"
        }
        with patch.object(
            da, "resolve_workspace_client", return_value=fake_client
        ) as rwc:
            token = da.resolve_serving_bearer_token(cfg)
        assert token == "oauth-token-xyz"
        rwc.assert_called_once()

    def test_returns_none_when_resolution_raises(self) -> None:
        cfg = self._cfg(
            "https://e2-demo-field-eng.cloud.databricks.com/serving-endpoints"
        )
        with patch.object(
            da, "resolve_workspace_client", side_effect=RuntimeError("no auth")
        ):
            assert da.resolve_serving_bearer_token(cfg) is None

    def test_returns_none_when_no_bearer_header(self) -> None:
        cfg = self._cfg(
            "https://e2-demo-field-eng.cloud.databricks.com/serving-endpoints"
        )
        fake_client = Mock()
        fake_client.config.authenticate.return_value = {}
        with patch.object(da, "resolve_workspace_client", return_value=fake_client):
            assert da.resolve_serving_bearer_token(cfg) is None
