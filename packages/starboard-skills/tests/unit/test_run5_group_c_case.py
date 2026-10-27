"""Run-5 group C: ``case revise`` hypothesis evidence/order, ``case show`` provenance."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from . import test_engagement_case_action as case_action
from .conftest import put_files
from .test_engagement_case_action import _ok
from .test_engagement_run4_c_case import _idle_open

analyzed = case_action.analyzed  # fixture: an analyzed Drive-backed run


def _revise(run, capsys, sandbox, cid: str, *argv: str) -> dict:
    return _ok(run, capsys, sandbox, "case", "revise", "--case-id", cid, *argv)


def _show(run, capsys, sandbox, cid: str) -> dict:
    return _ok(run, capsys, sandbox, "case", "show", "--case-id", cid)


@pytest.mark.unit
class TestRestatement:
    def test_rewording_keeps_evidence_status_and_position(
        self, analyzed, covered_env, capsys
    ):
        cid = _idle_open(analyzed, capsys, covered_env)["case_id"]
        put_files(analyzed, {"raw/a.json": "{}", "raw/b.json": "{}"})
        a = _revise(
            analyzed,
            capsys,
            covered_env,
            cid,
            "--evidence",
            "raw/a.json",
            "--hypothesis",
            "first",
            "--hypothesis-status",
            "supported",
        )
        _revise(analyzed, capsys, covered_env, cid, "--hypothesis", "second")
        _revise(analyzed, capsys, covered_env, cid, "--hypothesis", "third")
        # Reword h1 with no new evidence and no status.
        _revise(
            analyzed,
            capsys,
            covered_env,
            cid,
            "--hypothesis-id",
            "h1",
            "--hypothesis",
            "first, tightened",
        )
        hyps = _show(analyzed, capsys, covered_env, cid)["hypotheses"]
        assert [h["hypothesis_id"] for h in hyps] == ["h1", "h2", "h3"]
        h1 = hyps[0]
        assert h1["statement"] == "first, tightened"
        assert h1["status"] == "supported"
        assert h1["evidence_ids"] == a["evidence_ids"] != []

    def test_status_only_step_keeps_position(self, analyzed, covered_env, capsys):
        cid = _idle_open(analyzed, capsys, covered_env)["case_id"]
        _revise(analyzed, capsys, covered_env, cid, "--hypothesis", "first")
        _revise(analyzed, capsys, covered_env, cid, "--hypothesis", "second")
        _revise(
            analyzed,
            capsys,
            covered_env,
            cid,
            "--hypothesis-id",
            "h1",
            "--hypothesis-status",
            "refuted",
        )
        hyps = _show(analyzed, capsys, covered_env, cid)["hypotheses"]
        assert [(h["hypothesis_id"], h["status"]) for h in hyps] == [
            ("h1", "refuted"),
            ("h2", "untested"),
        ]


@pytest.mark.unit
class TestSameStepEvidenceJoins:
    def _two_files(self, run, capsys, sandbox) -> tuple[str, str]:
        cid = _idle_open(run, capsys, sandbox)["case_id"]
        put_files(run, {"raw/a.json": "{}", "raw/b.json": "{}"})
        a = _revise(
            run,
            capsys,
            sandbox,
            cid,
            "--evidence",
            "raw/a.json",
            "--hypothesis",
            "auto-stop is off",
        )
        (a_id,) = a["evidence_ids"]
        return cid, a_id

    def test_new_evidence_is_added_to_the_existing_list(
        self, analyzed, covered_env, capsys
    ):
        cid, a_id = self._two_files(analyzed, capsys, covered_env)
        b = _revise(
            analyzed,
            capsys,
            covered_env,
            cid,
            "--hypothesis-id",
            "h1",
            "--evidence",
            "raw/b.json",
        )
        (b_id,) = b["evidence_ids"]
        (hyp,) = _show(analyzed, capsys, covered_env, cid)["hypotheses"]
        assert hyp["evidence_ids"] == [a_id, b_id]

    def test_explicit_list_replaces_old_ids_but_keeps_new_evidence(
        self, analyzed, covered_env, capsys
    ):
        cid, a_id = self._two_files(analyzed, capsys, covered_env)
        b = _revise(
            analyzed,
            capsys,
            covered_env,
            cid,
            "--hypothesis-id",
            "h1",
            "--evidence",
            "raw/b.json",
            "--hypothesis-evidence",
            a_id,
        )
        (b_id,) = b["evidence_ids"]
        (hyp,) = _show(analyzed, capsys, covered_env, cid)["hypotheses"]
        assert hyp["evidence_ids"] == [a_id, b_id]

    def test_explicit_list_alone_still_replaces(self, analyzed, covered_env, capsys):
        cid, a_id = self._two_files(analyzed, capsys, covered_env)
        b = _revise(analyzed, capsys, covered_env, cid, "--evidence", "raw/b.json")
        (b_id,) = b["evidence_ids"]
        _revise(
            analyzed,
            capsys,
            covered_env,
            cid,
            "--hypothesis-id",
            "h1",
            "--hypothesis-evidence",
            b_id,
        )
        (hyp,) = _show(analyzed, capsys, covered_env, cid)["hypotheses"]
        assert hyp["evidence_ids"] == [b_id]


@pytest.mark.unit
def test_evidence_runs_names_the_run_that_cited_each_id():
    from starboard_skills.helpers.engagement.case_cmds import _evidence_runs

    case = SimpleNamespace(
        evidence_revisions=[{"run_id": "run_case", "evidence_ids": ["ev_c"]}]
    )
    finding = SimpleNamespace(
        run_id="run_f",
        revisions=[
            SimpleNamespace(run_id="run_old", evidence_ids=("ev_a", "ev_b")),
            SimpleNamespace(run_id="run_new", evidence_ids=("ev_b",)),
        ],
        evidence_ids=("ev_a", "ev_d"),
    )
    assert _evidence_runs(case, finding) == {
        "ev_c": "run_case",
        "ev_a": "run_old",
        "ev_b": "run_old",
        "ev_d": "run_f",
    }


@pytest.mark.unit
def test_show_carries_a_source_run_for_evidence_outside_this_run(
    analyzed, covered_env, capsys
):
    cid = _idle_open(analyzed, capsys, covered_env)["case_id"]
    shown = _show(analyzed, capsys, covered_env, cid)
    # Every id with a null path names the run that cited it.
    for ev, path in shown["evidence_paths"].items():
        if path is None:
            assert shown["evidence_from_run"][ev]
    assert set(shown["evidence_from_run"]) <= set(shown["evidence_paths"])
