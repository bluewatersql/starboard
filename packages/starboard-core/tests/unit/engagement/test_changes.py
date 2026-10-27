# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ChangeInput construction (WP3-7, D3-11)."""

from __future__ import annotations

import pytest
from starboard_core.engagement.changes import ChangeContext, build
from starboard_core.engagement.concerns import evaluate
from starboard_core.engagement.records import (
    Action,
    ActionEvent,
    action_id,
    change_id,
    concern_key,
    finding_id,
    play_id,
)

from .test_concerns import CUR, PRIOR, job_triplet, obs, prior, selection_for


def _rate_pair() -> tuple[list, list]:
    return job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)


def test_continuing_rate_change_has_pp_delta_and_relative_pct() -> None:
    cur, base = _rate_pair()
    changes = build(
        cur, selection_for(cur, base), context=ChangeContext(baselines=base)
    )
    by_metric = {c.metric: c for c in changes}
    rate = by_metric["job_failure_rate_pct"]
    assert rate.change_id == change_id(cur[2].observation_id, base[2].observation_id)
    assert rate.comparison == "continuing"
    assert rate.delta == pytest.approx(7.0) and rate.delta_unit == "pp"
    assert rate.relative_pct == pytest.approx(700.0)
    assert rate.causality == "not_assessed"
    assert (rate.baseline_interval_start, rate.current_interval_end) == (
        "2026-09-08",
        "2026-10-07",
    )
    assert rate.source_windows == (
        ("2026-09-08", "2026-09-22", "customer_workspace"),
        ("2026-09-23", "2026-10-07", "customer_workspace"),
    )
    co = {m["metric"]: m for m in rate.co_movements}
    assert set(co) == {"job_runs", "failed_job_runs"}
    assert co["failed_job_runs"]["delta"] == pytest.approx(7.0)
    assert by_metric["failed_job_runs"].delta_unit == "count"


def test_no_baseline_means_no_change() -> None:
    cur = job_triplet(100, 8, 8.0)
    assert build(cur, selection_for(cur, []), context=ChangeContext()) == ()


def test_zero_baseline_has_no_relative_pct() -> None:
    cur = job_triplet(100, 8, 8.0)
    base = job_triplet(100, 0, 0.0, maker=prior)
    changes = build(
        cur, selection_for(cur, base), context=ChangeContext(baselines=base)
    )
    rate = next(c for c in changes if c.metric == "job_failure_rate_pct")
    assert rate.relative_pct is None


def test_missing_baseline_record_raises() -> None:
    cur, base = _rate_pair()
    with pytest.raises(ValueError, match="baseline"):
        build(cur, selection_for(cur, base), context=ChangeContext())


def test_flag_new_comparison_is_emitted() -> None:
    p_cur = job_triplet(100, 1, 1.0, maker=prior)
    p_flags = evaluate(
        p_cur, selection_for(p_cur, [], run_id=PRIOR), [], run_id=PRIOR, baselines=[]
    ).flags
    cur = job_triplet(100, 8, 8.0)
    flags = evaluate(
        cur, selection_for(cur, p_cur), [], run_id=CUR, baselines=p_cur
    ).flags
    all_cur, all_base = [*cur, *flags], [*p_cur, *p_flags]
    changes = build(
        all_cur,
        selection_for(all_cur, all_base),
        context=ChangeContext(baselines=all_base),
    )
    flag_change = next(c for c in changes if c.metric == "job_failure_concern")
    assert flag_change.comparison == "new" and flag_change.delta == 1.0


def test_unknown_current_and_non_entity_kinds_are_skipped() -> None:
    cur = [
        obs(
            metric="job_runs",
            state="unknown",
            coverage="unknown",
            value=None,
            unknown_reason="source_unavailable",
        )
    ]
    base = [prior(metric="job_runs")]
    assert (
        build(cur, selection_for(cur, base), context=ChangeContext(baselines=base))
        == ()
    )
    fin_cur = [
        obs(
            entity_kind="finding",
            entity_id="r::x",
            metric="finding_present",
            unit="flag",
            value=1.0,
            method_version="findings_manifest_v2",
        )
    ]
    fin_base = [
        prior(
            entity_kind="finding",
            entity_id="r::x",
            metric="finding_present",
            unit="flag",
            value=1.0,
            method_version="findings_manifest_v2",
        )
    ]
    sel = selection_for(fin_cur, fin_base)
    assert build(fin_cur, sel, context=ChangeContext(baselines=fin_base)) == ()


def test_context_events_config_step_and_action() -> None:
    cur = [
        obs(
            family="efficiency",
            entity_kind="warehouse",
            entity_id="wh-1",
            metric="queued_pct",
            unit="pct",
            value=30.0,
        )
    ]
    base = [
        prior(
            family="efficiency",
            entity_kind="warehouse",
            entity_id="wh-1",
            metric="queued_pct",
            unit="pct",
            value=10.0,
        )
    ]
    findings = evaluate(
        cur, selection_for(cur, base), [], run_id=CUR, baselines=base
    ).findings
    assert findings == ()  # efficiency has no fact concern rule
    fid = finding_id(
        concern_key("acme", "123", "warehouse", "wh-1", "rule:warehouse_queueing")
    )
    aid = action_id(fid, "rule_finding_review", PRIOR)
    action = Action(
        action_id=aid,
        finding_id=fid,
        play_id=play_id("rule_finding_review", fid),
        case_id=None,
        owner_role="warehouse_owner",
        owner_label=None,
        next_step="review warehouse queueing",
        proposal_state="proposed",
        acceptance_state="pending",
        execution_state="not_started",
        executed_at=None,
        verification_window_start=None,
        verification_window_end=None,
        outcome_state="not_observed",
        outcome_observation_ids=(),
        attribution="not_established",
        events=(
            ActionEvent(
                seq=1,
                kind="proposed",
                run_id=PRIOR,
                at="2026-09-23T00:00:00+00:00",
                recorded_by="rule",
            ),
        ),
        run_id=PRIOR,
    )

    class _F:  # minimal finding stand-in (only finding_id / observation_ids are read)
        finding_id = fid
        observation_ids = (cur[0].observation_id,)

    ctx = ChangeContext(
        baselines=base,
        config_changes=[
            {
                "warehouse_id": "wh-1",
                "change_time": "2026-09-25 10:00:00",
                "change": "max_num_clusters",
                "workspace_id": "123",
            },
            {
                "warehouse_id": "wh-2",
                "change_time": "2026-09-25 10:00:00",
                "change": "auto_stop_mins",
                "workspace_id": "123",
            },
            {
                "warehouse_id": "wh-1",
                "change_time": "2026-01-01 00:00:00",
                "change": "too_old",
                "workspace_id": "123",
            },
        ],
        step_change={"date": "2026-09-20", "method": "two_window_median"},
        actions=[action],
        findings=[_F()],  # type: ignore[list-item]
    )
    (change,) = build(cur, selection_for(cur, base), context=ctx)
    assert [(e["kind"], e["ref"]) for e in change.context_events] == [
        ("step_change", "step_change:2026-09-20"),
        ("action_event", f"{aid}:proposed"),
        ("config_change", "warehouse:wh-1:max_num_clusters"),
    ]
    assert change.delta == pytest.approx(20.0) and change.delta_unit == "pp"


def test_superseded_aggregate_becomes_co_movement() -> None:
    cur, base = _rate_pair()
    agg = obs(
        metric="job_failure_rate_pct",
        unit="pct",
        value=7.5,
        method_version="job_aggregate_v1",
        dedupe_key="job_aggregate_slice|42",
    )
    ctx = ChangeContext(baselines=base, superseded=[(cur[2].observation_id, agg)])
    rate = next(
        c
        for c in build(cur, selection_for(cur, base), context=ctx)
        if c.metric == "job_failure_rate_pct"
    )
    assert {
        "metric": "job_failure_rate_pct",
        "unit": "pct",
        "observation_id": agg.observation_id,
    } in [dict(m) for m in rate.co_movements]


def test_reconstruction_source_windows_override() -> None:
    cur, base = _rate_pair()
    windows = {cur[2].observation_id: [("2026-09-23", "2026-10-07", "internal_mirror")]}
    ctx = ChangeContext(baselines=base, source_windows=windows)
    rate = next(
        c
        for c in build(cur, selection_for(cur, base), context=ctx)
        if c.metric == "job_failure_rate_pct"
    )
    assert rate.source_windows == (("2026-09-23", "2026-10-07", "internal_mirror"),)
