# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared fixtures for the discovery unit tests."""

from __future__ import annotations

import pytest
from starboard_core.engagement.overlay import OverlaySignal


@pytest.fixture(autouse=True)
def _public_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the discovery tools as a public install unless a test opts in.

    The dev venv has the internal package installed, so the real overlay detector
    would report "enabled" and skip the local discovery files. Pinned at the seam
    the adapter looks up (``discovery_tools.detect_overlay``).
    """
    from starboard.tools.adapters import discovery_tools

    monkeypatch.setattr(
        discovery_tools, "detect_overlay", lambda **_kw: OverlaySignal(enabled=False)
    )
