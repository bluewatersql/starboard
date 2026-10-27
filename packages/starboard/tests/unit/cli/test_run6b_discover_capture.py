# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-6b: a ``--run-folder`` discovery is a resumable capture with a wall-clock budget.

* ``--run-folder`` turns the capture record on and sets the deadline from
  ``--max-seconds`` (default ``DEFAULT_MAX_SECONDS``; ``0`` = no budget).
* ``--max-seconds`` without a run (``--run-folder`` or ``--authorization``) is a
  usage error (nothing to resume into).
* A budget-stopped capture exits ``CAPTURE_INCOMPLETE`` (9) with a retryable JSON
  envelope naming the same command and the done/remaining counts.
* The summary reports ``resumed``; capture working state stays out of its refs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from starboard.cli.cli import main as cli_main
from starboard.cli.cli.exit_codes import CAPTURE_INCOMPLETE, USAGE_ERROR
from starboard.discovery.engine import EngineResult
from starboard_core.domain.models.discovery.capture import (
    DEFAULT_MAX_SECONDS,
    PROGRESS_PATH,
    CaptureIncomplete,
)

from tests.unit.cli._engagement_support import covered_env, drive_run
from tests.unit.cli.test_phase2_discover_sink import _args, _Client, _discover


class _Engine:
    """Records its config; leaves capture state in the sink like the real engine."""

    configs: list[Any] = []

    def __init__(
        self, sql_executor: Any, llm_client: Any, config: Any, **_kw: Any
    ) -> None:
        self.config = config
        _Engine.configs.append(config)

    async def run(self, on_progress: Any = None) -> EngineResult:
        if self.config.sink is not None:
            self.config.sink.put_bytes(PROGRESS_PATH, b"{}", "application/json")
        return EngineResult(trace_id="t", resumed={"queries_reused": 2})


class _StoppedEngine(_Engine):
    async def run(self, on_progress: Any = None) -> EngineResult:
        raise CaptureIncomplete(done=5, remaining=7, reused=2)


@pytest.fixture(autouse=True)
def _seams(monkeypatch: pytest.MonkeyPatch) -> None:
    _Engine.configs = []
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _Engine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _Client)


def _run_folder_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **overrides: object
) -> argparse.Namespace:
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    return _args(run_folder=folder, **overrides)


@pytest.mark.unit
async def test_run_folder_capture_is_resumable_with_the_default_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _run_folder_args(monkeypatch, tmp_path)
    before = time.monotonic()
    code = await _discover(args)
    assert code == 0
    (config,) = _Engine.configs
    assert config.capture is True
    assert config.deadline is not None
    assert before + DEFAULT_MAX_SECONDS - 5 <= config.deadline
    assert config.deadline <= time.monotonic() + DEFAULT_MAX_SECONDS
    payload = json.loads(capsys.readouterr().out)
    assert payload["resumed"] == {"queries_reused": 2}
    assert not [r for r in payload["refs"] if r["path"].startswith("capture/")]


@pytest.mark.unit
async def test_no_cache_keeps_the_capture_resumable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = _run_folder_args(monkeypatch, tmp_path, no_cache=True)
    assert await _discover(args) == 0
    (config,) = _Engine.configs
    assert config.enable_cache is False
    assert config.capture is True


@pytest.mark.unit
@pytest.mark.parametrize(("seconds", "expect_deadline"), [(0, False), (30, True)])
async def test_max_seconds_sets_or_disables_the_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, seconds: int, expect_deadline: bool
) -> None:
    args = _run_folder_args(monkeypatch, tmp_path, max_seconds=seconds)
    assert await _discover(args) == 0
    (config,) = _Engine.configs
    assert config.capture is True
    if expect_deadline:
        assert config.deadline is not None
        assert config.deadline - time.monotonic() <= seconds
    else:
        assert config.deadline is None


@pytest.mark.unit
@pytest.mark.parametrize("seconds", [30, -1])
async def test_max_seconds_without_run_folder_or_negative_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    seconds: int,
) -> None:
    if seconds < 0:
        args = _run_folder_args(monkeypatch, tmp_path, max_seconds=seconds)
    else:
        args = _args(max_seconds=seconds, json=True)
    assert await _discover(args) == USAGE_ERROR
    assert _Engine.configs == []
    assert "--max-seconds" in capsys.readouterr().err


@pytest.mark.unit
async def test_local_run_keeps_capture_off(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await _discover(_args()) == 0
    (config,) = _Engine.configs
    assert config.capture is False
    assert config.deadline is None


@pytest.mark.unit
async def test_budget_stop_is_a_retryable_capture_incomplete_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _StoppedEngine)
    args = _run_folder_args(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "/x/bin/starboard",
            "--discover",
            "--run-folder",
            args.run_folder,
            "--data-only",
        ],
    )
    code = await _discover(args)
    assert code == CAPTURE_INCOMPLETE == 9
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["ok"] is False
    assert body["error_type"] == "CAPTURE_INCOMPLETE"
    assert body["retryable"] is True
    assert body["progress"] == {"done": 5, "remaining": 7, "reused": 2}
    assert body["resume"] == (
        f"starboard --discover --run-folder {args.run_folder} --data-only"
    )
    assert "re-run" in body["hint"]
    assert "Traceback" not in captured.err
