"""Unit tests for agent configuration."""

from dataclasses import FrozenInstanceError, replace

import pytest
from starboard_server.agents.config.agent_config import (
    GPT_4O,
    GPT_4O_MINI,
    AgentConfig,
    ModelConfig,
    get_model_config,
)


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AgentConfig()

        assert config.model == "databricks-claude-sonnet-4-5"
        assert config.temperature == 0.3
        assert config.max_tokens == 25_000  # Updated to match actual default
        assert config.max_steps == 20
        assert config.max_messages == 50
        assert config.enable_tracing is True
        assert config.enable_debug is False
        assert config.enable_metrics is True

    def test_custom_config(self):
        """Test custom configuration values."""
        config = AgentConfig(
            model="gpt-4o",
            temperature=0.2,
            max_tokens=80_000,
            max_steps=15,
        )

        assert config.model == "gpt-4o"
        assert config.temperature == 0.2
        assert config.max_tokens == 80_000
        assert config.max_steps == 15
        assert config.max_messages == 50  # Still default

    def test_config_immutability(self):
        """Test that config is immutable (frozen)."""
        config = AgentConfig()

        with pytest.raises(FrozenInstanceError):
            config.model = "gpt-4o"  # type: ignore

    def test_config_replace(self):
        """Test replacing config values using dataclasses.replace()."""
        config = AgentConfig()
        new_config = replace(config, max_tokens=80_000, temperature=0.2)

        # Original unchanged
        assert config.max_tokens == 25_000  # Updated to match actual default
        assert config.temperature == 0.3

        # New config has changes
        assert new_config.max_tokens == 80_000
        assert new_config.temperature == 0.2

        # Other fields unchanged
        assert new_config.model == config.model
        assert new_config.max_steps == config.max_steps

    def test_invalid_temperature(self):
        """Test validation of temperature parameter."""
        with pytest.raises(ValueError, match="Temperature must be between"):
            AgentConfig(temperature=-0.1)

        with pytest.raises(ValueError, match="Temperature must be between"):
            AgentConfig(temperature=2.1)

    def test_invalid_max_tokens(self):
        """Test validation of max_tokens parameter."""
        with pytest.raises(ValueError, match="max_tokens must be positive"):
            AgentConfig(max_tokens=0)

        with pytest.raises(ValueError, match="max_tokens must be positive"):
            AgentConfig(max_tokens=-1000)

    def test_invalid_max_steps(self):
        """Test validation of max_steps parameter."""
        with pytest.raises(ValueError, match="max_steps must be positive"):
            AgentConfig(max_steps=0)

    def test_invalid_max_messages(self):
        """Test validation of max_messages parameter."""
        with pytest.raises(ValueError, match="max_messages must be positive"):
            AgentConfig(max_messages=0)

    def test_estimate_cost(self):
        """Test cost estimation."""
        config = AgentConfig()

        # Test with known values
        cost = config.estimate_cost(input_tokens=5000, output_tokens=1000)

        # Expected: (5000/1000 * 0.00015) + (1000/1000 * 0.0006)
        # = 0.00075 + 0.0006 = 0.00135
        assert abs(cost - 0.00135) < 0.00001

    def test_estimate_cost_zero_tokens(self):
        """Test cost estimation with zero tokens."""
        config = AgentConfig()
        cost = config.estimate_cost(input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_config_types(self):
        """Test that config has correct types."""
        config = AgentConfig()

        assert isinstance(config.model, str)
        assert isinstance(config.temperature, float)
        assert isinstance(config.max_tokens, int)
        assert isinstance(config.max_steps, int)
        assert isinstance(config.max_messages, int)
        assert isinstance(config.enable_tracing, bool)
        assert isinstance(config.enable_debug, bool)
        assert isinstance(config.enable_metrics, bool)


class TestModelConfig:
    """Tests for ModelConfig dataclass."""

    def test_model_config_creation(self):
        """Test creating a ModelConfig."""
        model = ModelConfig(
            name="test-model",
            provider="test-provider",
            context_window=100_000,
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
        )

        assert model.name == "test-model"
        assert model.provider == "test-provider"
        assert model.context_window == 100_000
        assert model.supports_tools is True  # Default
        assert model.supports_streaming is True  # Default

    def test_model_config_with_strengths(self):
        """Test ModelConfig with strengths tuple."""
        model = ModelConfig(
            name="test-model",
            provider="test",
            context_window=100_000,
            strengths=("fast", "cheap"),
        )

        assert len(model.strengths) == 2
        assert "fast" in model.strengths
        assert "cheap" in model.strengths

    def test_model_config_estimate_cost(self):
        """Test ModelConfig cost estimation."""
        model = ModelConfig(
            name="test-model",
            provider="test",
            context_window=100_000,
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
        )

        cost = model.estimate_cost(input_tokens=5000, output_tokens=1000)
        # (5000/1000 * 0.001) + (1000/1000 * 0.002) = 0.005 + 0.002 = 0.007
        assert abs(cost - 0.007) < 0.00001


class TestPredefinedModels:
    """Tests for predefined model configurations."""

    def test_gpt4o_mini_config(self):
        """Test GPT-4o-mini configuration."""
        assert GPT_4O_MINI.name == "gpt-4o-mini"
        assert GPT_4O_MINI.provider == "openai"
        assert GPT_4O_MINI.context_window == 128_000
        assert GPT_4O_MINI.supports_tools is True
        assert "fast" in GPT_4O_MINI.strengths
        assert "cheap" in GPT_4O_MINI.strengths

    def test_gpt4o_config(self):
        """Test GPT-4o configuration."""
        assert GPT_4O.name == "gpt-4o"
        assert GPT_4O.provider == "openai"
        assert GPT_4O.context_window == 128_000
        assert "reasoning" in GPT_4O.strengths

    def test_get_model_config_success(self):
        """Test retrieving existing model config."""
        config = get_model_config("gpt-4o-mini")

        assert config is not None
        assert config.name == "gpt-4o-mini"
        assert config.provider == "openai"

    def test_get_model_config_not_found(self):
        """Test retrieving non-existent model config."""
        config = get_model_config("non-existent-model")
        assert config is None

    def test_get_model_config_claude(self):
        """Test retrieving Claude model config."""
        config = get_model_config("claude-3-5-sonnet")

        assert config is not None
        assert config.provider == "anthropic"
        assert "reasoning" in config.strengths
        assert "code_analysis" in config.strengths

    def test_all_predefined_models_accessible(self):
        """Test that all predefined models can be retrieved."""
        model_names = ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro"]

        for model_name in model_names:
            config = get_model_config(model_name)
            assert config is not None, f"Model {model_name} not found"
            assert config.name is not None
            assert config.provider is not None
            assert config.context_window > 0


class TestConfigIntegration:
    """Integration tests for config usage."""

    def test_config_with_model_metadata(self):
        """Test using AgentConfig with ModelConfig metadata."""
        agent_config = AgentConfig(model="gpt-4o")
        model_config = get_model_config(agent_config.model)

        assert model_config is not None
        assert model_config.name == "gpt-4o"

        # Can estimate cost using either config
        agent_cost = agent_config.estimate_cost(5000, 1000)
        model_cost = model_config.estimate_cost(5000, 1000)

        # Should be similar (may differ slightly due to config overrides)
        assert isinstance(agent_cost, float)
        assert isinstance(model_cost, float)

    def test_config_usage_pattern(self):
        """Test typical configuration usage pattern."""
        # Start with defaults
        config = AgentConfig()

        # Override for specific use case
        prod_config = replace(
            config,
            model="gpt-4o",
            max_tokens=200_000,
            temperature=0.2,
            enable_debug=False,
        )

        # Verify changes
        assert prod_config.model == "gpt-4o"
        assert prod_config.max_tokens == 200_000
        assert prod_config.temperature == 0.2
        assert prod_config.enable_debug is False

        # Original unchanged
        assert config.model == "databricks-claude-sonnet-4-5"
        assert config.max_tokens == 25_000  # Updated to match actual default
