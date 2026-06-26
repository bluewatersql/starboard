# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pytest configuration and shared fixtures for integration tests.

This conftest provides fixtures for cross-package integration testing.
Package-specific fixtures are registered in each package's root conftest.py.
"""

import os
import warnings

import pytest

# Filter warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")


def _databricks_available() -> bool:
    """Check if Databricks credentials are available."""
    # Check for Databricks auth - either token or OAuth config
    has_token = bool(os.environ.get("DATABRICKS_TOKEN"))
    has_host = bool(os.environ.get("DATABRICKS_HOST"))
    has_profile = bool(os.environ.get("DATABRICKS_CONFIG_PROFILE"))

    # Try to import and validate Databricks SDK
    if has_token and has_host:
        return True
    if has_profile:
        return True

    # Check if default auth works (databricks-cli profile)
    try:
        from databricks.sdk import WorkspaceClient

        # Try to create client - will fail if no valid auth
        client = WorkspaceClient()
        # Try a simple API call to validate
        client.current_user.me()
        return True
    except Exception:
        return False


# Cache the result to avoid repeated checks
_DATABRICKS_AVAILABLE = None


def databricks_available() -> bool:
    """Cached check for Databricks availability."""
    global _DATABRICKS_AVAILABLE
    if _DATABRICKS_AVAILABLE is None:
        _DATABRICKS_AVAILABLE = _databricks_available()
    return _DATABRICKS_AVAILABLE


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
