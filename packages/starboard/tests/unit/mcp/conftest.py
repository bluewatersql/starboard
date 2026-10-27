# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared fixtures for the MCP unit tests."""

from __future__ import annotations

import pytest
from starboard_core.engagement.overlay import OverlaySignal


@pytest.fixture(autouse=True)
def _public_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the MCP server as a public install unless a test opts in.

    The dev venv has the internal package installed, so the real overlay detector
    would report "enabled" and arm the write guard on every tool call. Pinned at
    the seam the server looks up (``starboard.mcp.server.detect_overlay``).
    """
    from starboard.mcp import server

    monkeypatch.setattr(
        server, "detect_overlay", lambda **_kw: OverlaySignal(enabled=False)
    )
