# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``python -m starboard_x.uc`` CLI (Phase-2 D4).

Covers the stable JSON envelope, exit-code contract, and the SDK-free guarantee
for the pure UC analyzers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]

_INPUT = {
    "table_name": "main.gold.fct_sales",
    "columns": [
        {"name": "sale_id", "data_type": "BIGINT", "position": 0, "nullable": False},
        {"name": "customer_id", "data_type": "STRING", "position": 1},
        {"name": "amount", "data_type": "DECIMAL", "position": 2},
        {"name": "created_at", "data_type": "TIMESTAMP", "position": 3},
        {"name": "payload", "data_type": "STRING", "position": 4},
    ],
}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "starboard_x.uc", *args],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


def _parse_envelope(proc: subprocess.CompletedProcess[str]) -> dict:
    payload = json.loads(proc.stdout)
    assert set(payload) >= {"ok", "domain", "command", "data", "error", "meta"}
    assert payload["meta"]["format"] == "json"
    return payload


@pytest.mark.unit
class TestUcAnalyze:
    def test_analyze_emits_envelope_with_anomalies_and_classification(
        self, tmp_path: Path
    ) -> None:
        input_file = tmp_path / "table.json"
        input_file.write_text(json.dumps(_INPUT))

        proc = _run_cli("analyze", "--input", str(input_file))
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["domain"] == "uc"
        assert env["command"] == "analyze"
        data = env["data"]
        assert data["column_count"] == 5
        # Fact table in the gold layer.
        assert data["classification"]["table_type"] == "fact"
        assert data["classification"]["data_layer"] == "gold"
        # 'payload' STRING triggers the JSON-blob anti-pattern.
        types = {a["anomaly_type"] for a in data["anomalies"]}
        assert "json_blob_antipattern" in types
        assert 0.0 <= data["schema_health"] <= 1.0
        assert "id_columns" in data["semantic_patterns"]

    def test_analyze_without_table_name_skips_classification(
        self, tmp_path: Path
    ) -> None:
        input_file = tmp_path / "table.json"
        input_file.write_text(json.dumps({"columns": _INPUT["columns"]}))
        proc = _run_cli("analyze", "--input", str(input_file))
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert "classification" not in env["data"]


@pytest.mark.unit
class TestUcExitCodes:
    def test_missing_input_file_is_arg_error(self) -> None:
        proc = _run_cli("analyze", "--input", "/no/such/file.json")
        assert proc.returncode == 4, proc.stdout
        assert _parse_envelope(proc)["ok"] is False

    def test_invalid_json_is_arg_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        proc = _run_cli("analyze", "--input", str(bad))
        assert proc.returncode == 4, proc.stdout

    def test_empty_columns_is_arg_error(self, tmp_path: Path) -> None:
        input_file = tmp_path / "table.json"
        input_file.write_text(json.dumps({"columns": []}))
        proc = _run_cli("analyze", "--input", str(input_file))
        assert proc.returncode == 4, proc.stdout


@pytest.mark.unit
class TestUcSdkFree:
    def test_analyze_imports_no_databricks_sdk(self, tmp_path: Path) -> None:
        input_file = tmp_path / "table.json"
        input_file.write_text(json.dumps(_INPUT))
        body = f"""
import sys, argparse
import starboard_x.uc.__main__ as m
ns = argparse.Namespace(input={str(input_file)!r}, format="json", command="analyze")
data = m._cmd_analyze(ns)
assert data["column_count"] == 5
sdk = sorted(
    x for x in sys.modules if x == "databricks" or x.startswith("databricks.")
)
assert not sdk, f"uc analyze imported databricks-sdk: {{sdk}}"
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
