"""``run check --run-folder``: the checklist over a Drive run folder plus remote items R1–R4."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starboard_core.engagement.write_guard import sandbox_diff
from starboard_skills.helpers import contract

from .conftest import (
    commit_manifest,
    covered_ok,
    drive_files,
    drive_sink,
    make_drive_run,
    put_files,
    run_main,
    upload_tree,
)
from .test_run_check import _make_run

_SELECTION = json.dumps({"run_id": "x", "selected": []})


@pytest.fixture
def drive_run(monkeypatch: pytest.MonkeyPatch):
    """An ``action_plan`` Drive run: ``run check`` gates today's full checklist."""
    run = make_drive_run(intent="action_plan")
    monkeypatch.setattr(contract, "_load_storage", lambda: run.store)
    return run


def _drive_run_dir(tmp_path: Path, run, *, internal: bool = False) -> dict:
    """A conformant run dir uploaded into ``run`` (plus a baseline selection)."""
    src = tmp_path / "src"
    src.mkdir()
    rd = _make_run(src, internal=internal)
    (rd / "analysis" / "run-authorization.json").unlink(missing_ok=True)
    (rd / "analysis" / "baseline-selection.json").write_text(_SELECTION)
    return upload_tree(run, rd)


@pytest.mark.unit
class TestCoveredRunCheck:
    def test_all_pass_writes_run_check_to_drive(self, tmp_path, covered_env, drive_run, capsys):
        _drive_run_dir(tmp_path, drive_run)
        before = covered_env.snapshot()
        code, out = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        doc = covered_ok(covered_env, before, out)
        assert code == 0, doc
        assert doc["ok"] is True
        data = doc["data"]
        assert data["run_id"] == drive_run.run_id
        assert data["run_folder_id"] == drive_run.folder_id
        assert data["summary"]["run_dir"] == f"drive:{drive_run.folder_id}"
        assert data["counts"]["failed"] == 0
        assert [r["path"] for r in data["refs"]] == ["analysis/run-check.json"]
        stored = json.loads(drive_files(drive_run)["analysis/run-check.json"])
        passed = stored["data"]["passed"]
        for item in ("R1:", "R2:", "R3:", "R4:", "15:"):
            assert any(p.startswith(item) for p in passed), item
        assert any("no committed manifest yet" in w for w in stored["data"]["warnings"])

    def test_custom_out_relpath(self, tmp_path, covered_env, drive_run, capsys):
        _drive_run_dir(tmp_path, drive_run)
        code, _ = run_main(
            ["run", "check", "--run-folder", drive_run.folder_id, "--out", "analysis/rc2.json"],
            capsys,
        )
        assert code == 0
        assert "analysis/rc2.json" in drive_files(drive_run)

    def test_internal_uses_generic_sanitizer_on_drive(self, tmp_path, covered_env, drive_run, capsys):
        _drive_run_dir(tmp_path, drive_run, internal=True)
        before = covered_env.snapshot()
        code, out = run_main(
            ["run", "check", "--run-folder", drive_run.folder_id, "--internal"], capsys
        )
        covered_ok(covered_env, before, out)
        assert code == 0
        stored = json.loads(drive_files(drive_run)["analysis/run-check.json"])
        (note,) = [w for w in stored["data"]["warnings"] if "item 16" in w]
        assert "checked generic wording only on a Drive run" in note
        assert "sanitize step's own result" in note
        assert "reads local files" not in note  # the sanitizer does read run folders

    def test_committed_refs_verified(self, tmp_path, covered_env, drive_run, capsys):
        refs = _drive_run_dir(tmp_path, drive_run)
        commit_manifest(drive_run, refs=refs.values())
        code, out = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        assert code == 0, out
        stored = json.loads(drive_files(drive_run)["analysis/run-check.json"])
        assert stored["data"]["remote"]["manifest_revision"] == 1
        assert stored["data"]["remote"]["refs_verified"] == len(refs) + 1
        assert stored["data"]["remote"]["workflow_profile"] == "action_plan"
        assert (stored["data"]["profile"], stored["data"]["profile_source"]) == (
            "action_plan",
            "descriptor",
        )
        assert not any("profile-specific gates" in w for w in stored["data"]["warnings"])
        # Publication pending with no customer report to deliver: nothing to warn about.
        assert not any(w.startswith("publication pending") for w in stored["data"]["warnings"])

    def test_publication_pending_warns_with_the_undelivered_count(
        self, tmp_path, covered_env, drive_run, capsys
    ):
        refs = _drive_run_dir(tmp_path, drive_run)
        commit_manifest(
            drive_run,
            refs=refs.values(),
            reports=({"report_id": "health-read-customer", "revision": 1,
                      "audience": "customer", "state": "approved"},),
        )
        code, out = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        assert code == 0, out
        warnings = json.loads(drive_files(drive_run)["analysis/run-check.json"])["data"]["warnings"]
        assert any(
            w.startswith("publication pending: 1 customer report(s) not yet delivered")
            for w in warnings
        ), warnings

    def test_changed_ref_fails_r2(self, tmp_path, covered_env, drive_run, capsys):
        refs = _drive_run_dir(tmp_path, drive_run)
        commit_manifest(drive_run, refs=refs.values())
        drive_sink(drive_run).put_bytes("analysis/action-plan.md", b"# edited\n", "text/markdown")
        code, out = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        assert code == 1
        failed = json.loads(drive_files(drive_run)["analysis/run-check.json"])["data"]["failed"]
        r2 = [f for f in failed if f["item"].startswith("R2:")]
        assert r2 and "analysis/action-plan.md" in r2[0]["reason"]

    def test_publication_complete_without_receipt_fails(self, tmp_path, covered_env, drive_run, capsys):
        refs = _drive_run_dir(tmp_path, drive_run)
        commit_manifest(
            drive_run,
            refs=refs.values(),
            states={"capture": "complete", "analysis": "complete", "check": "complete",
                    "publication": "complete"},
        )
        code, _ = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        assert code == 1
        failed = json.loads(drive_files(drive_run)["analysis/run-check.json"])["data"]["failed"]
        assert any(f["item"].startswith("R4:") and "no delivery receipt" in f["reason"] for f in failed)

    @pytest.mark.parametrize(
        ("reports", "passes"),
        [
            # rev1 ready, rev2 delivered: only the latest revision counts.
            ([("health-read-customer", 1, "customer", "ready"),
              ("health-read-customer", 2, "customer", "delivered")], True),
            # An internal report never needs a receipt.
            ([("health-read", 1, "internal", "ready"),
              ("health-read-customer", 1, "customer", "delivered")], True),
            # The latest customer revision is undelivered.
            ([("health-read-customer", 1, "customer", "delivered"),
              ("health-read-customer", 2, "customer", "approved")], False),
        ],
    )
    def test_r4_counts_latest_customer_revision_only(
        self, tmp_path, covered_env, drive_run, capsys, reports, passes
    ):
        refs = _drive_run_dir(tmp_path, drive_run)
        commit_manifest(
            drive_run,
            refs=refs.values(),
            states={"capture": "complete", "analysis": "complete", "check": "complete",
                    "publication": "complete"},
            reports=tuple(
                {"report_id": rid, "revision": rev, "audience": aud, "state": st}
                for rid, rev, aud, st in reports
            ),
            receipts=("rcpt-1",),
        )
        run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        data = json.loads(drive_files(drive_run)["analysis/run-check.json"])["data"]
        r4_failed = [f for f in data["failed"] if f["item"].startswith("R4:")]
        if passes:
            assert not r4_failed, r4_failed
            assert any(p.startswith("R4:") for p in data["passed"])
        else:
            assert r4_failed and "health-read-customer" in r4_failed[0]["reason"]

    def test_failed_stage_fails_r3(self, tmp_path, covered_env, drive_run, capsys):
        refs = _drive_run_dir(tmp_path, drive_run)
        commit_manifest(
            drive_run,
            refs=refs.values(),
            states={"capture": "failed", "analysis": "pending", "check": "pending",
                    "publication": "pending"},
        )
        code, _ = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        assert code == 1
        failed = json.loads(drive_files(drive_run)["analysis/run-check.json"])["data"]["failed"]
        assert any(f["item"].startswith("R3:") and "capture" in f["reason"] for f in failed)

    def test_missing_baseline_selection_fails_item15(self, tmp_path, covered_env, drive_run, capsys):
        src = tmp_path / "src"
        src.mkdir()
        upload_tree(drive_run, _make_run(src))
        code, _ = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        assert code == 1
        failed = json.loads(drive_files(drive_run)["analysis/run-check.json"])["data"]["failed"]
        assert any(f["item"].startswith("15:") and "baseline-selection" in f["reason"] for f in failed)

    def test_missing_items_fail_like_local(self, covered_env, drive_run, capsys):
        put_files(drive_run, {"README.md": "# Run\n"})
        before = covered_env.snapshot()
        code, out = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        doc = covered_ok(covered_env, before, out)
        assert code == 1 and doc["ok"] is False
        assert doc["data"]["counts"]["failed"] >= 10


@pytest.mark.unit
class TestRunCheckRefusals:
    def test_stdout_refused_on_covered_run(self, tmp_path, covered_env, drive_run, capsys):
        _drive_run_dir(tmp_path, drive_run)
        code, out = run_main(
            ["run", "check", "--run-folder", drive_run.folder_id, "--stdout"], capsys
        )
        assert code == 2
        assert "LOCAL_STORAGE_REFUSED" in out
        assert "analysis/run-check.json" not in drive_files(drive_run)

    def test_local_out_refused_on_covered_run(self, tmp_path, covered_env, drive_run, capsys):
        _drive_run_dir(tmp_path, drive_run)
        before = covered_env.snapshot()
        code, out = run_main(
            ["run", "check", "--run-folder", drive_run.folder_id, "--out",
             str(tmp_path / "cwd" / "rc.json")],
            capsys,
        )
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert sandbox_diff(before, covered_env.snapshot()) == []

    def test_run_dir_and_run_folder_conflict(self, tmp_path, covered_env, drive_run, capsys):
        code, out = run_main(
            ["run", "check", str(tmp_path), "--run-folder", drive_run.folder_id], capsys
        )
        assert code == 4 and "not both" in out

    def test_no_run_dir_no_run_folder(self, capsys):
        code, out = run_main(["run", "check"], capsys)
        assert code == 4 and "run-dir" in out

    def test_overlay_local_out_without_descriptor_refused(self, tmp_path, covered_env, capsys):
        rd = _make_run(tmp_path)
        code, out = run_main(
            ["run", "check", str(rd), "--out", str(rd / "analysis" / "run-check.json")], capsys
        )
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert not (rd / "analysis" / "run-check.json").exists()


@pytest.mark.unit
class TestPublicRunCheckRunFolder:
    def test_public_run_folder_writes_drive(self, tmp_path, drive_run, capsys):
        _drive_run_dir(tmp_path, drive_run)
        code, out = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
        assert code == 0
        assert out.count("\n") == 1
        assert "analysis/run-check.json" in drive_files(drive_run)

    def test_public_stdout_prints_full_envelope(self, tmp_path, drive_run, capsys):
        _drive_run_dir(tmp_path, drive_run)
        code, out = run_main(
            ["run", "check", "--run-folder", drive_run.folder_id, "--stdout"], capsys
        )
        assert code == 0
        doc = json.loads(out)
        assert len(doc["data"]["passed"]) == doc["data"]["counts"]["passed"]
