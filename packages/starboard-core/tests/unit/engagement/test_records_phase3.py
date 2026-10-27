# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the phase-3 engagement records (spec §B, D3-1, D3-14, D3-24)."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.records import (
    ENTITY_KINDS,
    SEVERITIES,
    UNITS,
    Action,
    ActionEvent,
    Case,
    ChangeInput,
    FamilyRead,
    FindingRecord,
    FindingRevision,
    HealthRead,
    Observation,
    Play,
    RunManifest,
    StorageRef,
    action_id,
    case_id,
    change_id,
    concern_key,
    episode_id,
    finding_id,
    observation_id,
    play_id,
)

RID = "20261007_12345678-1234-4234-8234-123456789abc"
RID2 = "20261008_22345678-1234-4234-8234-123456789abc"
OBS = "obs_" + "a" * 24
OBS2 = "obs_" + "c" * 24
EV = "ev_" + "b" * 24
KEY = concern_key("acme", "123", "job", "42", "job_failure_rise")
FID = finding_id(KEY)
QUESTION = "Why did job 42 start failing after 2026-09-23?"
SIX = (
    "consumption_trajectory",
    "efficiency",
    "reliability",
    "adoption_breadth",
    "concentration",
    "governance",
)
CMD = "starboard-helper verify run vt-job-run-states --job-ids 42 --start 2026-09-23 --end 2026-10-07 --limit 20000"


def round_trip(record: Any) -> Any:
    return type(record).from_dict(json.loads(json.dumps(record.to_dict())))


# ---- identity helpers (B1) ---------------------------------------------------


def test_concern_key_format() -> None:
    assert KEY == "ck1|acme|123|job|42|job_failure_rise|-"
    assert (
        concern_key(
            "acme", "123", "job", "42", "job_failure_rise", "sig:oom/outofmemoryerror"
        )
        == "ck1|acme|123|job|42|job_failure_rise|sig:oom/outofmemoryerror"
    )
    assert concern_key("acme", "123", "warehouse", "wh1", "rule:warehouse_queueing")
    assert concern_key("acme", "123", "job", "42", "case:job")
    assert concern_key("acme", "123", "workspace", "123", "ws_job_failure_rise")


@pytest.mark.parametrize("index", range(6))
def test_concern_key_refuses_pipe_in_any_field(index: int) -> None:
    args = ["acme", "123", "job", "42", "job_failure_rise", "-"]
    args[index] = args[index] + "|x"
    with pytest.raises(ValueError, match=r"\|"):
        concern_key(*args)


@pytest.mark.parametrize(
    "args",
    [
        ("acme", "123", "job", RID, "job_failure_rise"),  # run ID as entity
        ("acme", RID, "job", "42", "job_failure_rise"),  # run ID as workspace
        ("acme", "123", "job", "health_check/2026", "job_failure_rise"),  # folder path
        ("acme", "123", "job", "job 42 keeps failing", "job_failure_rise"),  # prose
        ("acme", "123", "job", "", "job_failure_rise"),
        ("acme", "123", "notebook", "42", "job_failure_rise"),  # unknown entity kind
        ("acme", "123", "job", "42", "failure"),  # unknown concern code
        ("acme", "123", "job", "42", "rule:"),
        ("acme", "123", "job", "42", "job_failure_rise", "free text"),
    ],
)
def test_concern_key_refuses_run_ticket_path_and_prose(args: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        concern_key(*args)


def test_id_helpers_stable_and_run_independent() -> None:
    assert FID.startswith("fnd_") and len(FID) == 4 + 24
    assert finding_id(KEY) == FID
    assert (
        finding_id(concern_key("acme", "123", "job", "43", "job_failure_rise")) != FID
    )
    with pytest.raises(ValueError):
        finding_id("W-W01::wh-1")  # a phase-2 key is not a concern key
    ep = episode_id(FID, RID)
    assert ep.startswith("ep_") and len(ep) == 3 + 24
    assert episode_id(FID, RID) == ep
    assert episode_id(FID, RID2) != ep
    with pytest.raises(ValueError):
        episode_id("bad", RID)
    with pytest.raises(ValueError):
        episode_id(FID, "not-a-run")
    pid = play_id("job_reliability_session", FID)
    assert pid.startswith("play_") and pid == play_id("job_reliability_session", FID)
    assert pid != play_id("job_reliability_investigation", FID)
    cid = case_id("acme", FID, RID, QUESTION)
    assert cid.startswith("case_") and cid == case_id("acme", FID, RID, QUESTION)
    assert cid != case_id("acme", FID, RID2, QUESTION)
    assert cid != case_id("acme", FID, RID, "Why did run 9002 fail?")
    with pytest.raises(ValueError):
        case_id("acme", FID, RID, "")
    aid = action_id(FID, "job_reliability_session", RID)
    assert aid.startswith("act_") and aid == action_id(
        FID, "job_reliability_session", RID
    )
    chg = change_id(OBS, OBS2)
    assert chg.startswith("chg_") and chg == change_id(OBS, OBS2)
    assert chg != change_id(OBS2, OBS)
    for value in (ep, pid, cid, aid, chg):
        assert len(value.split("_", 1)[1]) == 24


# ---- FindingRecord / FindingRevision (B2) -----------------------------------


def make_revision(**over: Any) -> FindingRevision:
    base: dict[str, Any] = {
        "revision": 1,
        "run_id": RID,
        "reason": "detected",
        "severity": "serious",
        "symptom_confidence": "confirmed",
        "cause_confidence": "unassessed",
        "observation_ids": (OBS,),
        "evidence_ids": (EV,),
        "case_id": None,
    }
    base.update(over)
    return FindingRevision(**base)


def make_finding(**over: Any) -> FindingRecord:
    base: dict[str, Any] = {
        "finding_id": FID,
        "finding_key": KEY,
        "concern_code": "job_failure_rise",
        "family": "reliability",
        "account_key": "acme",
        "workspace_id": "123",
        "entity_kind": "job",
        "entity_id": "42",
        "episode_id": episode_id(FID, RID),
        "episode_started_run_id": RID,
        "state": "active",
        "severity": "serious",
        "last_confirmed_severity": "serious",
        "symptom_confidence": "confirmed",
        "cause_confidence": "unassessed",
        "rule_id": "reliability_rule_v1",
        "rule_version": 1,
        "revision": 1,
        "revisions": (make_revision(),),
        "observation_ids": (OBS,),
        "evidence_ids": (EV,),
        "possible_links": (),
        "case_ids": (),
        "action_ids": (),
        "run_id": RID,
    }
    base.update(over)
    return FindingRecord(**base)


def test_finding_revision_round_trip_and_validation() -> None:
    r = make_revision(
        case_id=case_id("acme", FID, RID, QUESTION), reason="investigated"
    )
    assert round_trip(r) == r
    assert isinstance(r.observation_ids, tuple)
    with pytest.raises(ValueError):
        make_revision(reason="merged")
    with pytest.raises(ValueError):
        make_revision(revision=0)
    with pytest.raises(ValueError):
        make_revision(severity="high")
    with pytest.raises(ValueError):
        make_revision(symptom_confidence="certain")
    with pytest.raises(ValueError):
        make_revision(cause_confidence="confirmed")  # no confirmed cause in phase 3
    with pytest.raises(ValueError):
        make_revision(run_id="bad")
    assert make_revision(severity=None, reason="unknown_current").severity is None


def test_finding_record_round_trip() -> None:
    second = make_revision(revision=2, run_id=RID2, reason="reassessed")
    f = make_finding(
        revision=2,
        revisions=(make_revision(), second),
        run_id=RID2,
        possible_links=(
            finding_id(concern_key("acme", "123", "job", "42", "case:job")),
        ),
        case_ids=(case_id("acme", FID, RID2, QUESTION),),
        action_ids=(action_id(FID, "job_reliability_session", RID),),
    )
    assert round_trip(f) == f
    data = f.to_dict()
    assert data["revisions"][1]["reason"] == "reassessed"
    assert json.loads(json.dumps(data)) == data
    assert isinstance(f.revisions, tuple)


@pytest.mark.parametrize(
    "over",
    [
        {"finding_id": "fnd_" + "0" * 24},  # does not match the key
        {"finding_key": "W-W01::wh-1"},  # phase-2 key
        {"entity_id": "43"},  # disagrees with the key
        {"workspace_id": "999"},
        {"concern_code": "ws_job_failure_rise"},
        {"family": "other"},  # never other
        {"family": "cost"},
        {"state": "gone"},
        {"severity": "high"},
        {"last_confirmed_severity": "high"},
        {"symptom_confidence": "maybe"},
        {"cause_confidence": "confirmed"},
        {"episode_id": "ep-1"},  # not the episode of (finding_id, started run)
        {"episode_started_run_id": RID2},
        {"revision": 2},  # last revision is 1
        {"revisions": ()},
        {"revisions": (make_revision(revision=2),), "revision": 2},  # not from 1
        {"rule_id": ""},
        {"rule_version": 0},
        {"run_id": "bad"},
        {"state": "active", "severity": None},  # active needs a severity
    ],
)
def test_finding_record_rejects(over: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_finding(**over)


def test_finding_record_unclassified_and_unknown() -> None:
    key = concern_key("acme", "123", "warehouse", "wh1", "rule:my_custom_rule")
    f = make_finding(
        finding_id=finding_id(key),
        finding_key=key,
        concern_code="rule:my_custom_rule",
        family="unclassified",
        entity_kind="warehouse",
        entity_id="wh1",
        episode_id=episode_id(finding_id(key), RID),
        state="unknown_current",
        severity=None,
        revisions=(make_revision(severity=None, reason="unknown_current"),),
    )
    assert round_trip(f) == f


def test_finding_record_from_dict_errors() -> None:
    data = make_finding().to_dict()
    with pytest.raises(ValueError):
        FindingRecord.from_dict(dict(data, schema_version=9))
    with pytest.raises(ValueError, match="credential"):
        FindingRecord.from_dict(dict(data, secret="x"))
    missing = dict(data)
    del missing["concern_code"]
    with pytest.raises(ValueError, match="concern_code"):
        FindingRecord.from_dict(missing)


def test_entity_kinds_and_severities() -> None:
    assert ENTITY_KINDS == (
        "workspace",
        "job",
        "warehouse",
        "pipeline",
        "query",
        "endpoint",
        "table",
        "product",
    )
    assert SEVERITIES == ("none", "watch", "serious", "critical")


# ---- FamilyRead / HealthRead (B3) --------------------------------------------


_EXP: dict[str, Any] = {
    "failed_runs": None,
    "failed_run_dbus": None,
    "exposure_dbus": None,
    "exposure_dbus_per_day": None,
}


def request(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "owner_role": "operator",
        "missing": ("F-06",),
        "command": "starboard --discover --data-only --json",
        "placeholders": (),
    }
    base.update(over)
    return base


def make_family(family: str = "reliability", **over: Any) -> FamilyRead:
    base: dict[str, Any] = {
        "family": family,
        "assessment": "assessed",
        "coverage": "complete",
        "severity": "none",
        "observation_ids": (OBS,),
        "finding_ids": (),
        "change_ids": (),
        "uncertainty": (),
        "unknown_reason": None,
        "acquisition_request": None,
    }
    base.update(over)
    return FamilyRead(**base)


def unknown_family(family: str, **over: Any) -> FamilyRead:
    base: dict[str, Any] = {
        "assessment": "unknown",
        "coverage": "unknown",
        "severity": None,
        "observation_ids": (),
        "unknown_reason": "missing_source:F-06",
        "acquisition_request": request(),
    }
    base.update(over)
    return make_family(family, **base)


def test_family_read_round_trip() -> None:
    fr = make_family(
        severity="serious",
        coverage="partial",
        finding_ids=(FID,),
        change_ids=(change_id(OBS, OBS2),),
        uncertainty=("per_job_cap_25", "verify_limit_reached"),
        acquisition_request=request(missing=("vt-job-run-states",)),
    )
    assert round_trip(fr) == fr
    assert fr.acquisition_request is not None
    assert fr.acquisition_request["missing"] == ("vt-job-run-states",)
    u = unknown_family("governance")
    assert round_trip(u) == u


@pytest.mark.parametrize(
    "over",
    [
        {"severity": None},  # assessed needs a severity
        {
            "assessment": "unknown",
            "coverage": "unknown",
            "severity": "none",
            "unknown_reason": "x",
            "acquisition_request": request(),
        },  # unknown has no severity
        {
            "assessment": "unknown",
            "coverage": "unknown",
            "severity": None,
            "acquisition_request": request(),
        },  # unknown needs unknown_reason
        {
            "assessment": "unknown",
            "coverage": "unknown",
            "severity": None,
            "unknown_reason": "x",
        },  # unknown needs an acquisition_request
        {"coverage": "partial"},  # partial needs an acquisition_request
        {"acquisition_request": request()},  # complete + assessed: no request
        {"unknown_reason": "x"},  # assessed: no unknown_reason
        {"assessment": "assessed", "coverage": "unknown"},
        {
            "assessment": "unknown",
            "coverage": "complete",
            "severity": None,
            "unknown_reason": "x",
            "acquisition_request": request(),
        },
        {"family": "other"},
        {"severity": "high"},
        {"coverage": "partial", "acquisition_request": request(owner_role="job_owner")},
        {
            "coverage": "partial",
            "acquisition_request": request(command="please run discovery"),
        },
        {
            "coverage": "partial",
            "acquisition_request": {"owner_role": "operator", "missing": ()},
        },
        {"coverage": "partial", "acquisition_request": request(extra=1)},
        {"uncertainty": ("Has Spaces",)},
        {"finding_ids": ("W-W01::wh-1",)},
        {"observation_ids": ("x",)},
    ],
)
def test_family_read_invariants(over: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_family(**over)


def make_health(**over: Any) -> HealthRead:
    families = tuple(
        make_family("reliability", severity="serious", finding_ids=(FID,))
        if f == "reliability"
        else unknown_family(f)
        for f in SIX
    )
    base: dict[str, Any] = {
        "run_id": RID,
        "account_key": "acme",
        "workspace_id": "123",
        "reporting_interval_start": "2026-09-23",
        "reporting_interval_end": "2026-10-07",
        "families": families,
        "verdict": "health_read",
        "assessed_count": 1,
        "top_concern_finding_ids": (FID,),
        "material_unknowns": tuple(f for f in SIX if f != "reliability"),
    }
    base.update(over)
    return HealthRead(**base)


def test_health_read_round_trip_and_order() -> None:
    h = make_health()
    assert h.method_version == "health_read_v1"
    assert tuple(f.family for f in h.families) == SIX
    assert h.unclassified is None
    assert round_trip(h) == h


def test_health_read_requires_exactly_six_families_in_order() -> None:
    h = make_health()
    with pytest.raises(ValueError):
        make_health(families=h.families[:5])
    with pytest.raises(ValueError):
        make_health(families=tuple(reversed(h.families)))
    with pytest.raises(ValueError):
        make_health(families=(*h.families[:5], unknown_family("other")))
    with pytest.raises(ValueError):
        make_health(families=(*h.families, unknown_family("governance")))


def test_health_read_verdict_and_counts() -> None:
    all_unknown = tuple(unknown_family(f) for f in SIX)
    h = make_health(
        families=all_unknown,
        verdict="insufficient_evidence",
        assessed_count=0,
        top_concern_finding_ids=(),
        material_unknowns=SIX,
    )
    assert round_trip(h) == h
    assert sum(f.acquisition_request is not None for f in h.families) == 6
    with pytest.raises(ValueError):
        replace(h, verdict="health_read")
    with pytest.raises(ValueError):
        make_health(verdict="insufficient_evidence")
    with pytest.raises(ValueError):
        make_health(assessed_count=2)
    with pytest.raises(ValueError):
        make_health(material_unknowns=("governance",))
    with pytest.raises(ValueError):
        make_health(verdict="healthy")
    with pytest.raises(ValueError):
        make_health(method_version="health_read_v2")
    with pytest.raises(ValueError):
        make_health(reporting_interval_start="2026-10-08")


def test_health_read_unclassified_is_unknown_and_uncounted() -> None:
    unc = make_family(
        "unclassified",
        assessment="unknown",
        coverage="unknown",
        severity=None,
        finding_ids=(FID,),
        observation_ids=(),
        unknown_reason="rule_family_unclassified",
    )
    h = make_health(unclassified=unc)
    assert h.assessed_count == 1
    assert "unclassified" not in h.material_unknowns
    assert round_trip(h) == h
    with pytest.raises(ValueError):
        make_health(unclassified=replace(unc, unknown_reason="missing_source:x"))
    with pytest.raises(ValueError):
        make_health(unclassified=make_family("reliability"))
    with pytest.raises(ValueError):
        make_health(
            unclassified=make_family(
                "unclassified", severity="watch", finding_ids=(FID,)
            )
        )


# ---- Play (B4) ---------------------------------------------------------------


def make_play(**over: Any) -> Play:
    base: dict[str, Any] = {
        "play_id": play_id("job_reliability_session", FID),
        "play_code": "job_reliability_session",
        "finding_ids": (FID,),
        "interaction_type": "working_session",
        "owner_role": "job_owner",
        "audience_class": "customer_shareable",
        "target_entity_kind": "job",
        "target_entity_id": "42",
        "reason": "job 42 failure rate 1.0% → 8.0% (+7.0 pp), 100 runs, windows "
        "2026-09-08..2026-09-22 + 2026-09-23..2026-10-07",
        "urgency": "high",
        "exposure": {
            "failed_runs": 8,
            "failed_run_dbus": 12.5,
            "exposure_dbus": 12.5,
            "exposure_dbus_per_day": None,
        },
        "evidence_strength": "strong",
        "missing_evidence": (),
        "next_step_kind": "act",
        "next_commands": (CMD, "starboard-helper job runs --job-id 42 --limit 25"),
        "follow_up_check": {
            "template": "vt-job-runs",
            "params": {"job_ids": "42", "limit": 20000},
            "success_criterion": "rate <= baseline + 2.0 pp over >= 50 runs",
        },
        "run_id": RID,
    }
    base.update(over)
    return Play(**base)


def test_play_round_trip_and_defaults() -> None:
    p = make_play()
    assert p.rule_id == "play_rules_v1"
    assert p.criticality == "unknown"
    assert p.reversibility == "unknown" and p.owner_availability == "unknown"
    assert p.host_rank is None and p.host_reorder_reason is None
    assert round_trip(p) == p
    ranked = make_play(
        host_rank=1,
        host_reorder_reason="owner is available this week",
        owner_label="data-platform team",
        criticality="high",
    )
    assert round_trip(ranked) == ranked
    acq = make_play(
        play_id=play_id("acquire_family_evidence", "governance"),
        play_code="acquire_family_evidence",
        finding_ids=(),
        interaction_type="acquisition",
        owner_role="operator",
        target_entity_kind="workspace",
        target_entity_id="123",
        reason="governance unknown: missing_source:PO-01",
        urgency="low",
        exposure={
            "failed_runs": None,
            "failed_run_dbus": None,
            "exposure_dbus": None,
            "exposure_dbus_per_day": None,
        },
        evidence_strength="weak",
        next_step_kind="acquire",
        next_commands=("starboard --discover --data-only --json",),
        follow_up_check=None,
    )
    assert round_trip(acq) == acq


@pytest.mark.parametrize(
    "over",
    [
        {"host_rank": 1},  # rank needs a reason
        {"host_reorder_reason": "because"},  # reason without a rank
        {"host_rank": 0, "host_reorder_reason": "x"},
        {"host_rank": 1, "host_reorder_reason": "ask jane.doe@example.com"},
        {"owner_label": "jane.doe@example.com"},
        {"finding_ids": ()},  # only acquisition plays may cite no finding
        {"finding_ids": ("bad",)},
        {"play_code": "do_something"},
        {"play_id": "play-1"},
        {"interaction_type": "meeting"},
        {"owner_role": "ceo"},
        {"urgency": "urgent"},
        {"criticality": "extreme"},
        {"evidence_strength": "very_strong"},
        {"next_step_kind": "wait"},
        {"rule_id": "play_rules_v2"},
        {"reason": ""},
        {"exposure": {"failed_runs": 8}},
        {"exposure": {"failed_runs": 8, "failed_run_dbus": None}},  # no exposure_dbus
        # no exposure_dbus_per_day
        {"exposure": {"failed_runs": 8, "failed_run_dbus": None, "exposure_dbus": None}},
        {"exposure": {**_EXP, "failed_runs": -1}},
        {"exposure": {**_EXP, "failed_runs": 1.5}},
        {"exposure": {**_EXP, "exposure_dbus": -1.0}},
        {"exposure": {**_EXP, "exposure_dbus_per_day": -1.0}},
        # failed_run_dbus without failed_runs (B4)
        {"exposure": {**_EXP, "failed_run_dbus": 786.24}},
        # a window total and a run-rate together (B8)
        {"exposure": {**_EXP, "exposure_dbus": 1.0, "exposure_dbus_per_day": 1.0}},
        # a placeholder the commands do not print / an unsupported placeholder
        {"placeholders": ("warehouse_id",)},
        {"next_commands": ("starboard-helper job fetch --job-id <job_id>",)},
        {"next_commands": ("rm -rf /",)},
        {
            "next_commands": (
                "starboard-helper verify run vt-job-runs --job-ids 42 --start a --end b",
            )
        },
        {"follow_up_check": {"template": "vt-job-runs"}},
        {"audience_class": "public"},
        {"target_entity_kind": "notebook"},
        {"run_id": "bad"},
    ],
)
def test_play_rejects(over: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_play(**over)


# ---- ChangeInput (B5) --------------------------------------------------------


def make_change(**over: Any) -> ChangeInput:
    base: dict[str, Any] = {
        "change_id": change_id(OBS, OBS2),
        "observation_id": OBS,
        "baseline_observation_id": OBS2,
        "family": "reliability",
        "metric": "job_failure_rate_pct",
        "unit": "pct",
        "entity_kind": "job",
        "entity_id": "42",
        "baseline_value": 1.0,
        "baseline_interval_start": "2026-09-08",
        "baseline_interval_end": "2026-09-22",
        "current_value": 8.0,
        "current_interval_start": "2026-09-23",
        "current_interval_end": "2026-10-07",
        "delta": 7.0,
        "delta_unit": "pp",
        "relative_pct": 700.0,
        "comparison": "continuing",
        "co_movements": (
            {
                "observation_id": "obs_" + "d" * 24,
                "metric": "job_runs",
                "delta": 0.0,
                "unit": "count",
            },
        ),
        "context_events": (
            {
                "kind": "config_change",
                "ref": "job:42",
                "at": "2026-09-25T00:00:00+00:00",
            },
        ),
        "source_windows": (
            ("2026-09-23", "2026-09-30", "customer_workspace"),
            ("2026-10-01", "2026-10-07", "internal_mirror"),
        ),
        "evidence_ids": (EV,),
    }
    base.update(over)
    return ChangeInput(**base)


def test_change_input_round_trip_and_constants() -> None:
    c = make_change()
    assert c.method_version == "change_inputs_v1"
    assert c.causality == "not_assessed"
    assert round_trip(c) == c
    assert c.source_windows[1] == ("2026-10-01", "2026-10-07", "internal_mirror")
    dbu = make_change(
        metric="total_dbus",
        unit="DBU",
        delta_unit="DBU",
        relative_pct=None,
        family="consumption_trajectory",
        entity_kind="workspace",
        entity_id="123",
        comparison="new",
    )
    assert round_trip(dbu) == dbu


def test_change_input_causality_cannot_be_set() -> None:
    with pytest.raises(ValueError):
        make_change(causality="caused_by_action")
    data = make_change().to_dict()
    with pytest.raises(ValueError):
        ChangeInput.from_dict(dict(data, causality="consistent"))


@pytest.mark.parametrize(
    "over",
    [
        {"change_id": change_id(OBS2, OBS)},
        {"delta_unit": "pct"},  # pct metrics move in pp
        {"unit": "USD", "delta_unit": "USD"},
        {"unit": "DBU", "delta_unit": "pp"},
        {"comparison": "missing_current_evidence"},  # D3-11: only selected pairs
        {"comparison": "no_prior_measurement"},
        {"family": "other"},
        {"context_events": ({"kind": "rumour", "ref": "x", "at": "2026-09-25"},)},
        {"context_events": ({"kind": "config_change", "ref": "x"},)},
        {"co_movements": ({"metric": "job_runs", "unit": "USD", "delta": 1.0},)},
        {"source_windows": (("2026-09-23", "2026-09-30"),)},
        {"source_windows": (("2026-09-23", "2026-09-30", "rumour"),)},
        {"method_version": "change_inputs_v2"},
        {"current_interval_start": "nope"},
    ],
)
def test_change_input_rejects(over: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_change(**over)


# ---- Case (B6) ---------------------------------------------------------------


def make_case(**over: Any) -> Case:
    base: dict[str, Any] = {
        "account_key": "acme",
        "workspace_id": "123",
        "origin": "finding",
        "origin_ref": FID,
        "finding_id": FID,
        "target_entity_kind": "job",
        "target_entity_id": "42",
        "question": QUESTION,
        "hypotheses": (
            {
                "hypothesis_id": "h1",
                "statement": "a library upgrade broke the job",
                "status": "untested",
                "evidence_ids": (),
            },
        ),
        "evidence_revisions": (
            {
                "revision": 1,
                "run_id": RID,
                "evidence_ids": (EV,),
                "observation_ids": (OBS,),
                "gaps": ("job_run_output",),
            },
        ),
        "state": "open",
        "opened_run_id": RID,
        "run_id": RID,
    }
    base.update(over)
    base.setdefault(
        "case_id",
        case_id(
            base["account_key"],
            base["origin_ref"],
            base["opened_run_id"],
            base["question"],
        ),
    )
    return Case(**base)


def test_case_round_trip() -> None:
    c = make_case()
    assert round_trip(c) == c
    assert c.hypotheses[0]["status"] == "untested"
    clue = make_case(origin="clue", origin_ref="job:42")
    assert round_trip(clue) == clue
    drive = make_case(
        origin="drive_object",
        origin_ref="drive:1AbC_x-9",
    )
    assert round_trip(drive) == drive


@pytest.mark.parametrize(
    "over",
    [
        {"case_id": case_id("acme", FID, RID2, QUESTION)},
        {"case_id": case_id("acme", FID, RID, "another question")},
        {"origin": "ticket"},
        {"origin": "clue"},  # a finding id is not a clue
        {"origin_ref": "job:42"},  # origin finding needs a finding id
        {"finding_id": "W-W01::wh-1"},
        {"question": ""},
        {"question": "x" * 501},
        {"state": "resolved"},
        {
            "hypotheses": (
                {
                    "hypothesis_id": "h1",
                    "statement": "s",
                    "status": "maybe",
                    "evidence_ids": (),
                },
            )
        },
        {"hypotheses": ({"hypothesis_id": "h1", "statement": "s"},)},
        {
            "evidence_revisions": (
                {
                    "revision": 2,
                    "run_id": RID,
                    "evidence_ids": (),
                    "observation_ids": (),
                    "gaps": (),
                },
            )
        },
        {"opened_run_id": "bad"},
    ],
)
def test_case_rejects(over: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_case(**over)


def test_case_clue_formats() -> None:
    for ref in ("job:42", "query:01ef-abc", "run:991"):
        make_case(origin="clue", origin_ref=ref)
    for ref in ("job:", "cluster:1", "job 42"):
        with pytest.raises(ValueError):
            make_case(origin="clue", origin_ref=ref)


# ---- host free text: email and credential rejection (D3-24) -----------------

EMAILS = [
    "contact jane.doe@example.com today",
    "JANE@EXAMPLE.CO.UK",
    "<ops+alerts@corp.example.io>",
    "mailto:someone@example.org",
    "jane＠example.com",  # full-width at sign
    "jane%40example.com",  # percent-encoded
    "jane&#64;example.com",  # HTML entity
    "jane [at] example [dot] com",
    "jane(at)example.com",
    "jane at example dot com",
    "jane.doe @ example.com",
]
CREDENTIALS = [
    "use dapi" + "0123456789abcdef" * 2,
    "password=hunter2",
    "token: abc123def",
    "Authorization: Bearer abc.def.ghi",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
    "AKIAABCDEFGHIJKLMNOP",
    "-----BEGIN RSA PRIVATE KEY-----",
    "ghp_" + "a" * 36,
    "xoxb-1234-5678-abcdef",
    "client_secret = s3cr3t",
]
CLEAN = [
    "job 42 @ 10:00 keeps failing",
    "is the @retry decorator involved?",
    "failure rate 1.0% → 8.0% (+7.0 pp)",
    "max_tokens and secretary are fine words",
    "see table main.sales.orders",
    "Why did job 42 start failing after 2026-09-23?",
]


@pytest.mark.parametrize("text", EMAILS)
def test_host_free_text_rejects_emails(text: str) -> None:
    with pytest.raises(ValueError, match="email"):
        make_case(question=text)
    with pytest.raises(ValueError, match="email"):
        make_play(host_rank=1, host_reorder_reason=text)


@pytest.mark.parametrize("text", CREDENTIALS)
def test_host_free_text_rejects_credentials(text: str) -> None:
    with pytest.raises(ValueError, match="credential"):
        make_case(question=text)


@pytest.mark.parametrize("text", CLEAN)
def test_host_free_text_allows_clean_text(text: str) -> None:
    assert make_case(question=text).question == text


def test_every_host_free_text_field_rejects_emails() -> None:
    bad = "ping jane.doe@example.com"
    with pytest.raises(ValueError, match="email"):
        make_case(
            hypotheses=(
                {
                    "hypothesis_id": "h1",
                    "statement": bad,
                    "status": "untested",
                    "evidence_ids": (),
                },
            )
        )
    with pytest.raises(ValueError, match="email"):
        make_play(owner_label=bad)
    with pytest.raises(ValueError, match="email"):
        make_play(reason=bad)
    with pytest.raises(ValueError, match="email"):
        make_action(next_step=bad)
    with pytest.raises(ValueError, match="email"):
        make_action(owner_label=bad)
    with pytest.raises(ValueError, match="email"):
        make_event(note=bad)
    with pytest.raises(ValueError, match="email"):
        Case.from_dict(dict(make_case().to_dict(), question=bad))


# ---- Action / ActionEvent (B7) ----------------------------------------------

AID = action_id(FID, "job_reliability_session", RID)
PID = play_id("job_reliability_session", FID)


def make_event(**over: Any) -> ActionEvent:
    base: dict[str, Any] = {
        "seq": 1,
        "kind": "proposed",
        "run_id": RID,
        "at": "2026-10-08T09:00:00+00:00",
        "recorded_by": "rule",
        "evidence_ids": (),
        "note": None,
    }
    base.update(over)
    return ActionEvent(**base)


def make_action(**over: Any) -> Action:
    base: dict[str, Any] = {
        "action_id": AID,
        "finding_id": FID,
        "play_id": PID,
        "case_id": None,
        "owner_role": "job_owner",
        "owner_label": None,
        "next_step": "Review the failing task with the job owner.",
        "proposal_state": "proposed",
        "acceptance_state": "pending",
        "execution_state": "not_started",
        "executed_at": None,
        "verification_window_start": None,
        "verification_window_end": None,
        "outcome_state": "not_observed",
        "outcome_observation_ids": (),
        "attribution": "not_established",
        "events": (make_event(),),
        "run_id": RID,
    }
    base.update(over)
    return Action(**base)


def test_action_event_round_trip_and_validation() -> None:
    e = make_event(
        seq=2,
        kind="accepted",
        recorded_by="host",
        note="agreed in the session",
        evidence_ids=(EV,),
    )
    assert round_trip(e) == e
    for over in (
        {"seq": 0},
        {"kind": "caused"},
        {"recorded_by": "llm"},
        {"at": "yesterday"},
        {"run_id": "bad"},
        {"note": "x" * 501},
    ):
        with pytest.raises(ValueError):
            make_event(**over)


def test_action_round_trip() -> None:
    a = make_action()
    assert round_trip(a) == a
    done = make_action(
        play_id=None,
        case_id=case_id("acme", FID, RID, QUESTION),
        verify_method="vt-job-run-states failure rate over the next 14 days",
        acceptance_state="accepted",
        execution_state="executed",
        executed_at="2026-10-09",
        verification_window_start="2026-10-10",
        verification_window_end="2026-10-24",
        outcome_state="improved",
        outcome_observation_ids=(OBS2,),
        attribution="consistent_with_action",
        events=(
            make_event(),
            make_event(seq=2, kind="accepted", recorded_by="host"),
            make_event(seq=3, kind="executed", recorded_by="operator"),
            make_event(seq=4, kind="outcome_observed", run_id=RID2),
        ),
        run_id=RID2,
    )
    assert round_trip(done) == done


@pytest.mark.parametrize(
    "over",
    [
        # an action originates from exactly one of a play or a case
        {"case_id": case_id("acme", FID, RID, QUESTION)},
        {"play_id": None},
        # executed requires accepted (D3-13)
        {"execution_state": "executed", "executed_at": "2026-10-09"},
        {
            "acceptance_state": "rejected",
            "execution_state": "executed",
            "executed_at": "2026-10-09",
        },
        # attribution needs executed + executed_at < window start + improved
        {"attribution": "consistent_with_action"},
        {
            "acceptance_state": "accepted",
            "execution_state": "executed",
            "executed_at": "2026-10-12",
            "verification_window_start": "2026-10-10",
            "outcome_state": "improved",
            "attribution": "consistent_with_action",
        },
        {
            "acceptance_state": "accepted",
            "execution_state": "executed",
            "executed_at": "2026-10-09",
            "verification_window_start": "2026-10-10",
            "outcome_state": "unknown",
            "attribution": "consistent_with_action",
        },
        {"executed_at": "2026-10-09"},  # executed_at without execution
        {"proposal_state": "open"},
        {"acceptance_state": "maybe"},
        {"execution_state": "done"},
        {"outcome_state": "caused"},
        {"attribution": "caused"},
        {"events": ()},
        {"events": (make_event(seq=2),)},
        {"events": (make_event(kind="accepted"),)},
        {"events": (make_event(), make_event(seq=3, kind="accepted"))},
        {"next_step": ""},
        {"next_step": "x" * 501},
        {"owner_role": "ceo"},
        {"action_id": "act-1"},
        {"finding_id": "x"},
        {
            "verification_window_start": "2026-10-24",
            "verification_window_end": "2026-10-10",
        },
    ],
)
def test_action_rejects(over: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_action(**over)


def test_no_state_named_caused() -> None:
    a = make_action()
    assert "caused" not in json.dumps(a.to_dict())


# ---- RunManifest D3-1 refs ---------------------------------------------------

_STATES = {
    "capture": "complete",
    "analysis": "complete",
    "check": "pending",
    "publication": "pending",
}
_D31 = ("health_ref", "plays_ref", "changes_ref", "cases_ref", "actions_ref")


def ref(path: str, object_id: str) -> StorageRef:
    return StorageRef(
        path=path,
        object_id=object_id,
        revision="r1",
        md5="0" * 32,
        size=10,
        mime_type="application/json",
    )


def make_manifest(**over: Any) -> RunManifest:
    base: dict[str, Any] = {
        "engagement_id": "eng-acme-2026",
        "run_id": RID,
        "revision": 1,
        "previous_object_id": None,
        "task": "health_check",
        "task_name": "ws-123",
        "source_mode": SourceMode.CUSTOMER_WORKSPACE,
        "storage_policy": StoragePolicy.DRIVE_REQUIRED,
        "descriptor_ref": ref("run-authorization.json", "desc-1"),
        "refs": (ref("analysis/report.json", "obj-1"),),
        "states": _STATES,
        "committed_at": "2026-10-08T09:30:00+00:00",
    }
    base.update(over)
    return RunManifest(**base)


def test_manifest_d31_refs_default_none() -> None:
    m = make_manifest()
    for name in _D31:
        assert getattr(m, name) is None
        assert m.to_dict()[name] is None
    assert RunManifest.from_dict(json.loads(json.dumps(m.to_dict()))) == m


def test_manifest_d31_refs_round_trip_as_storage_ref() -> None:
    paths = {
        "health_ref": "analysis/health.json",
        "plays_ref": "analysis/plays.json",
        "changes_ref": "analysis/changes.json",
        "cases_ref": "analysis/cases.json",
        "actions_ref": "analysis/actions.json",
    }
    m = make_manifest(**{n: ref(p, f"o-{n}") for n, p in paths.items()})
    back = RunManifest.from_dict(json.loads(json.dumps(m.to_dict())))
    assert back == m
    for name, path in paths.items():
        value = getattr(back, name)
        assert isinstance(value, StorageRef)
        assert value.path == path


@pytest.mark.parametrize("name", _D31)
def test_manifest_d31_refs_must_be_storage_refs(name: str) -> None:
    with pytest.raises(TypeError):
        make_manifest(**{name: {"path": "analysis/health.json"}})
    with pytest.raises(TypeError):
        make_manifest(**{name: "obj-1"})


# ---- Units (D3-14) -------------------------------------------------------------


def make_obs(**over: Any) -> Observation:
    base: dict[str, Any] = {
        "run_id": RID,
        "account_key": "acme",
        "workspace_id": "123",
        "family": "reliability",
        "entity_kind": "job",
        "entity_id": "42",
        "metric": "job_runs",
        "value": 100.0,
        "unit": "count",
        "grain": "interval",
        "method_version": "job_reliability_v1",
        "interval_start": "2026-09-23",
        "interval_end": "2026-10-07",
        "as_of": "2026-10-08T00:00:00+00:00",
        "coverage": "complete",
        "coverage_fraction": None,
        "state": "measured",
        "unknown_reason": None,
        "evidence_ids": (),
        "source_kind": "customer_workspace",
        "audience_class": "customer_shareable",
    }
    base.update(over)
    probe = {
        k: base[k]
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
    }
    base["observation_id"] = observation_id(tuple(probe.values()))
    return Observation(**base)


def test_units_vocabulary() -> None:
    assert UNITS == (
        "DBU",
        "DSU",
        "DBU/day",
        "count",
        "pct",
        "pp",
        "flag",
        "ratio",
        "s",
        "ms",
        "bytes",
    )


@pytest.mark.parametrize("unit", UNITS)
def test_observation_accepts_every_unit(unit: str) -> None:
    assert make_obs(unit=unit).unit == unit


@pytest.mark.parametrize("unit", ["product", "USD", "$", "dbu", "percent", ""])
def test_observation_rejects_free_form_unit(unit: str) -> None:
    with pytest.raises(ValueError):
        make_obs(unit=unit)


def test_observation_accepts_unclassified_family() -> None:
    # A finding of an untagged rule maps to ``unclassified`` (D3-17).
    assert (
        make_obs(
            family="unclassified", metric="finding_present", unit="flag", value=1.0
        ).family
        == "unclassified"
    )
