"""Tests for the ``--out`` file-output mode of ``starboard-helper``.

``--out FILE`` writes the full success envelope to disk and prints only a
compact summary to stdout, so large fetches (query history, job/table lists)
don't get truncated in the host's tool result. Errors are never redirected.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starboard_skills.helpers import __main__ as cli


def _client_with_jobs(n: int = 2) -> MagicMock:
    c = MagicMock()
    jobs = [
        SimpleNamespace(job_id=i, settings=SimpleNamespace(name=f"job-{i}"))
        for i in range(n)
    ]
    c.jobs.list.return_value = iter(jobs)
    return c


def _run(argv, monkeypatch, capsys, client):
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: client)
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    code = exc.value.code if isinstance(exc.value.code, int) else 1
    return code, capsys.readouterr().out


def test_out_writes_file_and_prints_summary(tmp_path, monkeypatch, capsys):
    out = tmp_path / "jobs.json"
    code, stdout = _run(
        ["job", "list", "--out", str(out)], monkeypatch, capsys, _client_with_jobs(2)
    )
    assert code == 0
    summary = json.loads(stdout)
    # stdout carries the compact summary, not the full data payload
    assert summary["out"] == str(out)
    assert summary["rows"] == 2
    assert summary["bytes"] > 0
    assert "note" in summary
    assert "data" not in summary
    # the file holds the full envelope with every row
    written = json.loads(out.read_text())
    assert written["ok"] is True
    assert len(written["data"]["jobs"]) == 2
    assert written["data"]["jobs"][0]["job_id"] == 0


def test_out_before_subcommand(tmp_path, monkeypatch, capsys):
    out = tmp_path / "b.json"
    code, stdout = _run(
        ["--out", str(out), "job", "list"], monkeypatch, capsys, _client_with_jobs(1)
    )
    assert code == 0
    assert out.exists()
    assert json.loads(stdout)["out"] == str(out)


def test_out_equals_form(tmp_path, monkeypatch, capsys):
    out = tmp_path / "eq.json"
    code, _ = _run(
        ["job", "list", f"--out={out}"], monkeypatch, capsys, _client_with_jobs(1)
    )
    assert code == 0
    assert out.exists()


def test_out_creates_parent_dirs(tmp_path, monkeypatch, capsys):
    out = tmp_path / "nested" / "dir" / "j.json"
    code, _ = _run(
        ["job", "list", "--out", str(out)], monkeypatch, capsys, _client_with_jobs(1)
    )
    assert code == 0
    assert out.exists()


def test_no_out_prints_full_envelope(monkeypatch, capsys):
    code, stdout = _run(["job", "list"], monkeypatch, capsys, _client_with_jobs(2))
    assert code == 0
    env = json.loads(stdout)
    # unchanged behaviour: full envelope inline on stdout
    assert len(env["data"]["jobs"]) == 2


def test_out_error_still_prints_and_writes_no_file(tmp_path, monkeypatch, capsys):
    out = tmp_path / "err.json"
    c = MagicMock()
    c.jobs.list.side_effect = RuntimeError("boom")
    code, stdout = _run(["job", "list", "--out", str(out)], monkeypatch, capsys, c)
    assert code != 0
    env = json.loads(stdout)
    assert env["ok"] is False and env["error"]  # error printed to stdout
    assert not out.exists()  # error is never redirected to the file


def test_extract_out_positions():
    assert cli._extract_out(["job", "list", "--out", "f"]) == ("f", ["job", "list"])
    assert cli._extract_out(["--out", "f", "job", "list"]) == ("f", ["job", "list"])
    assert cli._extract_out(["job", "--out=f", "list"]) == ("f", ["job", "list"])
    assert cli._extract_out(["job", "list"]) == (None, ["job", "list"])
    # a dangling --out (no value) is left in place for argparse to reject
    assert cli._extract_out(["job", "list", "--out"]) == (
        None,
        ["job", "list", "--out"],
    )


def test_count_rows():
    assert cli._count_rows([1, 2, 3]) == 3
    assert cli._count_rows({"jobs": [1, 2], "count": 2}) == 2
    assert cli._count_rows({"x": [1], "y": [2, 3]}) == 3
    assert cli._count_rows({"a": {"b": 1}}) is None
    assert cli._count_rows("scalar") is None


def test_count_rows_prefers_row_count_key():
    # W27: when data has an explicit row_count, use it instead of summing all
    # list-valued fields (which would count the columns list as rows).
    data = {
        "row_count": 11,
        "columns": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
                    "k", "l", "m", "n", "o", "p", "q", "r"],  # 18 columns
        "rows": [{"a": i} for i in range(11)],
    }
    assert cli._count_rows(data) == 11  # not 18 + 11 = 29


def test_count_rows_row_count_zero_is_valid():
    # row_count=0 is a legitimate value (empty result set), not falsy-skipped.
    assert cli._count_rows({"row_count": 0, "columns": ["x"], "rows": []}) == 0
