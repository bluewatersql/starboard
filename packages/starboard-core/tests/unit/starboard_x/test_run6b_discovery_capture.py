# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-6b: ``python -m starboard_x.discovery run --run-folder`` is a resumable capture.

* ``--run-folder`` hands the run sink and a deadline (``--max-seconds``, default
  ``DEFAULT_MAX_SECONDS``; ``0`` = no budget) to the engine.
* ``--max-seconds`` without a run (``--run-folder`` or ``--authorization``), or
  negative, is an arg-error (exit 4).
* A budget-stopped capture exits ``CAPTURE_INCOMPLETE`` (9) with a retryable
  envelope naming the same command and the done/remaining counts.
* The summary reports ``resumed``; capture working state stays out of its refs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.domain.models.discovery.capture import (
    DEFAULT_MAX_SECONDS,
    EXIT_CAPTURE_INCOMPLETE,
    PROGRESS_PATH,
    CaptureIncomplete,
)
from starboard_core.engagement.overlay import OverlaySignal
from starboard_x.discovery import __main__ as disc

from tests.unit.starboard_x._writer_support import (
    covered_env,
    drive_run,
    fake_result,
)


class _CaptureEngine:
    """Leaves capture state in the run sink like the real engine; reports ``resumed``."""

    def __init__(self, args: argparse.Namespace, *, stop: bool = False) -> None:
        self._args = args
        self._stop = stop

    async def run(self) -> Any:
        sink = self._args.capture_sink
        sink.put_bytes(PROGRESS_PATH, b"{}", "application/json")
        if self._stop:
            raise CaptureIncomplete(done=5, remaining=7, reused=2)
        result = fake_result()
        result.resumed = {"queries_reused": 2}
        return result


def _run_main(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any]]:
    code = 0
    try:
        disc.main(argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
    return code, json.loads(capsys.readouterr().out)


def _covered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, stop: bool = False
) -> tuple[str, list[argparse.Namespace]]:
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store)
    monkeypatch.setattr(
        disc, "detect_overlay", lambda **_kw: OverlaySignal(True, ("t",))
    )
    monkeypatch.setattr(disc, "load_engagement_storage", lambda: store)
    seen: list[argparse.Namespace] = []

    def build(args: argparse.Namespace) -> _CaptureEngine:
        seen.append(args)
        return _CaptureEngine(args, stop=stop)

    monkeypatch.setattr(disc, "build_engine", build)
    return folder, seen


@pytest.mark.unit
def test_run_folder_capture_gets_the_sink_and_the_default_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder, seen = _covered(monkeypatch, tmp_path)
    before = time.monotonic()
    code, env = _run_main(["run", "--data-only", "--run-folder", folder], capsys)
    assert code == 0, env
    (args,) = seen
    assert args.capture_sink is not None
    assert before + DEFAULT_MAX_SECONDS - 5 <= args.capture_deadline
    assert args.capture_deadline <= time.monotonic() + DEFAULT_MAX_SECONDS
    assert env["data"]["resumed"] == {"queries_reused": 2}
    assert not [r for r in env["data"]["refs"] if r["path"].startswith("capture/")]


@pytest.mark.unit
@pytest.mark.parametrize(("seconds", "expect_deadline"), [("0", False), ("30", True)])
def test_max_seconds_sets_or_disables_the_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    seconds: str,
    expect_deadline: bool,
) -> None:
    folder, seen = _covered(monkeypatch, tmp_path)
    argv = ["run", "--data-only", "--run-folder", folder, "--max-seconds", seconds]
    code, env = _run_main(argv, capsys)
    assert code == 0, env
    (args,) = seen
    assert args.capture_sink is not None
    if expect_deadline:
        assert args.capture_deadline - time.monotonic() <= int(seconds)
    else:
        assert args.capture_deadline is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--data-only", "--max-seconds", "30"],
        ["run", "--data-only", "--run-folder", "F", "--max-seconds", "-1"],
    ],
)
def test_max_seconds_without_run_folder_or_negative_is_an_arg_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    monkeypatch.setattr(
        disc, "detect_overlay", lambda **_kw: OverlaySignal(enabled=False)
    )
    built: list[Any] = []
    monkeypatch.setattr(disc, "build_engine", built.append)
    code, env = _run_main(argv, capsys)
    assert code == 4
    assert built == []
    assert "--max-seconds" in env["error"]


@pytest.mark.unit
def test_budget_stop_is_a_retryable_capture_incomplete_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder, _ = _covered(monkeypatch, tmp_path, stop=True)
    argv = ["run", "--data-only", "--run-folder", folder]
    monkeypatch.setattr(sys, "argv", ["/x/starboard_x/discovery/__main__.py", *argv])
    code, env = _run_main(argv, capsys)
    assert code == EXIT_CAPTURE_INCOMPLETE == 9
    assert env["ok"] is False
    assert env["errors"] == [
        {"code": "CAPTURE_INCOMPLETE", "message": env["error"], "retryable": True}
    ]
    assert env["data"]["progress"] == {"done": 5, "remaining": 7, "reused": 2}
    assert env["data"]["resume"] == (
        f"python -m starboard_x.discovery run --data-only --run-folder {folder}"
    )
    assert "re-run" in env["data"]["hint"]


@pytest.mark.unit
def test_build_engine_turns_capture_on_only_with_a_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bs = pytest.importorskip("starboard.bootstrap")
    monkeypatch.setattr(
        disc, "detect_overlay", lambda **_kw: OverlaySignal(enabled=False)
    )
    configs: list[dict[str, Any]] = []
    monkeypatch.setattr(bs, "get_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bs, "AsyncDatabricksClient", lambda cfg: SimpleNamespace(get_workspace_id=None)
    )
    monkeypatch.setattr(bs, "AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(bs, "EngineConfig", lambda **kw: configs.append(kw) or kw)
    monkeypatch.setattr(bs, "DiscoveryEngine", lambda **_kw: SimpleNamespace())
    monkeypatch.setattr(bs, "apply_cli_target", lambda *_a: None)
    base = {"lookback_days": 30, "max_parallelism": 4, "packs": None}

    disc.build_engine(argparse.Namespace(**base))
    sink = object()
    disc.build_engine(
        argparse.Namespace(**base, capture_sink=sink, capture_deadline=123.0)
    )

    local, run = configs
    assert local["capture"] is False
    assert local["sink"] is None
    assert local["deadline"] is None
    assert run["capture"] is True
    assert run["sink"] is sink
    assert run["deadline"] == 123.0


@pytest.mark.unit
def test_no_cache_help_says_resume_is_independent() -> None:
    parser = disc.build_parser()
    help_text = parser._subparsers._group_actions[0].choices["run"].format_help()  # type: ignore[union-attr]
    assert "--max-seconds" in help_text
    assert "resume" in " ".join(help_text.split())
