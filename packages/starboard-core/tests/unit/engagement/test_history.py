# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for per-observation baseline selection and finding states (P2-G6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from starboard_core.engagement.history import (
    Candidate,
    comparison_key,
    finding_states,
    same_lookback,
    select_baselines,
    selection_reason,
    window_comparison,
    window_days,
)
from starboard_core.engagement.records import (
    BaselineSelection,
    FindingRecord,
    FindingRevision,
    Observation,
    Registration,
    action_id,
    case_id,
    concern_key,
    episode_id,
    finding_id,
    observation_id,
)

CUR = "20261101_12345678-1234-4234-8234-123456789abc"
PRIOR = "20261001_22345678-1234-4234-8234-123456789abc"
OLDER = "20260901_32345678-1234-4234-8234-123456789abc"
INTERVAL = ("2026-10-02", "2026-10-31")
NOW = "2026-11-01T00:00:00+00:00"


def obs(**over: Any) -> Observation:
    base: dict[str, Any] = {
        "run_id": CUR,
        "account_key": "acme",
        "workspace_id": "123",
        "family": "other",
        "entity_kind": "job",
        "entity_id": "j1",
        "metric": "dbus",
        "value": 10.0,
        "unit": "DBU",
        "grain": "interval",
        "method_version": "discovery_facts_v1",
        "interval_start": "2026-10-02",
        "interval_end": "2026-10-31",
        "as_of": "2026-11-01T00:00:00+00:00",
        "coverage": "complete",
        "coverage_fraction": None,
        "state": "measured",
        "unknown_reason": None,
        "evidence_ids": (),
        "source_kind": "customer_workspace",
        "audience_class": "customer_shareable",
        "dedupe_key": None,
    }
    base.update(over)
    tmp = dict(base)
    key = tuple(
        tmp[k]
        for k in (
            "account_key",
            "workspace_id",
            "family",
            "entity_kind",
            "entity_id",
            "metric",
            "interval_start",
            "interval_end",
            "method_version",
        )
    )
    base["observation_id"] = observation_id(key)
    return Observation(**base)


def prior_obs(**over: Any) -> Observation:
    base: dict[str, Any] = {
        "run_id": PRIOR,
        "interval_start": "2026-09-01",
        "interval_end": "2026-09-30",
        "as_of": "2026-10-01T00:00:00+00:00",
        "value": 8.0,
    }
    base.update(over)
    return obs(**base)


def cand(o: Observation, rev: int = 3, reg: str | None = None) -> Candidate:
    return Candidate(
        observation=o, committed_revision=rev, registration_id=reg or f"reg_{o.run_id}"
    )


def flag(value: float, **over: Any) -> dict[str, Any]:
    return {
        "entity_kind": "finding",
        "entity_id": "W-W01::wh-1",
        "metric": "finding_present",
        "unit": "flag",
        "method_version": "findings_manifest_v2",
        "value": value,
        **over,
    }


def select(
    current: list[Observation], candidates: list[Candidate], **kw: Any
) -> BaselineSelection:
    return select_baselines(
        current, candidates, reporting_interval=INTERVAL, computed_at=NOW, **kw
    )


def only(selection: BaselineSelection) -> dict[str, Any]:
    assert len(selection.selected) == 1, selection.selected
    return dict(selection.selected[0])


def test_comparison_key() -> None:
    assert comparison_key(obs()) == ("acme", "123", "other", "job", "j1", "dbus")


def test_candidate_validation() -> None:
    with pytest.raises(ValueError):
        Candidate(
            observation=prior_obs(), committed_revision=0, registration_id="reg_x"
        )
    with pytest.raises(TypeError):
        Candidate(observation={}, committed_revision=1, registration_id="reg_x")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Candidate(observation=prior_obs(), committed_revision=1, registration_id="")


def test_no_prior_measurement() -> None:
    s = select([obs()], [])
    entry = only(s)
    assert entry["comparison"] == "no_prior_measurement"
    assert entry["baseline_observation_id"] is None
    assert s.run_id == CUR
    assert s.reporting_interval == INTERVAL
    assert s.unavailable == ()


def test_current_run_candidates_are_ignored() -> None:
    same_run = cand(obs(interval_start="2026-09-01", interval_end="2026-09-30"))
    assert only(select([obs()], [same_run]))["comparison"] == "no_prior_measurement"


def test_continuing_numeric() -> None:
    p = prior_obs()
    entry = only(select([obs()], [cand(p)]))
    assert entry == {
        "key": ("acme", "123", "other", "job", "j1", "dbus"),
        "current_observation_id": obs().observation_id,
        "baseline_observation_id": p.observation_id,
        "comparison": "continuing",
    }


def test_flag_states_continuing_recovered_new() -> None:
    assert (
        only(select([obs(**flag(1.0))], [cand(prior_obs(**flag(1.0)))]))["comparison"]
        == "continuing"
    )
    assert (
        only(select([obs(**flag(0.0))], [cand(prior_obs(**flag(1.0)))]))["comparison"]
        == "recovered"
    )
    assert (
        only(select([obs(**flag(1.0))], [cand(prior_obs(**flag(0.0)))]))["comparison"]
        == "new"
    )


def test_missing_current_evidence_unknown_current() -> None:
    p = prior_obs()
    unknown = obs(state="unknown", value=None, unknown_reason="F-04 timed out")
    entry = only(select([unknown], [cand(p)]))
    assert entry["comparison"] == "missing_current_evidence"
    assert entry["current_observation_id"] == unknown.observation_id
    assert entry["baseline_observation_id"] == p.observation_id


def test_missing_current_evidence_absent_current() -> None:
    p = prior_obs()
    entry = only(select([], [cand(p)], run_id=CUR))
    assert entry["comparison"] == "missing_current_evidence"
    assert entry["current_observation_id"] is None


def test_prior_clear_flag_without_current_is_omitted() -> None:
    s = select([], [cand(prior_obs(**flag(0.0)))], run_id=CUR)
    assert s.selected == ()


def test_run_id_required_without_current() -> None:
    with pytest.raises(ValueError):
        select_baselines([], [], reporting_interval=INTERVAL)


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"unit": "DSU"}, "unit_mismatch"),
        ({"grain": "daily"}, "grain_mismatch"),
        ({"method_version": "discovery_facts_v0"}, "method_mismatch"),
        (
            {"interval_start": "2026-09-15", "interval_end": "2026-10-15"},
            "interval_overlap",
        ),
    ],
)
def test_not_comparable(over: dict[str, Any], reason: str) -> None:
    p = prior_obs(**over)
    s = select([obs()], [cand(p)])
    entry = only(s)
    assert entry["comparison"] == "not_comparable"
    assert entry["baseline_observation_id"] is None
    assert [dict(r) for r in s.rejected] == [
        {
            "key": ("acme", "123", "other", "job", "j1", "dbus"),
            "candidate_observation_id": p.observation_id,
            "candidate_run_id": p.run_id,
            "interval": {"start": p.interval_start, "end": p.interval_end},
            "reason": reason,
        }
    ]


def test_overlap_adjusted_allows_overlap() -> None:
    p = prior_obs(interval_start="2026-09-15", interval_end="2026-10-15")
    s = select([obs()], [cand(p)], overlap_adjusted=True)
    assert only(s)["comparison"] == "continuing"


def test_unmeasured_prior_is_rejected_not_incomparable() -> None:
    p = prior_obs(state="unknown", value=None, unknown_reason="timeout")
    q = prior_obs(coverage="unknown", entity_id="j1", run_id=OLDER)
    s = select([obs()], [cand(p), cand(q)])
    assert only(s)["comparison"] == "no_prior_measurement"
    assert sorted(r["reason"] for r in s.rejected) == [
        "prior_coverage_unknown",
        "prior_not_measured",
    ]


def test_late_upload_cannot_displace_newer_window() -> None:
    newer = prior_obs()
    older = prior_obs(
        run_id=OLDER,
        interval_start="2026-08-01",
        interval_end="2026-08-31",
        as_of="2026-09-01T00:00:00+00:00",
    )
    # The older window was committed later (higher revision / uploaded late).
    s = select([obs()], [cand(older, rev=99), cand(newer, rev=1)])
    assert only(s)["baseline_observation_id"] == newer.observation_id


def test_ordering_ties_break_on_as_of_then_revision() -> None:
    # Same interval_end; distinct interval_start so the observation IDs differ.
    a = prior_obs(as_of="2026-10-01T00:00:00+00:00")
    b = prior_obs(
        run_id=OLDER, interval_start="2026-09-02", as_of="2026-10-02T00:00:00+00:00"
    )
    assert a.observation_id != b.observation_id
    assert (
        only(select([obs()], [cand(a), cand(b)]))["baseline_observation_id"]
        == b.observation_id
    )
    c = prior_obs(run_id=OLDER, interval_start="2026-08-31")
    s = select([obs()], [cand(a, rev=1), cand(c, rev=2)])
    assert only(s)["baseline_observation_id"] == c.observation_id
    s = select([obs()], [cand(a, rev=2), cand(c, rev=1)])
    assert only(s)["baseline_observation_id"] == a.observation_id


def test_mirror_dedupe_key_counted_once() -> None:
    a = prior_obs(dedupe_key="evt-1", source_kind="customer_workspace")
    b = prior_obs(
        run_id=OLDER,
        dedupe_key="evt-1",
        source_kind="internal_mirror",
        audience_class="internal_only",
    )
    s = select([obs()], [cand(a, rev=2), cand(b, rev=1)])
    assert only(s)["baseline_observation_id"] == a.observation_id
    assert [r["reason"] for r in s.rejected] == ["duplicate_dedupe_key"]


def test_same_observation_from_two_registries_is_not_double_counted() -> None:
    p = prior_obs()
    s = select([obs()], [cand(p, reg="reg_operator"), cand(p, reg="reg_shared")])
    assert only(s)["baseline_observation_id"] == p.observation_id
    assert s.rejected == ()


@dataclass(frozen=True)
class FakeView:
    registration: Registration | None
    object_id: str
    reason: str
    status: str = "history_unavailable"


def test_unavailable_registration_surfaced_never_baseline() -> None:
    views = [FakeView(None, "obj-9", "access revoked")]
    s = select([obs()], [], unavailable=views)
    assert only(s)["comparison"] == "history_unavailable"
    assert [dict(u) for u in s.unavailable] == [
        {"registration_id": "obj-9", "reason": "history_unavailable: access revoked"}
    ]
    # An eligible baseline from another registration still wins; unavailable stays listed.
    s2 = select([obs()], [cand(prior_obs())], unavailable=views)
    assert only(s2)["comparison"] == "continuing"
    assert len(s2.unavailable) == 1


def test_ok_views_are_not_unavailable() -> None:
    s = select([obs()], [], unavailable=[FakeView(None, "obj-1", "", status="ok")])
    assert s.unavailable == ()
    assert only(s)["comparison"] == "no_prior_measurement"


def test_per_key_selection_across_families() -> None:
    a_cur = obs()
    b_cur = obs(entity_id="j2")
    a_prior = prior_obs()
    b_prior = prior_obs(entity_id="j2", run_id=OLDER)  # e.g. from a ticket folder
    s = select([a_cur, b_cur], [cand(a_prior), cand(b_prior)])
    got = {e["key"][4]: e["baseline_observation_id"] for e in s.selected}
    assert got == {"j1": a_prior.observation_id, "j2": b_prior.observation_id}


# ---- finding_states (Finding v1) ---------------------------------------------

KEY = concern_key("acme", "123", "warehouse", "wh-1", "rule:warehouse_queueing")
FID = finding_id(KEY)
CASE = case_id("acme", FID, PRIOR, "why is wh-1 queueing?")
ACT = action_id(FID, "rule_finding_review", PRIOR)


def rev(
    n: int,
    run: str,
    reason: str = "detected",
    severity: str | None = "serious",
    obs_ids: tuple[str, ...] = (),
) -> FindingRevision:
    return FindingRevision(
        revision=n,
        run_id=run,
        reason=reason,
        severity=severity,
        symptom_confidence="confirmed",
        cause_confidence="unassessed",
        observation_ids=obs_ids,
        evidence_ids=(),
        case_id=None,
    )


def frec(
    run: str = CUR,
    *,
    state: str = "active",
    severity: str | None = "serious",
    last: str | None = "serious",
    obs_ids: tuple[str, ...] = (),
    started: str | None = None,
    revisions: tuple[FindingRevision, ...] | None = None,
    case_ids: tuple[str, ...] = (),
    action_ids: tuple[str, ...] = (),
) -> FindingRecord:
    started = started or run
    revs = revisions or (rev(1, run, severity=severity, obs_ids=obs_ids),)
    return FindingRecord(
        finding_id=FID,
        finding_key=KEY,
        concern_code="rule:warehouse_queueing",
        family="efficiency",
        account_key="acme",
        workspace_id="123",
        entity_kind="warehouse",
        entity_id="wh-1",
        episode_id=episode_id(FID, started),
        episode_started_run_id=started,
        state=state,
        severity=severity,
        last_confirmed_severity=last,
        symptom_confidence="confirmed",
        cause_confidence="unassessed",
        rule_id="warehouse_queueing",
        rule_version=1,
        revision=len(revs),
        revisions=revs,
        observation_ids=obs_ids,
        run_id=run,
        case_ids=case_ids,
        action_ids=action_ids,
    )


def test_finding_continuing_keeps_episode_and_chains_revision() -> None:
    p_o, c_o = prior_obs(**flag(1.0)), obs(**flag(1.0))
    sel = select([c_o], [cand(p_o)])
    prior = [
        frec(PRIOR, obs_ids=(p_o.observation_id,), case_ids=(CASE,), action_ids=(ACT,))
    ]
    current = [frec(severity="watch", last="watch", obs_ids=(c_o.observation_id,))]
    (out,) = finding_states(prior, sel, current)
    assert out.finding_id == FID
    assert (out.state, out.severity, out.last_confirmed_severity, out.run_id) == (
        "active",
        "watch",
        "watch",
        CUR,
    )
    assert out.episode_id == episode_id(FID, PRIOR)
    assert out.episode_started_run_id == PRIOR
    assert out.revision == 2
    assert [(r.revision, r.run_id, r.reason) for r in out.revisions] == [
        (1, PRIOR, "detected"),
        (2, CUR, "reassessed"),
    ]
    assert out.revisions[1].observation_ids == (c_o.observation_id,)
    assert (out.case_ids, out.action_ids) == ((CASE,), (ACT,))


def test_finding_continuing_watch_stays_watch() -> None:
    p_o, c_o = prior_obs(**flag(1.0)), obs(**flag(1.0))
    sel = select([c_o], [cand(p_o)])
    prior = [frec(PRIOR, obs_ids=(p_o.observation_id,))]
    current = [frec(state="watch", severity="watch", obs_ids=(c_o.observation_id,))]
    (out,) = finding_states(prior, sel, current)
    assert out.state == "watch"


def test_finding_new_starts_episode_after_recovery() -> None:
    p_o, c_o = prior_obs(**flag(0.0)), obs(**flag(1.0))
    sel = select([c_o], [cand(p_o)])
    prior = [
        frec(
            PRIOR,
            state="recovered",
            severity="none",
            started=OLDER,
            obs_ids=(p_o.observation_id,),
            revisions=(rev(1, OLDER), rev(2, PRIOR, "recovered", "none")),
        )
    ]
    (out,) = finding_states(prior, sel, [frec(obs_ids=(c_o.observation_id,))])
    assert (out.state, out.episode_id, out.episode_started_run_id) == (
        "active",
        episode_id(FID, CUR),
        CUR,
    )
    assert [(r.revision, r.reason) for r in out.revisions] == [
        (1, "detected"),
        (2, "recovered"),
        (3, "detected"),
    ]
    assert out.revision == 3


def test_finding_unknown_current_keeps_last_confirmed_severity() -> None:
    p_o = prior_obs(**flag(1.0))
    sel = select([], [cand(p_o)], run_id=CUR)
    prior = [
        frec(PRIOR, severity="critical", last="critical", obs_ids=(p_o.observation_id,))
    ]
    (out,) = finding_states(prior, sel, [])
    assert (out.state, out.severity, out.last_confirmed_severity, out.run_id) == (
        "unknown_current",
        None,
        "critical",
        CUR,
    )
    assert out.episode_id == episode_id(FID, PRIOR)
    assert [(r.revision, r.run_id, r.reason, r.severity) for r in out.revisions] == [
        (1, PRIOR, "detected", "critical"),
        (2, CUR, "unknown_current", None),
    ]


def test_finding_recovered_then_historical_then_dropped() -> None:
    p_o, c_o = prior_obs(**flag(1.0)), obs(**flag(0.0))
    sel = select([c_o], [cand(p_o)])
    prior = [frec(PRIOR, obs_ids=(p_o.observation_id,), action_ids=(ACT,))]
    (rec,) = finding_states(prior, sel, [])
    assert (rec.state, rec.severity, rec.last_confirmed_severity) == (
        "recovered",
        "none",
        "serious",
    )
    assert rec.episode_id == episode_id(FID, PRIOR)
    assert rec.observation_ids == (c_o.observation_id,)
    assert rec.revisions[-1].reason == "recovered"
    assert rec.revisions[-1].observation_ids == (c_o.observation_id,)
    assert rec.action_ids == (ACT,)
    later = "20261201_42345678-1234-4234-8234-123456789abc"
    (hist,) = finding_states([rec], select([], [], run_id=later), [])
    assert (hist.state, hist.run_id, hist.revision) == ("historical", later, 3)
    assert hist.revisions[-1].reason == "historical"
    after = "20270101_52345678-1234-4234-8234-123456789abc"
    assert finding_states([hist], select([], [], run_id=after), []) == ()


def test_recovered_finding_cites_measured_values() -> None:
    # D3-13: the outcome comes from the measured comparison, so the recovered
    # revision cites the measured value alongside the cleared flag.
    p_flag, c_flag = prior_obs(**flag(1.0)), obs(**flag(0.0))
    p_rate, c_rate = prior_obs(value=8.0), obs(value=1.0)
    sel = select([c_flag, c_rate], [cand(p_flag), cand(p_rate)])
    obs_ids = (p_flag.observation_id, p_rate.observation_id)
    (rec,) = finding_states([frec(PRIOR, obs_ids=obs_ids)], sel, [])
    assert rec.state == "recovered"
    assert rec.observation_ids == (c_flag.observation_id, c_rate.observation_id)
    assert rec.revisions[-1].observation_ids == rec.observation_ids


def test_finding_without_selection_info_is_unknown_current() -> None:
    prior = [frec(PRIOR, state="watch", severity="watch", last="watch")]
    (out,) = finding_states(prior, select([], [], run_id=CUR), [])
    assert (out.state, out.severity, out.last_confirmed_severity) == (
        "unknown_current",
        None,
        "watch",
    )
    assert out.revisions[-1].reason == "unknown_current"


def test_current_finding_with_unknown_observation() -> None:
    p_o = prior_obs(**flag(1.0))
    c_o = obs(
        **{**flag(1.0), "value": None, "state": "unknown", "unknown_reason": "degraded"}
    )
    sel = select([c_o], [cand(p_o)])
    prior = [frec(PRIOR, obs_ids=(p_o.observation_id,))]
    current = [
        frec(
            state="unknown_current",
            severity=None,
            last=None,
            obs_ids=(c_o.observation_id,),
        )
    ]
    (out,) = finding_states(prior, sel, current)
    assert (out.state, out.severity, out.last_confirmed_severity) == (
        "unknown_current",
        None,
        "serious",
    )
    assert out.episode_id == episode_id(FID, PRIOR)
    assert [(r.run_id, r.reason, r.severity) for r in out.revisions] == [
        (PRIOR, "detected", "serious"),
        (CUR, "unknown_current", None),
    ]


def test_highest_revision_prior_wins_regardless_of_order() -> None:
    """A later troubleshooting run that revised the finding beats the health run."""
    p_o = prior_obs(**flag(1.0))
    sel = select([], [cand(p_o)], run_id=CUR)
    health = frec(OLDER, obs_ids=(p_o.observation_id,))
    revised = frec(
        PRIOR,
        started=OLDER,
        obs_ids=(p_o.observation_id,),
        revisions=(rev(1, OLDER), rev(2, PRIOR, "investigated")),
        case_ids=(CASE,),
    )
    for prior in ([health, revised], [revised, health]):
        (out,) = finding_states(prior, sel, [])
        assert out.revision == 3
        assert out.case_ids == (CASE,)
        assert [r.reason for r in out.revisions] == [
            "detected",
            "investigated",
            "unknown_current",
        ]


def test_equal_revision_priors_first_given_wins() -> None:
    sel = select([], [], run_id=CUR)
    a = frec(PRIOR, case_ids=(CASE,))
    b = frec(OLDER)
    (out,) = finding_states([a, b], sel, [])
    assert out.case_ids == (CASE,)
    assert out.episode_started_run_id == PRIOR


def test_already_chained_current_is_not_chained_twice() -> None:
    p_o, c_o = prior_obs(**flag(1.0)), obs(**flag(1.0))
    sel = select([c_o], [cand(p_o)])
    held = frec(PRIOR, obs_ids=(p_o.observation_id,))
    current = frec(
        started=PRIOR,
        obs_ids=(c_o.observation_id,),
        revisions=(rev(1, PRIOR), rev(2, CUR, "reassessed")),
    )
    (out,) = finding_states([held], sel, [current])
    assert out.revision == 2
    assert [r.run_id for r in out.revisions] == [PRIOR, CUR]


def test_prior_records_from_the_current_run_are_ignored() -> None:
    same_run = frec(CUR)
    assert finding_states([same_run], select([], [], run_id=CUR), []) == ()


def test_late_upload_of_older_interval_is_not_the_baseline() -> None:
    newer = prior_obs(**flag(1.0))
    older = prior_obs(
        **flag(0.0),
        run_id=OLDER,
        interval_start="2026-08-01",
        interval_end="2026-08-31",
        as_of="2026-09-01T00:00:00+00:00",
    )
    c_o = obs(**flag(1.0))
    sel = select([c_o], [cand(older, rev=99), cand(newer, rev=1)])
    assert only(sel)["comparison"] == "continuing"
    prior = [frec(PRIOR, obs_ids=(newer.observation_id,))]
    (out,) = finding_states(prior, sel, [frec(obs_ids=(c_o.observation_id,))])
    assert out.episode_started_run_id == PRIOR


# ---- reporting-window length (window_mismatch) -----------------------------------------


def _reasons(s: BaselineSelection) -> list[str]:
    return [r["reason"] for r in s.rejected]


def test_seven_day_current_vs_thirty_day_prior_is_not_comparable() -> None:
    current = obs(interval_start="2026-10-25", interval_end="2026-10-31")  # 7 days
    s = select([current], [cand(prior_obs())])  # 30-day prior
    assert only(s)["comparison"] == "not_comparable"
    assert only(s)["baseline_observation_id"] is None
    assert _reasons(s) == ["window_mismatch"]


def test_ninety_day_current_vs_thirty_day_prior_is_not_comparable() -> None:
    current = obs(interval_start="2026-08-03", interval_end="2026-10-31")  # 90 days
    s = select([current], [cand(prior_obs())])
    assert only(s)["comparison"] == "not_comparable"
    assert _reasons(s) == ["window_mismatch"]


def test_flag_across_window_lengths_is_not_new_or_recovered() -> None:
    # A 30-day prior flag must not read as `recovered` on a 7-day run (and vice versa `new`).
    cur = obs(interval_start="2026-10-25", interval_end="2026-10-31", **flag(0.0))
    prior_flag = prior_obs(**flag(1.0))
    assert only(select([cur], [cand(prior_flag)]))["comparison"] == "not_comparable"
    cur_on = obs(interval_start="2026-10-25", interval_end="2026-10-31", **flag(1.0))
    prior_off = prior_obs(**flag(0.0))
    assert only(select([cur_on], [cand(prior_off)]))["comparison"] == "not_comparable"


def test_same_window_with_hours_of_jitter_is_comparable() -> None:
    current = obs(
        interval_start="2026-10-02T03:30:00+00:00",
        interval_end="2026-10-31T05:00:00+00:00",
    )
    prior = prior_obs(
        interval_start="2026-09-01T00:00:00+00:00",
        interval_end="2026-09-30T00:00:00+00:00",
    )
    s = select([current], [cand(prior)])
    assert only(s)["comparison"] == "continuing"
    assert only(s)["baseline_observation_id"] == prior.observation_id
    assert s.rejected == ()


def test_date_only_and_timestamp_ends_of_one_window_are_comparable() -> None:
    prior = prior_obs(
        interval_start="2026-09-01T00:00:00+00:00",
        interval_end="2026-09-30T23:59:59+00:00",
    )
    assert only(select([obs()], [cand(prior)]))["comparison"] == "continuing"


def test_ninety_day_current_picks_the_ninety_day_prior_over_a_newer_thirty() -> None:
    current = obs(interval_start="2026-08-03", interval_end="2026-10-31")  # 90 days
    thirty = prior_obs(
        run_id=OLDER, interval_start="2026-07-02", interval_end="2026-07-31"
    )
    thirty_newer = prior_obs(interval_start="2026-07-03", interval_end="2026-08-01")
    ninety = prior_obs(
        run_id=OLDER,
        interval_start="2026-04-01",
        interval_end="2026-06-29",  # 89 days, older than both 30-day priors
        as_of="2026-07-01T00:00:00+00:00",
    )
    s = select(
        [current], [cand(thirty), cand(thirty_newer), cand(ninety)]
    )
    assert only(s)["comparison"] == "continuing"
    assert only(s)["baseline_observation_id"] == ninety.observation_id
    assert _reasons(s).count("window_mismatch") == 2


def test_key_without_current_uses_the_reporting_interval_length() -> None:
    # reporting_interval is 29 days: the 30-day prior is eligible, the 7-day one is not.
    thirty = prior_obs(**flag(1.0))
    seven = prior_obs(
        run_id=OLDER,
        interval_start="2026-09-24",
        interval_end="2026-09-30",
        **flag(1.0),
    )
    s = select([], [cand(thirty), cand(seven)], run_id=CUR)
    assert only(s)["comparison"] == "missing_current_evidence"
    assert only(s)["baseline_observation_id"] == thirty.observation_id
    assert _reasons(s) == ["window_mismatch"]
    only_seven = select([], [cand(seven)], run_id=CUR)
    assert only_seven.selected == ()
    assert _reasons(only_seven) == ["window_mismatch"]


def test_overlap_adjusted_still_requires_matching_window() -> None:
    current = obs(interval_start="2026-10-25", interval_end="2026-10-31")
    s = select([current], [cand(prior_obs())], overlap_adjusted=True)
    assert only(s)["comparison"] == "not_comparable"


# ---- run-level window comparability --------------------------------------------------


def test_window_days_inclusive_for_dates() -> None:
    assert window_days("2026-09-01", "2026-09-07") == 7
    assert window_days("2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z") == 7


def test_window_comparison_without_prior_is_comparable() -> None:
    w = window_comparison([], INTERVAL)
    assert w == {
        "comparable": True,
        "reason": None,
        "prior_run_id": None,
        "prior_lookback_days": None,
        "current_lookback_days": 30,
        "prior_runs": [],
    }


def test_window_comparison_mismatch_names_the_prior_run() -> None:
    p = prior_obs(interval_start="2026-08-02", interval_end="2026-08-31")
    w = window_comparison([cand(p)], ("2026-10-25", "2026-10-31"))
    assert w["comparable"] is False
    assert w["reason"] == "window_mismatch"
    assert (w["prior_lookback_days"], w["current_lookback_days"]) == (30, 7)
    assert w["prior_runs"] == [
        {
            "run_id": PRIOR,
            "interval": {"start": "2026-08-02", "end": "2026-08-31"},
            "task": None,
            "skipped_reason": None,
        }
    ]


def test_window_comparison_any_same_length_prior_is_comparable() -> None:
    older = prior_obs(
        run_id=OLDER, interval_start="2026-08-25", interval_end="2026-08-31"
    )
    newer = prior_obs(interval_start="2026-09-01", interval_end="2026-09-30")
    w = window_comparison([cand(newer), cand(older)], ("2026-10-25", "2026-10-31"))
    assert w["comparable"] is True and w["reason"] is None
    assert (w["prior_run_id"], w["prior_lookback_days"]) == (OLDER, 7)
    assert [r["run_id"] for r in w["prior_runs"]] == [PRIOR, OLDER]


def test_window_comparison_overlapping_priors_are_not_comparable() -> None:
    # Same 30-day length as the current run, but it ends inside the current window.
    p = prior_obs(interval_start="2026-09-20", interval_end="2026-10-19")
    s = select([obs()], [cand(p)])
    assert only(s)["comparison"] == "not_comparable"
    w = window_comparison([cand(p)], INTERVAL, s)
    assert (w["comparable"], w["reason"]) == (False, "interval_overlap")
    assert window_comparison([cand(p)], INTERVAL)["comparable"] is True


def test_window_comparison_with_one_baseline_is_comparable() -> None:
    p = prior_obs()
    s = select([obs()], [cand(p)])
    w = window_comparison([cand(p)], INTERVAL, s)
    assert (w["comparable"], w["reason"]) == (True, None)


def test_window_comparison_prior_interval_is_the_runs_own_window() -> None:
    # A prior run whose odd observation covers a wider window keeps its own window.
    run_obs = [prior_obs(entity_id=f"j{i}") for i in range(3)]
    wide = prior_obs(entity_id="j9", interval_start="2026-07-01")
    w = window_comparison([cand(o) for o in (*run_obs, wide)], INTERVAL)
    assert w["prior_runs"] == [
        {
            "run_id": PRIOR,
            "interval": {"start": "2026-09-01", "end": "2026-09-30"},
            "task": None,
            "skipped_reason": None,
        }
    ]
    assert w["prior_lookback_days"] == 30


def test_selection_reason_is_the_dominant_rejection() -> None:
    overlap = prior_obs(interval_start="2026-09-20", interval_end="2026-10-19")
    unmeasured = prior_obs(
        entity_id="j2", state="unknown", value=None, unknown_reason="missing_source:q"
    )
    overlap2 = prior_obs(
        entity_id="j3", interval_start="2026-09-20", interval_end="2026-10-19"
    )
    current = [obs(), obs(entity_id="j2"), obs(entity_id="j3")]
    s = select(current, [cand(overlap), cand(unmeasured), cand(overlap2)])
    assert selection_reason(s) == "interval_overlap"


def test_selection_reason_prefers_a_measured_prior_rejection() -> None:
    """Unmeasured families reject on every run; the overlap is the run's reason."""
    overlap = prior_obs(interval_start="2026-09-20", interval_end="2026-10-19")
    unmeasured = [
        prior_obs(entity_id=f"j{n}", state="unknown", value=None,
                  unknown_reason="missing_source:q")
        for n in range(2, 5)
    ]
    current = [obs(), *(obs(entity_id=f"j{n}") for n in range(2, 5))]
    s = select(current, [cand(overlap), *(cand(u) for u in unmeasured)])
    assert selection_reason(s) == "interval_overlap"
    only_unmeasured = select(current[1:], [cand(u) for u in unmeasured])
    assert selection_reason(only_unmeasured) == "prior_not_measured"


def test_selection_reason_without_rejections() -> None:
    assert selection_reason(select([obs()], [])) == "no_prior_measurement"
    assert selection_reason(select([obs()], [cand(prior_obs())])) is None


def test_window_mismatch_reject_names_the_candidate_run() -> None:
    p = prior_obs(interval_start="2026-10-25", interval_end="2026-10-31")
    s = select([obs()], [cand(p)])
    (entry,) = [dict(r) for r in s.rejected]
    assert entry["reason"] == "window_mismatch"
    assert entry["candidate_run_id"] == PRIOR
    assert entry["interval"] == {"start": "2026-10-25", "end": "2026-10-31"}


# ---- run-4 A1 / A3: eligible priors, declared windows, the compared run's reason ----

TROUBLE = "20261020_42345678-1234-4234-8234-123456789abc"


def test_newer_other_task_run_is_never_the_compared_prior() -> None:
    """A newer troubleshooting run (31-day, no manifest) loses to the older health run."""
    health = prior_obs()
    trouble = prior_obs(
        run_id=TROUBLE, entity_kind="case", interval_start="2026-09-13",
        interval_end="2026-10-13", method_version="acquisition_v1",
    )
    w = window_comparison(
        [
            Candidate(health, 1, "reg_h", run_task="health_check", run_manifest=True),
            Candidate(trouble, 1, "reg_t", run_task="troubleshooting", run_manifest=False),
        ],
        INTERVAL,
        task="health_check",
    )
    assert w["prior_run_id"] == PRIOR and w["comparable"] is True
    assert [(r["run_id"], r["task"], r["skipped_reason"]) for r in w["prior_runs"]] == [
        (TROUBLE, "troubleshooting", "other_task"),
        (PRIOR, "health_check", None),
    ]


def test_run_without_a_manifest_is_never_the_compared_prior() -> None:
    w = window_comparison(
        [Candidate(prior_obs(), 1, "reg_p", run_task="health_check", run_manifest=False)],
        INTERVAL,
        task="health_check",
    )
    assert (w["comparable"], w["reason"], w["prior_run_id"]) == (
        False, "no_eligible_prior", None,
    )
    assert w["prior_runs"][0]["skipped_reason"] == "no_findings_manifest"


def test_pinned_prior_waives_task_and_manifest_rules() -> None:
    w = window_comparison(
        [Candidate(prior_obs(), 1, "reg_p", run_task="troubleshooting", run_manifest=False)],
        INTERVAL,
        task="health_check",
        pinned=True,
    )
    assert w["prior_run_id"] == PRIOR and w["prior_runs"][0]["skipped_reason"] is None


def test_unknown_task_or_manifest_stays_eligible() -> None:
    w = window_comparison([cand(prior_obs())], INTERVAL, task="health_check")
    assert w["prior_run_id"] == PRIOR and w["comparable"] is True


def test_same_day_thirty_day_prior_is_interval_overlap_not_window_mismatch() -> None:
    """A same-window prior whose job reliability spans are wider still reads as the
    declared 30-day window, and its reason is interval_overlap (sonnet P04a)."""
    window = {"interval_start": "2026-10-02", "interval_end": "2026-10-31"}
    wide = {"interval_start": "2026-08-31", "interval_end": "2026-10-31",
            "method_version": "job_reliability_v1"}
    current = [obs(entity_id="ws"), *(obs(entity_id=f"j{i}", **wide) for i in range(4))]
    priors = [
        prior_obs(entity_id="ws", **window),
        *(prior_obs(entity_id=f"j{i}", **wide) for i in range(4)),
    ]
    # An older 7-day run whose keys all reject with window_mismatch outnumbers nothing.
    seven = [
        prior_obs(run_id=OLDER, entity_id=f"k{i}", interval_start="2026-09-24",
                  interval_end="2026-09-30")
        for i in range(9)
    ]
    cands = [cand(o) for o in (*priors, *seven)]
    s = select([*current, *(obs(entity_id=f"k{i}") for i in range(9))], cands)
    w = window_comparison(cands, INTERVAL, s)
    assert w["prior_run_id"] == PRIOR
    assert w["prior_runs"][0]["interval"] == {"start": "2026-10-02", "end": "2026-10-31"}
    assert (w["prior_lookback_days"], w["current_lookback_days"]) == (30, 30)
    assert (w["comparable"], w["reason"]) == (False, "interval_overlap")


def test_thirty_one_day_prior_is_the_same_length_as_thirty() -> None:
    p = prior_obs(interval_start="2026-08-31", interval_end="2026-09-30")
    w = window_comparison([cand(p)], INTERVAL)
    assert (w["prior_lookback_days"], w["current_lookback_days"]) == (31, 30)
    assert w["reason"] != "window_mismatch"
    assert same_lookback(31, 30) and same_lookback(30, 30)
    assert not same_lookback(32, 30) and not same_lookback(7, 30)


def test_selection_reason_of_one_run() -> None:
    overlap = prior_obs(interval_start="2026-09-20", interval_end="2026-10-19")
    short = [
        prior_obs(run_id=OLDER, entity_id=f"j{n}", interval_start="2026-09-24",
                  interval_end="2026-09-30")
        for n in range(2, 5)
    ]
    current = [obs(), *(obs(entity_id=f"j{n}") for n in range(2, 5))]
    s = select(current, [cand(overlap), *(cand(o) for o in short)])
    assert selection_reason(s) == "window_mismatch"
    assert selection_reason(s, PRIOR) == "interval_overlap"


def test_candidate_metadata_validation() -> None:
    with pytest.raises(ValueError):
        Candidate(prior_obs(), 1, "reg", run_task="")
    with pytest.raises(ValueError):
        Candidate(prior_obs(), 1, "reg", run_manifest="yes")  # type: ignore[arg-type]
