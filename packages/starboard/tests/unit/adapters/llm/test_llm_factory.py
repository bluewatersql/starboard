# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for LLM client factory pattern."""

from unittest.mock import Mock, patch

import pytest
from starboard.adapters.llm import BaseLLMClient, create_llm_client
from starboard.infra.core.config import EnvConfig


class TestLLMFactory:
    """Test LLM client factory function."""

    def test_create_llm_client_with_openai_provider(self) -> None:
        """Test factory creates OpenAIProvider when provider is 'openai'."""
        config = EnvConfig(
            llm_provider="openai",
            llm_api_key="test-key",
            llm_model="gpt-4",
        )

        client = create_llm_client(cfg=config)

        assert isinstance(client, BaseLLMClient)
        assert client.__class__.__name__ == "OpenAIProvider"

    def test_create_llm_client_defaults_to_openai(self) -> None:
        """Test factory defaults to OpenAIProvider when provider not specified."""
        config = EnvConfig(
            llm_provider="",  # Empty string should default to openai
            llm_api_key="test-key",
            llm_model="gpt-4",
        )

        client = create_llm_client(cfg=config)

        assert isinstance(client, BaseLLMClient)
        assert client.__class__.__name__ == "OpenAIProvider"

    def test_create_llm_client_loads_from_env_when_none(self) -> None:
        """Test factory loads config from environment when cfg is None."""
        # Patch the correct import path (EnvConfig is in infra.core.config)
        with patch("starboard.infra.core.config.EnvConfig") as mock_config_class:
            mock_config = Mock(spec=EnvConfig)
            mock_config.llm_provider = "openai"
            mock_config.llm_api_key = "test-key"
            mock_config.llm_model = "gpt-4"
            mock_config.llm_base_url = None
            mock_config.llm_temperature = 0.4
            mock_config.llm_max_tokens = 8192
            mock_config.llm_seed = 42
            mock_config.llm_planning_model = None
            mock_config.llm_judge_model = None
            mock_config.llm_synth_model = None
            mock_config.llm_planning_temperature = None
            mock_config.llm_judge_temperature = None
            mock_config.llm_synth_temperature = None
            mock_config_class.from_env.return_value = mock_config

            with patch("starboard.adapters.llm.openai.client.AsyncOpenAI"):
                client = create_llm_client(cfg=None)

                assert isinstance(client, BaseLLMClient)
                mock_config_class.from_env.assert_called_once()

    def test_create_llm_client_raises_for_unsupported_provider(self) -> None:
        """Test factory raises ValueError for unsupported providers."""
        config = EnvConfig(
            llm_provider="anthropic",  # Not yet supported
            llm_api_key="test-key",
            llm_model="claude-3",
        )

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            create_llm_client(cfg=config)

    def test_create_llm_client_case_insensitive_provider(self) -> None:
        """Test factory handles case-insensitive provider names."""
        config = EnvConfig(
            llm_provider="OPENAI",  # Uppercase
            llm_api_key="test-key",
            llm_model="gpt-4",
        )

        client = create_llm_client(cfg=config)

        assert isinstance(client, BaseLLMClient)
        assert client.__class__.__name__ == "OpenAIProvider"

    def test_databricks_serving_uses_resolved_oauth_token(self) -> None:
        """When LLM_BASE_URL is a Databricks serving endpoint, the client uses the
        token resolved from the auth'd client — not the static LLM_API_KEY."""
        config = EnvConfig(
            llm_provider="openai",
            llm_api_key="stale-pat",
            llm_model="databricks-claude-sonnet-4-5",
            llm_base_url="https://ws.cloud.databricks.com/serving-endpoints",
        )
        with patch(
            "starboard.adapters.llm.databricks_auth.resolve_serving_bearer_token",
            return_value="fresh-oauth-token",
        ):
            client = create_llm_client(cfg=config)
        # OpenAIProvider stores the resolved key on its AsyncOpenAI client.
        assert client.async_client.api_key == "fresh-oauth-token"

    def test_falls_back_to_env_key_when_no_oauth_token(self) -> None:
        """When no Databricks token can be resolved, the client falls back to the
        configured LLM_API_KEY (e.g. real OpenAI, or resolution failure)."""
        config = EnvConfig(
            llm_provider="openai",
            llm_api_key="env-key",
            llm_model="gpt-4o",
            llm_base_url="https://api.openai.com/v1",
        )
        with patch(
            "starboard.adapters.llm.databricks_auth.resolve_serving_bearer_token",
            return_value=None,
        ):
            client = create_llm_client(cfg=config)
        assert client.async_client.api_key == "env-key"

    def test_create_llm_client_logs_provider_selection(self) -> None:
        """Test factory logs provider selection."""
        config = EnvConfig(
            llm_provider="openai",
            llm_api_key="test-key",
            llm_model="gpt-4",
        )

        with patch("starboard.adapters.llm.logger") as mock_logger:
            create_llm_client(cfg=config)

            mock_logger.debug.assert_called_once()
            call_args = mock_logger.debug.call_args
            assert "creating_llm_client" in call_args[0][0]
            assert call_args[1]["extra"]["provider"] == "openai"
            assert call_args[1]["extra"]["model"] == "gpt-4"
