# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for discovery fields on EnvConfig.

Tests cover:
- Default values for discovery_* fields
- from_env() loading from environment variables
- sync_to_env() writing discovery fields
- validate_config() checking discovery constraints
"""

import os
from unittest.mock import patch

import pytest
from starboard_server.infra.core.config import EnvConfig


class TestEnvConfigDiscoveryDefaults:
    def test_default_lookback(self):
        cfg = EnvConfig()
        assert cfg.discovery_lookback_days == 30

    def test_default_parallelism(self):
        cfg = EnvConfig()
        assert cfg.discovery_max_parallelism == 8

    def test_default_domains(self):
        cfg = EnvConfig()
        assert cfg.discovery_domains is None

    def test_default_data_only(self):
        cfg = EnvConfig()
        assert cfg.discovery_data_only is False

    def test_default_output_dir(self):
        cfg = EnvConfig()
        assert cfg.discovery_output_dir == "./discovery_output"

    def test_default_llm_model(self):
        cfg = EnvConfig()
        assert cfg.discovery_llm_model is None

    def test_default_llm_temperature(self):
        cfg = EnvConfig()
        assert cfg.discovery_llm_temperature == 0.3


class TestEnvConfigDiscoveryFromEnv:
    def test_loads_lookback_days(self):
        with patch.dict(os.environ, {"DISCOVERY_LOOKBACK_DAYS": "90"}, clear=False):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_lookback_days == 90

    def test_loads_max_parallelism(self):
        with patch.dict(os.environ, {"DISCOVERY_MAX_PARALLELISM": "8"}, clear=False):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_max_parallelism == 8

    def test_loads_domains(self):
        with patch.dict(
            os.environ, {"DISCOVERY_DOMAINS": "billing,jobs,compute"}, clear=False
        ):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_domains == ["billing", "jobs", "compute"]

    def test_loads_domains_strips_whitespace(self):
        with patch.dict(
            os.environ, {"DISCOVERY_DOMAINS": " billing , jobs "}, clear=False
        ):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_domains == ["billing", "jobs"]

    def test_no_domains_env_returns_none(self):
        env = {k: v for k, v in os.environ.items() if k != "DISCOVERY_DOMAINS"}
        with patch.dict(os.environ, env, clear=True):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_domains is None

    def test_loads_data_only(self):
        with patch.dict(os.environ, {"DISCOVERY_DATA_ONLY": "true"}, clear=False):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_data_only is True

    def test_loads_output_dir(self):
        with patch.dict(os.environ, {"DISCOVERY_OUTPUT_DIR": "/tmp/out"}, clear=False):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_output_dir == "/tmp/out"

    def test_loads_llm_model(self):
        with patch.dict(os.environ, {"DISCOVERY_LLM_MODEL": "gpt-4o"}, clear=False):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_llm_model == "gpt-4o"

    def test_loads_llm_temperature(self):
        with patch.dict(os.environ, {"DISCOVERY_LLM_TEMPERATURE": "0.5"}, clear=False):
            cfg = EnvConfig.from_env()
        assert cfg.discovery_llm_temperature == 0.5


class TestEnvConfigDiscoverySyncToEnv:
    def test_sync_lookback(self):
        cfg = EnvConfig(discovery_lookback_days=60)
        with patch.dict(os.environ, {}, clear=False):
            cfg.sync_to_env()
            assert os.environ["DISCOVERY_LOOKBACK_DAYS"] == "60"

    def test_sync_parallelism(self):
        cfg = EnvConfig(discovery_max_parallelism=8)
        with patch.dict(os.environ, {}, clear=False):
            cfg.sync_to_env()
            assert os.environ["DISCOVERY_MAX_PARALLELISM"] == "8"

    def test_sync_domains(self):
        cfg = EnvConfig(discovery_domains=["billing", "jobs"])
        with patch.dict(os.environ, {}, clear=False):
            cfg.sync_to_env()
            assert os.environ["DISCOVERY_DOMAINS"] == "billing,jobs"

    def test_sync_domains_none_skipped(self):
        cfg = EnvConfig(discovery_domains=None)
        env_copy = dict(os.environ)
        env_copy.pop("DISCOVERY_DOMAINS", None)
        with patch.dict(os.environ, env_copy, clear=True):
            cfg.sync_to_env()
            assert "DISCOVERY_DOMAINS" not in os.environ

    def test_sync_data_only(self):
        cfg = EnvConfig(discovery_data_only=True)
        with patch.dict(os.environ, {}, clear=False):
            cfg.sync_to_env()
            assert os.environ["DISCOVERY_DATA_ONLY"] == "true"

    def test_sync_llm_model(self):
        cfg = EnvConfig(discovery_llm_model="gpt-4o")
        with patch.dict(os.environ, {}, clear=False):
            cfg.sync_to_env()
            assert os.environ["DISCOVERY_LLM_MODEL"] == "gpt-4o"

    def test_sync_llm_model_none_skipped(self):
        cfg = EnvConfig(discovery_llm_model=None)
        env_copy = dict(os.environ)
        env_copy.pop("DISCOVERY_LLM_MODEL", None)
        with patch.dict(os.environ, env_copy, clear=True):
            cfg.sync_to_env()
            assert "DISCOVERY_LLM_MODEL" not in os.environ


class TestEnvConfigDiscoveryValidation:
    def test_valid_lookback_30(self):
        cfg = EnvConfig(discovery_lookback_days=30, offline_mode=True)
        cfg.validate_config()

    def test_valid_lookback_60(self):
        cfg = EnvConfig(discovery_lookback_days=60, offline_mode=True)
        cfg.validate_config()

    def test_valid_lookback_90(self):
        cfg = EnvConfig(discovery_lookback_days=90, offline_mode=True)
        cfg.validate_config()

    def test_invalid_lookback(self):
        cfg = EnvConfig(discovery_lookback_days=45, offline_mode=True)
        with pytest.raises(ValueError, match="discovery_lookback_days"):
            cfg.validate_config()

    def test_parallelism_too_low(self):
        cfg = EnvConfig(discovery_max_parallelism=0, offline_mode=True)
        with pytest.raises(ValueError, match="discovery_max_parallelism"):
            cfg.validate_config()

    def test_parallelism_too_high(self):
        cfg = EnvConfig(discovery_max_parallelism=32, offline_mode=True)
        with pytest.raises(ValueError, match="discovery_max_parallelism"):
            cfg.validate_config()

    def test_parallelism_boundary_1(self):
        cfg = EnvConfig(discovery_max_parallelism=1, offline_mode=True)
        cfg.validate_config()

    def test_parallelism_boundary_16(self):
        cfg = EnvConfig(discovery_max_parallelism=16, offline_mode=True)
        cfg.validate_config()


class TestEnvConfigDiscoveryOverride:
    def test_model_copy(self):
        cfg = EnvConfig()
        overridden = cfg.model_copy(update={"discovery_lookback_days": 90})
        assert overridden.discovery_lookback_days == 90
        assert cfg.discovery_lookback_days == 30
