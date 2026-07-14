# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for LLM temperature overrides and provider constraints.

Tests that temperature is correctly overridden for models with provider-specific
constraints (e.g., GPT-5 models requiring temperature=1.0).
"""

from unittest.mock import patch

import pytest
from starboard.adapters.llm.openai.client import OpenAIProvider
from starboard.infra.core.config import EnvConfig


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    return EnvConfig(
        llm_api_key="test-key",
        llm_model="databricks-claude-sonnet-4-5",
        llm_temperature=0.5,
        llm_max_tokens=75000,
    )


@pytest.fixture
def llm_client(mock_config):
    """Create LLM client for testing."""
    return OpenAIProvider(cfg=mock_config)


class TestGPT5TemperatureOverride:
    """Tests for GPT-5 model temperature override."""

    def test_is_gpt5_model_detection(self, llm_client):
        """Test GPT-5 model detection logic."""
        # GPT-5 variants should be detected
        assert llm_client._is_gpt5_model("gpt-5") is True
        assert llm_client._is_gpt5_model("gpt-5-turbo") is True
        assert llm_client._is_gpt5_model("gpt-5-mini") is True
        assert llm_client._is_gpt5_model("GPT-5") is True  # Case insensitive
        assert llm_client._is_gpt5_model("databricks-gpt-5") is True
        assert llm_client._is_gpt5_model("databricks-gpt-5-1") is True
        assert llm_client._is_gpt5_model("gpt5") is True

        # Non-GPT-5 models should not be detected
        assert llm_client._is_gpt5_model("gpt-4o") is False
        assert llm_client._is_gpt5_model("gpt-4") is False
        assert llm_client._is_gpt5_model("claude-3-opus") is False
        assert llm_client._is_gpt5_model("gemini-2.5-pro") is False

    def test_temperature_override_for_gpt5(self, llm_client):
        """Test that temperature is overridden to 1.0 for GPT-5 models."""
        # Build params with GPT-5 model and temperature != 1.0
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="databricks-gpt-5",
            temperature=0.5,  # Should be overridden to 1.0
        )

        assert params["model"] == "databricks-gpt-5"
        assert params["temperature"] == 1.0  # Overridden
        assert params["messages"] == [{"role": "user", "content": "test"}]

    def test_temperature_already_1_for_gpt5(self, llm_client):
        """Test that temperature=1.0 is not modified for GPT-5."""
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-5-turbo",
            temperature=1.0,  # Already correct
        )

        assert params["temperature"] == 1.0  # Unchanged

    def test_no_override_for_non_gpt5(self, llm_client):
        """Test that temperature is not overridden for non-GPT-5 models."""
        # GPT-4o should not have temperature overridden
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-4o",
            temperature=0.3,
        )

        assert params["temperature"] == 0.3  # Not overridden

        # Claude should not have temperature overridden
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="claude-3-opus",
            temperature=0.7,
        )

        assert params["temperature"] == 0.7  # Not overridden

    @patch("starboard.adapters.llm.openai.client.logger")
    def test_logging_when_temperature_overridden(self, mock_logger, llm_client):
        """Test that info log is emitted when temperature is overridden."""
        llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="databricks-gpt-5-1",
            temperature=0.35,
        )

        # Check that logger.debug was called with correct parameters
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args

        assert call_args[0][0] == "temperature_overridden_by_provider_constraint"
        assert call_args[1]["model"] == "databricks-gpt-5-1"
        assert call_args[1]["requested_temperature"] == 0.35
        assert call_args[1]["actual_temperature"] == 1.0
        assert "GPT-5" in call_args[1]["reason"]

    @patch("starboard.adapters.llm.openai.client.logger")
    def test_no_logging_when_no_override(self, mock_logger, llm_client):
        """Test that no log is emitted when temperature is not overridden."""
        # Non-GPT-5 model
        llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-4o",
            temperature=0.5,
        )

        # Logger should not be called for temperature override
        mock_logger.debug.assert_not_called()

    def test_multiple_gpt5_variants(self, llm_client):
        """Test temperature override for various GPT-5 naming conventions."""
        gpt5_variants = [
            "gpt-5",
            "gpt-5-turbo",
            "gpt-5-mini",
            "GPT-5-TURBO",
            "databricks-gpt-5",
            "databricks-gpt-5-1",
            "databricks-gpt-5-mini",
            "gpt5",
            "gpt5-turbo",
        ]

        for model in gpt5_variants:
            params = llm_client._build_request_params(
                messages=[{"role": "user", "content": "test"}],
                model=model,
                temperature=0.2,
            )

            assert params["temperature"] == 1.0, f"Failed for model: {model}"

    def test_temperature_override_with_phase(self, llm_client):
        """Test that temperature override works when using phase-based defaults."""
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-5",
            phase="router",  # Phase might have its own temperature
            # No explicit temperature - should use phase default then override
        )

        assert params["temperature"] == 1.0  # Overridden regardless of phase

    def test_temperature_override_streaming(self, llm_client):
        """Test that temperature override applies to streaming requests."""
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="databricks-gpt-5-1",
            temperature=0.4,
            stream=True,
        )

        assert params["temperature"] == 1.0  # Overridden
        assert params["stream"] is True


class TestProviderConstraints:
    """Tests for various provider-specific constraints."""

    def test_gemini_model_detection_still_works(self, llm_client):
        """Ensure Gemini detection is not affected by GPT-5 changes."""
        assert llm_client._is_gemini_model("gemini-2.5-pro") is True
        assert llm_client._is_gemini_model("databricks-gemini-2.5-flash") is True
        assert llm_client._is_gemini_model("gpt-5") is False

    def test_both_constraints_can_apply(self, llm_client):
        """Test that multiple provider constraints can coexist."""
        # This is a hypothetical test - if a model matched both constraints,
        # both should be handled correctly

        # GPT-5 gets temperature override
        gpt5_params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-5",
            temperature=0.5,
        )
        assert gpt5_params["temperature"] == 1.0

        # Gemini gets schema flattening (tested elsewhere)
        # Just verify it doesn't affect temperature
        gemini_params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gemini-2.5-pro",
            temperature=0.7,
        )
        assert gemini_params["temperature"] == 0.7  # Not overridden


class TestEdgeCases:
    """Test edge cases for temperature override."""

    def test_temperature_none_with_gpt5(self, llm_client):
        """Test behavior when temperature is None for GPT-5."""
        # When temperature is None, it uses the client's default
        # If that default != 1.0 for GPT-5, it should still be overridden
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-5",
            temperature=None,  # Will use client default
        )

        # Should use client default (0.5 from mock_config), then override to 1.0
        assert params["temperature"] == 1.0

    def test_temperature_zero_with_gpt5(self, llm_client):
        """Test that temperature=0.0 is also overridden for GPT-5."""
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-5",
            temperature=0.0,  # Very deterministic
        )

        assert params["temperature"] == 1.0  # Still overridden

    def test_temperature_above_1_with_gpt5(self, llm_client):
        """Test that high temperatures are also overridden for GPT-5."""
        params = llm_client._build_request_params(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-5",
            temperature=1.5,  # Very creative
        )

        assert params["temperature"] == 1.0  # Normalized to 1.0
