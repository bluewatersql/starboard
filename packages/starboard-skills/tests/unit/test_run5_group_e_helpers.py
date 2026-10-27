"""Run-5 group E (helper verbs): negative lookups on ``--out``, ``query sql`` pair, ``query slow`` window.

No live calls: the SDK client is faked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound
from starboard_skills.helpers import query as q

from .conftest import drive_files, run_main

FULL = "main.s.missing"


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    w = MagicMock()
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


# --------------------------------------------------------------------------- #
# E1: a not-found lookup still writes its envelope to --out (exit stays 2)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestNotFoundWritesOut:
    def test_local_out_holds_the_not_found_envelope(self, tmp_path, sdk, capsys):
        sdk.tables.get.side_effect = NotFound("Table 'main.s.missing' does not exist.")
        out = tmp_path / "raw" / "uc-table.json"
        code, stdout = run_main(
            ["uc", "table", "--full-name", FULL, "--out", str(out)], capsys
        )
        assert code == 2
        printed = json.loads(stdout)
        assert printed["ok"] is False
        stored = json.loads(out.read_text())
        assert stored["ok"] is False
        assert stored["domain"] == "uc" and stored["command"] == "table"
        assert stored["error"] == printed["error"]
        assert "not found or not visible to this identity" in stored["error"]

    def test_no_out_writes_nothing(self, tmp_path, sdk, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sdk.tables.get.side_effect = NotFound("nope")
        code, _ = run_main(["uc", "table", "--full-name", FULL], capsys)
        assert code == 2
        assert list(tmp_path.iterdir()) == []

    def test_api_error_still_writes_nothing(self, tmp_path, sdk, capsys):
        sdk.tables.get.side_effect = RuntimeError("boom")
        out = tmp_path / "x.json"
        code, _ = run_main(
            ["uc", "table", "--full-name", FULL, "--out", str(out)], capsys
        )
        assert code == 3
        assert not out.exists()

    def test_drive_out_is_written_to_the_run_folder_only(
        self, covered_env, drive_run, sdk, capsys
    ):
        sdk.tables.get.side_effect = NotFound("gone")
        before = covered_env.snapshot()
        code, stdout = run_main(
            [
                "uc",
                "table",
                "--full-name",
                FULL,
                "--run-folder",
                drive_run.folder_id,
                "--out",
                "raw/uc-table.json",
            ],
            capsys,
        )
        assert code == 2
        assert json.loads(stdout)["ok"] is False
        from starboard_core.engagement.write_guard import sandbox_diff

        assert sandbox_diff(before, covered_env.snapshot()) == []
        stored = json.loads(drive_files(drive_run)["raw/uc-table.json"])
        assert stored["ok"] is False
        assert "not found or not visible to this identity" in stored["error"]


# --------------------------------------------------------------------------- #
# E2: query sql --out x.json also writes the x.sql sibling
# --------------------------------------------------------------------------- #
def _sql_client(monkeypatch):
    resp = SimpleNamespace(
        manifest=SimpleNamespace(
            schema=SimpleNamespace(columns=[SimpleNamespace(name="n", type_name=None)])
        ),
        result=SimpleNamespace(data_array=[["1"]]),
        status=SimpleNamespace(state=SimpleNamespace(value="SUCCEEDED")),
        statement_id="s1",
    )
    w = MagicMock()
    w.statement_execution.execute_statement.return_value = resp
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    monkeypatch.setattr(q, "_preflight", lambda profile: None)
    return w


@pytest.mark.unit
class TestQuerySqlPair:
    SQL = "SELECT 1 AS n"

    def test_local_pair(self, tmp_path, monkeypatch, capsys):
        _sql_client(monkeypatch)
        out = tmp_path / "check.json"
        code, _ = run_main(
            [
                "query",
                "sql",
                "--sql",
                self.SQL,
                "--warehouse-id",
                "wh",
                "--out",
                str(out),
            ],
            capsys,
        )
        assert code == 0
        assert json.loads(out.read_text())["ok"] is True
        assert (tmp_path / "check.sql").read_text().strip() == self.SQL

    def test_out_without_json_suffix_gets_sql_appended(
        self, tmp_path, monkeypatch, capsys
    ):
        _sql_client(monkeypatch)
        out = tmp_path / "check"
        code, _ = run_main(
            [
                "query",
                "sql",
                "--sql",
                self.SQL,
                "--warehouse-id",
                "wh",
                "--out",
                str(out),
            ],
            capsys,
        )
        assert code == 0
        assert (tmp_path / "check.sql").read_text().strip() == self.SQL

    def test_no_out_writes_no_sql_file(self, tmp_path, monkeypatch, capsys):
        _sql_client(monkeypatch)
        monkeypatch.chdir(tmp_path)
        code, _ = run_main(
            ["query", "sql", "--sql", self.SQL, "--warehouse-id", "wh"], capsys
        )
        assert code == 0
        assert list(tmp_path.iterdir()) == []

    def test_other_verbs_write_no_sql_file(self, tmp_path, sdk, capsys):
        sdk.jobs.list.return_value = iter([])
        out = tmp_path / "jobs.json"
        code, _ = run_main(["job", "list", "--out", str(out)], capsys)
        assert code == 0
        assert not (tmp_path / "jobs.sql").exists()

    def test_drive_pair(self, covered_env, drive_run, monkeypatch, capsys):
        _sql_client(monkeypatch)
        before = covered_env.snapshot()
        code, _ = run_main(
            [
                "query",
                "sql",
                "--sql",
                self.SQL,
                "--warehouse-id",
                "wh",
                "--run-folder",
                drive_run.folder_id,
                "--out",
                "analysis/verify/check.json",
            ],
            capsys,
        )
        assert code == 0
        from starboard_core.engagement.write_guard import sandbox_diff

        assert sandbox_diff(before, covered_env.snapshot()) == []
        files = drive_files(drive_run)
        assert json.loads(files["analysis/verify/check.json"])["ok"] is True
        assert files["analysis/verify/check.sql"].decode().strip() == self.SQL


# --------------------------------------------------------------------------- #
# E3: query slow echoes the window it actually scanned
# --------------------------------------------------------------------------- #
def _stmt(qid: str, start_ms: int, duration: int = 20_000):
    return SimpleNamespace(
        query_id=qid,
        status=None,
        query_text="select 1",
        duration=duration,
        warehouse_id="w",
        query_start_time_ms=start_ms,
        error_message=None,
        rows_produced=1,
        bytes_produced=1,
    )


def _slow_args(**kw):
    base = {
        "warehouse_id": None,
        "min_duration_ms": 10_000,
        "limit": 25,
        "lookback_days": None,
        "exclude_warehouse_id": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.unit
class TestQuerySlowWindow:
    def test_no_lookback_echoes_scanned_range(self, monkeypatch):
        rows = [_stmt("a", 1_790_000_000_000), _stmt("b", 1_780_000_000_000, 30_000)]
        w = MagicMock()
        w.query_history.list.return_value = SimpleNamespace(
            res=rows, next_page_token=None
        )
        monkeypatch.setattr(q, "_client", lambda: w)
        win = q.cmd_slow(_slow_args())["window"]
        assert (
            win["lookback_days"] is None and win["start"] is None and win["end"] is None
        )
        assert win["scanned_first_start"] == q._iso_ms(1_780_000_000_000)
        assert win["scanned_last_start"] == q._iso_ms(1_790_000_000_000)
        assert win["scan_capped"] is False

    def test_scan_cap_is_flagged(self, monkeypatch):
        rows = [_stmt(f"s{i}", 1_790_000_000_000 - i) for i in range(200)]
        w = MagicMock()
        w.query_history.list.return_value = SimpleNamespace(
            res=rows, next_page_token=None
        )
        monkeypatch.setattr(q, "_client", lambda: w)
        assert q.cmd_slow(_slow_args())["window"]["scan_capped"] is True

    def test_empty_scan_has_null_range(self, monkeypatch):
        w = MagicMock()
        w.query_history.list.return_value = SimpleNamespace(
            res=[], next_page_token=None
        )
        monkeypatch.setattr(q, "_client", lambda: w)
        win = q.cmd_slow(_slow_args())["window"]
        assert win["scanned_first_start"] is None and win["scanned_last_start"] is None
