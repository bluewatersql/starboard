# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``python -m starboard_x.warehouse`` CLI (Phase-2 D4).

Covers the stable JSON envelope, the exit-code contract, and the SDK-free
guarantee for the pure warehouse analyzers (no ``databricks-sdk`` imported when
running ``analyze``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]

_HISTORY = [
    {
        "statement_id": "s1",
        "warehouse_id": "wh1",
        "statement_type": "SELECT",
        "total_duration_ms": 1200,
        "waiting_in_queue_ms": 100,
        "read_bytes": 1000,
        "written_bytes": 0,
        "start_time": "2026-01-01T10:00:00Z",
        "executed_by": "alice",
    },
    {
        "statement_id": "s2",
        "warehouse_id": "wh1",
        "statement_type": "SELECT",
        "total_duration_ms": 65000,
        "waiting_in_queue_ms": 30000,
        "read_bytes": 2_000_000_000,
        "written_bytes": 0,
        "start_time": "2026-01-01T11:00:00Z",
        "executed_by": "bob",
    },
]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "starboard_x.warehouse", *args],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


def _parse_envelope(proc: subprocess.CompletedProcess[str]) -> dict:
    payload = json.loads(proc.stdout)
    assert set(payload) >= {"ok", "domain", "command", "data", "error", "meta"}
    assert payload["meta"]["format"] == "json"
    assert "contract_version" in payload["meta"]
    return payload


@pytest.mark.unit
class TestWarehouseAnalyze:
    def test_analyze_emits_envelope_with_fingerprint_and_health(
        self, tmp_path: Path
    ) -> None:
        history = tmp_path / "history.json"
        history.write_text(json.dumps(_HISTORY))

        proc = _run_cli("analyze", "--history", str(history))
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["domain"] == "warehouse"
        assert env["command"] == "analyze"
        data = env["data"]
        assert data["warehouse_id"] == "wh1"
        assert data["fingerprint"]["total_queries"] == 2
        # Health is scored; status is one of the known categories.
        assert data["health"]["health_status"] in {
            "healthy",
            "warning",
            "critical",
            "inactive",
        }

    def test_analyze_selects_warehouse_by_flag(self, tmp_path: Path) -> None:
        history = tmp_path / "history.json"
        history.write_text(json.dumps(_HISTORY))
        proc = _run_cli(
            "analyze", "--history", str(history), "--warehouse-id", "wh1"
        )
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["data"]["fingerprint"]["warehouse_id"] == "wh1"

    def test_analyze_object_history_shape(self, tmp_path: Path) -> None:
        history = tmp_path / "history.json"
        history.write_text(
            json.dumps(
                {
                    "warehouse_id": "wh1",
                    "warehouse_name": "Prod",
                    "analysis_window_days": 14,
                    "records": _HISTORY,
                }
            )
        )
        proc = _run_cli("analyze", "--history", str(history))
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["data"]["fingerprint"]["warehouse_name"] == "Prod"
        assert env["data"]["fingerprint"]["analysis_window_days"] == 14


@pytest.mark.unit
class TestWarehouseExitCodes:
    def test_missing_history_file_is_arg_error(self) -> None:
        proc = _run_cli("analyze", "--history", "/no/such/history.json")
        assert proc.returncode == 4, proc.stdout
        assert _parse_envelope(proc)["ok"] is False

    def test_no_subcommand_is_arg_error(self) -> None:
        proc = _run_cli()
        assert proc.returncode == 4, proc.stdout

    def test_unknown_warehouse_is_not_found(self, tmp_path: Path) -> None:
        history = tmp_path / "history.json"
        history.write_text(json.dumps(_HISTORY))
        proc = _run_cli(
            "analyze", "--history", str(history), "--warehouse-id", "ghost"
        )
        assert proc.returncode == 2, proc.stdout
        assert _parse_envelope(proc)["ok"] is False

    def test_multi_warehouse_history_requires_selection(self, tmp_path: Path) -> None:
        history = tmp_path / "history.json"
        rows = _HISTORY + [{**_HISTORY[0], "warehouse_id": "wh2"}]
        history.write_text(json.dumps(rows))
        proc = _run_cli("analyze", "--history", str(history))
        assert proc.returncode == 4, proc.stdout


@pytest.mark.unit
class TestWarehouseSdkFree:
    """The pure ``analyze`` path must import no databricks-sdk (kernel boundary)."""

    def test_analyze_imports_no_databricks_sdk(self, tmp_path: Path) -> None:
        history = tmp_path / "history.json"
        history.write_text(json.dumps(_HISTORY))
        body = f"""
import sys
import starboard_x.warehouse.__main__ as m
m.build_parser()  # wire the parser
# Run the analyze handler directly (no subprocess) to load the analyzers.
import argparse
ns = argparse.Namespace(
    history={str(history)!r}, warehouse_id=None, warehouse_name=None,
    window_days=None, format="json", command="analyze",
)
data = m._cmd_analyze(ns)
assert data["fingerprint"]["total_queries"] == 2
sdk = sorted(
    x for x in sys.modules
    if x == "databricks" or x.startswith("databricks.")
)
assert not sdk, f"warehouse analyze imported databricks-sdk: {{sdk}}"
print("OK")
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


class TestEpochTimestamps:
    """Regression: QueryRecord.from_dict must accept epoch-ms/int start_time.

    Databricks/SDK query records carry ``start_time`` as epoch milliseconds
    (int), not ISO strings. Before the fix the analyzer did ``r.start_time.hour``
    on a raw int and raised ``'int' object has no attribute 'hour'``.
    """

    def test_from_dict_parses_epoch_ms(self) -> None:
        from datetime import datetime

        from starboard_core.domain.analyzers.warehouse_analyzer import QueryRecord

        rec = QueryRecord.from_dict({"start_time": 1_760_000_000_000})  # ms
        assert isinstance(rec.start_time, datetime)
        assert rec.start_time.hour is not None  # no AttributeError

    def test_from_dict_bad_start_time_is_none(self) -> None:
        from starboard_core.domain.analyzers.warehouse_analyzer import QueryRecord

        assert QueryRecord.from_dict({"start_time": True}).start_time is None
        assert QueryRecord.from_dict({"start_time": {"nope": 1}}).start_time is None
        assert QueryRecord.from_dict({}).start_time is None

    def test_analyze_epoch_ms_history_no_crash(self) -> None:
        """End-to-end: an epoch-ms history analyzes without the .hour crash."""
        import time

        now_ms = int(time.time() * 1000)
        history = {
            "warehouse_id": "wh1",
            "records": [
                {
                    "statement_id": "s1",
                    "warehouse_id": "wh1",
                    "statement_type": "SELECT",
                    "total_duration_ms": 1200,
                    "waiting_in_queue_ms": 50,
                    "read_bytes": 1000,
                    "written_bytes": 0,
                    "start_time": now_ms,
                    "executed_by": "u1",
                }
            ],
        }
        hist_file = Path("/tmp/wh_epoch_regression.json")
        hist_file.write_text(json.dumps(history), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "starboard_x.warehouse", "analyze", "--history", str(hist_file)],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is True
        assert envelope["data"]["fingerprint"]["total_queries"] == 1
