# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase 2 (P2-G3): ``StarboardClient.from_env`` keeps sessions in memory on an
overlay install (no ``~/.starboard`` session state); public installs are unchanged.

Lives with the CLI tests because the SDK reuses the CLI's agent factory and
``SessionManager``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starboard.sdk.client import StarboardClient
from starboard_core.engagement.overlay import OverlaySignal


async def _db_path(monkeypatch: pytest.MonkeyPatch, *, overlay: bool) -> str:
    config = SimpleNamespace(databricks_host="https://h", databricks_token="t")
    monkeypatch.setattr("starboard.bootstrap.get_config", lambda: config)
    monkeypatch.setattr(
        "starboard_core.engagement.overlay.detect_overlay",
        lambda **_kw: OverlaySignal(overlay, ("test",)),
    )

    async def create(*_a: object, **_k: object) -> tuple[object, None]:
        return object(), None

    monkeypatch.setattr("starboard.cli.cli.main.create_agent_manager", create)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    client: Any = await StarboardClient.from_env(session_db="~/custom/sessions.db")
    try:
        return str(client._session_mgr._db_path)
    finally:
        await client._session_mgr.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_install_sessions_stay_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await _db_path(monkeypatch, overlay=True) == ":memory:"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_public_install_keeps_session_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert await _db_path(monkeypatch, overlay=False) == "~/custom/sessions.db"
