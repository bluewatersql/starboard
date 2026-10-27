"""``notebook render --run-folder``: backlog + verify pairs read from Drive, notebooks written there."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starboard_core.engagement.write_guard import sandbox_diff

from .conftest import covered_ok, drive_files, evidence, put_files, run_main
from .test_notebook_helper import run_dir  # noqa: F401  (fixture)

# Exactly the files the public local render changes (golden_helpers/notebook_render.json).
_GOLDEN_FILES = sorted(json.loads(
    (Path(__file__).parent / "golden_helpers" / "notebook_render.json").read_text()
)["files"])


def _upload(run, root) -> None:
    put_files(run, {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted((root / "analysis").rglob("*")) if p.is_file()
    })


def _render(run, root, capsys, *extra: str):
    return run_main(
        ["notebook", "render", "--all", "--source-templates", str(root / "source.md"),
         "--run-folder", run.folder_id, *extra],
        capsys,
    )


@pytest.mark.unit
class TestCoveredNotebook:
    def test_default_paths_on_drive(self, run_dir, covered_env, drive_run, capsys):  # noqa: F811
        _upload(drive_run, run_dir)
        before = covered_env.snapshot()
        code, out = _render(drive_run, run_dir, capsys)
        doc = covered_ok(covered_env, before, out)
        assert code == 0, doc
        written = [r["path"] for r in doc["data"]["refs"]]
        assert sorted(written) == _GOLDEN_FILES  # notebooks + the backlog notebook_path write-back
        files = drive_files(drive_run)
        for p in written:
            assert p in files
        assert not (run_dir / "deliverables").exists()
        assert evidence(drive_run) == []  # rendered deliverables are not acquired evidence


@pytest.mark.unit
class TestNotebookRefusals:
    def test_stdout_refused(self, run_dir, covered_env, drive_run, capsys):  # noqa: F811
        _upload(drive_run, run_dir)
        code, out = _render(drive_run, run_dir, capsys, "--stdout")
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out

    def test_local_out_refused(self, run_dir, covered_env, drive_run, capsys):  # noqa: F811
        _upload(drive_run, run_dir)
        before = covered_env.snapshot()
        code, out = _render(drive_run, run_dir, capsys, "--out", str(run_dir / "cwd" / "nb"))
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert sandbox_diff(before, covered_env.snapshot()) == []

    def test_out_outside_notebooks_dir(self, run_dir, covered_env, drive_run, capsys):  # noqa: F811
        _upload(drive_run, run_dir)
        code, out = _render(drive_run, run_dir, capsys, "--out", "analysis")
        assert code == 4 and "deliverables/notebooks" in out

    def test_run_dir_with_run_folder(self, run_dir, covered_env, drive_run, capsys):  # noqa: F811
        code, out = _render(drive_run, run_dir, capsys, "--run-dir", str(run_dir))
        assert code == 4 and "--run-dir does not apply" in out

    def test_missing_backlog_on_drive(self, run_dir, covered_env, drive_run, capsys):  # noqa: F811
        code, out = _render(drive_run, run_dir, capsys)
        assert code == 2 and "backlog not found" in out
