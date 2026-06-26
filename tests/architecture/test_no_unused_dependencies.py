# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Architecture test: verify removed unused dependencies are not installed.

These packages were confirmed as having zero imports in the codebase and were
removed from pyproject.toml. This test asserts they cannot be imported, which
would fail if they were accidentally re-added as transitive dependencies that
also export a top-level module.
"""

import importlib

import pytest


def _assert_not_importable(module_name: str) -> None:
    """Assert that a module cannot be imported (i.e., is not installed)."""
    try:
        importlib.import_module(module_name)
        pytest.fail(
            f"Package '{module_name}' was importable but should not be installed. "
            "It may have been re-added as a dependency."
        )
    except ModuleNotFoundError:
        pass  # Expected - package is not installed


@pytest.mark.unit
def test_chromadb_not_installed() -> None:
    """chromadb was removed from starboard-server dependencies (zero imports)."""
    _assert_not_importable("chromadb")


@pytest.mark.unit
def test_slack_sdk_not_installed() -> None:
    """slack-sdk was removed from starboard-server dependencies (zero imports)."""
    _assert_not_importable("slack_sdk")


@pytest.mark.unit
def test_tabulate_not_installed() -> None:
    """tabulate was removed from starboard-server dependencies (zero imports)."""
    _assert_not_importable("tabulate")


@pytest.mark.unit
def test_rapidfuzz_not_installed() -> None:
    """rapidfuzz was removed from starboard-server dependencies (zero imports)."""
    _assert_not_importable("rapidfuzz")


@pytest.mark.unit
def test_sqlparse_not_installed() -> None:
    """sqlparse was removed from starboard-server dependencies (zero imports)."""
    _assert_not_importable("sqlparse")
