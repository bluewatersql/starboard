"""Fetch helpers under the engagement storage policy (``--run-folder`` / ``--stdout``).

Covered = overlay on + a Drive run folder: the full envelope goes to
the run folder through the sink, stdout is the bounded compact envelope, nothing is
written under HOME / cwd / TMPDIR, and the write is recorded as run evidence.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from .conftest import RID, covered_ok, drive_files, evidence, run_main


def _client(n: int = 2) -> MagicMock:
    c = MagicMock()
    c.jobs.list.return_value = iter(
        [SimpleNamespace(job_id=i, settings=SimpleNamespace(name=f"job-{i}")) for i in range(n)]
    )
    return c


class _Sdk:
    """Fake WorkspaceClient factory: counts constructions, ``n`` jobs per list."""

    def __init__(self) -> None:
        self.calls = 0
        self.n = 2

    def __call__(self, *a, **k) -> MagicMock:
        self.calls += 1
        return _client(self.n)


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> _Sdk:
    fake = _Sdk()
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", fake)
    return fake


@pytest.mark.unit
class TestCoveredFetch:
    def test_out_goes_to_run_folder(self, covered_env, drive_run, sdk, capsys):
        before = covered_env.snapshot()
        code, out = run_main(
            ["job", "list", "--run-folder", drive_run.folder_id, "--out", "raw/jobs.json"], capsys
        )
        assert code == 0
        env = covered_ok(covered_env, before, out)
        assert env["ok"] is True and env["domain"] == "job"
        data = env["data"]
        assert data["run_id"] == RID and data["run_folder_id"] == drive_run.folder_id
        assert data["summary"]["out"] == "raw/jobs.json"
        assert data["counts"] == {"rows": 2}
        files = drive_files(drive_run)
        stored = json.loads(files["raw/jobs.json"])
        assert stored["ok"] is True and stored["data"]["count"] == 2
        assert files["raw/jobs.json"] == json.dumps(stored, indent=2).encode()
        (ev,) = evidence(drive_run)
        assert ev["storage_ref"]["path"] == "raw/jobs.json"
        assert ev["producer"] == "starboard-helper job list"
        assert ev["source_kind"] == "customer_workspace"
        assert ev["row_count"] == 2 and ev["scope_workspace_ids"] == ["123"]

    def test_flags_after_or_before_subcommand(self, covered_env, drive_run, sdk, capsys):
        code, out = run_main(
            [f"--run-folder={drive_run.folder_id}", "--out=raw/j.json", "job", "list"], capsys
        )
        assert code == 0
        assert "raw/j.json" in drive_files(drive_run)

    def test_no_out_prints_bounded_envelope(self, covered_env, drive_run, sdk, capsys):
        sdk.n = 3000
        before = covered_env.snapshot()
        code, out = run_main(["job", "list", "--limit", "3000", "--run-folder", drive_run.folder_id], capsys)
        assert code == 0
        env = covered_ok(covered_env, before, out)
        assert env["data"]["run_id"] == RID
        assert env["truncated"] is True or env["data"].get("truncated") is True

    def test_large_out_summary_is_bounded(self, covered_env, drive_run, sdk, capsys):
        sdk.n = 3000
        before = covered_env.snapshot()
        code, out = run_main(
            ["job", "list", "--limit", "3000", "--run-folder", drive_run.folder_id, "--out", "raw/jobs.json"], capsys
        )
        assert code == 0
        env = covered_ok(covered_env, before, out)
        assert env["data"]["counts"] == {"rows": 3000}
        assert len(json.loads(drive_files(drive_run)["raw/jobs.json"])["data"]["jobs"]) == 3000


@pytest.mark.unit
class TestCoveredRefusals:
    def _refused(self, code: int, out: str, needle: str) -> None:
        assert code == 2
        env = json.loads(out)
        assert env["ok"] is False and env["error"].startswith(needle)

    def test_stdout_refused(self, covered_env, drive_run, sdk, capsys):
        code, out = run_main(
            ["job", "list", "--run-folder", drive_run.folder_id, "--stdout"], capsys
        )
        self._refused(code, out, "LOCAL_STORAGE_REFUSED")
        assert "--stdout" in json.loads(out)["error"]
        assert sdk.calls == 0, "refused before any fetch"

    def test_local_out_refused(self, covered_env, drive_run, sdk, tmp_path, capsys):
        code, out = run_main(
            ["job", "list", "--run-folder", drive_run.folder_id, "--out", str(tmp_path / "j.json")],
            capsys,
        )
        self._refused(code, out, "LOCAL_STORAGE_REFUSED")
        assert sdk.calls == 0 and not (tmp_path / "j.json").exists()

    def test_no_run_folder_refused(self, covered_env, sdk, tmp_path, capsys):
        code, out = run_main(["job", "list", "--out", str(tmp_path / "j.json")], capsys)
        self._refused(code, out, "LOCAL_STORAGE_REFUSED")
        assert "--run-folder" in json.loads(out)["error"]
        assert sdk.calls == 0 and not (tmp_path / "j.json").exists()

    def test_plain_fetch_refused_on_overlay(self, covered_env, sdk, capsys):
        code, out = run_main(["job", "list"], capsys)
        self._refused(code, out, "LOCAL_STORAGE_REFUSED")
        assert sdk.calls == 0

    def test_unknown_run_folder_is_arg_error(self, covered_env, drive_run, sdk, capsys):
        code, out = run_main(["job", "list", "--run-folder", "nope", "--out", "raw/j.json"], capsys)
        assert code == 2  # a missing helper target is exit 2, not storage NOT_FOUND (7)
        assert json.loads(out)["ok"] is False and sdk.calls == 0


@pytest.mark.unit
class TestPublicRunFolder:
    def test_public_run_folder_writes_drive(self, drive_run, sdk, capsys):
        code, out = run_main(
            ["job", "list", "--run-folder", drive_run.folder_id, "--out", "raw/jobs.json"], capsys
        )
        assert code == 0
        assert json.loads(out)["data"]["summary"]["out"] == "raw/jobs.json"
        assert "raw/jobs.json" in drive_files(drive_run)

    def test_public_run_folder_bad_relpath_is_arg_error(self, drive_run, sdk, tmp_path, capsys):
        code, out = run_main(
            ["job", "list", "--run-folder", drive_run.folder_id, "--out", "../x.json"], capsys
        )
        assert code == 4 and "run-relative" in json.loads(out)["error"]
        assert sdk.calls == 0

    def test_public_stdout_flag_prints_full_envelope(self, sdk, capsys):
        code, out = run_main(["job", "list", "--stdout"], capsys)
        assert code == 0
        assert json.loads(out)["data"]["count"] == 2
