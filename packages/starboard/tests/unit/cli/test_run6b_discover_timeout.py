# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-6b: a source timeout while the engine is built is a coded, retryable exit.

The internal scope lookup runs while the discovery engine is constructed; when it
hits its statement deadline the CLI must print one line (no traceback), emit a JSON
envelope (``--json`` or ``--run-folder``) with ``error_type: SOURCE_TIMEOUT`` and
``retryable: true``, and exit ``TIMEOUT_ERROR``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.cli.cli.exit_codes import TIMEOUT_ERROR
from starboard_core.ports.fleet_sql import FleetSourceTimeout

from tests.unit.cli._engagement_support import covered_env, drive_run
from tests.unit.cli.test_phase2_public_golden import discover_config


class _Client:
    def __init__(self, *a: object, **k: object) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def get_workspace_id(self) -> str:
        return "123"


@pytest.fixture(autouse=True)
def _public_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _Client)


class _SlowScopeEngine:
    def __init__(self, *a: Any, **k: Any) -> None:
        raise FleetSourceTimeout(
            "internal scope lookup did not finish within 300s",
            hint="The shared warehouse is busy; re-run the same command.",
        )


class _BareTimeoutEngine:
    def __init__(self, *a: Any, **k: Any) -> None:
        raise FleetSourceTimeout("statement did not finish within 300s")


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "discover": True,
        "data_only": True,
        "no_cache": True,
        "json": True,
        "lookback_days": 30,
        "discovery_domains": None,
        "internal_account": None,
        "internal_workspace_id": "856",
        "include_deep_dive": False,
        "full_stdout": False,
        "stdout_mode": None,
        "authorization": None,
        "output_path": None,
        "out_dir": None,
        "run_folder": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


async def _discover(args: argparse.Namespace) -> int:
    try:
        await cli_main.run_discovery_mode(args, discover_config(), Console(stderr=True))
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.mark.unit
async def test_scope_lookup_timeout_is_one_line_source_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _SlowScopeEngine)
    code = await _discover(_args())
    assert code == TIMEOUT_ERROR
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["ok"] is False
    assert body["error_type"] == "SOURCE_TIMEOUT"
    assert body["retryable"] is True
    assert body["hint"] == "The shared warehouse is busy; re-run the same command."
    assert "Traceback" not in captured.err
    assert captured.err.count("SOURCE_TIMEOUT") == 1


@pytest.mark.unit
async def test_source_timeout_without_hint_gets_the_rerun_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _BareTimeoutEngine)
    code = await _discover(_args())
    assert code == TIMEOUT_ERROR
    body = json.loads(capsys.readouterr().out)
    assert "re-run the same command" in body["hint"]
    assert body["retryable"] is True


@pytest.mark.unit
async def test_run_folder_source_timeout_prints_the_envelope_without_json_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _SlowScopeEngine)
    code = await _discover(
        _args(run_folder=folder, json=False, internal_workspace_id=None)
    )
    assert code == TIMEOUT_ERROR
    body = json.loads(capsys.readouterr().out)
    assert body["error_type"] == "SOURCE_TIMEOUT"
    assert body["retryable"] is True
