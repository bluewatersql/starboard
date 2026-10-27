"""E1 Scenario 1: account review, no ticket (``drive_backed``; spec §H.1, D4-1, D4-13).

A ``health_check`` run is routed, analysed, recurred and reported (the
``deliverables/health-read.md`` body registered as the ``health-read`` report),
and ``run check`` gates it by the descriptor's profile. Every manifest revision
records ``workflow_profile == "health_check"``. A second run's
``engagement history`` selects run 1's observations, and run 2 carries run 1's
``finding_id`` and ``action_id``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from . import _fixtures
from ._support import (
    ACTION_PLAN_ONLY,
    HEALTH_READ,
    Ctx,
    analyze,
    commit,
    engagement_ok,
    failed_ids,
    finding,
    health_body,
    host_put,
    ids,
    new_run,
    readme,
    records,
    recovery_run,
    run_check,
    run_recur,
    verify_slice,
    write_inputs,
)

pytestmark = pytest.mark.parametrize("mode", ["drive_backed"])

PROFILE_ITEMS = {"health_present", "plays_present", "health_report"}


def _all_manifests(store: Any, rf: str) -> list[dict[str, Any]]:
    """Every committed manifest revision of the run, oldest first."""
    from starboard_core.engagement.commit import (
        _find_manifest_folder,
        _revisions,
        read_all,
        read_descriptor,
    )

    auth, _ = read_descriptor(store, rf)
    folder = _find_manifest_folder(store, rf, auth.run_id)
    assert folder is not None
    by_rev = _revisions(store, folder.id, auth.run_id)
    return [json.loads(read_all(store, by_rev[n][0].id)) for n in sorted(by_rev)]


def _reviewed_run(ctx: Ctx) -> Any:
    """Run 1: route -> capture -> analyze -> recur -> health read -> report."""
    run = new_run(ctx, task="health_check")
    write_inputs(
        ctx, run, facts=_fixtures.current_facts(), review=_fixtures.review_manifest()
    )
    rels = (
        verify_slice(ctx, run, _fixtures.S1, _fixtures.s1_rows(), suffix="s1"),
        verify_slice(ctx, run, _fixtures.S2, _fixtures.s2_rows(), suffix="s2"),
    )
    analyze(ctx, run, _fixtures.CURRENT, verify=rels)
    commit(ctx, run)
    code, _data, raw = run_recur(ctx, run, baseline=True)
    assert code == 0, raw
    recs = records(ctx, run)
    host_put(ctx, run, HEALTH_READ, health_body(recs.health))
    readme(ctx, run)
    commit(ctx, run)
    assert run.rf
    report = engagement_ok(
        ctx,
        run,
        "report",
        "--run-folder",
        run.rf,
        "--report-id",
        "health-read",
        "--audience",
        "internal",
        "--path",
        HEALTH_READ,
    )
    assert report["state"] != "blocked_audience", report
    return run


def test_health_check_run_assesses_six_families_and_owns_a_play(ctx: Ctx) -> None:
    from starboard_core.engagement.catalog import SIX_FAMILIES

    run = _reviewed_run(ctx)
    recs = records(ctx, run)
    families = {f["family"]: f for f in recs.health["families"]}
    assert set(families) == set(SIX_FAMILIES)
    assert {f["assessment"] for f in families.values()} <= {"assessed", "unknown"}
    assert recs.plays, "a health_check run has at least one play"
    assert all(p["owner_role"] for p in recs.plays)


def test_health_check_run_check_gates_by_the_descriptor_profile(ctx: Ctx) -> None:
    run = _reviewed_run(ctx)
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == "health_check", raw[:2000]
    assert data.get("profile_source") == "descriptor"
    skipped = ids(data.get("skipped_by_profile"))
    assert skipped >= ACTION_PLAN_ONLY
    assert not skipped & ids(data.get("passed"))
    assert ids(data.get("passed")) >= PROFILE_ITEMS, failed_ids(data)
    assert code == 0, failed_ids(data)
    assert failed_ids(data) == set()


def test_every_manifest_revision_records_the_health_check_profile(ctx: Ctx) -> None:
    run = _reviewed_run(ctx)
    run_check(ctx, run)
    commit(ctx, run, "check")
    assert run.rf
    revisions = _all_manifests(ctx.store, run.rf)
    assert len(revisions) >= 3
    assert [m.get("workflow_profile") for m in revisions] == ["health_check"] * len(
        revisions
    )


def test_second_run_history_selects_run_one_and_carries_finding_and_action(
    ctx: Ctx,
) -> None:
    first = _reviewed_run(ctx)
    recs1 = records(ctx, first)
    fid = _fixtures.finding_id_j42()
    detected = finding(recs1, fid)
    action = next(a for a in recs1.actions if a["finding_id"] == fid)
    run1_obs = {o["observation_id"] for o in recs1.observations}

    second = recovery_run(ctx, task="health_check")
    assert second.rf and second.rf != first.rf
    hist = engagement_ok(ctx, second, "history", "--run-folder", second.rf)
    assert hist["candidates"] >= 1
    picked = {
        s["baseline_observation_id"]
        for s in hist["selected"]
        if s.get("baseline_observation_id")
    }
    assert picked, hist
    assert picked <= run1_obs

    recs2 = records(ctx, second)
    carried = finding(recs2, fid)
    assert carried["finding_id"] == detected["finding_id"]
    assert carried["episode_id"] == detected["episode_id"]
    assert action["action_id"] in [
        a["action_id"] for a in recs2.actions if a["finding_id"] == fid
    ]
    assert run1_obs.isdisjoint({o["observation_id"] for o in recs2.observations})
    # Phase-4: the second run's manifest records the same profile.
    revisions = _all_manifests(ctx.store, second.rf)
    assert {m.get("workflow_profile") for m in revisions} == {"health_check"}
