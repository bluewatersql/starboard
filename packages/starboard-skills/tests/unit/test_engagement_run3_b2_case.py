"""Run-3 fixes to ``engagement case|action`` (B2-3, B2-4, B2-5, B2-6, B2-9) and
the ``verify run --end`` help (B2-10)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from . import test_engagement_case_action as case_action
from .conftest import drive_files, put_files, run_main
from .test_engagement_case_action import (
    _OUTPUT,
    _TRACE,
    _eng,
    _ok,
    _open_clue,
    _records,
)

analyzed = case_action.analyzed  # fixture: an analyzed Drive-backed run


def _idle_case(run, capsys, sandbox) -> dict:
    (idle,) = [
        f for f in _records(run, "analysis/findings.json") if f["rule_id"] == "W-IDLE"
    ]
    return _ok(
        run, capsys, sandbox, "case", "open", "--finding-id", idle["finding_id"],
        "--question", "Why is warehouse wh-1 idle?",
    )


def _case(run, case_id: str) -> dict:
    (case,) = [c for c in _records(run, "analysis/cases.json") if c["case_id"] == case_id]
    return case


@pytest.mark.unit
class TestActionIdempotent:
    def test_accept_twice_is_ok_and_writes_nothing(self, analyzed, covered_env, capsys):
        aid = _records(analyzed, "analysis/actions.json")[0]["action_id"]
        first = _ok(analyzed, capsys, covered_env, "action", "accept", "--action-id", aid)
        assert first["already"] is None and first["outputs"]
        before = drive_files(analyzed)
        again = _ok(analyzed, capsys, covered_env, "action", "accept", "--action-id", aid)
        assert again["already"] == "accepted" and again["outputs"] == []
        assert again["acceptance_state"] == "accepted" and again["action_id"] == aid
        assert drive_files(analyzed) == before

    def test_execute_twice_is_ok(self, analyzed, covered_env, capsys):
        aid = _records(analyzed, "analysis/actions.json")[0]["action_id"]
        _ok(analyzed, capsys, covered_env, "action", "accept", "--action-id", aid)
        argv = ("action", "execute", "--action-id", aid, "--executed-at", "2026-10-09")
        _ok(analyzed, capsys, covered_env, *argv)
        before = drive_files(analyzed)
        again = _ok(analyzed, capsys, covered_env, *argv)
        assert again["already"] == "executed" and again["executed_at"] == "2026-10-09"
        assert drive_files(analyzed) == before

    def test_a_real_conflict_still_exits_2(self, analyzed, covered_env, capsys):
        aid = _records(analyzed, "analysis/actions.json")[0]["action_id"]
        _ok(analyzed, capsys, covered_env, "action", "accept", "--action-id", aid)
        code, out = _eng(analyzed, capsys, "action", "reject", "--action-id", aid)
        assert code == 2 and "INVALID_TRANSITION" in out, out


@pytest.mark.unit
class TestCaseOpenOutputs:
    def test_finding_case_lists_only_what_it_wrote(self, analyzed, covered_env, capsys):
        findings = drive_files(analyzed)["analysis/findings.json"]
        data = _idle_case(analyzed, capsys, covered_env)
        assert data["outputs"] == ["analysis/cases.json"]
        assert drive_files(analyzed)["analysis/findings.json"] == findings

    def test_clue_case_lists_findings_it_wrote(self, analyzed, covered_env, capsys):
        data = _open_clue(analyzed, capsys, covered_env)
        assert data["outputs"] == ["analysis/cases.json", "analysis/findings.json"]


@pytest.mark.unit
class TestHypothesisById:
    def _hypothesise(self, run, capsys, sandbox) -> tuple[str, str]:
        case_id = _idle_case(run, capsys, sandbox)["case_id"]
        _ok(
            run, capsys, sandbox, "case", "revise", "--case-id", case_id,
            "--hypothesis", "auto-stop is off",
        )
        (hyp,) = _case(run, case_id)["hypotheses"]
        assert hyp["status"] == "untested"
        return case_id, hyp["hypothesis_id"]

    def test_status_alone_reuses_the_stored_statement(
        self, analyzed, covered_env, capsys
    ):
        case_id, hid = self._hypothesise(analyzed, capsys, covered_env)
        _ok(
            analyzed, capsys, covered_env, "case", "revise", "--case-id", case_id,
            "--hypothesis-id", hid, "--hypothesis-status", "refuted",
        )
        (hyp,) = _case(analyzed, case_id)["hypotheses"]
        assert hyp["hypothesis_id"] == hid
        assert (hyp["statement"], hyp["status"]) == ("auto-stop is off", "refuted")

    def test_unknown_id_without_statement_is_usage(self, analyzed, covered_env, capsys):
        case_id, _ = self._hypothesise(analyzed, capsys, covered_env)
        before = _records(analyzed, "analysis/cases.json")
        code, out = _eng(
            analyzed, capsys, "case", "revise", "--case-id", case_id,
            "--hypothesis-id", "h-missing", "--hypothesis-status", "refuted",
        )
        assert code == 2, out
        (error,) = json.loads(out)["errors"]
        assert error["code"] == "USAGE" and "'h-missing'" in error["message"]
        assert "--hypothesis" in error["message"]
        assert _records(analyzed, "analysis/cases.json") == before

    def test_status_without_any_hypothesis_is_usage(self, analyzed, covered_env, capsys):
        case_id = _idle_case(analyzed, capsys, covered_env)["case_id"]
        code, out = _eng(
            analyzed, capsys, "case", "revise", "--case-id", case_id,
            "--hypothesis-status", "refuted",
        )
        assert code == 2 and "--hypothesis-id" in out, out


@pytest.mark.unit
class TestVerifyIsJobOnly:
    def test_other_verify_payload_names_evidence(self, analyzed, covered_env, capsys):
        case_id = _idle_case(analyzed, capsys, covered_env)["case_id"]
        warehouse = {
            "ok": True,
            "data": {
                "verify": {"params": {"ws": "123", "warehouse_ids": "wh-1"}},
                "rows": [{"warehouse_id": "wh-1", "queries": 3}],
            },
        }
        put_files(analyzed, {"raw/wh-verify.json": json.dumps(warehouse)})
        code, out = _eng(
            analyzed, capsys, "case", "revise", "--case-id", case_id,
            "--verify", "raw/wh-verify.json",
        )
        assert code == 2, out
        (error,) = json.loads(out)["errors"]
        assert error["code"] == "USAGE"
        assert "vt-job-run-states" in error["message"]
        assert "--evidence <path>" in error["message"]

    def test_help_names_the_alternative(self, capsys):
        code, out = run_main(["engagement", "case", "revise", "--help"], capsys)
        assert code == 0
        assert "vt-job-run-states" in out and "--evidence" in out


@pytest.mark.unit
class TestCaseShowEvidencePaths:
    def test_evidence_ids_map_to_their_artifact(self, analyzed, covered_env, capsys):
        opened = _open_clue(analyzed, capsys, covered_env)
        put_files(
            analyzed,
            {_OUTPUT: json.dumps({"error": "Job aborted", "error_trace": _TRACE})},
        )
        revised = _ok(
            analyzed, capsys, covered_env, "case", "revise", "--case-id",
            opened["case_id"], "--evidence", _OUTPUT,
        )
        (eid,) = revised["evidence_ids"]
        shown = _ok(
            analyzed, capsys, covered_env, "case", "show", "--case-id", opened["case_id"]
        )
        assert shown["evidence_paths"] == {eid: _OUTPUT}


@pytest.mark.unit
class TestVerifyEndHelp:
    def test_help_matches_behaviour(self, capsys):
        code, out = run_main(["verify", "run", "--help"], capsys)
        assert code == 0
        flat = " ".join(out.split())
        assert "before today" not in flat and "today's partial data" in flat

    def test_today_is_accepted_as_end(self):
        from starboard_skills.helpers.verify import derive_params

        today = dt.date.today()
        start = (today - dt.timedelta(days=6)).isoformat()
        params = derive_params(ws="123", start=start, end=today.isoformat())
        assert params["end"] == today.isoformat() and params["window_days"] == "7"
