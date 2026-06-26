# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for configuration precedence and environment variable syncing.

Tests the following priority order (highest to lowest):
1. Direct (CLI arguments)
2. Config file (config.yaml)
3. Environment variables
4. Defaults
"""

import os
from unittest.mock import patch

from starboard_server.infra.core.config import EnvConfig, get_config, set_config


class TestConfigPrecedence:
    """Test configuration precedence order."""

    def test_env_config_from_env_reads_environment_variables(self):
        """Test that EnvConfig.from_env() reads from environment variables."""
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_HOST": "https://test.databricks.com",
                "DATABRICKS_TOKEN": "test-token",
                "DATABRICKS_WAREHOUSE_ID": "test-warehouse",
                "LLM_MODEL": "gpt-4o",
                "LLM_TEMPERATURE": "0.7",
            },
            clear=False,
        ):
            config = EnvConfig.from_env()

            assert config.databricks_host == "https://test.databricks.com"
            assert config.databricks_token == "test-token"
            assert config.databricks_warehouse_id == "test-warehouse"
            assert config.llm_model == "gpt-4o"
            assert config.llm_temperature == 0.7

    def test_sync_to_env_updates_environment_variables(self):
        """Test that sync_to_env() updates runtime environment variables."""
        config = EnvConfig(
            databricks_host="https://synced.databricks.com",
            databricks_token="synced-token",
            databricks_warehouse_id="synced-warehouse",
            llm_model="gpt-4o-mini",
            llm_temperature=0.5,
        )

        # Clear environment first
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_HOST": "",
                "DATABRICKS_TOKEN": "",
                "DATABRICKS_WAREHOUSE_ID": "",
                "LLM_MODEL": "",
                "LLM_TEMPERATURE": "",
            },
            clear=False,
        ):
            config.sync_to_env()

            assert os.getenv("DATABRICKS_HOST") == "https://synced.databricks.com"
            assert os.getenv("DATABRICKS_TOKEN") == "synced-token"
            assert os.getenv("DATABRICKS_WAREHOUSE_ID") == "synced-warehouse"
            assert os.getenv("LLM_MODEL") == "gpt-4o-mini"
            assert os.getenv("LLM_TEMPERATURE") == "0.5"

    def test_sync_to_env_syncs_openai_api_key_for_openai_provider(self):
        """Test that sync_to_env() syncs LLM_API_KEY to OPENAI_API_KEY for openai provider."""
        config = EnvConfig(
            llm_provider="openai",
            llm_api_key="test-openai-key",
        )

        with patch.dict(os.environ, {}, clear=False):
            config.sync_to_env()

            assert os.getenv("LLM_API_KEY") == "test-openai-key"
            assert os.getenv("OPENAI_API_KEY") == "test-openai-key"

    def test_sync_to_env_does_not_sync_none_values(self):
        """Test that sync_to_env() does not override environment with None values."""
        # Set initial environment values
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_HOST": "https://original.databricks.com",
                "LLM_MODEL": "original-model",
            },
            clear=False,
        ):
            config = EnvConfig(
                databricks_host=None,  # None value should not overwrite
                llm_model="new-model",  # Non-None should update
            )

            config.sync_to_env()

            # Original value should remain (not overwritten by None)
            assert os.getenv("DATABRICKS_HOST") == "https://original.databricks.com"
            # New value should be set
            assert os.getenv("LLM_MODEL") == "new-model"

    def test_set_config_updates_global_singleton(self):
        """Test that set_config() updates the global config singleton."""
        custom_config = EnvConfig(
            databricks_host="https://custom.databricks.com",
            llm_model="custom-model",
        )

        # Reset global config
        from starboard_server.infra.core import config as config_module

        config_module._env_config = None

        # Set custom config
        set_config(custom_config, sync_to_env=False)

        # get_config() should return the custom config
        assert get_config() == custom_config
        assert get_config().databricks_host == "https://custom.databricks.com"
        assert get_config().llm_model == "custom-model"

    def test_set_config_syncs_to_env_when_enabled(self):
        """Test that set_config() syncs to environment when sync_to_env=True."""
        custom_config = EnvConfig(
            databricks_host="https://synced-via-set.databricks.com",
            llm_model="synced-model",
        )

        with patch.dict(os.environ, {}, clear=False):
            set_config(custom_config, sync_to_env=True)

            # Environment should be updated
            assert (
                os.getenv("DATABRICKS_HOST") == "https://synced-via-set.databricks.com"
            )
            assert os.getenv("LLM_MODEL") == "synced-model"

    def test_config_precedence_direct_over_file(self):
        """
        Test that direct config (CLI args) takes precedence over file config.

        Scenario:
        - Environment: DATABRICKS_HOST=env-host
        - File: DATABRICKS_HOST=file-host
        - Direct: DATABRICKS_HOST=direct-host
        - Expected: direct-host (highest precedence)
        """
        from dataclasses import replace

        # Base config from environment
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_HOST": "env-host",
            },
            clear=False,
        ):
            base_config = EnvConfig.from_env()

            # Override with file config
            file_config = replace(base_config, databricks_host="file-host")

            # Override with direct config (highest precedence)
            final_config = replace(file_config, databricks_host="direct-host")

            # Sync to environment
            final_config.sync_to_env()

            # Direct config should win
            assert final_config.databricks_host == "direct-host"
            assert os.getenv("DATABRICKS_HOST") == "direct-host"

    def test_config_precedence_file_over_env(self):
        """
        Test that file config takes precedence over environment variables.

        Scenario:
        - Environment: LLM_MODEL=env-model
        - File: LLM_MODEL=file-model
        - Expected: file-model (file > env)
        """
        from dataclasses import replace

        with patch.dict(
            os.environ,
            {
                "LLM_MODEL": "env-model",
            },
            clear=False,
        ):
            base_config = EnvConfig.from_env()
            assert base_config.llm_model == "env-model"

            # Override with file config
            file_config = replace(base_config, llm_model="file-model")
            file_config.sync_to_env()

            # File config should win
            assert file_config.llm_model == "file-model"
            assert os.getenv("LLM_MODEL") == "file-model"

    def test_databricks_sdk_reads_synced_environment(self):
        """
        Test that Databricks SDK can read configuration synced to environment.

        This simulates the bug where Databricks SDK couldn't see config from files/CLI.
        """
        # Start with no environment variables
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_HOST": "",
                "DATABRICKS_TOKEN": "",
            },
            clear=True,
        ):
            # Config loaded from file (simulated)
            config = EnvConfig(
                databricks_host="https://file-config.databricks.com",
                databricks_token="file-token",
            )

            # Sync to environment (this is the fix)
            config.sync_to_env()

            # Databricks SDK reads from os.environ
            # Simulate this by checking environment directly
            assert os.getenv("DATABRICKS_HOST") == "https://file-config.databricks.com"
            assert os.getenv("DATABRICKS_TOKEN") == "file-token"

    def test_sync_to_env_handles_complex_types(self):
        """Test that sync_to_env() properly converts complex types to strings."""
        import json

        config = EnvConfig(
            disabled_agent_domains=["diagnostic", "table"],
            domain_model_overrides={"router": "gpt-4o-mini", "query": "gpt-4o"},
            domain_temperature_overrides={"router": 0.2, "query": 0.3},
        )

        with patch.dict(os.environ, {}, clear=False):
            config.sync_to_env()

            # List
            assert os.getenv("DISABLED_AGENT_DOMAINS") == "diagnostic,table"

            # Dict (JSON)
            model_overrides = json.loads(os.getenv("DOMAIN_MODEL_OVERRIDES"))
            assert model_overrides == {"router": "gpt-4o-mini", "query": "gpt-4o"}

            temp_overrides = json.loads(os.getenv("DOMAIN_TEMPERATURE_OVERRIDES"))
            assert temp_overrides == {"router": 0.2, "query": 0.3}
