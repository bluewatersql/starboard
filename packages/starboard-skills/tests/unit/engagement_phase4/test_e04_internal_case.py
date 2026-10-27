"""E4 Scenario 4: focused failure, internal only (spec §H.4, D4-4, B2).

``internal_local`` and ``drive_backed`` with ``internal_only`` (drive_default).

* ``case open --clue job:42`` with no discovery and no workspace auth (no
  ``verify-identity``) -> targeted verify slices ->
  ``case revise`` -> ``action accept`` -> ``deliverables/case-report.md`` -> ``run check`` (profile
  ``troubleshooting``) exits 0 with the discovery items skipped.
* A later ``health_check`` run links the case (``possible_links``); an
  unreadable registry gives ``history_unavailable`` (Drive: the registry is the
  cross-folder history).
* ``case open --finding-id <prior F>`` without ``case revise`` fails
  ``case_linked``; after ``case revise`` it passes.
* Drive-object intake: a customer-shared profile put in the run folder ->
  ``case open --drive-object drive:<id>`` -> ``case revise --evidence`` on the
  parsed profile -> the same pass path, with no local file.

Workspace (D4-15): the ``internal_only`` run names its one workspace at
preflight (``--internal-workspace-id``; ``authorized_scope`` basis
``declared``), so a standalone ``case open`` (``--clue`` / ``--drive-object``)
runs FIRST, before any slice, and resolves the workspace from the scope; the
Drive run's targeted slices then pass the scope check.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from . import _fixtures
from ._support import (
    CASE_REPORT,
    DISCOVERY,
    FACTS,
    MANIFEST,
    QUESTION,
    Ctx,
    Run,
    analyze,
    case_report,
    clean,
    commit,
    current_run,
    eng,
    engagement_ok,
    error_text,
    failed_ids,
    finding,
    has,
    host_put,
    ids,
    job_obs,
    module,
    new_run,
    preflight_argv,
    read_json,
    readme,
    records,
    run_check,
    verify_slice,
    write,
)

BOTH = pytest.mark.parametrize("mode", ["internal_local", "drive_backed"])
DRIVE = pytest.mark.parametrize("mode", ["drive_backed"])

CASES = "analysis/cases.json"
DISCOVERY_ITEMS = frozenset({"2", "3", "4"})
TROUBLE_ITEMS = {"case_linked", "focused_report"}
TROUBLE_README = "not applicable: troubleshooting run"
PROFILE = {
    "graphs": [
        {
            "nodes": [
                {"id": "1", "name": "Scan parquet t", "tag": "FileScan", "metrics": []}
            ],
            "edges": [],
        }
    ],
    "query": {"id": "q-e4", "status": "FINISHED", "metrics": {"totalTimeMs": 1000}},
}


def _trouble_run(ctx: Ctx) -> Run:
    """An ``internal_only`` troubleshooting run: preflight -> route, no verify-identity.

    ``new_run`` passes ``--internal-workspace-id`` at preflight (D4-15).
    """
    run = new_run(
        ctx,
        task="troubleshooting",
        task_name="job-42",
        source_mode="internal_only",
    )
    assert not has(ctx, run, FACTS) and not has(ctx, run, DISCOVERY)
    return run


def _open(ctx: Ctx, run: Run, *origin: str) -> dict[str, Any]:
    return engagement_ok(
        ctx, run, "case", "open", *run.flags(), *origin, "--question", QUESTION
    )


def _revise(ctx: Ctx, run: Run, case_id: str, *step: str) -> dict[str, Any]:
    return engagement_ok(
        ctx, run, "case", "revise", *run.flags(), "--case-id", case_id, *step
    )


def _finish(ctx: Ctx, run: Run, case_ids: list[str], action_id: str | None) -> None:
    """The troubleshooting deliverable set: README + ``deliverables/case-report.md``."""
    host_put(ctx, run, CASE_REPORT, case_report(case_ids, action_id=action_id))
    readme(ctx, run, delivery=f"- {CASE_REPORT}", recur=TROUBLE_README)
    commit(ctx, run)


def _assert_troubleshooting_pass(ctx: Ctx, run: Run) -> None:
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == "troubleshooting", raw[:2000]
    assert data.get("profile_source") == "descriptor"
    assert ids(data.get("skipped_by_profile")) >= DISCOVERY_ITEMS
    assert ids(data.get("passed")) >= TROUBLE_ITEMS, failed_ids(data)
    assert failed_ids(data) == set(), raw[:2000]
    assert code == 0


def _clue_case(ctx: Ctx, *, propose: bool = False) -> tuple[Run, dict[str, Any]]:
    """Clue case -> targeted slices -> ``case revise`` (the run is not committed).

    ``propose``: ``engagement analyze`` over the targeted slices and the review
    manifest (no discovery facts) before the revise, which proposes the job-42
    action.
    """
    run = _trouble_run(ctx)
    opened = _open(ctx, run, "--clue", f"job:{_fixtures.JOB}")
    assert opened["origin"] == "clue"
    rels = (
        verify_slice(ctx, run, _fixtures.S1, _fixtures.s1_rows(), suffix="s1"),
        verify_slice(ctx, run, _fixtures.S2, _fixtures.s2_rows(), suffix="s2"),
    )
    if propose:
        write(ctx, run, {MANIFEST: _fixtures.review_manifest()})
        analyze(ctx, run, _fixtures.CURRENT, verify=rels, facts=False)
    revised = _revise(
        ctx,
        run,
        opened["case_id"],
        "--verify",
        rels[1],
        "--hypothesis",
        "the 2026-09-22 change broke job 42",
    )
    assert revised["finding_id"] == opened["finding_id"]
    assert revised["finding_revision"] == opened["finding_revision"] + 1
    return run, opened


@BOTH
def test_clue_case_without_discovery_passes_the_troubleshooting_gate(
    ctx: Ctx,
) -> None:
    run, opened = _clue_case(ctx, propose=True)
    actions = read_json(ctx, run, "analysis/actions.json")
    assert actions
    action_id = actions[0]["action_id"]
    engagement_ok(ctx, run, "action", "accept", *run.flags(), "--action-id", action_id)
    _finish(ctx, run, [opened["case_id"]], action_id)
    _assert_troubleshooting_pass(ctx, run)


@BOTH
@pytest.mark.parametrize(
    ("task_name", "clue"),
    [
        ("queries-123", "query:01f0-aaaa-bbbb"),
        ("warehouse-abc123", "query:01f0-cccc-dddd"),
        ("jobs-123", "job:42"),
        ("pipeline-p-77", "pipeline:p-77"),
    ],
)
def test_a_scope_named_run_opens_the_case_on_the_target_it_found(
    ctx: Ctx, task_name: str, clue: str
) -> None:
    """No target id up front: the run is named after the searched scope, the target is
    found inside it, and the case opens on that target's clue."""
    run = new_run(
        ctx, task="troubleshooting", task_name=task_name, source_mode="internal_only"
    )
    opened = _open(ctx, run, "--clue", clue)
    kind, _, ident = clue.partition(":")
    (found,) = [
        f
        for f in read_json(ctx, run, "analysis/findings.json")
        if f["finding_id"] == opened["finding_id"]
    ]
    assert (found["entity_kind"], found["entity_id"]) == (kind, ident)
    _finish(ctx, run, [opened["case_id"]], None)
    _assert_troubleshooting_pass(ctx, run)


@BOTH
def test_a_dated_task_name_is_refused_naming_the_scope_names(ctx: Ctx) -> None:
    argv = preflight_argv(
        ctx,
        task="troubleshooting",
        task_name="queries-2026-10-12 slow",
        source_mode="internal_only",
        internal_scope="123",
    )
    code, env, raw = eng(ctx.capsys, *argv)
    assert code != 0, raw
    text = error_text(env, raw)
    assert "queries-<workspace_id>" in text and "warehouse-<warehouse_id>" in text


@BOTH
def test_finding_case_links_only_after_case_revise(ctx: Ctx) -> None:
    first, opened = _clue_case(ctx)
    _finish(ctx, first, [opened["case_id"]], None)
    prior = opened["finding_id"]

    run = _trouble_run(ctx)
    assert run.case_root == first.case_root
    case = _open(ctx, run, "--finding-id", prior)
    assert case["finding_id"] == prior
    _finish(ctx, run, [case["case_id"]], None)
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == "troubleshooting", raw[:2000]
    assert "case_linked" in failed_ids(data)
    assert "focused_report" not in failed_ids(data)
    assert code == 1

    rel = verify_slice(ctx, run, _fixtures.S2, _fixtures.s2_rows(), suffix="s2")
    revised = _revise(ctx, run, case["case_id"], "--verify", rel)
    assert revised["finding_id"] == prior
    commit(ctx, run)
    _assert_troubleshooting_pass(ctx, run)


@DRIVE
def test_a_later_health_run_links_the_case(ctx: Ctx) -> None:
    run, opened = _clue_case(ctx)
    _finish(ctx, run, [opened["case_id"]], None)
    cases = read_json(ctx, run, CASES)
    case = next(c for c in cases if c["case_id"] == opened["case_id"])
    assert case["origin"] == "clue"

    health = current_run(ctx, task="health_check")
    j42 = finding(records(ctx, health), _fixtures.finding_id_j42())
    assert j42["concern_code"] == "job_failure_rise"
    assert case["finding_id"] in j42["possible_links"]
    assert j42["finding_id"] != case["finding_id"]


def _corrupt_tree(store: Any, folder_id: str) -> int:
    count = 0
    for obj in store.list_children(folder_id):
        if obj.is_folder:
            count += _corrupt_tree(store, obj.id)
        else:
            store.corrupt_object(obj.id)
            count += 1
    return count


@DRIVE
def test_an_unreadable_registry_gives_history_unavailable(ctx: Ctx) -> None:
    from starboard_core.engagement.registry import ensure_registry

    run, opened = _clue_case(ctx)
    _finish(ctx, run, [opened["case_id"]], None)
    handles = ensure_registry(ctx.store, _fixtures.ACCOUNT)
    corrupted = sum(
        _corrupt_tree(ctx.store, h.registrations_folder_id)
        + _corrupt_tree(ctx.store, h.index_folder_id)
        for h in handles
    )
    assert corrupted >= 1

    health = current_run(ctx, task="health_check", commit_it=False)
    recs = records(ctx, health)
    rate = job_obs(recs, "job_failure_rate_pct")
    entries = [*recs.baselines["selected"], *recs.baselines["unavailable"]]
    mine = [
        e for e in entries if e.get("current_observation_id") == rate["observation_id"]
    ]
    assert [e["comparison"] for e in mine] == ["history_unavailable"]
    j42 = finding(recs, _fixtures.finding_id_j42())
    assert opened["finding_id"] not in j42["possible_links"]


@DRIVE
def test_drive_object_intake_opens_and_revises_the_case(ctx: Ctx) -> None:
    before = ctx.sandbox.snapshot()
    run = _trouble_run(ctx)
    shared = host_put(ctx, run, "raw/customer-profile.json", json.dumps(PROFILE))
    ref = f"drive:{shared['object_id']}"
    opened = _open(ctx, run, "--drive-object", ref)
    assert opened["origin"] == "drive_object"
    case = next(
        c for c in read_json(ctx, run, CASES) if c["case_id"] == opened["case_id"]
    )
    assert case["origin"] == "drive_object" and case["origin_ref"] == ref

    mark = ctx.sandbox.snapshot()
    code, _env, raw = module("diagnostic", ctx.capsys, "profile", "--input", ref)
    assert code == 0, raw
    parsed = clean(ctx.sandbox, mark, raw)
    assert parsed["data"]["query"]["id"] == "q-e4"
    host_put(ctx, run, "raw/customer-profile-parsed.json", json.dumps(parsed))
    revised = _revise(
        ctx, run, opened["case_id"], "--evidence", "raw/customer-profile-parsed.json"
    )
    assert revised["finding_id"] == opened["finding_id"]
    assert revised["finding_revision"] == opened["finding_revision"] + 1

    _finish(ctx, run, [opened["case_id"]], None)
    _assert_troubleshooting_pass(ctx, run)
    assert ctx.sandbox.snapshot() == before
