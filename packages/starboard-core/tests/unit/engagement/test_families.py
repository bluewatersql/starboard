# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the six-family observation producers (phase 3 WP3-6, spec §C)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from starboard_core.domain.rules.schema import RULE_FAMILIES
from starboard_core.engagement.catalog import (
    FAMILY_METRICS,
    METHOD_VERSION,
    SIX_FAMILIES,
)
from starboard_core.engagement.dedupe import (
    AGGREGATE_KEY_PREFIX,
    job_aggregate_dedupe_key,
    merge,
)
from starboard_core.engagement.families import (
    RUN_LEVEL_KEY_PREFIX,
    from_facts,
    from_reliability,
    rule_coverage,
)
from starboard_core.engagement.jobruns import (
    METHOD_VERSION as RELIABILITY_METHOD,
)
from starboard_core.engagement.jobruns import (
    UNCERTAINTY_PER_JOB_CAP,
    UNCERTAINTY_VERIFY_LIMIT,
    RunSlice,
    reconstruct_runs,
)
from starboard_core.engagement.records import FAMILIES, UNITS, Observation

RID = "20261101_12345678-1234-4234-8234-123456789abc"
EV = ("ev_" + "a" * 24,)
EV_VERIFY = "ev_" + "b" * 24
WS = "123"
START, END = "2026-10-02", "2026-10-31"


def facts(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "window": {"start": START, "end": END, "days": 30, "label": "30d"},
        "total": {"dbus": 1000.0, "dsu": 5.0},
        "product_mix": [
            {"product": "JOBS", "dbus": 600.0, "pct": 60.0},
            {"product": "SQL", "dbus": 300.0, "pct": 30.0},
            {"product": "DLT", "dbus": 100.0, "pct": 10.0},
        ],
        "months": {
            "last_full": {"month": "2026-09", "dbus": 900.0},
            "prior_full": {"month": "2026-08", "dbus": 750.0},
            "mom_growth_pct": 20.0,
        },
        "top_jobs": [
            {
                "job_id": f"j{i}",
                "name": None,
                "dbus": d,
                "pct": d / 10,
                "workspace_id": WS,
            }
            for i, d in enumerate(
                (250.0, 150.0, 100.0, 50.0, 50.0, 40.0, 30.0, 20.0, 10.0, 10.0)
            )
        ],
        "top_pipelines": [],
        "top_warehouses": [
            {
                "warehouse_id": "wh-1",
                "name": "Main",
                "dbus": 200.0,
                "pct": 20.0,
                "workspace_id": WS,
            },
            {
                "warehouse_id": "wh-2",
                "name": "Dev",
                "dbus": 100.0,
                "pct": 10.0,
                "workspace_id": WS,
            },
        ],
        "step_change": {"date": "2026-10-20", "lift_daily_dbus": 12.5},
        "job_reliability": {
            "runs": 200,
            "failed_runs": 10,
            "cancelled_runs": 4,
            "failure_rate_pct": 5.0,
            "window": {"start": START, "end": END},
        },
        "job_reliability_by_job": {
            "jobs": [
                {
                    "workspace_id": WS,
                    "job_id": "j1",
                    "runs": 40,
                    "failed_runs": 8,
                    "cancelled_runs": 1,
                    "failure_rate_pct": 20.0,
                },
                {
                    "workspace_id": WS,
                    "job_id": "j2",
                    "runs": 0,
                    "failed_runs": 0,
                    "cancelled_runs": 0,
                    "failure_rate_pct": None,
                },
            ],
            "cap": 25,
            "cap_reached": False,
            "coverage": "partial",
            "uncertainty": ["per_job_cap_25"],
            "method_version": "job_reliability_v1",
            "window": {"start": START, "end": END},
        },
        "performance_mode": {"pool_dbus": 400.0, "performance_optimized_pct": 25.0},
        "warehouses": {"count": 2, "classic_dbus": 75.0, "serverless_dbus": 225.0},
        "sources": {},
        "unavailable": {},
        "fallbacks": {},
        "fallback_notes": {},
    }
    base.update(over)
    return base


def ff(f: dict[str, Any], **kw: Any) -> tuple[Observation, ...]:
    args: dict[str, Any] = {
        "run_id": RID,
        "account_key": "acme",
        "workspace_id": WS,
        "source_kind": "customer_workspace",
        "evidence_ids": EV,
    }
    args.update(kw)
    return from_facts(f, **args)


def index(obs: tuple[Observation, ...]) -> dict[tuple[str, str, str], Observation]:
    out = {(o.entity_kind, o.entity_id, o.metric): o for o in obs}
    assert len(out) == len(obs), "duplicate (entity, metric)"
    return out


def ws_metric(obs: tuple[Observation, ...], metric: str) -> Observation:
    return index(obs)[("workspace", WS, metric)]


# ---- families / catalog identity ---------------------------------------------------


def test_six_families_single_source_of_truth() -> None:
    assert SIX_FAMILIES is RULE_FAMILIES
    assert tuple(f for f in FAMILIES if f != "other") == SIX_FAMILIES
    assert tuple(FAMILY_METRICS) == SIX_FAMILIES


def test_rule_helpers_reexported_from_domain_rules() -> None:
    from starboard_core.domain import rules
    from starboard_core.domain.rules import registry

    assert rules.rule_family is registry.rule_family
    assert rules.rule_entity_kind is registry.rule_entity_kind
    assert {"rule_family", "rule_entity_kind"} <= set(rules.__all__)
    assert rules.rule_family("warehouse_queueing") == "efficiency"
    assert rules.rule_entity_kind("job_high_failure_rate") == "job"


# ---- from_facts ----------------------------------------------------------------------


def test_every_fact_metric_in_the_catalog_is_emitted_with_its_unit_and_grain() -> None:
    obs = ff(facts())
    produced = {(o.family, o.metric, o.entity_kind): o.unit for o in obs}
    expected = {
        (family, spec.metric, spec.entity_kind): spec.unit
        for family, specs in FAMILY_METRICS.items()
        for spec in specs
        if spec.source != "findings_manifest"
    }
    assert produced == expected
    assert all(o.unit in UNITS for o in obs)
    assert all(o.family in SIX_FAMILIES for o in obs)


def test_no_family_other_and_no_off_catalog_metric() -> None:
    obs = ff(facts())
    catalog = {(f, s.metric) for f, specs in FAMILY_METRICS.items() for s in specs}
    assert all(o.family != "other" for o in obs)
    assert all((o.family, o.metric) in catalog for o in obs)


def test_fact_values_and_arithmetic() -> None:
    obs = ff(facts())
    v = {o.metric: o.value for o in obs if o.entity_kind == "workspace"}
    assert v["total_dbus"] == 1000.0
    assert v["total_dsu"] == 5.0
    assert v["last_full_month_dbus"] == 900.0
    assert v["month_over_month_pct"] == 20.0
    assert v["step_change_present"] == 1.0
    assert v["step_change_lift_daily_dbus"] == 12.5
    assert v["performance_optimized_pct"] == 25.0
    assert v["warehouse_serverless_share_pct"] == 75.0  # 225 / (75 + 225)
    assert v["job_runs"] == 200.0
    assert v["failed_job_runs"] == 10.0
    assert v["cancelled_job_runs"] == 4.0
    assert v["job_failure_rate_pct"] == 5.0
    assert v["products_in_use"] == 3.0
    assert v["top_job_share_pct"] == 25.0
    assert v["top10_jobs_share_pct"] == 71.0  # 710 / 1000
    assert v["top_warehouse_share_pct"] == 20.0
    assert v["top_product_share_pct"] == 60.0
    flags = {o.entity_id: o.value for o in obs if o.metric == "product_in_use"}
    assert flags == {"JOBS": 1.0, "SQL": 1.0, "DLT": 1.0}


def test_share_rounding_and_top10_uses_only_ten_items() -> None:
    jobs = [
        {"job_id": f"j{i}", "dbus": 1.0, "pct": None, "workspace_id": WS}
        for i in range(12)
    ]
    obs = ff(facts(total={"dbus": 3.0, "dsu": None}, top_jobs=jobs))
    assert ws_metric(obs, "top_job_share_pct").value == 33.33
    # top10 sums at most ten items
    assert ws_metric(obs, "top10_jobs_share_pct").value == round(10 / 3 * 100, 2)
    assert ws_metric(obs, "total_dsu").value == 0.0  # no DSU rows: measured zero


def test_methods_interval_and_identity() -> None:
    obs = ff(facts())
    for o in obs:
        assert (o.interval_start, o.interval_end) == (START, END)
        assert o.run_id == RID and o.account_key == "acme"
        assert o.evidence_ids == EV
        assert o.audience_class == "customer_shareable"
        if o.family == "reliability":
            assert o.method_version == RELIABILITY_METHOD
        else:
            assert o.method_version == METHOD_VERSION
    assert len({o.observation_id for o in obs}) == len(obs)


def test_unavailable_field_gives_unknown_with_missing_source_code() -> None:
    f = facts(
        warehouses=None,
        performance_mode=None,
        total=None,
        product_mix=None,
        unavailable={
            "warehouses": "source query F-08 failed: PERMISSION_DENIED (and F-09)",
            "performance_mode": "source query F-07 failed: timeout",
            "total": "no rows",
        },
    )
    obs = ff(f)
    serverless = ws_metric(obs, "warehouse_serverless_share_pct")
    assert serverless.state == "unknown" and serverless.value is None
    assert serverless.coverage == "unknown"
    assert serverless.unknown_reason == "missing_source:F-08,F-09"
    assert ws_metric(obs, "performance_optimized_pct").unknown_reason == (
        "missing_source:F-07"
    )
    # Without an ID in the text, the catalog source stands in.
    assert ws_metric(obs, "total_dbus").unknown_reason == "missing_source:F-01"
    assert ws_metric(obs, "products_in_use").unknown_reason == "missing_source:F-01"
    # Shares over a missing total are unknown, not zero.
    assert ws_metric(obs, "top_job_share_pct").state == "unknown"
    assert not [o for o in obs if o.metric == "product_in_use"]
    for o in obs:
        if o.state == "unknown":
            assert o.unknown_reason and " " not in o.unknown_reason


def test_no_step_change_is_a_measured_zero_flag() -> None:
    obs = ff(facts(step_change=None))
    assert ws_metric(obs, "step_change_present").value == 0.0
    lift = ws_metric(obs, "step_change_lift_daily_dbus")
    assert lift.state == "unknown" and lift.unknown_reason == "no_step_change"
    obs = ff(facts(step_change=None, unavailable={"step_change": "F-03 failed"}))
    assert ws_metric(obs, "step_change_present").unknown_reason == "missing_source:F-03"


def test_null_ratios_are_unknown_with_reasons() -> None:
    f = facts(
        performance_mode={"pool_dbus": 0.0, "performance_optimized_pct": None},
        warehouses={"count": 0, "classic_dbus": 0.0, "serverless_dbus": 0.0},
        months={
            "last_full": {"month": "2026-09", "dbus": 5.0},
            "prior_full": {"month": "2026-08", "dbus": 0.0},
            "mom_growth_pct": None,
        },
        job_reliability={
            "runs": 0,
            "failed_runs": 0,
            "cancelled_runs": 0,
            "failure_rate_pct": None,
        },
    )
    obs = ff(f)
    assert ws_metric(obs, "performance_optimized_pct").unknown_reason == (
        "no_performance_pool_dbus"
    )
    assert ws_metric(obs, "warehouse_serverless_share_pct").unknown_reason == (
        "no_warehouse_dbus"
    )
    assert (
        ws_metric(obs, "month_over_month_pct").unknown_reason == "no_prior_month_dbus"
    )
    assert ws_metric(obs, "job_runs").value == 0.0
    assert ws_metric(obs, "job_failure_rate_pct").unknown_reason == "no_runs"


def test_fallback_top_jobs_is_partial_and_window_mismatch_is_unknown() -> None:
    same = facts(fallbacks={"top_jobs": "C-J01"})
    assert ws_metric(ff(same), "top_job_share_pct").coverage == "partial"
    jobs = copy.deepcopy(facts()["top_jobs"])
    for j in jobs:
        j["pct"] = None
    other = facts(top_jobs=jobs, fallbacks={"top_jobs": "C-B04"})
    top = ws_metric(ff(other), "top_job_share_pct")
    assert top.state == "unknown" and top.unknown_reason == "window_mismatch:C-B04"


def test_empty_top_list_with_spend_is_zero_share() -> None:
    obs = ff(facts(top_warehouses=[]))
    assert ws_metric(obs, "top_warehouse_share_pct").value == 0.0


def test_workspace_reliability_comes_only_from_f06() -> None:
    obs = ff(
        facts(job_reliability=None, unavailable={"job_reliability": "F-06 failed"})
    )
    for metric in (
        "job_runs",
        "failed_job_runs",
        "cancelled_job_runs",
        "job_failure_rate_pct",
    ):
        o = ws_metric(obs, metric)
        assert o.state == "unknown" and o.unknown_reason == "missing_source:F-06"
    # The per-job F-12 values are still there but never roll up.
    assert [o for o in obs if o.entity_kind == "job" and o.metric == "job_runs"]


def test_f12_per_job_observations_carry_cap_uncertainty_and_aggregate_key() -> None:
    obs = ff(facts())
    jobs = [o for o in obs if o.entity_kind == "job"]
    assert {o.entity_id for o in jobs} == {"j1", "j2"}
    j1 = index(obs)[("job", "j1", "job_failure_rate_pct")]
    assert j1.value == 20.0 and j1.unit == "pct"
    assert j1.family == "reliability" and j1.method_version == RELIABILITY_METHOD
    assert j1.coverage == "partial"
    assert j1.dedupe_key == job_aggregate_dedupe_key(
        WS, "j1", START, END, RELIABILITY_METHOD
    )
    assert j1.dedupe_key.startswith(AGGREGATE_KEY_PREFIX)
    for o in jobs:
        assert o.uncertainty == (UNCERTAINTY_PER_JOB_CAP,)
    j2 = index(obs)[("job", "j2", "job_failure_rate_pct")]
    assert j2.state == "unknown" and j2.unknown_reason == "no_runs"
    # Workspace observations carry no per-job uncertainty.
    assert ws_metric(obs, "job_runs").uncertainty == ()


def test_jobs_outside_the_f12_cap_get_no_observation() -> None:
    obs = ff(facts(job_reliability_by_job=None))
    assert not [o for o in obs if o.entity_kind == "job"]


def test_internal_source_kind_is_internal_only() -> None:
    obs = ff(facts(), source_kind="internal_mirror")
    assert {o.audience_class for o in obs} == {"internal_only"}


def test_from_facts_requires_a_window() -> None:
    with pytest.raises(ValueError, match="window"):
        ff(facts(window=None))


# ---- from_reliability ----------------------------------------------------------------


def run_row(job: str, run: str, state: str | None, day: str) -> dict[str, Any]:
    return {
        "workspace_id": WS,
        "job_id": job,
        "run_id": run,
        "result_state": state,
        "first_period_start": f"{day}T01:00:00Z",
        "last_period_end": f"{day}T02:00:00Z",
    }


def recon(*, limit_reached: bool = False, expected: tuple[tuple[str, str], ...] = ()):
    rows = (
        run_row("j1", "r1", "SUCCESS", "2026-10-05"),
        run_row("j1", "r2", "FAILED", "2026-10-06"),
        run_row("j1", "r3", "SUCCESS", "2026-10-07"),
        run_row("j1", "r4", "CANCELLED", "2026-10-08"),
    )
    s = RunSlice(
        source_kind="customer_workspace",
        window_start=START,
        window_end=END,
        job_ids=("j1",),
        evidence_id=EV_VERIFY,
        rows=rows,
        limit_reached=limit_reached,
        workspace_id=WS,
    )
    return reconstruct_runs(
        [s],
        interval_start=START,
        interval_end=END,
        today="2026-11-01",
        expected_jobs=expected,
    )


def fr(r: Any, **kw: Any) -> tuple[Observation, ...]:
    args: dict[str, Any] = {
        "run_id": RID,
        "account_key": "acme",
        "source_kind": "customer_workspace",
        "interval": (START, END),
    }
    args.update(kw)
    return from_reliability(r, **args)


def test_from_reliability_is_per_job_only() -> None:
    obs = fr(recon())
    assert obs and {o.entity_kind for o in obs} == {"job"}
    v = {o.metric: o for o in obs}
    assert set(v) == {"job_runs", "failed_job_runs", "job_failure_rate_pct"}
    assert v["job_runs"].value == 4.0
    assert v["failed_job_runs"].value == 1.0
    assert v["job_failure_rate_pct"].value == 25.0
    for o in obs:
        assert o.family == "reliability"
        assert o.method_version == RELIABILITY_METHOD
        assert o.evidence_ids == (EV_VERIFY,)
        assert o.coverage == "complete"
        assert o.dedupe_key and not o.dedupe_key.startswith(AGGREGATE_KEY_PREFIX)
        assert o.uncertainty == ()
        assert o.dedupe_key == RUN_LEVEL_KEY_PREFIX + "|".join(
            (WS, "j1", START, END, RELIABILITY_METHOD)
        )
    units = {(s.metric, s.entity_kind): s.unit for s in FAMILY_METRICS["reliability"]}
    assert all(units[(o.metric, "job")] == o.unit for o in obs)


def test_verify_limit_is_carried_as_uncertainty() -> None:
    obs = fr(recon(limit_reached=True))
    for o in obs:
        assert o.coverage == "partial"
        assert UNCERTAINTY_VERIFY_LIMIT in o.uncertainty
        # dedupe_key is supersession identity only; it never encodes uncertainty.
        assert o.dedupe_key == RUN_LEVEL_KEY_PREFIX + "|".join(
            (WS, o.entity_id, START, END, RELIABILITY_METHOD)
        )


def test_unknown_expected_job_is_unknown() -> None:
    obs = fr(recon(expected=((WS, "j9"),)))
    j9 = [o for o in obs if o.entity_id == "j9"]
    assert len(j9) == 3
    for o in j9:
        assert o.state == "unknown" and o.coverage == "unknown"
        assert o.unknown_reason == "missing_source:vt-job-run-states"


def test_run_level_reconstruction_supersedes_f12_aggregate_in_merge() -> None:
    aggregate = [
        o for o in ff(facts()) if o.entity_kind == "job" and o.entity_id == "j1"
    ]
    run_level = fr(recon())
    by_id = {o.observation_id: o for o in run_level}
    assert {o.observation_id for o in aggregate} == set(by_id)
    result = merge([*aggregate, *run_level])
    assert {o.observation_id for o in result.observations} == set(by_id)
    kept = {o.metric: o for o in result.observations}
    assert kept["job_failure_rate_pct"].value == 25.0
    assert kept["job_failure_rate_pct"].uncertainty == ()
    assert len(result.superseded) == 3


# ---- rule_coverage -------------------------------------------------------------------


def manifest(*findings: dict[str, Any], **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "snapshot_version": "2.0",
        "run_date": "2026-11-01",
        "workspace": "prod",
        "workspace_id": WS,
        "lookback_days": 30,
        "products_dbu": {},
        "findings": list(findings),
        "degraded": False,
        "unavailable_queries": [],
        "unavailable_domains": [],
        "cost_basis": "list-price DBU",
        "evidence_source": None,
        "discovery_skipped": False,
        "coverage_note": None,
    }
    base.update(over)
    return base


def finding(rule_id: str, entity_id: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"{rule_id}::{entity_id}",
        "rule_id": rule_id,
        "category": "x",
        "severity": "high",
        "score": 5.0,
        "entity_id": entity_id,
        "entity_label": None,
        "evidence_dbu_estimate": None,
        "query_id": None,
        "evidence_capped": False,
        "composite_key": f"{rule_id}::{entity_id}",
    }
    base.update(over)
    return base


def rc(m: dict[str, Any], **kw: Any) -> dict[tuple[str, str], Observation]:
    args: dict[str, Any] = {
        "run_id": RID,
        "account_key": "acme",
        "workspace_id": WS,
        "interval": (START, END),
        "evidence_ids": EV,
    }
    args.update(kw)
    obs = rule_coverage(m, **args)
    out = {(o.family, o.metric): o for o in obs}
    assert len(out) == len(obs)
    return out


def test_rule_coverage_emits_both_metrics_for_every_family() -> None:
    out = rc(manifest())
    assert set(out) == {
        (f, m)
        for f in SIX_FAMILIES
        for m in ("rules_evaluated", "active_rule_findings")
    }
    for o in out.values():
        assert o.entity_kind == "workspace" and o.entity_id == WS
        assert o.unit == "count" and o.method_version == METHOD_VERSION


def test_families_without_rules_are_unknown_no_family_rules() -> None:
    out = rc(manifest())
    for family in ("adoption_breadth", "concentration"):
        o = out[(family, "rules_evaluated")]
        assert o.state == "unknown" and o.unknown_reason == "no_family_rules"


def test_observation_only_families_are_assessable_from_facts() -> None:
    """OD-2: adoption_breadth / concentration have no rules, but their fact
    metrics are measured when present; only rule coverage is unknown."""
    fact_obs = ff(facts())
    coverage = rc(manifest())
    for family in ("adoption_breadth", "concentration"):
        required = {
            s.metric
            for s in FAMILY_METRICS[family]
            if s.required and s.entity_kind == "workspace"
        }
        measured = {
            o.metric for o in fact_obs if o.family == family and o.state == "measured"
        }
        assert required and required <= measured
        for o in fact_obs:
            if o.family == family and o.metric in required:
                assert o.coverage == "complete" and o.uncertainty == ()
        for metric in ("rules_evaluated", "active_rule_findings"):
            o = coverage[(family, metric)]
            assert o.state == "unknown" and o.unknown_reason == "no_family_rules"


def test_default_review_assesses_reliability_and_efficiency() -> None:
    m = manifest(
        finding("job_high_failure_rate", "j1"),
        finding("job_wait_tasks", "j2"),
        finding("job_high_failure_rate", "j3"),
        reviewed_domains=["jobs", "sql", "warehouse"],
    )
    out = rc(m)
    assert out[("reliability", "active_rule_findings")].value == 2.0
    assert out[("efficiency", "active_rule_findings")].value == 1.0
    assert out[("reliability", "rules_evaluated")].value >= 2.0
    # Default domains do not include uc / portfolio_readiness.
    gov = out[("governance", "rules_evaluated")]
    assert gov.state == "unknown"
    assert gov.unknown_reason == "not_reviewed:uc,portfolio_readiness"


def test_governance_unknown_when_its_evidence_is_unavailable() -> None:
    m = manifest(unavailable_queries=["PO-01", "C-B01", "C-J01"])
    out = rc(m, reviewed_domains=["uc", "portfolio-readiness"])
    o = out[("governance", "rules_evaluated")]
    assert o.state == "unknown"
    assert o.unknown_reason == "missing_source:C-B01,C-J01,PO-01"
    assert out[("governance", "active_rule_findings")].state == "unknown"


def test_unreviewed_domains_win_over_failed_evidence() -> None:
    """uc reviewed (its PO-01 failed) but portfolio_readiness never reviewed:
    the actionable cause is the missing ``--domains portfolio-readiness``."""
    out = rc(manifest(unavailable_queries=["PO-01"]), reviewed_domains=["uc"])
    o = out[("governance", "rules_evaluated")]
    assert o.unknown_reason == "not_reviewed:portfolio_readiness"


def test_unavailable_domain_counts_as_reviewed() -> None:
    m = manifest(
        unavailable_domains=["uc", "portfolio-readiness"],
        unavailable_queries=["PO-01", "C-B01", "C-J01"],
    )
    o = rc(m, reviewed_domains=[])[("governance", "rules_evaluated")]
    assert o.unknown_reason == "missing_source:C-B01,C-J01,PO-01"


def test_governance_assessed_with_reviewed_uc_and_zero_findings() -> None:
    out = rc(manifest(), reviewed_domains=["uc"])
    evaluated = out[("governance", "rules_evaluated")]
    assert evaluated.state == "measured" and evaluated.value == 1.0
    assert evaluated.coverage == "partial"  # the portfolio_readiness rules were not run
    active = out[("governance", "active_rule_findings")]
    assert active.value == 0.0


#: Live run 2 P01: public discovery got 0 of 21 queries (all PermissionDenied).
P01_UNAVAILABLE = [
    "C-J03",
    "C-J04",
    "C-J08",
    "C-J09",
    "C-Q02",
    "F-03",
    "W-W01",
    "W-W02",
    "W-W07",
]


def p01_manifest(**over: Any) -> dict[str, Any]:
    return manifest(
        degraded=True,
        unavailable_queries=P01_UNAVAILABLE,
        unavailable_domains=["jobs", "sql", "warehouse"],
        reviewed_domains=["jobs", "sql", "warehouse"],
        **over,
    )


@pytest.mark.parametrize("recorded", [True, False])
def test_p01_unavailable_evidence_never_assesses_a_family(recorded: bool) -> None:
    """Unavailable evidence (portfolio C-J04) must not make portfolio_readiness
    reviewed, so its C-B01 / C-J01 governance rules are not evaluated."""
    m = p01_manifest()
    if not recorded:  # a manifest without reviewed_domains reviewed no domain
        del m["reviewed_domains"]
    out = rc(m)
    gov = out[("governance", "rules_evaluated")]
    assert gov.state == "unknown" and gov.value is None
    assert gov.unknown_reason == "not_reviewed:uc,portfolio_readiness"
    assert all(o.state == "unknown" for o in out.values())


def test_failed_evidence_query_leaves_its_rule_not_evaluated() -> None:
    # PO-01 failed in discovery: reviewed uc, but the rule never ran.
    out = rc(manifest(unavailable_queries=["PO-01"], reviewed_domains=["uc"]))
    gov = out[("governance", "rules_evaluated")]
    assert gov.state == "unknown" and gov.unknown_reason == (
        "not_reviewed:portfolio_readiness"
    )
    # C-J01 failed: only C-B01 of the portfolio governance rules ran.
    out = rc(
        manifest(unavailable_queries=["C-J01"]),
        reviewed_domains=["portfolio_readiness"],
    )
    gov = out[("governance", "rules_evaluated")]
    assert gov.state == "measured" and gov.value == 1.0
    assert gov.coverage == "partial"


def test_a_finding_is_positive_evidence_without_reviewed_domains() -> None:
    out = rc(manifest(finding("table_missing_maintenance", "t1")))
    gov = out[("governance", "rules_evaluated")]
    assert gov.state == "measured" and gov.value == 1.0
    assert out[("governance", "active_rule_findings")].value == 1.0


def test_reviewed_domains_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="reviewed_domains"):
        rc(manifest(reviewed_domains="uc"))


def test_rule_coverage_complete_and_degraded() -> None:
    domains = ["uc", "portfolio_readiness", "jobs"]
    out = rc(manifest(), reviewed_domains=domains)
    assert out[("governance", "rules_evaluated")].value == 3.0
    assert out[("governance", "rules_evaluated")].coverage == "complete"
    out = rc(manifest(degraded=True), reviewed_domains=domains)
    assert out[("governance", "rules_evaluated")].coverage == "partial"


def test_unclassified_findings_count_nowhere() -> None:
    out = rc(manifest(finding("not_a_rule", "x")))
    assert all(
        o.value in (None, 0.0)
        for (f, m), o in out.items()
        if m == "active_rule_findings"
    )
