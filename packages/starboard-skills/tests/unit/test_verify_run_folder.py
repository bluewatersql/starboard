"""``verify run --run-folder``: the .sql/.json pair goes to ``analysis/verify`` on Drive."""

from __future__ import annotations

import json

import pytest
from starboard_core.engagement.write_guard import sandbox_diff
from starboard_skills.helpers import query as q

from .conftest import covered_ok, drive_files, evidence, run_main
from .test_verify_helper import _TEMPLATES

_ARGS = ["--ws", "123", "--start", "2026-09-01", "--end", "2026-09-30", "--warehouse-id", "wh-1"]


@pytest.fixture
def templates(tmp_path):
    p = tmp_path / "verify-sql.md"
    p.write_text(_TEMPLATES, encoding="utf-8")
    return str(p)


@pytest.fixture
def fake_sql(monkeypatch):
    monkeypatch.setattr(
        q, "cmd_sql",
        lambda args: {"columns": ["a"], "rows": [["1"]], "row_count": 1,
                      "limit_reached": False, "state": "SUCCEEDED", "read_only": True},
    )


def _verify(run, templates, capsys, *extra: str, vt: str = "vt-product-totals"):
    return run_main(
        ["verify", "run", vt, "--templates", templates, *_ARGS,
         "--run-folder", run.folder_id, *extra],
        capsys,
    )


@pytest.mark.unit
class TestCoveredVerify:
    def test_pair_written_to_analysis_verify(self, covered_env, drive_run, templates, fake_sql, capsys):
        before = covered_env.snapshot()
        code, out = _verify(drive_run, templates, capsys)
        doc = covered_ok(covered_env, before, out)
        assert code == 0, doc
        data = doc["data"]
        assert data["sql_path"] == "analysis/verify/vt-product-totals.sql"
        assert data["json_path"] == "analysis/verify/vt-product-totals.json"
        assert sorted(r["path"] for r in data["refs"]) == [
            "analysis/verify/vt-product-totals.json", "analysis/verify/vt-product-totals.sql",
            "evidence/index.json"]
        files = drive_files(drive_run)
        result = json.loads(files["analysis/verify/vt-product-totals.json"])
        assert result["ok"] is True and result["data"]["row_count"] == 1
        (ev,) = evidence(drive_run)
        assert ev["storage_ref"]["path"] == "analysis/verify/vt-product-totals.json"
        assert ev["producer"] == "verify:vt-product-totals"
        assert ev["scope_workspace_ids"] == ["123"]

    def test_out_subdir_relpath(self, covered_env, drive_run, templates, fake_sql, capsys):
        code, out = _verify(drive_run, templates, capsys, "--out", "analysis/verify/round2")
        assert code == 0, out
        assert "analysis/verify/round2/vt-product-totals.json" in drive_files(drive_run)

    def test_arg_error_leaves_failure_json(self, covered_env, drive_run, templates, fake_sql, capsys):
        before = covered_env.snapshot()
        code, _ = run_main(
            ["verify", "run", "vt-product-totals", "--templates", templates, "--ws", "123",
             "--warehouse-id", "wh-1", "--run-folder", drive_run.folder_id],
            capsys,
        )
        assert code == 4
        assert sandbox_diff(before, covered_env.snapshot()) == []
        files = drive_files(drive_run)
        assert json.loads(files["analysis/verify/vt-product-totals.json"])["ok"] is False
        assert "analysis/verify/vt-product-totals.sql" not in files
        assert evidence(drive_run) == []


@pytest.mark.unit
class TestVerifyRefusals:
    def test_stdout_refused(self, covered_env, drive_run, templates, fake_sql, capsys):
        code, out = _verify(drive_run, templates, capsys, "--stdout")
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert drive_files(drive_run) == {}

    def test_local_out_refused(self, tmp_path, covered_env, drive_run, templates, fake_sql, capsys):
        before = covered_env.snapshot()
        code, out = _verify(drive_run, templates, capsys, "--out", str(tmp_path / "cwd" / "v"))
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert sandbox_diff(before, covered_env.snapshot()) == []

    def test_out_outside_verify_dir(self, covered_env, drive_run, templates, fake_sql, capsys):
        code, out = _verify(drive_run, templates, capsys, "--out", "deliverables")
        assert code == 4 and "analysis/verify" in out

    def test_ws_outside_scope(self, covered_env, drive_run, templates, fake_sql, capsys):
        code, out = run_main(
            ["verify", "run", "vt-product-totals", "--templates", templates, "--ws", "999",
             "--start", "2026-09-01", "--end", "2026-09-30", "--warehouse-id", "wh-1",
             "--run-folder", drive_run.folder_id],
            capsys,
        )
        assert code == 2 and "outside the run's authorized scope" in out

    def test_local_out_without_run_folder_refused(self, tmp_path, covered_env, templates, fake_sql, capsys):
        code, out = run_main(
            ["verify", "run", "vt-product-totals", "--templates", templates, *_ARGS,
             "--out", str(tmp_path / "cwd" / "v")],
            capsys,
        )
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert not (tmp_path / "cwd" / "v").exists()


@pytest.mark.unit
class TestVerifyRunProfile:
    """``verify run --run-folder`` reads as the run's verified profile."""

    @pytest.fixture
    def verified_run(self, monkeypatch):
        from starboard_skills.helpers import contract

        from .conftest import make_drive_run

        run = make_drive_run(basis="verified", workspace_profile="acme-ws")
        monkeypatch.setattr(contract, "_load_storage", lambda: run.store)
        return run

    @pytest.fixture
    def seen(self, monkeypatch):
        profiles: list[str | None] = []

        def cmd_sql(args):
            profiles.append(args.profile)
            return {"columns": ["a"], "rows": [["1"]], "row_count": 1,
                    "limit_reached": False, "state": "SUCCEEDED", "read_only": True}

        monkeypatch.setattr(q, "cmd_sql", cmd_sql)
        return profiles

    def test_omitted_profile_defaults_to_the_verified_one(
        self, covered_env, verified_run, templates, seen, capsys
    ):
        code, out = _verify(verified_run, templates, capsys)
        assert code == 0, out
        assert seen == ["acme-ws"]

    def test_the_verified_profile_is_accepted(
        self, covered_env, verified_run, templates, seen, capsys
    ):
        code, out = _verify(verified_run, templates, capsys, "--profile", "acme-ws")
        assert code == 0, out
        assert seen == ["acme-ws"]

    def test_another_profile_is_refused_and_nothing_is_written(
        self, covered_env, verified_run, templates, seen, capsys
    ):
        code, out = _verify(verified_run, templates, capsys, "--profile", "other")
        assert code == 2
        assert json.loads(out)["error"].startswith("PROFILE_MISMATCH")
        assert seen == []
        assert drive_files(verified_run) == {}


@pytest.mark.unit
def test_descriptor_is_downloaded_once_per_command(
    covered_env, drive_run, templates, fake_sql, capsys
):
    """The sink's opener reads the run descriptor; the helper run reuses it (scope check)."""
    store = drive_run.store
    names: list[str] = []
    get_stream = store.get_stream

    def counted(object_id, *args, **kwargs):
        names.append(store.get(object_id).name)
        return get_stream(object_id, *args, **kwargs)

    store.get_stream = counted
    code, out = _verify(drive_run, templates, capsys)
    assert code == 0, out
    assert names.count("run-authorization.json") == 1, names
