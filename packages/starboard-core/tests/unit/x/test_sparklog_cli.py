# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``python -m starboard_x.sparklog`` CLI (Phase-2 D4).

Covers the stable JSON envelope, exit codes, local parsing on the base install,
and the cloud-source gating (actionable error when the extra is absent).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]

# A pre-parsed Spark application JSON (the path-based factory auto-detects the
# pre-parsed shape and loads it without needing a live cloud/cluster source).
_PARSED_APP = {
    "metadata": {
        "application_info": {
            "id": "app-local-1",
            "name": "LocalApp",
            "timestamp_start_ms": 1000,
            "timestamp_end_ms": 2000,
            "runtime_sec": 1,
            "spark_version": "3.4.0",
        },
        "existsSQL": False,
        "existsExecutors": False,
    },
    "jobData": [],
    "stageData": [],
    "taskData": [],
    "accumData": [],
}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "starboard_x.sparklog", *args],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


def _parse_envelope(proc: subprocess.CompletedProcess[str]) -> dict:
    payload = json.loads(proc.stdout)
    assert set(payload) >= {"ok", "domain", "command", "data", "error", "meta"}
    return payload


@pytest.mark.unit
class TestSparklogParseLocal:
    def test_parse_local_emits_envelope(self, tmp_path: Path) -> None:
        log = tmp_path / "eventlog.json"
        log.write_text(json.dumps(_PARSED_APP))

        proc = _run_cli("parse", "--source", "local", "--path", str(log))
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["domain"] == "sparklog"
        assert env["command"] == "parse"
        assert env["data"]["source"] == "local"
        assert "counts" in env["data"]
        assert set(env["data"]["counts"]) == {
            "jobs",
            "stages",
            "tasks",
            "sql",
            "executors",
        }

    def test_parse_local_missing_path_is_not_found(self) -> None:
        proc = _run_cli(
            "parse", "--source", "local", "--path", "/no/such/eventlog.json"
        )
        assert proc.returncode == 2, proc.stdout
        assert _parse_envelope(proc)["ok"] is False


@pytest.mark.unit
class TestSparklogExitCodes:
    def test_missing_required_flags_is_arg_error(self) -> None:
        proc = _run_cli("parse", "--source", "local")
        assert proc.returncode == 4, proc.stdout

    def test_bad_source_choice_is_arg_error(self) -> None:
        proc = _run_cli("parse", "--source", "ftp", "--path", "x")
        assert proc.returncode == 4, proc.stdout

    def test_source_path_scheme_mismatch_is_arg_error(self) -> None:
        proc = _run_cli("parse", "--source", "local", "--path", "s3://b/k.json")
        assert proc.returncode == 4, proc.stdout


@pytest.mark.unit
class TestSparklogCloudGating:
    """A cloud source with its extra absent exits 1 (auth) with an install hint."""

    def test_s3_without_boto3_is_actionable_auth_error(self) -> None:
        body = """
import importlib.util as u
_orig = u.find_spec
u.find_spec = lambda name, *a, **k: None if name == "boto3" else _orig(name, *a, **k)

import starboard_x.sparklog.__main__ as m
from starboard_x.contract import AuthError

try:
    m._check_source_available("s3")
except AuthError as exc:
    assert "sparklog-aws" in str(exc), str(exc)
    print("OK")
else:
    print("FAIL: no AuthError raised")
"""
        result = subprocess.run(
            [sys.executable, "-c", body],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    def test_dbfs_without_sdk_is_actionable_auth_error(self) -> None:
        body = """
import importlib.util as u
_orig = u.find_spec
u.find_spec = lambda name, *a, **k: None if name == "databricks.sdk" else _orig(name, *a, **k)

import starboard_x.sparklog.__main__ as m
from starboard_x.contract import AuthError

try:
    m._check_source_available("dbfs")
except AuthError as exc:
    assert "databricks" in str(exc), str(exc)
    print("OK")
else:
    print("FAIL: no AuthError raised")
"""
        result = subprocess.run(
            [sys.executable, "-c", body],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout
