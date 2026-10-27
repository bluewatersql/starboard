"""Run-5 Group B fix B3: ``engagement status`` accepts ``--run-id`` together with
the run's ``--run-folder`` or ``--run-dir`` when they agree, and refuses a
mismatch (``RUN_ID_MISMATCH``, exit 2). ``--run-dir`` + ``--run-folder`` stays USAGE.
"""

from __future__ import annotations

from . import test_engagement_helper_phase2 as phase2
from .test_engagement_helper_phase2 import _internal_local_run, ok, routed, run

store, ws, sandbox = phase2.store, phase2.ws, phase2.sandbox

OTHER = "20990101_6f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f"


class TestDriveRun:
    def test_consistent_pair_is_accepted(self, capsys, store):
        pre, data = routed(capsys)
        out = ok(
            capsys,
            "status",
            "--run-id",
            pre["run_id"],
            "--run-folder",
            data["run_folder_id"],
        )
        assert out["run_id"] == pre["run_id"]
        assert out["run_folder_id"] == data["run_folder_id"]

    def test_mismatched_pair_is_refused(self, capsys, store):
        _, data = routed(capsys)
        code, env, _ = run(
            capsys, "status", "--run-id", OTHER, "--run-folder", data["run_folder_id"]
        )
        assert code == 2
        assert env["errors"][0]["code"] == "RUN_ID_MISMATCH"
        assert OTHER in env["errors"][0]["message"]


class TestLocalRun:
    def test_consistent_pair_is_accepted(self, capsys):
        run_dir = _internal_local_run(capsys)
        out = ok(capsys, "status", "--run-id", run_dir.name, "--run-dir", str(run_dir))
        assert out["run_id"] == run_dir.name

    def test_mismatched_pair_is_refused(self, capsys):
        run_dir = _internal_local_run(capsys)
        code, env, _ = run(
            capsys, "status", "--run-id", OTHER, "--run-dir", str(run_dir)
        )
        assert code == 2
        assert env["errors"][0]["code"] == "RUN_ID_MISMATCH"


def test_run_dir_with_run_folder_is_usage(capsys, tmp_path):
    code, env, _ = run(
        capsys, "status", "--run-dir", str(tmp_path), "--run-folder", "folder-x"
    )
    assert code == 2 and env["errors"][0]["code"] == "USAGE"
    assert "--run-dir" in env["errors"][0]["message"]


def test_no_selector_is_usage(capsys):
    code, env, _ = run(capsys, "status")
    assert code == 2 and env["errors"][0]["code"] == "USAGE"
