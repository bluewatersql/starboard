# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the health read projection (WP3-7, D3-6, D3-7)."""

from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

import pytest
from starboard_core.engagement.catalog import SIX_FAMILIES
from starboard_core.engagement.changes import ChangeContext, build
from starboard_core.engagement.families import rule_coverage
from starboard_core.engagement.health import (
    DISCOVERY_COMMAND,
    REVIEW_COMMAND,
    health_eligible,
    no_evidence,
    project,
)
from starboard_core.engagement.records import HealthRead, Observation

from .test_concerns import (
    CUR,
    EV,
    INTERVAL,
    job_triplet,
    manifest,
    obs,
    present,
    prior,
    run,
    selection_for,
)
from .test_families import p01_manifest

pytestmark = pytest.mark.unit


def ws_reliability(**over: Any) -> list[Observation]:
    out = job_triplet(500, 40, 8.0, entity_kind="workspace", entity_id="123", **over)
    out.append(
        obs(
            entity_kind="workspace",
            entity_id="123",
            metric="cancelled_job_runs",
            value=3.0,
            **over,
        )
    )
    return out


def health(
    current: list[Observation], findings: Any = (), changes: Any = ()
) -> HealthRead:
    return project(
        current,
        list(findings),
        list(changes),
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
    )


def family(read: HealthRead, name: str) -> Any:
    return next(f for f in read.families if f.family == name)


def test_no_observations_is_insufficient_evidence() -> None:
    read = health([])
    assert read.verdict == "insufficient_evidence" and read.assessed_count == 0
    assert read.material_unknowns == SIX_FAMILIES
    for fam in read.families:
        assert fam.severity is None and fam.coverage == "unknown"
        assert fam.unknown_reason and fam.unknown_reason.startswith("missing_source:")
        assert fam.acquisition_request is not None
    gov = family(read, "governance")
    assert gov.acquisition_request["missing"] == ("findings_manifest",)
    assert gov.acquisition_request["command"] == REVIEW_COMMAND
    assert (
        family(read, "reliability").acquisition_request["command"] == DISCOVERY_COMMAND
    )
    assert family(read, "reliability").unknown_reason == "missing_source:F-06"


def test_no_score_no_healthy_label_no_dollars() -> None:
    names = {f.name for f in fields(HealthRead)}
    assert not {"score", "healthy", "dollars", "cost"} & names
    text = str(health(ws_reliability()).to_dict()).lower()
    assert "healthy" not in text and "$" not in text


def test_complete_reliability_with_watch_finding() -> None:
    cur = ws_reliability()
    findings = run(cur, []).findings
    read = health(cur, findings)
    rel = family(read, "reliability")
    assert (rel.assessment, rel.coverage, rel.severity) == (
        "assessed",
        "complete",
        "watch",
    )
    assert rel.acquisition_request is None and rel.unknown_reason is None
    assert rel.finding_ids == tuple(f.finding_id for f in findings)
    assert read.verdict == "health_read" and read.assessed_count == 1
    assert "reliability" not in read.material_unknowns
    assert read.top_concern_finding_ids == rel.finding_ids


def test_assessed_without_findings_is_none_severity() -> None:
    rel = family(
        health(
            job_triplet(500, 2, 0.4, entity_kind="workspace", entity_id="123")
            + [
                obs(
                    entity_kind="workspace",
                    entity_id="123",
                    metric="cancelled_job_runs",
                    value=0.0,
                )
            ]
        ),
        "reliability",
    )
    assert rel.severity == "none" and rel.coverage == "complete"


def test_partial_family_requests_missing_required_sources() -> None:
    cur = job_triplet(100, 8, 8.0)  # per-job only: F-06 workspace metrics missing
    rel = family(health(cur), "reliability")
    assert (rel.assessment, rel.coverage) == ("assessed", "partial")
    assert rel.acquisition_request == {
        "owner_role": "operator",
        "missing": ("F-06",),
        "command": DISCOVERY_COMMAND,
        "placeholders": (),
    }


def test_partial_coverage_observation_keeps_family_partial() -> None:
    rel = family(health(ws_reliability(coverage="partial")), "reliability")
    assert rel.coverage == "partial" and rel.acquisition_request is not None


def test_od2_fact_families_assessable_despite_unknown_rule_metric() -> None:
    cur = [
        obs(
            family="adoption_breadth",
            entity_kind="workspace",
            entity_id="123",
            metric="products_in_use",
            value=7.0,
        ),
        obs(
            family="adoption_breadth",
            entity_kind="workspace",
            entity_id="123",
            metric="rules_evaluated",
            value=None,
            state="unknown",
            coverage="unknown",
            unknown_reason="no_family_rules",
            method_version="findings_manifest_v2",
        ),
        obs(
            family="concentration",
            entity_kind="workspace",
            entity_id="123",
            metric="top_job_share_pct",
            unit="pct",
            value=40.0,
        ),
        obs(
            family="concentration",
            entity_kind="workspace",
            entity_id="123",
            metric="top10_jobs_share_pct",
            unit="pct",
            value=80.0,
        ),
    ]
    read = health(cur)
    assert family(read, "adoption_breadth").coverage == "complete"
    assert family(read, "adoption_breadth").severity == "none"
    assert family(read, "concentration").assessment == "assessed"


def test_p01_unavailable_evidence_is_insufficient_evidence() -> None:
    """Live run 2 P01: every evidence query unavailable assesses no family."""
    cur = rule_coverage(
        p01_manifest(),
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
        evidence_ids=(EV,),
    )
    read = health(list(cur))
    assert read.verdict == "insufficient_evidence" and read.assessed_count == 0
    gov = family(read, "governance")
    assert (gov.assessment, gov.severity) == ("unknown", None)
    # Live run 3: the reason is the real cause, not a missing manifest.
    assert gov.unknown_reason == "not_reviewed:uc,portfolio_readiness"
    assert gov.acquisition_request["command"] == REVIEW_COMMAND
    assert "--domains jobs,sql,warehouse,uc,portfolio-readiness" in REVIEW_COMMAND


def test_governance_failed_evidence_asks_for_discovery() -> None:
    m = p01_manifest()
    m["unavailable_queries"] = [*m["unavailable_queries"], "PO-01", "C-B01", "C-J01"]
    cur = rule_coverage(
        m,
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
        evidence_ids=(EV,),
        reviewed_domains=["uc", "portfolio-readiness"],
    )
    gov = family(health(list(cur)), "governance")
    assert gov.unknown_reason == "missing_source:C-B01,C-J01,PO-01"
    assert gov.acquisition_request["missing"] == ("C-B01", "C-J01", "PO-01")
    assert gov.acquisition_request["command"] == DISCOVERY_COMMAND


def test_no_evidence_makes_every_family_unknown() -> None:
    read = health(ws_reliability())
    assert read.verdict == "health_read"
    out = no_evidence(read, "no_evidence:discovery_0_of_21_queries_succeeded", ["F-06"])
    assert out.verdict == "insufficient_evidence" and out.assessed_count == 0
    assert out.material_unknowns == SIX_FAMILIES
    for fam in out.families:
        assert (fam.assessment, fam.coverage, fam.severity) == (
            "unknown",
            "unknown",
            None,
        )
        assert fam.unknown_reason == "no_evidence:discovery_0_of_21_queries_succeeded"
        assert fam.acquisition_request == {
            "owner_role": "operator",
            "missing": ("F-06",),
            "command": DISCOVERY_COMMAND,
            "placeholders": (),
        }
    assert HealthRead.from_dict(out.to_dict()) == out


def test_governance_needs_both_rule_metrics() -> None:
    rule: dict[str, Any] = {
        "family": "governance",
        "entity_kind": "workspace",
        "entity_id": "123",
        "method_version": "findings_manifest_v2",
    }
    only_one = [obs(metric="rules_evaluated", value=4.0, **rule)]
    gov = family(health(only_one), "governance")
    assert gov.coverage == "partial"
    assert gov.acquisition_request["command"] == REVIEW_COMMAND
    both = [*only_one, obs(metric="active_rule_findings", value=0.0, **rule)]
    assert family(health(both), "governance").coverage == "complete"


def test_aggregate_observations_carry_per_job_cap_uncertainty() -> None:
    cur = [
        replace(o, dedupe_key="job_aggregate_slice|123|42|a|b|v1")
        for o in job_triplet(100, 8, 8.0)
    ]
    assert family(health(cur), "reliability").uncertainty == ("per_job_cap_25",)


def test_change_ids_attach_to_family() -> None:
    cur, base = job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)
    changes = build(
        cur, selection_for(cur, base), context=ChangeContext(baselines=base)
    )
    rel = family(health(cur, (), changes), "reliability")
    assert set(rel.change_ids) == {c.change_id for c in changes}


def test_top_concerns_order_severity_then_exposure_then_id() -> None:
    base = job_triplet(100, 1, 1.0, maker=prior)
    big = job_triplet(100, 30, 30.0, entity_id="7")
    small = job_triplet(100, 10, 10.0, entity_id="8")
    watch = job_triplet(100, 8, 8.0, entity_id="9")
    base7 = job_triplet(100, 1, 1.0, maker=prior, entity_id="7")
    base8 = job_triplet(100, 1, 1.0, maker=prior, entity_id="8")
    cur = [*big, *small, *watch]
    result = run(cur, [*base, *base7, *base8])
    ids = {f.entity_id: f.finding_id for f in result.findings}
    read = health(cur, result.findings)
    assert read.top_concern_finding_ids == (ids["7"], ids["8"], ids["9"])


def test_unclassified_findings_projected_separately() -> None:
    entry = {"rule_id": "made_up_rule", "entity_id": "x", "severity": "high"}
    cur = [present("made_up_rule::x", family="other")]
    findings = run(cur, [], manifest=manifest(entry)).findings
    assert findings[0].family == "unclassified"
    read = health(cur, findings)
    assert read.unclassified is not None
    assert read.unclassified.finding_ids == (findings[0].finding_id,)
    assert read.unclassified.unknown_reason == "rule_family_unclassified"
    assert findings[0].finding_id not in [
        f for fam in read.families for f in fam.finding_ids
    ]


def test_acquisition_observations_are_not_health_inputs() -> None:
    acquired = ws_reliability(method_version="acquisition_v1")
    assert not any(health_eligible(o) for o in acquired)
    assert family(health(acquired), "reliability").assessment == "unknown"
