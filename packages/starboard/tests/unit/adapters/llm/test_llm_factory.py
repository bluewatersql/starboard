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
            mock_config.llm_review_model = None
            mock_config.llm_synth_model = None
            mock_config.llm_planning_temperature = None
            mock_config.llm_judge_temperature = None
            mock_config.llm_review_temperature = None
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
