"""
Tests for model limits and constraints.

Tests the model_limits module which defines maximum token limits and other
constraints for various LLM providers.
"""

import pytest
from starboard_server.infra.constraints.model_limits import (
    ANTHROPIC_MODELS,
    DATABRICKS_MODELS,
    DEFAULT_MODEL_LIMITS,
    GEMINI_MODELS,
    OPENAI_MODELS,
    ModelLimits,
    get_max_tokens_by_model,
    get_model_limits,
    list_supported_models,
)


class TestModelLimits:
    """Tests for ModelLimits dataclass."""

    def test_model_limits_immutable(self):
        """Test that ModelLimits is immutable (frozen dataclass)."""
        limits = ModelLimits(max_output_tokens=16384, context_window=128000)

        with pytest.raises(AttributeError):
            limits.max_output_tokens = 8192  # Should fail - frozen

    def test_model_limits_defaults(self):
        """Test ModelLimits default values."""
        limits = ModelLimits(max_output_tokens=16384, context_window=128000)

        assert limits.max_output_tokens == 16384
        assert limits.context_window == 128000
        assert limits.supports_streaming is True  # Default
        assert limits.supports_function_calling is True  # Default

    def test_model_limits_custom_flags(self):
        """Test ModelLimits with custom support flags."""
        limits = ModelLimits(
            max_output_tokens=32768,
            context_window=128000,
            supports_streaming=False,
            supports_function_calling=False,
        )

        assert limits.supports_streaming is False
        assert limits.supports_function_calling is False


class TestGetMaxTokensByModel:
    """Tests for get_max_tokens_by_model function."""

    def test_openai_gpt4o_max(self):
        """Test getting max tokens for GPT-4o."""
        max_tokens = get_max_tokens_by_model("gpt-4o", use_max=True)
        assert max_tokens == 16384

    def test_openai_gpt4o_conservative(self):
        """Test getting conservative default for GPT-4o."""
        max_tokens = get_max_tokens_by_model("gpt-4o", use_max=False)
        # Conservative: min(16384//4, 4096) = 4096
        assert max_tokens == 4096

    def test_anthropic_claude_opus_max(self):
        """Test getting max tokens for Claude Opus."""
        max_tokens = get_max_tokens_by_model("claude-3-opus-20240229", use_max=True)
        assert max_tokens == 4096

    def test_gemini_pro_max(self):
        """Test getting max tokens for Gemini Pro."""
        max_tokens = get_max_tokens_by_model("gemini-1.5-pro", use_max=True)
        assert max_tokens == 8192

    def test_databricks_gpt5_max(self):
        """Test getting max tokens for Databricks GPT-5."""
        max_tokens = get_max_tokens_by_model("databricks-gpt-5", use_max=True)
        assert max_tokens == 65536

    def test_databricks_gpt5_1_max(self):
        """Test getting max tokens for Databricks GPT-5-1."""
        max_tokens = get_max_tokens_by_model("databricks-gpt-5-1", use_max=True)
        assert max_tokens == 65536

    def test_case_insensitive(self):
        """Test that model lookup is case insensitive."""
        assert get_max_tokens_by_model("GPT-4O", use_max=True) == 16384
        assert get_max_tokens_by_model("gpt-4o", use_max=True) == 16384
        assert get_max_tokens_by_model("Gpt-4o", use_max=True) == 16384

    def test_whitespace_trimming(self):
        """Test that whitespace is trimmed from model names."""
        assert get_max_tokens_by_model("  gpt-4o  ", use_max=True) == 16384
        assert get_max_tokens_by_model("\tgpt-4o\n", use_max=True) == 16384

    def test_unknown_model_uses_default(self):
        """Test that unknown models use default limits."""
        max_tokens = get_max_tokens_by_model("unknown-model-xyz", use_max=True)
        assert max_tokens == DEFAULT_MODEL_LIMITS.max_output_tokens

    def test_unknown_model_with_custom_fallback(self):
        """Test that custom fallback is used for unknown models."""
        max_tokens = get_max_tokens_by_model(
            "unknown-model-xyz",
            use_max=True,
            fallback=10000,
        )
        assert max_tokens == 10000

    def test_fuzzy_matching_for_versioned_models(self):
        """Test that versioned model names are matched."""
        # Should match "gpt-4o" even with version suffix
        max_tokens = get_max_tokens_by_model("gpt-4o-2024-05-13", use_max=True)
        assert max_tokens > 0  # Should find a match

    def test_o1_models_max_tokens(self):
        """Test o1 reasoning models have correct max tokens."""
        assert get_max_tokens_by_model("o1-preview", use_max=True) == 32768
        assert get_max_tokens_by_model("o1-mini", use_max=True) == 65536

    def test_databricks_prefix_models(self):
        """Test various Databricks-prefixed models."""
        models = [
            ("databricks-claude-sonnet-4-5", 8192),
            ("databricks-gpt-5", 65536),
            ("databricks-gpt-5-mini", 16384),
            ("databricks-gemini-2.5-pro", 8192),
        ]

        for model, expected_max in models:
            assert get_max_tokens_by_model(model, use_max=True) == expected_max


class TestGetModelLimits:
    """Tests for get_model_limits function."""

    def test_get_complete_limits_gpt4o(self):
        """Test getting complete limits for GPT-4o."""
        limits = get_model_limits("gpt-4o")

        assert limits.max_output_tokens == 16384
        assert limits.context_window == 128000
        assert limits.supports_streaming is True
        assert limits.supports_function_calling is True

    def test_get_complete_limits_o1_preview(self):
        """Test getting limits for o1-preview (no streaming/function calling)."""
        limits = get_model_limits("o1-preview")

        assert limits.max_output_tokens == 32768
        assert limits.context_window == 128000
        assert limits.supports_streaming is False  # o1 doesn't support streaming
        assert limits.supports_function_calling is False  # o1 doesn't support functions

    def test_get_complete_limits_unknown_model(self):
        """Test that unknown models return default limits."""
        limits = get_model_limits("unknown-model-xyz")

        assert limits == DEFAULT_MODEL_LIMITS

    def test_get_complete_limits_claude(self):
        """Test getting limits for Claude model."""
        limits = get_model_limits("claude-3-opus-20240229")

        assert limits.max_output_tokens == 4096
        assert limits.context_window == 200000

    def test_get_complete_limits_gemini(self):
        """Test getting limits for Gemini model."""
        limits = get_model_limits("gemini-1.5-pro")

        assert limits.max_output_tokens == 8192
        assert limits.context_window == 2097152  # 2M tokens


class TestListSupportedModels:
    """Tests for list_supported_models function."""

    def test_returns_all_providers(self):
        """Test that all providers are returned."""
        models = list_supported_models()

        assert "openai" in models
        assert "anthropic" in models
        assert "gemini" in models
        assert "databricks" in models

    def test_openai_models_present(self):
        """Test that OpenAI models are listed."""
        models = list_supported_models()

        assert "gpt-4o" in models["openai"]
        assert "gpt-4o-mini" in models["openai"]
        assert "o1-preview" in models["openai"]

    def test_anthropic_models_present(self):
        """Test that Anthropic models are listed."""
        models = list_supported_models()

        assert "claude-3-opus-20240229" in models["anthropic"]
        assert "claude-3-sonnet-20240229" in models["anthropic"]

    def test_gemini_models_present(self):
        """Test that Gemini models are listed."""
        models = list_supported_models()

        assert "gemini-1.5-pro" in models["gemini"]
        assert "gemini-1.5-flash" in models["gemini"]

    def test_databricks_models_present(self):
        """Test that Databricks models are listed."""
        models = list_supported_models()

        assert "databricks-gpt-5" in models["databricks"]
        assert "databricks-claude-sonnet-4-5" in models["databricks"]
        assert "databricks-gemini-2.5-pro" in models["databricks"]


class TestModelRegistries:
    """Tests for model registry completeness and correctness."""

    def test_openai_registry_not_empty(self):
        """Test that OpenAI registry has models defined."""
        assert len(OPENAI_MODELS) > 0

    def test_anthropic_registry_not_empty(self):
        """Test that Anthropic registry has models defined."""
        assert len(ANTHROPIC_MODELS) > 0

    def test_gemini_registry_not_empty(self):
        """Test that Gemini registry has models defined."""
        assert len(GEMINI_MODELS) > 0

    def test_databricks_registry_not_empty(self):
        """Test that Databricks registry has models defined."""
        assert len(DATABRICKS_MODELS) > 0

    def test_all_limits_have_positive_values(self):
        """Test that all model limits have positive values."""
        for registry in [
            OPENAI_MODELS,
            ANTHROPIC_MODELS,
            GEMINI_MODELS,
            DATABRICKS_MODELS,
        ]:
            for model, limits in registry.items():
                assert limits.max_output_tokens > 0, (
                    f"{model} has invalid max_output_tokens"
                )
                assert limits.context_window > 0, f"{model} has invalid context_window"
                assert limits.context_window >= limits.max_output_tokens, (
                    f"{model} context_window should be >= max_output_tokens"
                )

    def test_default_limits_reasonable(self):
        """Test that default limits are reasonable."""
        assert DEFAULT_MODEL_LIMITS.max_output_tokens == 4096
        assert DEFAULT_MODEL_LIMITS.context_window == 16384
        assert DEFAULT_MODEL_LIMITS.supports_streaming is True
        assert DEFAULT_MODEL_LIMITS.supports_function_calling is True


class TestConservativeDefaults:
    """Tests for conservative default behavior."""

    def test_conservative_for_small_models(self):
        """Test conservative default for models with small max tokens."""
        # Model with max_output_tokens = 4096
        # Conservative: min(4096//4, 4096) = min(1024, 4096) = 1024
        max_tokens = get_max_tokens_by_model("gpt-3.5-turbo", use_max=False)
        assert max_tokens == 1024

    def test_conservative_for_large_models(self):
        """Test conservative default for models with large max tokens."""
        # Model with max_output_tokens = 65536
        # Conservative: min(65536//4, 4096) = min(16384, 4096) = 4096
        max_tokens = get_max_tokens_by_model("o1-mini", use_max=False)
        assert max_tokens == 4096

    def test_conservative_never_exceeds_4096(self):
        """Test that conservative default never exceeds 4096."""
        # Test all models
        for registry in [
            OPENAI_MODELS,
            ANTHROPIC_MODELS,
            GEMINI_MODELS,
            DATABRICKS_MODELS,
        ]:
            for model in registry:
                conservative = get_max_tokens_by_model(model, use_max=False)
                assert conservative <= 4096, (
                    f"{model} conservative default exceeds 4096"
                )


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_model_name(self):
        """Test behavior with empty model name."""
        max_tokens = get_max_tokens_by_model("", use_max=True)
        assert max_tokens == DEFAULT_MODEL_LIMITS.max_output_tokens

    def test_none_fallback(self):
        """Test that None fallback uses default."""
        max_tokens = get_max_tokens_by_model(
            "unknown",
            use_max=True,
            fallback=None,
        )
        assert max_tokens == DEFAULT_MODEL_LIMITS.max_output_tokens

    def test_zero_fallback(self):
        """Test that zero fallback is respected."""
        max_tokens = get_max_tokens_by_model(
            "unknown",
            use_max=True,
            fallback=0,
        )
        assert max_tokens == 0

    def test_special_characters_in_model_name(self):
        """Test model names with special characters."""
        # Should not crash, should return default
        max_tokens = get_max_tokens_by_model("model@#$%", use_max=True)
        assert max_tokens == DEFAULT_MODEL_LIMITS.max_output_tokens
