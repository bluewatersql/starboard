# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""W5: EnvConfig repr must never expose secret fields.

Ensures that ``databricks_token`` and ``llm_api_key`` are suppressed from
``__repr__`` so they cannot leak through Rich pretty-exceptions with
show_locals=True or any other repr-based traceback renderer.
"""

from __future__ import annotations

import traceback

import pytest
from starboard.infra.core.config import EnvConfig

SECRET_TOKEN = "dapi-super-secret-token-abc123"
SECRET_KEY = "sk-openai-super-secret-key-xyz"


@pytest.fixture()
def cfg_with_secrets() -> EnvConfig:
    return EnvConfig(
        databricks_host="https://myws.cloud.databricks.com",
        databricks_token=SECRET_TOKEN,
        llm_api_key=SECRET_KEY,
    )


class TestEnvConfigReprRedaction:
    def test_token_absent_from_repr(self, cfg_with_secrets: EnvConfig) -> None:
        assert SECRET_TOKEN not in repr(cfg_with_secrets)

    def test_llm_key_absent_from_repr(self, cfg_with_secrets: EnvConfig) -> None:
        assert SECRET_KEY not in repr(cfg_with_secrets)

    def test_host_still_visible_in_repr(self, cfg_with_secrets: EnvConfig) -> None:
        # Non-secret fields should still appear in repr.
        assert "myws.cloud.databricks.com" in repr(cfg_with_secrets)

    def test_token_absent_from_traceback_locals(
        self, cfg_with_secrets: EnvConfig
    ) -> None:
        """Simulate a traceback that captures the config as a local variable.

        Even if a future caller enables show_locals=True (Rich or native), the
        token must not appear because pydantic's repr suppresses it.
        """
        cfg = cfg_with_secrets  # intentional local variable name

        def _failing_function(config: EnvConfig) -> None:
            raise RuntimeError("auth failed")  # config is in locals here

        tb_text = ""
        try:
            _failing_function(cfg)
        except RuntimeError:
            tb_text = traceback.format_exc()

        # The traceback text itself doesn't include locals (Python default), but
        # verifying repr() is the important safety gate — rich/locals mode calls
        # repr() on each local variable.
        assert SECRET_TOKEN not in repr(cfg)
        assert SECRET_KEY not in repr(cfg)
        # The traceback message should also not contain either secret.
        assert SECRET_TOKEN not in tb_text
        assert SECRET_KEY not in tb_text

    def test_model_dump_still_returns_token_value(
        self, cfg_with_secrets: EnvConfig
    ) -> None:
        """repr=False must not strip the value from model_dump() — only from repr."""
        d = cfg_with_secrets.model_dump()
        assert d["databricks_token"] == SECRET_TOKEN
        assert d["llm_api_key"] == SECRET_KEY
