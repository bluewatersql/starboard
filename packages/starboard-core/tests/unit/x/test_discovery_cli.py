# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``python -m starboard_x.discovery`` CLI (Phase-2 D4).

The discovery engine lives in the heavier ``starboard`` server package, so the
CLI imports it lazily inside :func:`build_engine`. These tests mock that seam:
they never require a live workspace and prove the deterministic (data-only,
no-LLM) path is what runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]


def _run_program(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


@pytest.mark.unit
class TestDiscoveryRunDataOnly:
    """``run --data-only`` mocks the engine and emits a data-only envelope."""

    def test_run_emits_envelope_no_llm(self) -> None:
        body = """
import sys

import starboard_x.discovery.__main__ as disc


class FakeQR:
    def __init__(self, ok):
        self.succeeded = ok


class FakePack:
    pack_name = "billing"
    results = [FakeQR(True), FakeQR(False)]


class FakeAudit:
    succeeded = True


class FakeResult:
    trace_id = "trace-xyz"
    elapsed_ms = 42.0
    errors = []
    audit_result = FakeAudit()
    pack_results = [FakePack()]
    domain_analyses = []   # data-only: no LLM analysis ran


class FakeEngine:
    def __init__(self):
        self.used_llm = False

    async def run(self):
        return FakeResult()


captured = {}


def fake_build(args):
    captured["data_only_flag"] = args.data_only
    captured["packs"] = args.packs
    return FakeEngine()


disc.build_engine = fake_build

try:
    disc.main(["run", "--data-only", "--packs", "billing"])
except SystemExit as exc:
    # main() prints the envelope, then exits; propagate the code for the test.
    assert captured["data_only_flag"] is True, captured
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["ok"] is True
        assert env["domain"] == "discovery"
        assert env["command"] == "run"
        data = env["data"]
        assert data["data_only"] is True
        assert data["domain_analyses"] == []  # no LLM analysis on the data-only path
        assert data["trace_id"] == "trace-xyz"
        assert data["pack_count"] == 1
        assert data["packs"][0]["pack"] == "billing"
        assert data["packs"][0]["queries"] == 2
        assert data["packs"][0]["succeeded"] == 1

    def test_build_engine_failure_is_auth_error(self) -> None:
        body = """
import sys

import starboard_x.discovery.__main__ as disc
from starboard_x.contract import AuthError


def boom(args):
    raise AuthError("could not build a Databricks client: no host configured")


disc.build_engine = boom

try:
    disc.main(["run", "--data-only"])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 1, proc.stdout  # auth
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert "client" in env["error"]


@pytest.mark.unit
class TestDiscoveryBuilderEnforcesDataOnly:
    """The real ``build_engine`` forces ``data_only=True`` + ``llm_client=None``."""

    def test_build_engine_data_only_and_no_llm(self) -> None:
        pytest.importorskip("starboard.bootstrap")
        body = """
import argparse
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

with (
    patch.object(bs, "get_config", return_value=MagicMock()),
    patch.object(bs, "AsyncDatabricksClient", MagicMock()),
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig") as EngineConfig,
    patch.object(bs, "DiscoveryEngine") as DiscoveryEngine,
):
    ns = argparse.Namespace(lookback_days=30, max_parallelism=4, packs=None)
    disc.build_engine(ns)

    assert EngineConfig.call_args.kwargs["data_only"] is True, EngineConfig.call_args
    assert DiscoveryEngine.call_args.kwargs["llm_client"] is None, (
        DiscoveryEngine.call_args
    )
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout


@pytest.mark.unit
class TestDiscoveryDepLight:
    """Importing the discovery CLI must not pull the server package / SDK."""

    def test_module_import_is_dep_light(self) -> None:
        body = """
import importlib
import sys

importlib.import_module("starboard_x.discovery.__main__")

leaked = sorted(
    m for m in sys.modules
    if m == "starboard"
    or m.startswith("starboard.")
    or m == "databricks"
    or m.startswith("databricks.")
    or m == "openai"
)
assert not leaked, f"discovery CLI import leaked heavy deps: {leaked}"
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout
