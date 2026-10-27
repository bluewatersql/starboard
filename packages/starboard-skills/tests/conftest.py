"""Suite-wide fixtures for the starboard-skills tests.

The internal package is installed in the dev workspace, so overlay detection is
ON by default here. Pin the helper's overlay seam OFF so public-path tests see
public behaviour; covered tests opt back in (``unit/conftest.py::covered_env``).

``contract._sdk_config`` builds a real SDK ``Config`` (which resolves auth eagerly);
tests mock the client classes, so it is stubbed to record its arguments instead.
"""

from __future__ import annotations

import pytest
from starboard_skills.helpers import contract


@pytest.fixture(autouse=True)
def _public_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overlay OFF unless a test opts in (the dev install has the internal package)."""
    from starboard_core.engagement.overlay import OverlaySignal

    monkeypatch.setattr(
        contract, "_detect_overlay", lambda: OverlaySignal(False), raising=False
    )


@pytest.fixture(autouse=True)
def _no_sdk_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real SDK auth resolution in unit tests (the client classes are mocked)."""
    monkeypatch.setattr(
        contract,
        "_sdk_config",
        lambda profile: {"profile": profile, "retry_timeout_seconds": contract.retry_budget_s()},
    )
