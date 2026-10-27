"""Run-4 group C: ``engagement case`` verbs (C3-C6, C8) on the Drive-backed harness."""

from __future__ import annotations

import json

import pytest

from . import test_engagement_case_action as case_action
from .conftest import drive_files, put_files, run_main
from .test_engagement_case_action import _ok, _open_clue, _records

analyzed = case_action.analyzed  # fixture: an analyzed Drive-backed run
RUN_OUTPUT = "raw/job-run-output-9001.json"
COLOURED = "\x1b[0;31mRestException\x1b[0m: INTERNAL_ERROR: cluster failed"


def _idle_open(run, capsys, sandbox) -> dict:
    (idle,) = [
        f for f in _records(run, "analysis/findings.json") if f["rule_id"] == "W-IDLE"
    ]
    return _ok(
        run, capsys, sandbox, "case", "open", "--finding-id", idle["finding_id"],
        "--question", "Why is warehouse wh-1 idle?",
    )


@pytest.mark.unit
class TestCaseVerbs:
    def test_ansi_run_output_gives_a_clean_signature_and_a_stable_id(
        self, analyzed, covered_env, capsys
    ):
        opened = _open_clue(analyzed, capsys, covered_env)
        put_files(
            analyzed,
            {RUN_OUTPUT: json.dumps({"error": "x", "error_trace": COLOURED})},
        )
        revised = _ok(
            analyzed, capsys, covered_env, "case", "revise",
            "--case-id", opened["case_id"], "--evidence", RUN_OUTPUT,
        )
        assert revised["error_signature"].endswith("/restexception:internal_error")
        assert "31m" not in json.dumps(revised)
        assert revised["finding_id"] == opened["finding_id"]
        assert revised["finding_key"] == opened["finding_key"]

    def test_open_and_show_never_move_the_finding_revision(
        self, analyzed, covered_env, capsys
    ):
        opened = _idle_open(analyzed, capsys, covered_env)
        findings = drive_files(analyzed)["analysis/findings.json"]
        shown = [
            _ok(analyzed, capsys, covered_env, "case", "show", "--case-id", opened["case_id"])
            for _ in range(2)
        ]
        assert drive_files(analyzed)["analysis/findings.json"] == findings
        assert opened["finding_revision"] == shown[0]["finding_revision"]
        assert shown[0]["finding_revision"] == shown[1]["finding_revision"]
        assert shown[0]["finding_revision_run_id"] == opened["finding_revision_run_id"]
        revised = _ok(
            analyzed, capsys, covered_env, "case", "revise", "--case-id", opened["case_id"]
        )
        assert revised["finding_revision"] == opened["finding_revision"] + 1
        again = _ok(
            analyzed, capsys, covered_env, "case", "show", "--case-id", opened["case_id"]
        )
        assert again["finding_revision"] == revised["finding_revision"]

    def test_show_lists_each_hypothesis_with_its_evidence(
        self, analyzed, covered_env, capsys
    ):
        opened = _idle_open(analyzed, capsys, covered_env)
        put_files(analyzed, {"raw/a.json": "{}", "raw/b.json": "{}"})
        first = _ok(
            analyzed, capsys, covered_env, "case", "revise", "--case-id", opened["case_id"],
            "--evidence", "raw/a.json", "--hypothesis", "auto-stop is off",
        )
        (a_id,) = first["evidence_ids"]
        shown = _ok(
            analyzed, capsys, covered_env, "case", "show", "--case-id", opened["case_id"]
        )
        (hyp,) = shown["hypotheses"]
        assert hyp["evidence_ids"] == [a_id] and hyp["statement"] == "auto-stop is off"
        assert hyp["status"] == "untested"

    def test_hypothesis_evidence_replaces_the_cited_list(
        self, analyzed, covered_env, capsys
    ):
        opened = _idle_open(analyzed, capsys, covered_env)
        put_files(analyzed, {"raw/a.json": "{}", "raw/b.json": "{}"})
        cid = opened["case_id"]
        a = _ok(
            analyzed, capsys, covered_env, "case", "revise", "--case-id", cid,
            "--evidence", "raw/a.json", "--hypothesis", "auto-stop is off",
        )
        b = _ok(
            analyzed, capsys, covered_env, "case", "revise", "--case-id", cid,
            "--evidence", "raw/b.json",
        )
        (a_id,), (b_id,) = a["evidence_ids"], b["evidence_ids"]
        _ok(
            analyzed, capsys, covered_env, "case", "revise", "--case-id", cid,
            "--hypothesis-id", "h1", "--hypothesis-evidence", b_id,
        )
        (hyp,) = _ok(
            analyzed, capsys, covered_env, "case", "show", "--case-id", cid
        )["hypotheses"]
        assert hyp["evidence_ids"] == [b_id] and a_id not in hyp["evidence_ids"]

    def test_help_documents_the_caps_and_values(self, capsys):
        def helptext(*argv: str) -> str:
            _, out = run_main(["engagement", *argv, "--help"], capsys)
            return " ".join(out.split())

        revise = helptext("case", "revise")
        assert "500 characters" in revise
        assert "REPLACES" in revise
        assert "unassessed (the start" in revise and "hypothesis -> supported" in revise
        opened = helptext("case", "open")
        assert "unassessed -> hypothesis -> supported" in opened
