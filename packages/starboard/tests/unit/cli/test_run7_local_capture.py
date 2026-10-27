# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 7: a local ``--authorization <run-dir>`` discovery is a resumable capture.

Run 7's public local runs hit the host's command limit and could not resume:
``--max-seconds`` and the capture record needed ``--run-folder``. A local run
dir now carries the capture record too (``<run-dir>/capture/``, keyed by the
descriptor's ``run_id``) and is bounded by ``--max-seconds``. The report still
goes to ``--out-dir``; only the capture record goes to the run dir.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.cli.cli.exit_codes import USAGE_ERROR
from starboard_core.domain.models.discovery.capture import DEFAULT_MAX_SECONDS
from starboard_core.engagement.sink import LocalDirSink

from tests.unit.cli.test_discover_authorization import (
    RUN_ID,
    _args,
    _config,
    _FakeClient,
    _FakeEngine,
    _overlay,
    _write_authorization,
)


@pytest.fixture(autouse=True)
def _seams(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeEngine.captured = {}
    _overlay(monkeypatch, enabled=False)
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", MagicMock())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)


async def _discover(**overrides: object) -> int:
    try:
        await cli_main.run_discovery_mode(_args(**overrides), _config(), Console())
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_local_run_dir_captures_with_the_default_budget(tmp_path: Path) -> None:
    _write_authorization(tmp_path, ["123"])
    before = time.monotonic()
    assert await _discover(authorization=str(tmp_path)) == 0
    cfg = _FakeEngine.captured["config"]
    assert cfg.capture is True
    assert cfg.sink is None  # the report stays on --out-dir
    assert isinstance(cfg.capture_sink, LocalDirSink)
    assert cfg.capture_sink.run_id == RUN_ID
    assert cfg.deadline is not None
    assert before + DEFAULT_MAX_SECONDS - 5 <= cfg.deadline
    assert cfg.deadline <= time.monotonic() + DEFAULT_MAX_SECONDS


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(("seconds", "expect_deadline"), [(0, False), (30, True)])
async def test_max_seconds_bounds_a_local_capture(
    tmp_path: Path, seconds: int, expect_deadline: bool
) -> None:
    _write_authorization(tmp_path, ["123"])
    assert await _discover(authorization=str(tmp_path), max_seconds=seconds) == 0
    cfg = _FakeEngine.captured["config"]
    assert cfg.capture is True
    if expect_deadline:
        assert cfg.deadline is not None
        assert cfg.deadline - time.monotonic() <= seconds
    else:
        assert cfg.deadline is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_max_seconds_without_a_run_is_still_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await _discover(max_seconds=30, json=True) == USAGE_ERROR
    assert _FakeEngine.captured == {}
    assert "--authorization <run-dir>" in capsys.readouterr().err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_run_without_authorization_keeps_capture_off() -> None:
    assert await _discover() == 0
    cfg = _FakeEngine.captured["config"]
    assert cfg.capture is False
    assert cfg.capture_sink is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_descriptor_without_run_id_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_authorization(tmp_path, ["123"])
    # Scope reads succeed; only the capture key is missing.
    monkeypatch.setattr(
        cli_main,
        "local_capture_sink",
        lambda _loc: (_ for _ in ()).throw(
            cli_main.ArgError("--authorization: no run_id")
        ),
    )
    assert await _discover(authorization=str(tmp_path), json=True) == USAGE_ERROR
    assert _FakeEngine.captured == {}
    assert "no run_id" in capsys.readouterr().out
