"""Public no-Drive LOCAL runs keep kernel records (phase 4, D4-5, spec §B7).

A public (overlay-off) run routed with ``storage_policy: local`` writes the same
health / case / action / play records as an internal-only local run, only under
its run dir, and reads prior history from its account root (``load_prior_local``,
D4-16).
Covered runs and copied non-LOCAL descriptors stay ``LOCAL_STORAGE_REFUSED``; a
public run dir without a run authorization is exit 4 with the preflight hint.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.policy import SourceMode, StorageDecision, StoragePolicy
from starboard_core.engagement.records import AccountRef, RunAuthorization
from starboard_core.engagement.sink import LocalDirSink
from starboard_skills.helpers import contract
from starboard_skills.helpers.engagement import _envelope

from .conftest import make_drive_run, run_main
from .test_engagement_case_action import _QUESTION
from .test_engagement_case_action import _verify as _verify_envelope
from .test_engagement_helper import FakeWorkspace
from .test_internal_only_local_bound import _internal_run
from .test_run_recur_drive import _finding, _manifest

_SETS = (
    "analysis/observations.json",
    "analysis/findings.json",
    "analysis/health.json",
    "analysis/plays.json",
    "analysis/changes.json",
    "analysis/cases.json",
    "analysis/actions.json",
    "analysis/baseline-selection.json",
)
_HINT = "run engagement preflight --storage local and route first"
_NOT_RUN_ID = "run dir name is not its run id; later runs will not find these records"
_DESCRIPTOR = "analysis/run-authorization.json"
_OFF = OverlaySignal(enabled=False)
_ON = OverlaySignal(enabled=True, reasons=("forced_by_env",))


def _overlay(monkeypatch: pytest.MonkeyPatch, signal: OverlaySignal) -> None:
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: signal)
    monkeypatch.setattr(contract, "_detect_overlay", lambda: signal, raising=False)


@pytest.fixture
def public(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Overlay off, a fake workspace, no Drive; returns the reports root."""
    _overlay(monkeypatch, _OFF)
    monkeypatch.delenv("STARBOARD_OVERLAY", raising=False)
    monkeypatch.delenv(_envelope.SHARED_REGISTRY_ENV, raising=False)
    monkeypatch.setattr(
        _envelope, "_make_workspace_client", lambda _p, _h: FakeWorkspace()
    )

    def no_drive() -> Any:
        raise AssertionError("a public local run makes no Drive call")

    monkeypatch.setattr(_envelope, "_make_storage", no_drive)
    monkeypatch.setattr(contract, "_load_storage", no_drive)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return tmp_path / "reports"


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    code, out = run_main(list(argv), capsys)
    assert code == 0, out
    return json.loads(out)["data"]


def _routed(
    capsys: pytest.CaptureFixture[str],
    reports: Path,
    *,
    task: str = "health_check",
    task_name: str = "ws-123",
    account: str = "acme",
    account_name: str | None = None,
) -> Path:
    """preflight -> verify-identity -> route a public LOCAL run; its run dir."""
    pre = _ok(
        capsys,
        "engagement",
        "preflight",
        "--source-mode",
        "customer_workspace",
        "--task",
        task,
        "--task-name",
        task_name,
        "--account-key",
        account,
        "--account-name",
        account_name or account.title(),
        "--reports-root",
        str(reports),
    )
    assert pre["destination"] == "local" and pre["covered"] is False
    rd = Path(pre["local_run_dir"])
    _ok(
        capsys,
        "engagement",
        "verify-identity",
        "--run-dir",
        str(rd),
        "--profile",
        account,
        "--expected-workspace-id",
        "123",
    )
    _ok(capsys, "engagement", "route", "--run-dir", str(rd))
    auth = json.loads((rd / _DESCRIPTOR).read_text())
    assert auth["storage_policy"] == "local"
    assert auth["source_mode"] == "customer_workspace"
    return rd


def _inputs(rd: Path, start: str, end: str, run_date: str, dbu: float) -> None:
    (rd / "findings-manifest.json").write_text(
        _manifest(start, end, [_finding("W-IDLE", "wh-1", dbu)], run_date)
    )


def _eng(
    capsys: pytest.CaptureFixture[str], rd: Path, *argv: str, root: Path | None = None
) -> tuple[int, str]:
    flags = ["--run-dir", str(rd), "--workspace-root", str(root or rd.parent)]
    return run_main(["engagement", *argv, *flags], capsys)


def _eng_ok(capsys: pytest.CaptureFixture[str], rd: Path, *argv: str) -> dict:
    code, out = _eng(capsys, rd, *argv)
    assert code == 0, out
    return json.loads(out)["data"]


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _records(rd: Path, rel: str) -> Any:
    return json.loads((rd / rel).read_text())


def _error(out: str) -> dict[str, Any]:
    (error,) = json.loads(out)["errors"]
    return error


def _analyzed(capsys: pytest.CaptureFixture[str], reports: Path) -> Path:
    rd = _routed(capsys, reports)
    _inputs(rd, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
    _eng_ok(capsys, rd, "analyze")
    return rd


# --------------------------------------------------------------------------- #
# The pipeline on a public LOCAL run
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestPublicLocalPipeline:
    def test_analyze_writes_every_record_set_only_under_the_run_dir(
        self, public, tmp_path, capsys
    ):
        rd = _routed(capsys, public)
        _inputs(rd, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        before = _files(tmp_path)
        data = _eng_ok(capsys, rd, "analyze")
        assert data["outputs"] == list(_SETS)
        assert data["workspace_id"] == "123" and data["baseline"] is True
        assert _NOT_RUN_ID not in data["warnings"]
        prefix = str(rd.relative_to(tmp_path)) + "/"
        added = _files(tmp_path) - before
        assert added == {prefix + rel for rel in _SETS}
        assert not (tmp_path / "cwd").exists() or _files(tmp_path / "cwd") == set()

    def test_case_action_and_play_work_on_the_same_run_dir(self, public, capsys):
        rd = _analyzed(capsys, public)
        opened = _eng_ok(
            capsys, rd, "case", "open", "--clue", "job:42", "--question", _QUESTION
        )
        assert opened["origin"] == "clue" and opened["case_state"] == "open"
        (rd / "analysis" / "verify").mkdir(parents=True)
        rel = "analysis/verify/vt-job-run-states-s2.json"
        (rd / rel).write_text(
            _verify_envelope(("2026-09-22", "2026-10-06"), 9000, internal=False)
        )
        revised = _eng_ok(
            capsys,
            rd,
            "case",
            "revise",
            "--case-id",
            opened["case_id"],
            "--verify",
            rel,
        )
        assert revised["case_id"] == opened["case_id"]
        assert revised["finding_revision"] >= 2
        assert opened["case_id"] in {c["case_id"] for c in _records(rd, _SETS[5])}

        aid = _records(rd, "analysis/actions.json")[0]["action_id"]
        accepted = _eng_ok(capsys, rd, "action", "accept", "--action-id", aid)
        assert accepted["acceptance_state"] == "accepted"

        pid = _records(rd, "analysis/plays.json")[0]["play_id"]
        ranked = _eng_ok(
            capsys,
            rd,
            "play",
            "rank",
            "--play-id",
            pid,
            "--rank",
            "1",
            "--reason",
            "largest DBU estimate",
        )
        assert ranked["host_rank"] == 1

    def test_a_second_run_reads_the_first_from_the_case_root(self, public, capsys):
        first = _routed(capsys, public)
        _inputs(first, "2026-08-08", "2026-09-07", "2026-09-08", 40.0)
        _eng_ok(capsys, first, "analyze")
        (detected,) = _records(first, "analysis/findings.json")

        second = _routed(capsys, public)
        assert second.parent == first.parent and second != first
        _inputs(second, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        data = _eng_ok(capsys, second, "analyze")
        assert data["counts"]["prior_candidates"] >= 1
        assert data["baseline"] is False
        (carried,) = _records(second, "analysis/findings.json")
        assert carried["finding_id"] == detected["finding_id"]
        assert carried["episode_id"] == detected["episode_id"]


# --------------------------------------------------------------------------- #
# Prior history is account-wide (D4-16)
# --------------------------------------------------------------------------- #
_OUTSIDE_LAYOUT = (
    "run dir is outside the preflight layout; prior read from the case root only"
)


@pytest.mark.unit
class TestAccountWidePrior:
    def test_a_sibling_task_roots_finding_is_visible(self, public, capsys):
        health = _analyzed(capsys, public)
        (detected,) = _records(health, "analysis/findings.json")
        trouble = _routed(capsys, public, task="troubleshooting", task_name="job-42")
        assert trouble.parents[2] == health.parents[2]
        opened = _eng_ok(
            capsys,
            trouble,
            "case",
            "open",
            "--finding-id",
            detected["finding_id"],
            "--question",
            _QUESTION,
        )
        assert opened["finding_id"] == detected["finding_id"]
        assert opened["episode_id"] == detected["episode_id"]
        assert _OUTSIDE_LAYOUT not in opened.get("warnings", [])

    def test_a_troubleshooting_revision_is_the_next_health_runs_prior(
        self, public, capsys
    ):
        health = _analyzed(capsys, public)
        (detected,) = _records(health, "analysis/findings.json")
        trouble = _routed(capsys, public, task="troubleshooting", task_name="job-42")
        opened = _eng_ok(
            capsys,
            trouble,
            "case",
            "open",
            "--finding-id",
            detected["finding_id"],
            "--question",
            _QUESTION,
        )
        revised = _eng_ok(
            capsys, trouble, "case", "revise", "--case-id", opened["case_id"]
        )
        assert revised["finding_revision"] == detected["revision"] + 1

        later = _routed(capsys, public)
        _inputs(later, "2026-10-08", "2026-11-06", "2026-11-07", 30.0)
        _eng_ok(capsys, later, "analyze")
        (carried,) = _records(later, "analysis/findings.json")
        assert carried["finding_id"] == detected["finding_id"]
        assert carried["revision"] == revised["finding_revision"] + 1

    def test_another_account_under_the_same_reports_root_is_not_read(
        self, public, capsys
    ):
        other = _routed(capsys, public, account="globex")
        _inputs(other, "2026-08-08", "2026-09-07", "2026-09-08", 40.0)
        _eng_ok(capsys, other, "analyze")
        (theirs,) = _records(other, "analysis/findings.json")

        mine = _routed(capsys, public)
        assert mine.parents[3] == other.parents[3]
        assert mine.parents[2] != other.parents[2]
        _inputs(mine, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        data = _eng_ok(capsys, mine, "analyze")
        assert data["baseline"] is True
        assert data["counts"]["prior_candidates"] == 0
        code, out = _eng(
            capsys,
            mine,
            "case",
            "open",
            "--finding-id",
            theirs["finding_id"],
            "--question",
            _QUESTION,
        )
        assert code == 4, out
        assert "in this run or the account's prior runs" in out

    def test_a_run_dir_outside_the_layout_falls_back_to_the_case_root(
        self, public, tmp_path, capsys
    ):
        first = _analyzed(capsys, public)
        (detected,) = _records(first, "analysis/findings.json")
        sibling = _routed(capsys, public, task="troubleshooting", task_name="job-42")
        moved = tmp_path / "loose" / "job-42" / sibling.name
        moved.parent.mkdir(parents=True)
        shutil.move(str(sibling), str(moved))
        code, out = _eng(
            capsys,
            moved,
            "case",
            "open",
            "--finding-id",
            detected["finding_id"],
            "--question",
            _QUESTION,
        )
        assert code == 4, out
        assert "in this run or the account's prior runs" in out

        _inputs(moved, "2026-10-08", "2026-11-06", "2026-11-07", 30.0)
        data = _eng_ok(capsys, moved, "analyze")
        assert _OUTSIDE_LAYOUT in data["warnings"]
        assert data["baseline"] is True

    def test_two_accounts_sharing_a_display_name_slug_never_mix(self, public, capsys):
        """sec-M1: the account root is a display-name slug, so two accounts can share
        it; a run of the other account is skipped whole -- even its unreadable files
        leave no gap naming its run id or its error text."""
        other = _routed(capsys, public, account="globex", account_name="Acme")
        _inputs(other, "2026-08-08", "2026-09-07", "2026-09-08", 40.0)
        _eng_ok(capsys, other, "analyze")
        (theirs,) = _records(other, "analysis/findings.json")
        (other / "analysis" / "cases.json").write_text("{globex-private-not-json")

        mine = _routed(capsys, public)
        assert mine.parents[2] == other.parents[2]
        _inputs(mine, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        code, out = _eng(capsys, mine, "analyze")
        assert code == 0, out
        data = json.loads(out)["data"]
        assert data["baseline"] is True
        assert data["counts"]["prior_candidates"] == 0
        written = "".join((mine / rel).read_text() for rel in _SETS)
        for leak in (other.name, "globex-private", "not readable"):
            assert leak not in out and leak not in written
        code, out = _eng(
            capsys,
            mine,
            "case",
            "open",
            "--finding-id",
            theirs["finding_id"],
            "--question",
            _QUESTION,
        )
        assert code == 4, out

    @pytest.mark.parametrize("level", ["task", "case"])
    def test_a_symlinked_sibling_is_not_followed(self, public, tmp_path, capsys, level):
        first = _analyzed(capsys, public)
        (detected,) = _records(first, "analysis/findings.json")
        account_root = first.parents[2]
        outside = tmp_path / "outside"
        shutil.move(str(account_root / "health_check"), str(outside))
        if level == "task":
            (account_root / "discovery").symlink_to(outside, target_is_directory=True)
        else:
            (account_root / "discovery").mkdir()
            (account_root / "discovery" / "ws-123").symlink_to(
                outside / "ws-123", target_is_directory=True
            )
        trouble = _routed(capsys, public, task="troubleshooting", task_name="job-42")
        code, out = _eng(
            capsys,
            trouble,
            "case",
            "open",
            "--finding-id",
            detected["finding_id"],
            "--question",
            _QUESTION,
        )
        assert code == 4, out
        assert "in this run or the account's prior runs" in out

    @pytest.mark.parametrize("crafted", [False, True])
    def test_a_shallow_layout_falls_back_whatever_the_preflight_says(
        self, public, tmp_path, capsys, crafted
    ):
        """The account root comes from the run authorization (the account's slug),
        never from the mutable preflight record."""
        first = _analyzed(capsys, public)
        (detected,) = _records(first, "analysis/findings.json")
        shallow = tmp_path / "shallow"
        shutil.copytree(first.parents[1], shallow / "health_check")
        sibling = _routed(capsys, public, task="troubleshooting", task_name="job-42")
        moved = shallow / "troubleshooting" / "job-42" / sibling.name
        moved.parent.mkdir(parents=True)
        shutil.move(str(sibling), str(moved))
        if crafted:
            rec = moved / "analysis" / "storage-preflight.json"
            pre = json.loads(rec.read_text())
            body = pre.get("data", pre)
            body.update(case_root=str(moved.parent), run_dir=str(moved))
            rec.write_text(json.dumps(pre))
        code, out = _eng(
            capsys,
            moved,
            "case",
            "open",
            "--finding-id",
            detected["finding_id"],
            "--question",
            _QUESTION,
        )
        assert code == 4, out
        _inputs(moved, "2026-10-08", "2026-11-06", "2026-11-07", 30.0)
        data = _eng_ok(capsys, moved, "analyze")
        assert _OUTSIDE_LAYOUT in data["warnings"]
        assert data["baseline"] is True

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads a chmod 000 dir")
    def test_an_unreadable_sibling_is_a_warning_not_a_crash(self, public, capsys):
        first = _analyzed(capsys, public)
        locked = first.parents[2] / "discovery"
        (locked / "ws-9").mkdir(parents=True)
        later = _routed(capsys, public)
        _inputs(later, "2026-10-08", "2026-11-06", "2026-11-07", 30.0)
        locked.chmod(0)
        try:
            data = _eng_ok(capsys, later, "analyze")
        finally:
            locked.chmod(0o755)
        assert data["baseline"] is False
        assert any(str(locked) in w and "not readable" in w for w in data["warnings"])


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestPublicLocalRefusals:
    def test_no_descriptor_is_exit_4_with_the_preflight_hint(
        self, public, tmp_path, capsys
    ):
        rd = tmp_path / "case" / "run-1"
        rd.mkdir(parents=True)
        _inputs(rd, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        before = _files(tmp_path)
        code, out = _eng(capsys, rd, "analyze")
        assert code == 4, out
        assert _HINT in out and "engagement preflight --storage local" in out
        assert _files(tmp_path) == before

    def test_an_unreadable_descriptor_is_exit_4(self, public, tmp_path, capsys):
        rd = tmp_path / "case" / "run-1"
        (rd / "analysis").mkdir(parents=True)
        (rd / _DESCRIPTOR).write_text("{not json")
        code, out = _eng(capsys, rd, "analyze")
        assert code == 4, out
        assert "not a valid run authorization" in out

    def test_case_open_without_a_descriptor_names_the_preflight_step(
        self, public, tmp_path, capsys
    ):
        rd = tmp_path / "case" / "run-1"
        rd.mkdir(parents=True)
        code, out = _eng(
            capsys, rd, "case", "open", "--clue", "job:42", "--question", _QUESTION
        )
        assert code == 4 and _HINT in out, out
        assert list(rd.iterdir()) == []

    def test_a_drive_descriptor_copied_locally_is_refused(
        self, public, tmp_path, capsys
    ):
        from starboard_core.engagement.commit import read_descriptor

        drive = make_drive_run()
        auth = read_descriptor(drive.store, drive.folder_id)[0]
        rd = tmp_path / "copy" / auth.run_id
        (rd / "analysis").mkdir(parents=True)
        (rd / _DESCRIPTOR).write_text(json.dumps(auth.to_dict()))
        _inputs(rd, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        code, out = _eng(capsys, rd, "analyze")
        assert code == 2, out
        assert _error(out)["code"] == "LOCAL_STORAGE_REFUSED", out
        assert sorted(p.name for p in (rd / "analysis").iterdir()) == [
            "run-authorization.json"
        ]

    def test_recur_names_a_descriptor_policy_that_keeps_no_records(
        self, public, tmp_path, capsys
    ):
        from starboard_core.engagement.commit import read_descriptor

        drive = make_drive_run()
        auth = read_descriptor(drive.store, drive.folder_id)[0]
        rd = tmp_path / "copy" / auth.run_id
        (rd / "analysis").mkdir(parents=True)
        (rd / _DESCRIPTOR).write_text(json.dumps(auth.to_dict()))
        _inputs(rd, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        code, out = run_main(
            ["run", "recur", str(rd), "--workspace-root", str(rd.parent)], capsys
        )
        assert code == 0, out
        policy = auth.storage_policy.value
        assert (
            f"run authorization storage_policy {policy} keeps no local kernel "
            "records: kernel records skipped"
        ) in json.loads(out)["data"]["warnings"]
        assert not (rd / "analysis" / "findings.json").exists()

    def test_overlay_on_customer_workspace_is_refused_and_writes_nothing(
        self, public, tmp_path, monkeypatch, capsys
    ):
        rd = _routed(capsys, public)
        _inputs(rd, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        _overlay(monkeypatch, _ON)
        before = _files(tmp_path)
        code, out = _eng(capsys, rd, "analyze")
        assert code == 2, out
        assert _error(out)["code"] == "LOCAL_STORAGE_REFUSED", out
        assert _files(tmp_path) == before

    def test_workspace_root_other_than_the_case_root_is_outside_run_dir(
        self, public, tmp_path, capsys
    ):
        rd = _routed(capsys, public)
        _inputs(rd, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        code, out = _eng(capsys, rd, "analyze", root=elsewhere)
        assert code == 2, out
        assert _error(out)["code"] == "OUTSIDE_RUN_DIR", out
        assert list(elsewhere.iterdir()) == []
        for rel in _SETS:
            assert not (rd / rel).exists(), rel

    def test_a_usage_refusal_echoes_the_run_status_unchanged(self, public, capsys):
        rd = _routed(capsys, public)
        code, out = _eng(
            capsys, rd, "case", "open", "--clue", "nonsense", "--question", _QUESTION
        )
        assert code == 2, out
        refused = json.loads(out)["data"]
        status = _ok(capsys, "engagement", "status", "--run-dir", str(rd))
        assert refused["run_status"] == status["run_status"] == "routed"
        assert refused["resume"] == status["resume"]

    def test_a_run_dir_not_named_by_its_run_id_warns(self, public, capsys):
        rd = _routed(capsys, public)
        renamed = rd.parent / "my-review"
        shutil.move(str(rd), str(renamed))
        _inputs(renamed, "2026-09-08", "2026-10-07", "2026-10-08", 30.0)
        data = _eng_ok(capsys, renamed, "analyze")
        assert _NOT_RUN_ID in data["warnings"]
        assert (renamed / "analysis" / "health.json").is_file()


# --------------------------------------------------------------------------- #
# HelperRun.records_root (spec §B7)
# --------------------------------------------------------------------------- #
def _auth(policy: StoragePolicy, source: SourceMode) -> RunAuthorization:
    return RunAuthorization(
        engagement_id="acme/health_check/ws-123",
        run_id="20261010_12345678-1234-4234-8234-123456789abc",
        intent="health_check",
        task="ws-123",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={"workspace_ids": ["123"]},
        authorized_scope={"account_key": "acme", "workspace_ids": ["123"]},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=source,
        storage_policy=policy,
        audience="operator",
        methodology_version="m1",
        drive=None,
    )


def _with_descriptor(rd: Path, auth: RunAuthorization | None) -> Path:
    (rd / "analysis").mkdir(parents=True, exist_ok=True)
    if auth is not None:
        (rd / _DESCRIPTOR).write_text(json.dumps(auth.to_dict()))
    return rd


def _helper(policy: StoragePolicy, root: Path) -> contract.HelperRun:
    decision = StorageDecision(policy, False, "test")

    def no_storage() -> Any:
        raise AssertionError("records_root needs no storage")

    return contract.HelperRun(
        decision, LocalDirSink(root, decision=decision), None, no_storage
    )


@pytest.mark.unit
class TestRecordsRoot:
    def test_internal_only_local_run_dir(self, tmp_path):
        rd = _internal_run(tmp_path)
        hr = _helper(StoragePolicy.INTERNAL_ONLY_LOCAL, rd)
        assert hr.records_root(rd) == rd.resolve()

    def test_public_local_with_a_local_descriptor(self, tmp_path):
        rd = _with_descriptor(
            tmp_path / "case" / "r",
            _auth(StoragePolicy.LOCAL, SourceMode.CUSTOMER_WORKSPACE),
        )
        hr = _helper(StoragePolicy.LOCAL, rd)
        assert hr.records_root(rd) == rd.resolve()
        assert hr.run_relpath(rd / "analysis") is None  # writers are unchanged

    @pytest.mark.parametrize(
        "auth",
        [
            None,
            _auth(StoragePolicy.DRIVE_OPTIONAL, SourceMode.CUSTOMER_WORKSPACE),
            _auth(StoragePolicy.DRIVE_REQUIRED, SourceMode.CUSTOMER_WORKSPACE),
        ],
        ids=["missing", "drive_optional", "drive_required"],
    )
    def test_public_local_without_a_local_descriptor_is_none(self, tmp_path, auth):
        rd = _with_descriptor(tmp_path / "case" / "r", auth)
        assert _helper(StoragePolicy.LOCAL, rd).records_root(rd) is None

    def test_an_unreadable_descriptor_is_none(self, tmp_path):
        rd = _with_descriptor(tmp_path / "case" / "r", None)
        (rd / _DESCRIPTOR).write_text("{not json")
        assert _helper(StoragePolicy.LOCAL, rd).records_root(rd) is None

    def test_a_sink_rooted_elsewhere_is_none(self, tmp_path):
        rd = _with_descriptor(
            tmp_path / "case" / "r",
            _auth(StoragePolicy.LOCAL, SourceMode.CUSTOMER_WORKSPACE),
        )
        other = tmp_path / "other"
        other.mkdir()
        assert _helper(StoragePolicy.LOCAL, other).records_root(rd) is None
        internal = _internal_run(tmp_path / "i")
        hr = _helper(StoragePolicy.INTERNAL_ONLY_LOCAL, other)
        assert hr.records_root(internal) is None

    def test_drive_optional_and_no_kernel_are_none(self, tmp_path):
        rd = _with_descriptor(
            tmp_path / "case" / "r",
            _auth(StoragePolicy.LOCAL, SourceMode.CUSTOMER_WORKSPACE),
        )
        plain = contract.HelperRun(None, None, None, lambda: None)  # type: ignore[arg-type,return-value]
        assert plain.records_root(rd) is None
        decision = StorageDecision(StoragePolicy.DRIVE_OPTIONAL, False, "test")
        drive = contract.HelperRun(decision, None, "rf-1", lambda: None)  # type: ignore[arg-type,return-value]
        assert drive.records_root(rd) is None
