"""E16: a case's next step and the troubleshoot verbs around it (live run 2).

``internal_local`` and ``drive_backed`` with ``internal_only`` unless noted.

* ``action propose --case-id`` records the host's next step as a ``pending``
  action on the case's finding (no play); the same step names the same action;
  ``accept`` -> ``execute`` move it; an ``engagement analyze`` re-run keeps it
  and its finding link.
* ``case revise``: a hypothesis cites this step's evidence by default; an
  unknown ``--hypothesis-evidence`` is USAGE; ``--hypothesis-id`` re-tests in
  place; once a revision cited the run output, later steps leave no
  ``job_run_output`` gap.
* ``run check`` without ``--internal`` reports items 12/16 as skipped.
* ``verify run --out analysis/verify/`` (trailing slash) writes under the run
  folder; a local ``--out`` on a covered run is ``LOCAL_STORAGE_REFUSED``.
* ``engagement read``: ``--jsonpath`` on a non-JSON artifact is USAGE; ``[n]`` /
  ``[*]`` steps; ``--max-bytes`` above the cap warns.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from . import _fixtures
from ._support import (
    CASE_REPORT,
    MANIFEST,
    QUESTION,
    VERIFY_DIR,
    WS,
    Ctx,
    Run,
    analyze,
    case_report,
    commit,
    eng,
    engagement_ok,
    error_code,
    failed_ids,
    helper,
    host_put,
    ids,
    new_run,
    read_json,
    readme,
    run_check,
    verify_slice,
    write,
)

BOTH = pytest.mark.parametrize("mode", ["internal_local", "drive_backed"])
DRIVE = pytest.mark.parametrize("mode", ["drive_backed"])

ACTIONS = "analysis/actions.json"
CASES = "analysis/cases.json"
FINDINGS = "analysis/findings.json"
TROUBLE_README = "not applicable: troubleshooting run"
NOT_INTERNAL = {"12", "16"}
RUN_OUTPUT = {
    "data": {
        "error_trace": "java.lang.OutOfMemoryError: Java heap space",
        "logs": "executor lost",
    }
}


def _run(ctx: Ctx, task_name: str = "job-42") -> Run:
    return new_run(
        ctx, task="troubleshooting", task_name=task_name, source_mode="internal_only"
    )


def _open(ctx: Ctx, run: Run, clue: str) -> dict[str, Any]:
    return engagement_ok(
        ctx, run, "case", "open", *run.flags(), "--clue", clue, "--question", QUESTION
    )


def _revise(ctx: Ctx, run: Run, case_id: str, *step: str) -> dict[str, Any]:
    return engagement_ok(
        ctx, run, "case", "revise", *run.flags(), "--case-id", case_id, *step
    )


def _propose(ctx: Ctx, run: Run, case_id: str) -> dict[str, Any]:
    return engagement_ok(
        ctx,
        run,
        "action",
        "propose",
        *run.flags(),
        "--case-id",
        case_id,
        "--next-step",
        "add a filter on the partition column",
        "--owner-role",
        "warehouse_owner",
        "--owner-label",
        "analytics team",
        "--verify-method",
        "p95 duration over the next 7 days",
    )


def _finding(ctx: Ctx, run: Run, finding_id: str) -> dict[str, Any]:
    (found,) = [
        f for f in read_json(ctx, run, FINDINGS) if f["finding_id"] == finding_id
    ]
    return found


def _case(ctx: Ctx, run: Run, case_id: str) -> dict[str, Any]:
    (found,) = [c for c in read_json(ctx, run, CASES) if c["case_id"] == case_id]
    return found


def _finish(ctx: Ctx, run: Run, case_ids: list[str], action_id: str | None) -> None:
    host_put(ctx, run, CASE_REPORT, case_report(case_ids, action_id=action_id))
    readme(ctx, run, delivery=f"- {CASE_REPORT}", recur=TROUBLE_README)
    commit(ctx, run)


@BOTH
def test_a_query_case_proposes_accepts_and_executes_its_next_step(ctx: Ctx) -> None:
    run = _run(ctx, "query-01f0-aaaa")
    opened = _open(ctx, run, "query:01f0-aaaa")
    write(ctx, run, {"raw/query-01f0-aaaa.json": {"data": {"query_id": "01f0-aaaa"}}})
    revised = _revise(
        ctx,
        run,
        opened["case_id"],
        "--evidence",
        "raw/query-01f0-aaaa.json",
        "--hypothesis",
        "a full scan of the fact table",
        "--hypothesis-status",
        "supported",
        "--cause-confidence",
        "supported",
    )
    assert revised["cause_confidence"] == "supported"
    (hyp,) = _case(ctx, run, opened["case_id"])["hypotheses"]
    assert hyp["evidence_ids"] == revised["evidence_ids"] != []

    proposed = _propose(ctx, run, opened["case_id"])
    assert proposed["created"] is True
    assert proposed["finding_id"] == opened["finding_id"]
    again = _propose(ctx, run, opened["case_id"])
    assert (again["action_id"], again["created"]) == (proposed["action_id"], False)
    action_id = proposed["action_id"]
    engagement_ok(ctx, run, "action", "accept", *run.flags(), "--action-id", action_id)
    engagement_ok(
        ctx,
        run,
        "action",
        "execute",
        *run.flags(),
        "--action-id",
        action_id,
        "--executed-at",
        "2026-10-09",
    )

    (action,) = [a for a in read_json(ctx, run, ACTIONS) if a["action_id"] == action_id]
    assert action["case_id"] == opened["case_id"] and action["play_id"] is None
    assert [e["kind"] for e in action["events"]] == ["proposed", "accepted", "executed"]
    assert action["verify_method"] == "p95 duration over the next 7 days"
    assert action_id in _finding(ctx, run, opened["finding_id"])["action_ids"]

    _finish(ctx, run, [opened["case_id"]], action_id)
    code, data, raw = run_check(ctx, run)
    assert failed_ids(data) == set(), raw[:2000]
    assert code == 0
    assert ids(data.get("skipped_not_internal")) == NOT_INTERNAL
    assert ids(data.get("passed")) & NOT_INTERNAL == set()


@BOTH
def test_an_analyze_rerun_keeps_the_case_action_and_its_link(ctx: Ctx) -> None:
    run = _run(ctx)
    opened = _open(ctx, run, f"job:{_fixtures.JOB}")
    rels = (
        verify_slice(ctx, run, _fixtures.S1, _fixtures.s1_rows(), suffix="s1"),
        verify_slice(ctx, run, _fixtures.S2, _fixtures.s2_rows(), suffix="s2"),
    )
    _revise(ctx, run, opened["case_id"], "--verify", rels[1])
    action_id = _propose(ctx, run, opened["case_id"])["action_id"]

    write(ctx, run, {MANIFEST: _fixtures.review_manifest()})
    analyze(ctx, run, _fixtures.CURRENT, verify=rels, facts=False)
    kept = [a for a in read_json(ctx, run, ACTIONS) if a["action_id"] == action_id]
    assert [a["case_id"] for a in kept] == [opened["case_id"]]
    assert action_id in _finding(ctx, run, opened["finding_id"])["action_ids"]


@BOTH
def test_an_unknown_hypothesis_evidence_id_is_a_usage_error(ctx: Ctx) -> None:
    run = _run(ctx)
    opened = _open(ctx, run, f"job:{_fixtures.JOB}")
    code, env, raw = eng(
        ctx.capsys,
        "case",
        "revise",
        *run.flags(),
        "--case-id",
        opened["case_id"],
        "--hypothesis",
        "the cluster lost an executor",
        "--hypothesis-evidence",
        "ev_" + "0" * 24,
    )
    assert code == 2, raw
    assert error_code(env) == "USAGE"
    assert "is not evidence of this run" in raw


@BOTH
def test_hypothesis_id_retests_the_hypothesis_in_place(ctx: Ctx) -> None:
    run = _run(ctx)
    opened = _open(ctx, run, f"job:{_fixtures.JOB}")
    write(ctx, run, {"raw/job-run-output-1.json": RUN_OUTPUT})
    first = _revise(
        ctx,
        run,
        opened["case_id"],
        "--evidence",
        "raw/job-run-output-1.json",
        "--hypothesis",
        "the executor ran out of heap",
        "--hypothesis-status",
        "supported",
    )
    _revise(
        ctx,
        run,
        first["case_id"],
        "--hypothesis-id",
        "h1",
        "--hypothesis",
        "the executor ran out of heap",
        "--hypothesis-status",
        "refuted",
        "--hypothesis-evidence",
        first["evidence_ids"][0],
    )
    (hyp,) = _case(ctx, run, first["case_id"])["hypotheses"]
    assert (hyp["hypothesis_id"], hyp["status"]) == ("h1", "refuted")
    assert hyp["evidence_ids"] == [first["evidence_ids"][0]]


@BOTH
def test_a_cited_run_output_leaves_no_gap_on_later_steps(ctx: Ctx) -> None:
    run = _run(ctx)
    opened = _open(ctx, run, f"job:{_fixtures.JOB}")
    write(ctx, run, {"raw/job-run-output-1.json": RUN_OUTPUT})
    cited = _revise(
        ctx, run, opened["case_id"], "--evidence", "raw/job-run-output-1.json"
    )
    assert cited["gaps"] == []
    later = _revise(ctx, run, opened["case_id"], "--hypothesis", "heap exhaustion")
    assert later["gaps"] == []

    control = _open(ctx, run, "job:43")
    uncited = _revise(ctx, run, control["case_id"], "--hypothesis", "unknown")
    assert uncited["gaps"] == ["job_run_output"]


def _verify_argv(run: Run, out: str) -> list[str]:
    assert run.rf
    return [
        "verify",
        "run",
        "vt-job-run-states",
        "--ws",
        WS,
        "--warehouse-id",
        "wh-1",
        "--start",
        _fixtures.S2[0],
        "--end",
        _fixtures.S2[1],
        "--job-ids",
        _fixtures.JOB,
        "--limit",
        "20000",
        "--suffix",
        "slash",
        "--run-folder",
        run.rf,
        "--out",
        out,
    ]


@DRIVE
def test_verify_out_with_a_trailing_slash_writes_under_the_run_folder(
    ctx: Ctx,
) -> None:
    run = new_run(ctx, task="troubleshooting", task_name="job-42")
    ctx.seams.sql = {
        "columns": list(_fixtures.RUN_COLUMNS),
        "rows": _fixtures.s2_rows(),
        "limit_reached": False,
    }
    code, _env, raw = helper(ctx.capsys, *_verify_argv(run, f"{VERIFY_DIR}/"))
    assert code == 0, raw
    rows = read_json(ctx, run, f"{VERIFY_DIR}/vt-job-run-states-slash.json")
    assert rows

    for out in ("../x", "/abs/x"):
        code, env, raw = helper(ctx.capsys, *_verify_argv(run, out))
        assert code == 2, raw
        assert error_code(env) == "LOCAL_STORAGE_REFUSED"


def _read(ctx: Ctx, run: Run, *argv: str) -> tuple[int, dict[str, Any], str]:
    assert run.rf
    return eng(ctx.capsys, "read", "--run-folder", run.rf, *argv)


@DRIVE
def test_engagement_read_jsonpath_steps_and_the_cap_warning(ctx: Ctx) -> None:
    run = _run(ctx)
    opened = _open(ctx, run, f"job:{_fixtures.JOB}")
    readme(ctx, run, delivery=f"- {CASE_REPORT}", recur=TROUBLE_README)

    code, env, raw = _read(ctx, run, "--path", "README.md", "--jsonpath", "$")
    assert code == 2, raw
    assert error_code(env) == "USAGE"
    assert "needs a JSON artifact" in raw

    code, env, raw = _read(
        ctx, run, "--path", FINDINGS, "--jsonpath", "[0].finding_id"
    )
    assert code == 0, raw
    assert env["data"]["excerpt"] == {
        "[0].finding_id": opened["finding_id"]
    }
    code, env, raw = _read(ctx, run, "--path", FINDINGS, "--jsonpath", "[*].finding_id")
    assert code == 0, raw
    assert opened["finding_id"] in env["data"]["excerpt"]["[*].finding_id"]

    code, env, raw = _read(ctx, run, "--path", FINDINGS, "--max-bytes", "100000")
    assert code == 0, raw
    assert env["data"]["warnings"] and "read cap" in env["data"]["warnings"][0]


def test_the_helper_owner_roles_are_the_record_owner_roles() -> None:
    from starboard_core.engagement.records import OwnerRole
    from starboard_skills.helpers.engagement.case_cmds import OWNER_ROLES

    assert sorted(OWNER_ROLES) == sorted(get_args(OwnerRole))
