# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for case open / revise (WP3-7, D3-5, D3-12)."""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.cases import CASE_RULE_ID, open_case, revise
from starboard_core.engagement.health import health_eligible, project
from starboard_core.engagement.plays import candidates
from starboard_core.engagement.records import Case, case_id, concern_key, finding_id

from .test_concerns import (
    CUR,
    EV,
    EV2,
    INTERVAL,
    PRIOR,
    job_triplet,
    obs,
    prior,
    run,
    selection_for,
)

pytestmark = pytest.mark.unit

TROUBLE = "20261009_42345678-1234-4234-8234-123456789abc"


def j42() -> Any:
    """The J-42 finding of a prior health-check run."""
    (finding,) = run(job_triplet(100, 8, 8.0, maker=prior), [], run_id=PRIOR).findings
    return finding


def acquired(**over: Any) -> Any:
    return obs(run_id=TROUBLE, method_version="acquisition_v1", **over)


def from_finding(finding: Any, run_id: str = TROUBLE) -> Case:
    case, created = open_case(
        account_key="acme",
        workspace_id="123",
        origin="finding",
        origin_ref=finding.finding_id,
        question="why did job 42 start failing?",
        run_id=run_id,
        finding=finding,
    )
    assert created is None
    return case


def test_open_from_finding_targets_its_entity() -> None:
    finding = j42()
    case = from_finding(finding)
    assert case.case_id == case_id(
        "acme", finding.finding_id, TROUBLE, "why did job 42 start failing?"
    )
    assert (case.finding_id, case.target_entity_kind, case.target_entity_id) == (
        finding.finding_id,
        "job",
        "42",
    )
    assert (case.state, case.hypotheses, case.evidence_revisions) == ("open", (), ())
    assert case.opened_run_id == case.run_id == TROUBLE


def test_open_from_finding_requires_matching_finding() -> None:
    with pytest.raises(ValueError, match="finding"):
        open_case(
            account_key="acme",
            workspace_id="123",
            origin="finding",
            origin_ref=j42().finding_id,
            question="q",
            run_id=TROUBLE,
        )


def test_revise_keeps_finding_and_episode_with_investigated_revision() -> None:
    finding = j42()
    case = from_finding(finding)
    evidence = [acquired(metric="job_failure_rate_pct", unit="pct", value=8.0)]
    new_case, revised = revise(
        case,
        finding,
        run_id=TROUBLE,
        observations=evidence,
        evidence_ids=(EV,),
        gaps=("job_run_output",),
    )
    assert (revised.finding_id, revised.episode_id) == (
        finding.finding_id,
        finding.episode_id,
    )
    assert revised.revision == 2 and revised.run_id == TROUBLE
    last = revised.revisions[-1]
    assert (last.reason, last.case_id, last.run_id) == (
        "investigated",
        case.case_id,
        TROUBLE,
    )
    assert last.observation_ids == (evidence[0].observation_id,)
    assert revised.cause_confidence == "unassessed" == last.cause_confidence
    assert revised.state == finding.state and revised.severity == finding.severity
    assert case.case_id in revised.case_ids
    (rev,) = new_case.evidence_revisions
    assert dict(rev) == {
        "revision": 1,
        "run_id": TROUBLE,
        "evidence_ids": (EV,),
        "observation_ids": (evidence[0].observation_id,),
        "gaps": ("job_run_output",),
    }
    assert new_case.hypotheses == () and new_case.run_id == TROUBLE


def test_second_revise_numbers_revisions_consecutively() -> None:
    finding = j42()
    case, revised = revise(
        from_finding(finding),
        finding,
        run_id=TROUBLE,
        observations=(),
        evidence_ids=(),
        gaps=("job_run_output",),
    )
    case, revised = revise(
        case, revised, run_id=CUR, observations=(), evidence_ids=(EV2,), gaps=()
    )
    assert [r["revision"] for r in case.evidence_revisions] == [1, 2]
    assert revised.revision == 3 and revised.revisions[-1].reason == "investigated"
    assert revised.case_ids == (case.case_id,)


def _hyp(status: str, evidence: tuple[str, ...] = (EV,)) -> dict[str, Any]:
    return {
        "hypothesis_id": "h1",
        "statement": "upstream schema change",
        "status": status,
        "evidence_ids": evidence,
    }


def test_supported_needs_evidence_and_supported_hypothesis() -> None:
    finding = j42()
    case = from_finding(finding)
    common: dict[str, Any] = {
        "run_id": TROUBLE,
        "observations": (),
        "evidence_ids": (EV,),
        "gaps": (),
    }
    with pytest.raises(ValueError, match="supported"):
        revise(case, finding, cause_confidence="supported", **common)
    with pytest.raises(ValueError, match="supported"):
        revise(
            case,
            finding,
            hypothesis=_hyp("untested"),
            cause_confidence="supported",
            **common,
        )
    with pytest.raises(ValueError, match="supported"):
        revise(
            case,
            finding,
            hypothesis=_hyp("supported", ()),
            cause_confidence="supported",
            **common,
        )
    new_case, revised = revise(
        case,
        finding,
        hypothesis=_hyp("supported"),
        cause_confidence="supported",
        **common,
    )
    assert revised.cause_confidence == "supported"
    assert revised.revisions[-1].cause_confidence == "supported"
    assert [h["status"] for h in new_case.hypotheses] == ["supported"]


def test_hypothesis_upserts_by_id_and_cause_is_kept_when_unset() -> None:
    finding = j42()
    case, revised = revise(
        from_finding(finding),
        finding,
        run_id=TROUBLE,
        observations=(),
        evidence_ids=(),
        gaps=(),
        hypothesis=_hyp("untested"),
        cause_confidence="hypothesis",
    )
    case, revised = revise(
        case,
        revised,
        run_id=TROUBLE,
        observations=(),
        evidence_ids=(),
        gaps=(),
        hypothesis=_hyp("refuted"),
    )
    assert [h["status"] for h in case.hypotheses] == ["refuted"]
    assert revised.cause_confidence == "hypothesis"


def test_standalone_clue_creates_case_job_finding() -> None:
    case, created = open_case(
        account_key="acme",
        workspace_id="123",
        origin="clue",
        origin_ref="job:77",
        question="nightly load fails",
        run_id=TROUBLE,
        error_signature="driver/outofmemoryerror",
    )
    assert created is not None
    key = concern_key(
        "acme", "123", "job", "77", "case:job", "sig:driver/outofmemoryerror"
    )
    assert (created.finding_key, created.finding_id) == (key, finding_id(key))
    assert created.concern_code == "case:job" and created.family == "unclassified"
    assert (created.state, created.severity, created.symptom_confidence) == (
        "watch",
        "watch",
        "unverified",
    )
    assert (created.cause_confidence, created.rule_id) == ("unassessed", CASE_RULE_ID)
    assert created.case_ids == (case.case_id,)
    assert created.revisions[0].case_id == case.case_id
    assert case.finding_id == created.finding_id
    assert (case.target_entity_kind, case.target_entity_id) == ("job", "77")


@pytest.mark.parametrize("kind", ["query", "pipeline"])
def test_query_and_pipeline_clues_name_their_entity(kind: str) -> None:
    ref = "01ef-abc.2" if kind == "query" else "a1b2c3d4-5678-90ab-cdef-1234567890ab"
    case, created = open_case(
        account_key="acme",
        workspace_id="123",
        origin="clue",
        origin_ref=f"{kind}:{ref}",
        question="this keeps failing",
        run_id=TROUBLE,
    )
    assert created is not None and created.concern_code == f"case:{kind}"
    # The entity a health finding on the same query / pipeline carries.
    assert (created.entity_kind, created.entity_id) == (kind, ref)
    assert (case.target_entity_kind, case.target_entity_id) == (kind, ref)
    assert case.origin_ref == f"{kind}:{ref}"


@pytest.mark.parametrize("ref", ["cluster:0612", "pipeline:", "pipelines:p1", "pipeline:-x"])
def test_unknown_or_malformed_clues_are_rejected(ref: str) -> None:
    with pytest.raises(ValueError, match="clue|origin_ref"):
        open_case(
            account_key="acme",
            workspace_id="123",
            origin="clue",
            origin_ref=ref,
            question="?",
            run_id=TROUBLE,
        )


def test_run_clue_and_drive_object_need_or_default_an_entity() -> None:
    case, created = open_case(
        account_key="acme",
        workspace_id="123",
        origin="clue",
        origin_ref="run:555",
        question="run 555 failed",
        run_id=TROUBLE,
        finding_entity=("job", "42"),
    )
    assert created is not None and created.concern_code == "case:run"
    assert (created.entity_kind, created.entity_id) == ("job", "42")
    assert (case.target_entity_kind, case.target_entity_id) == ("run", "555")
    case, created = open_case(
        account_key="acme",
        workspace_id="123",
        origin="drive_object",
        origin_ref="drive:abc_123",
        question="see attached profile",
        run_id=TROUBLE,
    )
    assert created is not None and created.concern_code == "case:drive_object"
    assert (created.entity_kind, created.entity_id) == ("workspace", "123")
    assert (case.target_entity_kind, case.target_entity_id) == (
        "drive_object",
        "abc_123",
    )


def test_gaps_are_recorded_and_codes_validated() -> None:
    finding = j42()
    case, _ = revise(
        from_finding(finding),
        finding,
        run_id=TROUBLE,
        observations=(),
        evidence_ids=(),
        gaps=("job_run_output", "spark_event_log"),
    )
    assert case.evidence_revisions[-1]["gaps"] == ("job_run_output", "spark_event_log")
    with pytest.raises(ValueError):
        revise(
            case,
            finding,
            run_id=TROUBLE,
            observations=(),
            evidence_ids=(),
            gaps=("not a code",),
        )


def test_case_observations_must_be_acquisitions_and_are_not_baselines() -> None:
    finding = j42()
    case = from_finding(finding)
    with pytest.raises(ValueError, match="acquisition_v1"):
        revise(
            case,
            finding,
            run_id=TROUBLE,
            observations=[obs()],
            evidence_ids=(),
            gaps=(),
        )
    evidence = acquired(
        metric="job_failure_rate_pct",
        unit="pct",
        value=8.0,
        interval_start="2026-09-08",
        interval_end="2026-09-22",
    )
    assert not health_eligible(evidence)
    current = obs(metric="job_failure_rate_pct", unit="pct", value=9.0)
    sel = selection_for([current], [evidence])
    (entry,) = sel.selected
    assert entry["baseline_observation_id"] is None
    assert [r["candidate_observation_id"] for r in sel.rejected] == [
        evidence.observation_id
    ]


def test_revise_rejects_another_finding() -> None:
    other = run(job_triplet(100, 8, 8.0, entity_id="9"), []).findings[0]
    with pytest.raises(ValueError, match="finding"):
        revise(
            from_finding(j42()),
            other,
            run_id=TROUBLE,
            observations=(),
            evidence_ids=(),
            gaps=(),
        )


def test_case_findings_are_excluded_from_health_and_plays() -> None:
    _, created = open_case(
        account_key="acme",
        workspace_id="123",
        origin="clue",
        origin_ref="job:77",
        question="nightly load fails",
        run_id=CUR,
    )
    assert created is not None
    read = project(
        [],
        [created],
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
    )
    assert created.finding_id not in read.top_concern_finding_ids
    assert read.unclassified is None
    plays = candidates([created], read, [], run_id=CUR, interval=INTERVAL)
    assert all(created.finding_id not in p.finding_ids for p in plays)


def test_hypothesis_upsert_keeps_its_position() -> None:
    finding = j42()
    case = from_finding(finding)
    for hid in ("h1", "h2", "h3"):
        case, finding = revise(
            case,
            finding,
            run_id=TROUBLE,
            observations=(),
            evidence_ids=(),
            gaps=(),
            hypothesis={**_hyp("untested"), "hypothesis_id": hid},
        )
    case, _ = revise(
        case,
        finding,
        run_id=TROUBLE,
        observations=(),
        evidence_ids=(),
        gaps=(),
        hypothesis={**_hyp("refuted"), "hypothesis_id": "h1"},
    )
    assert [(h["hypothesis_id"], h["status"]) for h in case.hypotheses] == [
        ("h1", "refuted"),
        ("h2", "untested"),
        ("h3", "untested"),
    ]
