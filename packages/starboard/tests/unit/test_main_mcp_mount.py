# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Tests for the fail-closed /mcp mount in ``starboard.main.create_app``.

The Streamable HTTP transport is network-exposed, so ``create_app`` must not
mount ``/mcp`` unless an API key is resolvable (``STARBOARD_MCP_API_KEY``) or
the operator explicitly opts in to no-auth (``STARBOARD_MCP_INSECURE``).
"""

from __future__ import annotations

import pytest


def _mcp_mounted(app: object) -> bool:
    return any(getattr(route, "path", None) == "/mcp" for route in app.routes)  # type: ignore[attr-defined]


@pytest.fixture()
def _mcp_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``load_mcp_config`` resolve a single 'default' workspace."""
    monkeypatch.delenv("STARBOARD_MCP_CONFIG", raising=False)
    monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")


def test_mcp_not_mounted_without_key(
    _mcp_config_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starboard.main import create_app

    monkeypatch.delenv("STARBOARD_MCP_API_KEY", raising=False)
    monkeypatch.delenv("STARBOARD_MCP_INSECURE", raising=False)

    app = create_app()
    assert _mcp_mounted(app) is False


def test_mcp_mounted_with_env_key(
    _mcp_config_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starboard.main import create_app

    monkeypatch.setenv("STARBOARD_MCP_API_KEY", "s3cret")
    monkeypatch.delenv("STARBOARD_MCP_INSECURE", raising=False)

    app = create_app()
    assert _mcp_mounted(app) is True


def test_mcp_mounted_when_insecure_opt_in(
    _mcp_config_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starboard.main import create_app

    monkeypatch.delenv("STARBOARD_MCP_API_KEY", raising=False)
    monkeypatch.setenv("STARBOARD_MCP_INSECURE", "1")

    app = create_app()
    assert _mcp_mounted(app) is True
