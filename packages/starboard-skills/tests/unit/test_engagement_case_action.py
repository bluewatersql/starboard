"""``engagement case|action|play``: host steps on a run's records, kept by re-analysis."""

from __future__ import annotations

import json

import pytest

from .conftest import covered_ok, drive_files, put_files, run_main
from .test_run_recur_drive import _current, _finding, _manifest

_QUESTION = "Why did job 42 fail after 2026-09-22?"
_OUTPUT = "raw/job-run-output-9001.json"
_TRACE = "Caused by: java.lang.OutOfMemoryError: Java heap space"


def _eng(run, capsys, *argv: str) -> tuple[int, str]:
    return run_main(["engagement", *argv, "--run-folder", run.folder_id], capsys)


def _ok(run, capsys, sandbox, *argv: str) -> dict:
    before = sandbox.snapshot()
    code, out = _eng(run, capsys, *argv)
    assert code == 0, out
    return covered_ok(sandbox, before, out)["data"]


def _records(run, rel: str) -> list[dict]:
    return json.loads(drive_files(run)[rel])


@pytest.fixture
def analyzed(covered_env, drive_run, capsys):
    _current(drive_run)
    _ok(drive_run, capsys, covered_env, "analyze")
    return drive_run


def _verify(window: tuple[str, str], first: int, *, internal: bool) -> str:
    """A ``vt-job-run-states`` verify envelope for job 42 (``internal`` = mirror)."""
    rows = [
        {
            "workspace_id": "123",
            "job_id": "42",
            "run_id": str(first + i),
            "result_state": "FAILED" if i < 5 else "SUCCESS",
            "first_period_start": f"{window[0]}T01:00:00",
            "last_period_end": f"{window[0]}T02:00:00",
        }
        for i in range(60)
    ]
    params = {"ws": "123", "start": window[0], "end": window[1], "job_ids": "42"}
    meta = {"params": params, **({"source": "internal"} if internal else {})}
    return json.dumps({"ok": True, "data": {"verify": meta, "rows": rows}})


def _open_clue(run, capsys, sandbox, clue: str = "job:42") -> dict:
    return _ok(
        run, capsys, sandbox, "case", "open", "--clue", clue, "--question", _QUESTION
    )


@pytest.mark.unit
class TestCase:
    def test_clue_opens_a_standalone_job_finding(self, analyzed, covered_env, capsys):
        data = _open_clue(analyzed, capsys, covered_env)
        assert data["origin"] == "clue" and data["case_state"] == "open"
        assert data["finding_key"] == "ck1|acme|123|job|42|case:job|-"
        (found,) = [
            f
            for f in _records(analyzed, "analysis/findings.json")
            if f["finding_id"] == data["finding_id"]
        ]
        assert (found["concern_code"], found["entity_kind"], found["entity_id"]) == (
            "case:job",
            "job",
            "42",
        )
        assert data["case_id"] in found["case_ids"]

    @pytest.mark.parametrize(
        ("kind", "ident"),
        [("pipeline", "a1b2c3d4-5678-90ab-cdef-1234567890ab"), ("query", "01ef-abc")],
    )
    def test_pipeline_and_query_clues_target_their_entity(
        self, analyzed, covered_env, capsys, kind, ident
    ):
        data = _open_clue(analyzed, capsys, covered_env, f"{kind}:{ident}")
        assert data["finding_key"] == f"ck1|acme|123|{kind}|{ident}|case:{kind}|-"
        (found,) = [
            f
            for f in _records(analyzed, "analysis/findings.json")
            if f["finding_id"] == data["finding_id"]
        ]
        assert (found["entity_kind"], found["entity_id"]) == (kind, ident)

    def test_unknown_clue_kind_is_a_usage_error_naming_the_valid_clues(
        self, analyzed, capsys
    ):
        code, out = _eng(
            analyzed, capsys, "case", "open", "--clue", "cluster:0612-abc",
            "--question", _QUESTION,
        )
        assert code == 2, out
        (error,) = json.loads(out)["errors"]
        assert error["code"] == "USAGE"
        assert "pipeline:<id>" in error["message"] and "query:<id>" in error["message"]
        assert _records(analyzed, "analysis/cases.json") == []

    def test_revise_without_run_output_records_the_gap(
        self, analyzed, covered_env, capsys
    ):
        case_id = _open_clue(analyzed, capsys, covered_env)["case_id"]
        data = _ok(
            analyzed, capsys, covered_env, "case", "revise", "--case-id", case_id
        )
        assert data["gaps"] == ["job_run_output"] and data["finding_revision"] == 2

    def test_revise_with_run_output_keeps_the_finding_id_and_reports_the_signature(
        self, analyzed, covered_env, capsys
    ):
        opened = _open_clue(analyzed, capsys, covered_env)
        put_files(
            analyzed,
            {_OUTPUT: json.dumps({"error": "Job aborted", "error_trace": _TRACE})},
        )
        data = _ok(
            analyzed,
            capsys,
            covered_env,
            "case",
            "revise",
            "--case-id",
            opened["case_id"],
            "--evidence",
            _OUTPUT,
        )
        assert data["gaps"] == [] and len(data["evidence_ids"]) == 1
        assert data["case_id"] == opened["case_id"]
        # The finding is not re-keyed: the id `case open` printed is the id forever.
        assert data["finding_key"] == opened["finding_key"]
        assert data["finding_key"].endswith("|-")
        assert data["error_signature"].endswith("/outofmemoryerror")
        case_ids = {
            f["finding_id"]
            for f in _records(analyzed, "analysis/findings.json")
            if f["concern_code"] == "case:job"
        }
        assert data["finding_id"] == opened["finding_id"]
        assert case_ids == {data["finding_id"]}
        shown = _ok(
            analyzed,
            capsys,
            covered_env,
            "case",
            "show",
            "--case-id",
            opened["case_id"],
        )
        assert shown["target"] == ["job", "42"]
        assert [r["evidence_ids"] for r in shown["evidence"]] == [data["evidence_ids"]]

    def test_two_open_cases_on_one_job_share_one_stable_finding(
        self, analyzed, covered_env, capsys
    ):
        first = _open_clue(analyzed, capsys, covered_env)
        second = _ok(
            analyzed,
            capsys,
            covered_env,
            "case",
            "open",
            "--clue",
            "job:42",
            "--question",
            "Why did run 9002 of job 42 fail?",
        )
        assert first["case_id"] != second["case_id"]
        assert first["finding_id"] == second["finding_id"]
        put_files(
            analyzed,
            {_OUTPUT: json.dumps({"error": "Job aborted", "error_trace": _TRACE})},
        )

        def revise(case_id: str) -> dict:
            return _ok(
                analyzed,
                capsys,
                covered_env,
                "case",
                "revise",
                "--case-id",
                case_id,
                "--evidence",
                _OUTPUT,
            )

        def by_id() -> dict[str, dict]:
            rows = _records(analyzed, "analysis/findings.json")
            return {f["finding_id"]: f for f in rows if f["concern_code"] == "case:job"}

        stable = first["finding_id"]
        assert revise(first["case_id"])["finding_id"] == stable
        assert revise(second["case_id"])["finding_id"] == stable
        found = by_id()
        assert list(found) == [stable]
        assert found[stable]["case_ids"] == [first["case_id"], second["case_id"]]

    def test_reanalysis_keeps_the_case_finding(self, analyzed, covered_env, capsys):
        opened = _open_clue(analyzed, capsys, covered_env)
        _ok(analyzed, capsys, covered_env, "analyze")
        ids = {f["finding_id"] for f in _records(analyzed, "analysis/findings.json")}
        assert opened["finding_id"] in ids
        cases = _records(analyzed, "analysis/cases.json")
        assert [c["case_id"] for c in cases] == [opened["case_id"]]

    def test_revise_mixed_sources_take_the_most_restrictive_kind(
        self, analyzed, covered_env, capsys
    ):
        case_id = _open_clue(analyzed, capsys, covered_env)["case_id"]
        put_files(
            analyzed,
            {
                "raw/runs-a.json": _verify(
                    ("2026-09-08", "2026-09-22"), 100, internal=False
                ),
                "raw/runs-b.json": _verify(
                    ("2026-09-23", "2026-10-07"), 200, internal=True
                ),
            },
        )
        data = _ok(
            analyzed,
            capsys,
            covered_env,
            "case",
            "revise",
            "--case-id",
            case_id,
            "--verify",
            "raw/runs-a.json",
            "--verify",
            "raw/runs-b.json",
        )
        assert data["observations_added"] > 0
        acquired = [
            o
            for o in _records(analyzed, "analysis/observations.json")
            if o["method_version"] == "acquisition_v1"
        ]
        assert acquired
        assert {o["source_kind"] for o in acquired} == {"internal_mirror"}
        assert {o["audience_class"] for o in acquired} == {"internal_only"}

    def test_inconclusive_hypothesis_status_is_rejected(
        self, analyzed, covered_env, capsys
    ):
        case_id = _open_clue(analyzed, capsys, covered_env)["case_id"]
        before = _records(analyzed, "analysis/cases.json")
        code, out = _eng(
            analyzed,
            capsys,
            "case",
            "revise",
            "--case-id",
            case_id,
            "--hypothesis",
            "heap too small",
            "--hypothesis-status",
            "inconclusive",
        )
        # The parser rejects it (engagement USAGE, exit 2); nothing is written.
        assert code == 2 and "invalid choice: 'inconclusive'" in out, out
        assert _records(analyzed, "analysis/cases.json") == before

    def test_analyze_after_revise_chains_on_the_investigated_copy(
        self, analyzed, covered_env, capsys
    ):
        (idle,) = [
            f
            for f in _records(analyzed, "analysis/findings.json")
            if f["rule_id"] == "W-IDLE"
        ]
        opened = _ok(
            analyzed,
            capsys,
            covered_env,
            "case",
            "open",
            "--finding-id",
            idle["finding_id"],
            "--question",
            "Why is warehouse wh-1 idle?",
        )
        revised = _ok(
            analyzed,
            capsys,
            covered_env,
            "case",
            "revise",
            "--case-id",
            opened["case_id"],
            "--hypothesis",
            "auto-stop is off",
        )
        assert revised["finding_revision"] == 2
        # The same run is re-assessed with W-IDLE now at medium (watch).
        medium = {**_finding("W-IDLE", "wh-1", 30.0), "severity": "medium"}
        put_files(
            analyzed,
            {
                "findings-manifest.json": _manifest(
                    "2026-09-08",
                    "2026-10-07",
                    [medium, _finding("Q-SLOW", "q-1", 5.0)],
                    "2026-10-08",
                )
            },
        )
        _ok(analyzed, capsys, covered_env, "analyze")
        (found,) = [
            f
            for f in _records(analyzed, "analysis/findings.json")
            if f["finding_id"] == idle["finding_id"]
        ]
        assert (found["state"], found["severity"]) == ("watch", "watch")
        assert found["revision"] == 3
        assert [r["reason"] for r in found["revisions"]][1] == "investigated"
        assert found["revisions"][-1]["reason"] != "investigated"
        assert found["episode_id"] == idle["episode_id"]
        assert opened["case_id"] in found["case_ids"]
        # Plays (and their actions) are built from the merged finding record.
        cited = {
            fid
            for p in _records(analyzed, "analysis/plays.json")
            for fid in p["finding_ids"]
        }
        assert idle["finding_id"] in cited
        # Re-analysing the run is idempotent.
        _ok(analyzed, capsys, covered_env, "analyze")
        (again,) = [
            f
            for f in _records(analyzed, "analysis/findings.json")
            if f["finding_id"] == idle["finding_id"]
        ]
        assert again == found

    def test_email_in_the_question_exits_2_without_echo(self, analyzed, capsys):
        code, out = _eng(
            analyzed,
            capsys,
            "case",
            "open",
            "--clue",
            "job:42",
            "--question",
            "ask pat.operator@acme.example",
        )
        assert code == 2, out
        assert "pat.operator" not in out and "acme.example" not in out
        assert _records(analyzed, "analysis/cases.json") == []

    def test_unknown_case_is_not_found(self, analyzed, capsys):
        code, out = _eng(analyzed, capsys, "case", "show", "--case-id", "case_missing")
        assert code == 4, out


@pytest.mark.unit
class TestAction:
    def _action_id(self, run) -> str:
        return _records(run, "analysis/actions.json")[0]["action_id"]

    def test_accept_then_execute(self, analyzed, covered_env, capsys):
        aid = self._action_id(analyzed)
        data = _ok(
            analyzed, capsys, covered_env, "action", "accept", "--action-id", aid
        )
        assert data["acceptance_state"] == "accepted"
        data = _ok(
            analyzed,
            capsys,
            covered_env,
            "action",
            "execute",
            "--action-id",
            aid,
            "--executed-at",
            "2026-10-09",
        )
        assert (data["execution_state"], data["executed_at"]) == (
            "executed",
            "2026-10-09",
        )

    def test_invalid_transition_exits_2(self, analyzed, covered_env, capsys):
        aid = self._action_id(analyzed)
        _ok(analyzed, capsys, covered_env, "action", "accept", "--action-id", aid)
        code, out = _eng(analyzed, capsys, "action", "reject", "--action-id", aid)
        assert code == 2 and "INVALID_TRANSITION" in out, out

    def test_credential_in_the_note_exits_2_without_echo(self, analyzed, capsys):
        aid = self._action_id(analyzed)
        before = _records(analyzed, "analysis/actions.json")
        code, out = _eng(
            analyzed,
            capsys,
            "action",
            "accept",
            "--action-id",
            aid,
            "--note",
            "password=hunter2",
        )
        assert code == 2, out
        assert "hunter2" not in out
        assert _records(analyzed, "analysis/actions.json") == before

    def test_reanalysis_keeps_a_host_moved_action(self, analyzed, covered_env, capsys):
        aid = self._action_id(analyzed)
        _ok(analyzed, capsys, covered_env, "action", "accept", "--action-id", aid)
        _ok(analyzed, capsys, covered_env, "analyze")
        (kept,) = [
            a
            for a in _records(analyzed, "analysis/actions.json")
            if a["action_id"] == aid
        ]
        assert kept["acceptance_state"] == "accepted"


@pytest.mark.unit
class TestPlay:
    def test_rank_records_the_host_order(self, analyzed, covered_env, capsys):
        pid = _records(analyzed, "analysis/plays.json")[0]["play_id"]
        data = _ok(
            analyzed,
            capsys,
            covered_env,
            "play",
            "rank",
            "--play-id",
            pid,
            "--rank",
            "1",
            "--reason",
            "largest DBU estimate",
        )
        assert data["host_rank"] == 1
        (ranked,) = [
            p for p in _records(analyzed, "analysis/plays.json") if p["play_id"] == pid
        ]
        assert ranked["host_rank"] == 1

    def test_reanalysis_keeps_the_host_rank(self, analyzed, covered_env, capsys):
        pid = _records(analyzed, "analysis/plays.json")[-1]["play_id"]
        _ok(
            analyzed,
            capsys,
            covered_env,
            "play",
            "rank",
            "--play-id",
            pid,
            "--rank",
            "1",
            "--reason",
            "criticality high: feeds the board report",
        )
        _ok(analyzed, capsys, covered_env, "analyze")
        (ranked,) = [
            p for p in _records(analyzed, "analysis/plays.json") if p["play_id"] == pid
        ]
        assert (ranked["host_rank"], ranked["host_reorder_reason"]) == (
            1,
            "criticality high: feeds the board report",
        )

    def test_unknown_play_is_not_found(self, analyzed, capsys):
        code, out = _eng(
            analyzed,
            capsys,
            "play",
            "rank",
            "--play-id",
            "play_x",
            "--rank",
            "1",
            "--reason",
            "x",
        )
        assert code == 4 and "NOT_FOUND" in out, out

    def test_rank_below_one_exits_2(self, analyzed, capsys):
        code, out = _eng(
            analyzed,
            capsys,
            "play",
            "rank",
            "--play-id",
            "play_x",
            "--rank",
            "0",
            "--reason",
            "x",
        )
        assert code == 2, out


@pytest.mark.unit
def test_prior_history_is_loaded_once_per_command(covered_env, drive_run, monkeypatch):
    import argparse

    from starboard_core.engagement import prior as prior_mod
    from starboard_skills.helpers.contract import NotFoundError
    from starboard_skills.helpers.engagement._envelope import CASES_PATH, FINDINGS_PATH
    from starboard_skills.helpers.engagement.analysis_cmds import open_run
    from starboard_skills.helpers.engagement.case_cmds import _lookup

    calls: list[int] = []
    real = prior_mod.load_prior

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(prior_mod, "load_prior", counting)
    args = argparse.Namespace(
        run_folder=drive_run.folder_id,
        run_dir=None,
        workspace_root=None,
        internal_domain=None,
    )
    with open_run(args) as run:
        for kind, rel, key in (
            ("cases", CASES_PATH, "case_id"),
            ("findings", FINDINGS_PATH, "finding_id"),
        ):
            with pytest.raises(NotFoundError):
                _lookup(run, kind, rel, key, "missing")
    assert len(calls) == 1
