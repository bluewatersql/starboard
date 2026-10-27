# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared fixtures for the CLI unit tests."""

from __future__ import annotations

import pytest
from starboard_core.engagement.overlay import OverlaySignal


@pytest.fixture(autouse=True)
def _public_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the starboard CLI as a public install unless a test opts in.

    The dev venv has the internal package installed, so the real overlay
    detector would report "enabled" and require ``--run-folder``. Pinned at the
    seams the CLI looks up (``cli_main.detect_overlay`` for ``--discover`` and
    the goal agent, ``review_command.detect_overlay`` for ``starboard review``).
    """
    from starboard.cli.cli import main as cli_main
    from starboard.cli.cli import review_command

    def public(**_kw: object) -> OverlaySignal:
        return OverlaySignal(enabled=False)

    monkeypatch.setattr(cli_main, "detect_overlay", public)
    monkeypatch.setattr(review_command, "detect_overlay", public)
