# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the phase-2 observation adapters (D-13)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from starboard_core.domain.rules import RuleRegistry, load_ruleset_from_string
from starboard_core.engagement.history import Candidate, select_baselines
from starboard_core.engagement.observations import (
    FINDINGS_METHOD,
    from_findings_manifest,
)
from starboard_core.engagement.records import Observation

RID = "20261101_12345678-1234-4234-8234-123456789abc"
PRIOR_RID = "20261001_22345678-1234-4234-8234-123456789abc"
EV = ("ev_" + "a" * 24,)
INTERVAL = ("2026-10-02", "2026-10-31")


def finding(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "W-W01::wh-1",
        "rule_id": "W-W01",
        "category": "warehouse",
        "severity": "high",
        "score": 7.5,
        "entity_id": "wh-1",
        "entity_label": "Main WH",
        "evidence_dbu_estimate": 120.5,
        "query_id": "W-W01",
        "evidence_capped": False,
        "composite_key": "W-W01::wh-1",
    }
    base.update(over)
    return base


def manifest(*findings: dict[str, Any], **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "snapshot_version": "2.0",
        "run_date": "2026-11-01",
        "workspace": "prod",
        "workspace_id": "123",
        "lookback_days": 30,
        "products_dbu": {"SQL": 100.0},
        "findings": list(findings),
        "degraded": False,
        "unavailable_queries": [],
        "unavailable_domains": [],
        "cost_basis": "list-price DBU",
        "evidence_source": None,
        "discovery_skipped": False,
        "coverage_note": None,
        "finding_count": len(findings),
    }
    base.update(over)
    return base


def fm(m: dict[str, Any], **kw: Any) -> tuple[Observation, ...]:
    args: dict[str, Any] = {
        "run_id": RID,
        "account_key": "acme",
        "workspace_id": "123",
        "interval": INTERVAL,
        "evidence_ids": EV,
    }
    args.update(kw)
    return from_findings_manifest(m, **args)


def by_metric(obs: tuple[Observation, ...], entity_id: str) -> dict[str, Observation]:
    return {o.metric: o for o in obs if o.entity_id == entity_id}


# ---- findings manifest -------------------------------------------------------


def test_finding_maps_to_presence_and_dbu_observations() -> None:
    obs = fm(manifest(finding()))
    got = by_metric(obs, "W-W01::wh-1")
    present = got["finding_present"]
    assert (present.value, present.unit, present.grain) == (1.0, "flag", "interval")
    assert present.method_version == FINDINGS_METHOD == "findings_manifest_v2"
    assert present.family == "unclassified"  # "W-W01" is not a rule id
    assert present.entity_kind == "finding"
    assert (present.interval_start, present.interval_end) == INTERVAL
    assert present.as_of == "2026-11-01"
    assert present.coverage == "complete"
    assert present.evidence_ids == EV
    assert present.audience_class == "customer_shareable"
    dbu = got["evidence_dbu_estimate"]
    assert (dbu.value, dbu.unit) == (120.5, "DBU")


def test_no_dbu_observation_without_estimate() -> None:
    obs = fm(manifest(finding(evidence_dbu_estimate=None)))
    assert set(by_metric(obs, "W-W01::wh-1")) == {"finding_present"}


def test_family_comes_from_the_rule_registry() -> None:
    m = manifest(finding(rule_id="warehouse_queueing", composite_key="q::wh-1"))
    assert {o.family for o in fm(m)} == {"efficiency"}
    m = manifest(finding(rule_id="job_high_failure_rate", composite_key="j::1"))
    assert {o.family for o in fm(m)} == {"reliability"}


def test_entry_family_tag_is_ignored() -> None:
    # The registry is the single source: an entry's own tag never wins.
    m = manifest(finding(rule_id="warehouse_queueing", family="governance"))
    assert fm(m)[0].family == "efficiency"
    assert fm(manifest(finding(family="efficiency")))[0].family == "unclassified"


def test_unknown_or_missing_rule_is_unclassified() -> None:
    assert fm(manifest(finding(rule_id="no_such_rule")))[0].family == "unclassified"
    assert fm(manifest(finding(rule_id=None)))[0].family == "unclassified"
    assert {o.family for o in fm(manifest(finding()))} == {"unclassified"}


_USER_RULES = """
domain: custom
rules:
  - id: my_untagged_rule
    name: Untagged
    category: custom
    short_description: A user rule with no family tag.
    rationale: Exercise the unclassified family.
    severity: medium
    default_effort: S
    default_impact: 2
    suggested_fix: Nothing to fix.
  - id: my_tagged_rule
    name: Tagged
    category: custom
    short_description: A user rule tagged governance.
    rationale: Exercise a user-tagged family.
    severity: medium
    default_effort: S
    default_impact: 2
    suggested_fix: Nothing to fix.
    family: governance
"""


def test_user_registry_rule_family() -> None:
    registry = RuleRegistry([load_ruleset_from_string(_USER_RULES)])
    untagged = manifest(finding(rule_id="my_untagged_rule", composite_key="u::1"))
    assert fm(untagged, registry=registry)[0].family == "unclassified"
    tagged = manifest(finding(rule_id="my_tagged_rule", composite_key="t::1"))
    assert fm(tagged, registry=registry)[0].family == "governance"


def test_composite_key_fallback_and_dedupe() -> None:
    f1 = finding()
    f1.pop("composite_key")
    f2 = finding(
        rule_id=None, id="llm-1", composite_key=None, evidence_dbu_estimate=None
    )
    obs = fm(manifest(f1, copy.deepcopy(f1), f2))
    keys = sorted({o.entity_id for o in obs})
    assert keys == ["W-W01::wh-1", "llm-1"]
    assert len([o for o in obs if o.metric == "finding_present"]) == 2


def test_partial_coverage_when_capped_or_domain_degraded() -> None:
    assert fm(manifest(finding(evidence_capped=True)))[0].coverage == "partial"
    m = manifest(finding(), degraded=True, unavailable_domains=["warehouse"])
    assert fm(m)[0].coverage == "partial"


def test_internal_source_is_internal_only() -> None:
    obs = fm(manifest(finding()), source_kind="internal_mirror")
    assert {o.audience_class for o in obs} == {"internal_only"}


def test_as_of_defaults_to_interval_end_without_run_date() -> None:
    assert fm(manifest(finding(), run_date=None))[0].as_of == INTERVAL[1]
    assert fm(manifest(finding()), as_of="2026-11-02T00:00:00+00:00")[
        0
    ].as_of.startswith("2026-11-02")


@pytest.mark.parametrize("version", ["1.0", None, "3.0"])
def test_rejects_non_v2_manifests(version: Any) -> None:
    with pytest.raises(ValueError):
        fm(manifest(finding(), snapshot_version=version))


def test_rejects_bad_findings() -> None:
    with pytest.raises(ValueError):
        fm(manifest(finding(), findings="nope"))
    with pytest.raises(ValueError):
        fm(manifest({"severity": "high"}))


def prior_presence(entity_id: str = "W-W01::wh-1") -> Observation:
    (o,) = [
        x
        for x in fm(
            manifest(
                finding(
                    id=entity_id, composite_key=entity_id, evidence_dbu_estimate=None
                )
            ),
            run_id=PRIOR_RID,
            interval=("2026-09-01", "2026-09-30"),
        )
        if x.metric == "finding_present"
    ]
    return o


def test_absent_prior_finding_becomes_clear_observation() -> None:
    prior = prior_presence()
    obs = fm(manifest(), prior=[prior])
    (clear,) = obs
    assert (clear.entity_id, clear.metric, clear.value, clear.state) == (
        "W-W01::wh-1",
        "finding_present",
        0.0,
        "measured",
    )
    sel = select_baselines(
        obs,
        [Candidate(prior, 1, "reg_x")],
        reporting_interval=INTERVAL,
        computed_at="2026-11-01T00:00:00+00:00",
    )
    assert sel.selected[0]["comparison"] == "recovered"


def test_absent_prior_finding_on_degraded_manifest_is_unknown() -> None:
    prior = prior_presence()
    (unknown,) = fm(
        manifest(degraded=True, unavailable_domains=["warehouse"]), prior=[prior]
    )
    assert unknown.state == "unknown"
    assert unknown.value is None
    assert "degraded" in (unknown.unknown_reason or "")
    sel = select_baselines(
        (unknown,),
        [Candidate(prior, 1, "reg_x")],
        reporting_interval=INTERVAL,
        computed_at="2026-11-01T00:00:00+00:00",
    )
    assert sel.selected[0]["comparison"] == "missing_current_evidence"


def test_prior_from_other_scope_or_still_present_is_ignored() -> None:
    prior = prior_presence()
    assert (
        len(fm(manifest(finding()), prior=[prior])) == 2
    )  # present + dbu, no extra clear
    assert fm(manifest(), workspace_id="999", prior=[prior]) == ()
