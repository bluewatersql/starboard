"""``charts render --run-folder``: data from Drive (relpath or drive:<id>), image to deliverables/charts."""

from __future__ import annotations

import json

import pytest
from starboard_core.engagement.write_guard import sandbox_diff
from starboard_skills.helpers import charts_render

from .conftest import covered_ok, drive_files, evidence, put_files, run_main

_ROWS = json.dumps([{"billing_origin_product": "JOBS", "total_dbus": 10}])


@pytest.fixture(autouse=True)
def _fake_render(monkeypatch):
    monkeypatch.setattr(charts_render, "_vegalite_to_png", lambda vl: b"\x89PNG-fake")
    monkeypatch.setattr(charts_render, "_vegalite_to_svg", lambda vl: b"<svg>fake</svg>")


def _charts(run, capsys, data: str, out: str = "deliverables/charts/spend.png", *extra: str):
    return run_main(
        ["charts", "render", "--kind", "spend-by-product", "--data", data, "--out", out,
         "--run-folder", run.folder_id, *extra],
        capsys,
    )


@pytest.mark.unit
class TestCoveredCharts:
    def test_relpath_data_to_drive(self, covered_env, drive_run, capsys):
        put_files(drive_run, {"charts/data/spend.json": _ROWS})
        before = covered_env.snapshot()
        code, out = _charts(drive_run, capsys, "charts/data/spend.json")
        doc = covered_ok(covered_env, before, out)
        assert code == 0, doc
        assert doc["data"]["out_path"] == "deliverables/charts/spend.png"
        assert [r["path"] for r in doc["data"]["refs"]] == ["deliverables/charts/spend.png"]
        assert drive_files(drive_run)["deliverables/charts/spend.png"] == b"\x89PNG-fake"
        assert evidence(drive_run) == []

    def test_drive_object_data(self, covered_env, drive_run, capsys):
        (ref,) = put_files(drive_run, {"analysis/rows.json": _ROWS}).values()
        before = covered_env.snapshot()
        code, out = _charts(drive_run, capsys, f"drive:{ref.object_id}",
                            "deliverables/charts/s.svg", "--format", "svg")
        covered_ok(covered_env, before, out)
        assert code == 0
        assert drive_files(drive_run)["deliverables/charts/s.svg"] == b"<svg>fake</svg>"

    def test_unknown_kind_before_data(self, covered_env, drive_run, capsys):
        code, out = run_main(
            ["charts", "render", "--kind", "nope", "--data", "missing.json",
             "--out", "deliverables/charts/x.png", "--run-folder", drive_run.folder_id],
            capsys,
        )
        assert code == 4 and "unknown chart kind" in out

    def test_missing_data(self, covered_env, drive_run, capsys):
        code, out = _charts(drive_run, capsys, "charts/data/none.json")
        assert code == 4 and "data file not found" in out


@pytest.mark.unit
class TestChartsRefusals:
    def test_stdout_refused(self, covered_env, drive_run, capsys):
        put_files(drive_run, {"charts/data/spend.json": _ROWS})
        code, out = _charts(drive_run, capsys, "charts/data/spend.json",
                            "deliverables/charts/spend.png", "--stdout")
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert "deliverables/charts/spend.png" not in drive_files(drive_run)

    def test_out_outside_charts_dir(self, covered_env, drive_run, capsys):
        put_files(drive_run, {"charts/data/spend.json": _ROWS})
        code, out = _charts(drive_run, capsys, "charts/data/spend.json", "analysis/spend.png")
        assert code == 4 and "deliverables/charts/" in out

    def test_local_out_refused(self, tmp_path, covered_env, drive_run, capsys):
        put_files(drive_run, {"charts/data/spend.json": _ROWS})
        before = covered_env.snapshot()
        code, out = _charts(drive_run, capsys, "charts/data/spend.json",
                            str(tmp_path / "cwd" / "spend.png"))
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert sandbox_diff(before, covered_env.snapshot()) == []

    def test_local_data_refused(self, tmp_path, covered_env, drive_run, capsys):
        (tmp_path / "rows.json").write_text(_ROWS)
        code, out = _charts(drive_run, capsys, str(tmp_path / "rows.json"))
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert drive_files(drive_run) == {}
