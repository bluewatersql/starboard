# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 7: ``run --authorization <run-dir>`` is a resumable capture too.

Public local runs hit the host's command limit and could not resume: the capture
record and ``--max-seconds`` needed ``--run-folder``. The local run dir now holds
the capture record (``<run-dir>/capture/``, keyed by the descriptor's ``run_id``)
and the report stays on ``--out-dir`` (the engine gets no report sink).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.domain.models.discovery.capture import DEFAULT_MAX_SECONDS
from starboard_core.engagement.overlay import OverlaySignal
from starboard_x.contract import ArgError
from starboard_x.discovery import __main__ as disc
from starboard_x.discovery.authorization import local_capture_sink

from tests.unit.starboard_x._writer_support import RID, local_run_dir
from tests.unit.starboard_x.test_run6b_discovery_capture import (
    _CaptureEngine,
    _run_main,
)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[argparse.Namespace]:
    monkeypatch.setattr(
        disc, "detect_overlay", lambda **_kw: OverlaySignal(enabled=False)
    )
    built: list[argparse.Namespace] = []

    def build(args: argparse.Namespace) -> _CaptureEngine:
        built.append(args)
        return _CaptureEngine(args)

    monkeypatch.setattr(disc, "build_engine", build)
    return built


@pytest.mark.unit
def test_a_local_run_dir_gets_a_capture_sink_and_the_default_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], seen: list[argparse.Namespace]
) -> None:
    run_dir = local_run_dir(tmp_path)
    before = time.monotonic()
    argv = [
        "run",
        "--data-only",
        "--authorization",
        str(run_dir),
        "--out-dir",
        str(tmp_path / "out"),
    ]
    code, env = _run_main(argv, capsys)
    assert code == 0, env
    (args,) = seen
    assert args.capture_sink.kind == "local"
    assert args.capture_sink.run_id == RID
    assert before + DEFAULT_MAX_SECONDS - 5 <= args.capture_deadline
    assert args.capture_deadline <= time.monotonic() + DEFAULT_MAX_SECONDS
    # _CaptureEngine wrote the progress record through the capture sink.
    assert (run_dir / "capture" / "discovery-progress.json").is_file()


@pytest.mark.unit
def test_max_seconds_zero_disables_the_local_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], seen: list[argparse.Namespace]
) -> None:
    run_dir = local_run_dir(tmp_path)
    argv = [
        "run",
        "--data-only",
        "--authorization",
        str(run_dir),
        "--out-dir",
        str(tmp_path / "out"),
        "--max-seconds",
        "0",
    ]
    code, env = _run_main(argv, capsys)
    assert code == 0, env
    (args,) = seen
    assert args.capture_sink.kind == "local"
    assert args.capture_deadline is None


@pytest.mark.unit
def test_local_capture_sink_needs_the_descriptor_run_id(tmp_path: Path) -> None:
    run_dir = local_run_dir(tmp_path)
    path = run_dir / "analysis" / "run-authorization.json"
    assert local_capture_sink(str(path)).run_id == RID  # the file form names the dir
    doc = json.loads(path.read_text())
    del doc["run_id"]
    path.write_text(json.dumps(doc))
    with pytest.raises(ArgError, match="run_id"):
        local_capture_sink(str(run_dir))
    with pytest.raises(ArgError):
        local_capture_sink(str(tmp_path / "missing"))


@pytest.mark.unit
def test_build_engine_keeps_a_local_capture_off_the_report_sink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
    sink = local_capture_sink(str(local_run_dir(tmp_path)))
    disc.build_engine(
        argparse.Namespace(
            lookback_days=30,
            max_parallelism=4,
            packs=None,
            capture_sink=sink,
            capture_deadline=12.0,
        )
    )
    (cfg,) = configs
    assert cfg["sink"] is None
    assert cfg["capture"] is True
    assert cfg["capture_sink"] is sink
    assert cfg["deadline"] == 12.0
