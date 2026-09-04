# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pytest configuration and shared fixtures for integration tests.

This conftest provides fixtures for cross-package integration testing.
Package-specific fixtures are registered in each package's root conftest.py.

Run the starboard-core, starboard, and starboard-skills suites in separate
pytest invocations; combined collection has colliding test-module basenames.
"""

import os
import warnings

import pytest

# Filter warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")


def databricks_available() -> bool:
    """Return True only when explicit Databricks env vars are present.

    Deliberately avoids the SDK's default credential chain (~/.databrickscfg)
    so that CI / offline runs — where DATABRICKS_HOST, DATABRICKS_TOKEN, and
    DATABRICKS_CONFIG_PROFILE are all unset — always skip the
    ``requires_databricks`` suite, even on machines that happen to have a
    local Databricks profile configured.

    Offline mode: all three vars unset  → False → skip
    With creds:   HOST+TOKEN set        → True  → run
    With profile: DATABRICKS_CONFIG_PROFILE set → True → run
    """
    has_token = bool(os.environ.get("DATABRICKS_TOKEN"))
    has_host = bool(os.environ.get("DATABRICKS_HOST"))
    has_profile = bool(os.environ.get("DATABRICKS_CONFIG_PROFILE"))
    return (has_token and has_host) or has_profile


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "requires_databricks: mark test as requiring Databricks credentials",
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests that require Databricks when credentials are not available."""
    if databricks_available():
        # Databricks is available, don't skip
        return

    skip_databricks = pytest.mark.skip(
        reason="Databricks credentials not available (set DATABRICKS_HOST and DATABRICKS_TOKEN, or configure databricks-cli)"
    )

    for item in items:
        if "requires_databricks" in item.keywords:
            item.add_marker(skip_databricks)


@pytest.fixture
def integration_config():
    """Provide configuration for integration tests."""
    return {
        "databricks_host": "https://test.databricks.com",
        "databricks_token": "test_token",
        "databricks_warehouse_id": "test_warehouse",
        "api_url": "http://localhost:8000",
        "test_timeout": 30,
    }
