# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``python -m starboard_x.sparklog`` CLI (Phase-2 D4).

Covers the stable JSON envelope, exit codes, ``--input drive:<id>|FILE`` intake
(D3-23: local files go through ``--input``; ``--source local`` is removed), and the
cloud-source gating (actionable error when the extra is absent).
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


# Pins the W30 intake overlay seam (``starboard_x._cli.detect_overlay``) OFF in the
# subprocess: the dev venv has the internal package installed, so the real detector
# reports "enabled" and a local input file would be refused. The gate itself is
# covered in tests/unit/x/test_cli_intake.py.
_PIN_PUBLIC = (
    "import runpy, starboard_x._cli as c;"
    "from starboard_core.engagement.overlay import OverlaySignal;"
    "c.detect_overlay = lambda **_k: OverlaySignal(enabled=False);"
)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _PIN_PUBLIC
            + "runpy.run_module('starboard_x.sparklog', run_name='__main__')",
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


def _parse_envelope(proc: subprocess.CompletedProcess[str]) -> dict:
    payload = json.loads(proc.stdout)
    assert set(payload) >= {"ok", "domain", "command", "data", "error", "meta"}
    return payload


_COUNTS = {"jobs", "stages", "tasks", "sql", "executors"}


def _pin_overlay(monkeypatch: pytest.MonkeyPatch, *, overlay: bool) -> None:
    from starboard_core.engagement.overlay import OverlaySignal
    from starboard_x import _cli

    monkeypatch.setattr(
        _cli, "detect_overlay", lambda **_k: OverlaySignal(enabled=overlay)
    )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch):
    """An in-memory Drive resolved through the engagement-storage entry point."""
    from types import SimpleNamespace

    from starboard_core.engagement import sink
    from starboard_core.engagement.memory_storage import InMemoryEngagementStorage

    memory = InMemoryEngagementStorage(owner_domain="databricks.com")
    entry = SimpleNamespace(value="tests:InMemory", load=lambda: lambda: memory)
    monkeypatch.setattr(
        sink, "metadata", SimpleNamespace(entry_points=lambda **_kw: [entry])
    )
    return memory


def _share(store, data: bytes) -> str:
    obj = store.put_stream(
        store.root_folder_id(),
        "eventlog.json",
        "application/json",
        [data],
        properties={},
    )
    return f"drive:{obj.id}"


def _main(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    from starboard_x.sparklog.__main__ import main

    with pytest.raises(SystemExit) as info:
        main(argv)
    return int(info.value.code), json.loads(capsys.readouterr().out)


@pytest.mark.unit
class TestSparklogParseInput:
    def test_public_local_file_emits_envelope(self, tmp_path: Path) -> None:
        log = tmp_path / "eventlog.json"
        log.write_text(json.dumps(_PARSED_APP))

        proc = _run_cli("parse", "--input", str(log))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["domain"] == "sparklog"
        assert env["command"] == "parse"
        assert env["data"]["input"] == str(log)
        assert set(env["data"]["counts"]) == _COUNTS
        assert env["data"]["metadata"]["application_info"]["id"] == "app-local-1"

    def test_public_local_file_full(self, tmp_path: Path) -> None:
        log = tmp_path / "eventlog.json"
        log.write_text(json.dumps(_PARSED_APP))
        proc = _run_cli("parse", "--input", str(log), "--full")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "application" in _parse_envelope(proc)["data"]

    def test_gzipped_local_file(self, tmp_path: Path) -> None:
        import gzip

        log = tmp_path / "eventlog.json.gz"
        log.write_bytes(gzip.compress(json.dumps(_PARSED_APP).encode()))
        proc = _run_cli("parse", "--input", str(log))
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_gzip_expansion_is_bounded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import gzip

        from starboard_x import _cli

        _pin_overlay(monkeypatch, overlay=False)
        log = tmp_path / "eventlog.json.gz"
        log.write_bytes(gzip.compress(b" " * 100_000))
        monkeypatch.setattr(_cli, "MAX_INTAKE_BYTES", 1_000)
        code, env = _main(["parse", "--input", str(log)], capsys)
        assert code == 4
        assert "decompresses to more than 1000 bytes" in env["error"]

    def test_missing_local_file_is_arg_error(self) -> None:
        proc = _run_cli("parse", "--input", "/no/such/eventlog.json")
        assert proc.returncode == 4, proc.stdout
        assert "file not found" in _parse_envelope(proc)["error"]

    def test_unparseable_input_is_arg_error(self, tmp_path: Path) -> None:
        log = tmp_path / "eventlog.json"
        # A pre-parsed application missing its required metadata.
        log.write_text(json.dumps({"metadata": {}, "jobData": []}))
        proc = _run_cli("parse", "--input", str(log))
        assert proc.returncode == 4, proc.stdout
        assert "could not parse --input" in _parse_envelope(proc)["error"]

    def test_drive_object_from_the_memory_store(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        store,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from starboard_core import log_parser

        calls: list[object] = []
        real = log_parser.create_spark_application_from_content

        def spy(content: object, **kwargs: object) -> object:
            calls.append(content)
            return real(content, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(log_parser, "create_spark_application_from_content", spy)
        _pin_overlay(monkeypatch, overlay=True)
        monkeypatch.chdir(tmp_path)
        data = json.dumps(_PARSED_APP).encode()
        ref = _share(store, data)
        code, env = _main(["parse", "--input", ref], capsys)
        assert code == 0, env
        assert env["data"]["input"] == ref
        assert set(env["data"]["counts"]) == _COUNTS
        assert calls == [data]
        # Nothing is written locally.
        assert [p for p in tmp_path.rglob("*") if p.is_file()] == []

    def test_overlay_local_file_is_refused_exit_2(self, tmp_path: Path) -> None:
        import os

        log = tmp_path / "eventlog.json"
        log.write_text(json.dumps(_PARSED_APP))
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "starboard_x.sparklog",
                "parse",
                "--input",
                str(log),
            ],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
            env={**os.environ, "STARBOARD_OVERLAY": "1"},
        )
        assert proc.returncode == 2, proc.stdout + proc.stderr
        env = _parse_envelope(proc)
        assert env["error"].startswith("LOCAL_FILE_INTAKE_REFUSED: --input ")

    def test_oversize_drive_object_is_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
        store,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from starboard_x import _cli

        _pin_overlay(monkeypatch, overlay=True)
        monkeypatch.setattr(_cli, "MAX_INTAKE_BYTES", 4)
        ref = _share(store, json.dumps(_PARSED_APP).encode())
        code, env = _main(["parse", "--input", ref], capsys)
        assert code == 4
        assert "larger than 4 bytes" in env["error"]

    def test_oversize_local_file_is_refused_before_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from starboard_x import _cli

        _pin_overlay(monkeypatch, overlay=False)
        monkeypatch.setattr(_cli, "MAX_INTAKE_BYTES", 4)
        log = tmp_path / "eventlog.json"
        log.write_text(json.dumps(_PARSED_APP))

        def no_read(*_a: object, **_k: object) -> bytes:
            raise AssertionError("read before the size check")

        monkeypatch.setattr(Path, "read_bytes", no_read)
        code, env = _main(["parse", "--input", str(log)], capsys)
        assert code == 4
        assert "larger than 4 bytes" in env["error"]


@pytest.mark.unit
class TestSparklogExitCodes:
    def test_source_local_is_removed(self, tmp_path: Path) -> None:
        log = tmp_path / "eventlog.json"
        log.write_text(json.dumps(_PARSED_APP))
        proc = _run_cli("parse", "--source", "local", "--path", str(log))
        assert proc.returncode == 4, proc.stdout
        assert "invalid choice: 'local'" in _parse_envelope(proc)["error"]

    def test_no_input_or_source_is_arg_error(self) -> None:
        proc = _run_cli("parse")
        assert proc.returncode == 4, proc.stdout

    def test_input_and_source_are_exclusive(self, tmp_path: Path) -> None:
        proc = _run_cli(
            "parse", "--input", "x.json", "--source", "https", "--path", "https://h/x"
        )
        assert proc.returncode == 4, proc.stdout

    def test_source_without_path_is_arg_error(self) -> None:
        proc = _run_cli("parse", "--source", "https")
        assert proc.returncode == 4, proc.stdout
        assert "--path" in _parse_envelope(proc)["error"]

    def test_path_without_source_is_arg_error(self) -> None:
        proc = _run_cli("parse", "--input", "x.json", "--path", "https://h/x")
        assert proc.returncode == 4, proc.stdout

    def test_bad_source_choice_is_arg_error(self) -> None:
        proc = _run_cli("parse", "--source", "ftp", "--path", "x")
        assert proc.returncode == 4, proc.stdout

    def test_source_path_scheme_mismatch_is_arg_error(self) -> None:
        proc = _run_cli("parse", "--source", "https", "--path", "s3://b/k.json")
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
