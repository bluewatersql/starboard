# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared fixtures for the MCP integration tests."""

from __future__ import annotations

import pytest
from starboard_core.engagement.overlay import OverlaySignal


@pytest.fixture(autouse=True)
def _public_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the MCP server as a public install (the dev venv has the overlay)."""
    from starboard.mcp import server

    monkeypatch.setattr(
        server, "detect_overlay", lambda **_kw: OverlaySignal(enabled=False)
    )
