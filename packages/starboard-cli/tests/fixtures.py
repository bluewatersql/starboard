# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pytest configuration and shared fixtures for starboard-cli tests."""

import warnings

import pytest

# Filter warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")


# NOTE: cli_runner fixture was removed - CLI uses argparse, not Click
# NOTE: mock_client fixture was removed - referenced non-existent methods


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file for CLI testing."""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(
        """
agent:
  model: gpt-4o-mini
  max_tokens: 120000
  max_steps: 20
  temperature: 0.3
"""
    )
    return str(config_file)
