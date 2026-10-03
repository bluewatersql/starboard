# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``python -m starboard_x.review`` CLI (Phase-3 D1b).

Covers the stable JSON envelope, the exit-code contract, ``--domains``
filtering, and the SDK-free guarantee (scoring pre-fetched rows imports no
``databricks-sdk``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]

_ROWS = {
    "W-W02": [
        {
            "warehouse_id": "wh-idle",
            "idle_running_hours": 12.0,
            "auto_stop_waste_pct": 80.0,
        }
    ],
    "C-Q02": [
        {"statement_id": "stmt-prune", "pruning_ratio": 0.02, "read_partitions": 500},
    ],
}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "starboard_x.review", *args],
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
class TestReviewScore:
    def test_score_emits_ranked_findings_envelope(self, tmp_path: Path) -> None:
        rows = tmp_path / "rows.json"
        rows.write_text(json.dumps(_ROWS))

        proc = _run_cli("score", "--rows", str(rows))
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["domain"] == "review"
        assert env["command"] == "score"

        data = env["data"]
        ids = [rf["finding"]["id"] for rf in data["findings"]]
        assert "warehouse_auto_stop_disabled::wh-idle" in ids
        assert "non_sargable_partition_filter::stmt-prune" in ids
        # Highest score first (auto-stop, 12.0).
        assert data["findings"][0]["finding"]["id"] == (
            "warehouse_auto_stop_disabled::wh-idle"
        )
        # Evidence citation references query_id + row.
        first_ev = data["findings"][0]["evidence"][0]
        assert first_ev["query_id"] == "W-W02"
        assert first_ev["row"]["warehouse_id"] == "wh-idle"

    def test_domains_filter(self, tmp_path: Path) -> None:
        rows = tmp_path / "rows.json"
        rows.write_text(json.dumps(_ROWS))

        proc = _run_cli("score", "--rows", str(rows), "--domains", "warehouse")
        assert proc.returncode == 0, proc.stderr
        data = _parse_envelope(proc)["data"]
        categories = {rf["finding"]["category"] for rf in data["findings"]}
        assert categories == {"warehouse"}

    def test_structured_input_with_failed_queries(self, tmp_path: Path) -> None:
        rows = tmp_path / "rows.json"
        rows.write_text(
            json.dumps(
                {
                    "rows_by_query_id": {"W-W01": []},
                    "failed_query_ids": ["W-W02"],
                    "workspace": "acme",
                }
            )
        )
        proc = _run_cli("score", "--rows", str(rows), "--domains", "warehouse")
        assert proc.returncode == 0, proc.stderr
        data = _parse_envelope(proc)["data"]
        assert data["workspace"] == "acme"
        assert data["degraded"] is True


@pytest.mark.unit
class TestReviewErrors:
    def test_missing_rows_file_is_arg_error(self) -> None:
        proc = _run_cli("score", "--rows", "/nonexistent/rows.json")
        assert proc.returncode == 4  # EXIT_ARG
        env = _parse_envelope(proc)
        assert env["ok"] is False
        assert env["error"]

    def test_missing_subcommand_is_arg_error(self) -> None:
        proc = _run_cli()
        assert proc.returncode == 4  # EXIT_ARG


@pytest.mark.unit
class TestReviewIsSdkFree:
    def test_scoring_does_not_import_databricks_sdk(self, tmp_path: Path) -> None:
        rows = tmp_path / "rows.json"
        rows.write_text(json.dumps(_ROWS))
        # Run in a subprocess that fails hard if databricks.sdk gets imported.
        probe = (
            "import sys, builtins;"
            "_imp=builtins.__import__;\n"
            "def guard(name,*a,**k):\n"
            "    if name=='databricks.sdk' or name.startswith('databricks.sdk.'):\n"
            "        raise AssertionError('databricks.sdk imported')\n"
            "    return _imp(name,*a,**k)\n"
            "builtins.__import__=guard;\n"
            "from starboard_x.review.__main__ import main;\n"
            f"main(['score','--rows',{str(rows)!r}])"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        # main() calls sys.exit(0) on success.
        assert proc.returncode == 0, proc.stderr
