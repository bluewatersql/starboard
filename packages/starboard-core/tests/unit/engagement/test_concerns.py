# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for concern_rules_v1 (WP3-7: reliability rule, OD-1 review mapping)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from starboard_core.engagement.concerns import (
    BELOW_MIN_VOLUME,
    FLAG_METRIC,
    REVIEW_SEVERITY,
    error_signature,
    evaluate,
    reliability_severity,
)
from starboard_core.engagement.history import (
    Candidate,
    finding_states,
    select_baselines,
)
from starboard_core.engagement.records import (
    BaselineSelection,
    Observation,
    concern_key,
    episode_id,
    finding_id,
    observation_id,
)

CUR = "20261008_12345678-1234-4234-8234-123456789abc"
PRIOR = "20260923_22345678-1234-4234-8234-123456789abc"
OLDER = "20260908_32345678-1234-4234-8234-123456789abc"
INTERVAL = ("2026-09-23", "2026-10-07")
PRIOR_INTERVAL = ("2026-09-08", "2026-09-22")
NOW = "2026-10-08T00:00:00+00:00"
EV = "ev_" + "b" * 24
EV2 = "ev_" + "c" * 24


def obs(**over: Any) -> Observation:
    base: dict[str, Any] = {
        "run_id": CUR,
        "account_key": "acme",
        "workspace_id": "123",
        "family": "reliability",
        "entity_kind": "job",
        "entity_id": "42",
        "metric": "job_runs",
        "value": 100.0,
        "unit": "count",
        "grain": "interval",
        "method_version": "discovery_facts_v1",
        "interval_start": INTERVAL[0],
        "interval_end": INTERVAL[1],
        "as_of": NOW,
        "coverage": "complete",
        "coverage_fraction": None,
        "state": "measured",
        "unknown_reason": None,
        "evidence_ids": (EV,),
        "source_kind": "customer_workspace",
        "audience_class": "customer_shareable",
        "dedupe_key": None,
    }
    base.update(over)
    key = tuple(
        base[k]
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


def prior(**over: Any) -> Observation:
    base: dict[str, Any] = {
        "run_id": PRIOR,
        "interval_start": PRIOR_INTERVAL[0],
        "interval_end": PRIOR_INTERVAL[1],
        "as_of": "2026-09-23T00:00:00+00:00",
        "evidence_ids": (EV2,),
    }
    base.update(over)
    return obs(**base)


def job_triplet(
    runs: float | None,
    failed: float | None,
    rate: float | None,
    *,
    maker: Any = obs,
    **over: Any,
) -> list[Observation]:
    out = []
    for metric, value, unit in (
        ("job_runs", runs, "count"),
        ("failed_job_runs", failed, "count"),
        ("job_failure_rate_pct", rate, "pct"),
    ):
        state = (
            {"state": "measured"}
            if value is not None
            else {
                "state": "unknown",
                "coverage": "unknown",
                "unknown_reason": "source_unavailable",
            }
        )
        out.append(maker(metric=metric, value=value, unit=unit, **{**state, **over}))
    return out


def selection_for(
    current: list[Observation], baselines: list[Observation], run_id: str = CUR
) -> BaselineSelection:
    return select_baselines(
        current,
        [
            Candidate(observation=b, committed_revision=1, registration_id="reg_x")
            for b in baselines
        ],
        reporting_interval=INTERVAL,
        computed_at=NOW,
        run_id=run_id,
    )


def run(
    cur: list[Observation], base: list[Observation], prior_findings: Any = (), **kw: Any
) -> Any:
    return evaluate(
        cur,
        selection_for(cur, base),
        list(prior_findings),
        run_id=kw.pop("run_id", CUR),
        baselines=base,
        **kw,
    )


# ---- reliability boundary table (OD-3) ---------------------------------------


@pytest.mark.parametrize(
    ("runs", "failed", "rate", "baseline", "expected"),
    [
        (49, 10, 20.0, 1.0, "none"),  # below min runs
        (100, 4, 4.0, None, "none"),  # below min failed
        (100, 9, 9.9, 5.0, "watch"),  # +4.9 pp at >= 5 %
        (100, 10, 10.0, 5.0, "serious"),  # +5.0 pp
        (100, 8, 8.0, None, "watch"),  # no baseline at 8 %
        (100, 6, 4.9, None, "none"),  # below watch rate, no baseline
        (100, 6, 4.0, 3.0, "none"),  # rise < 5 and rate < 5 %
        (60, 30, 50.0, 10.0, "critical"),  # OD-3 critical
        (60, 24, 50.0, 10.0, "serious"),  # failed < 25 → not critical
        (100, 49, 49.0, 10.0, "serious"),  # rate < 50 → not critical
        (100, 60, 60.0, 58.0, "watch"),  # high rate, no rise → watch only
        (None, 5, 10.0, 1.0, None),  # runs not measured → unknown
    ],
)
def test_reliability_severity_boundaries(
    runs: float | None,
    failed: float,
    rate: float,
    baseline: float | None,
    expected: str | None,
) -> None:
    assert reliability_severity(runs, failed, rate, baseline) == expected


def test_review_severity_od1_mapping() -> None:
    assert dict(REVIEW_SEVERITY) == {
        "critical": "critical",
        "high": "serious",
        "medium": "watch",
        "low": "watch",
    }


@pytest.mark.parametrize(
    ("text", "category", "expected"),
    [
        ("java.lang.OutOfMemoryError: Java heap space", "oom", "oom/outofmemoryerror"),
        ("Py4JJavaError: AnalysisException: x", "spark", "spark/py4jjavaerror"),
        ("no exception here", "timeout", "timeout/unknown"),
        (None, None, "unknown/unknown"),
        ("ValueError: bad", None, "unknown/valueerror"),
        # A REST error code tells a missing object from other REST failures.
        (
            "RestException: NOT_FOUND: table due to: DOES_NOT_EXIST",
            None,
            "unknown/restexception:not_found",
        ),
        (
            "\x1b[0;31mRestException\x1b[0m: INTERNAL_ERROR: boom",
            "spark_error",
            "spark_error/restexception:internal_error",
        ),
        ("RestException: no code here", None, "unknown/restexception"),
        (
            "RestException    Traceback (most recent call last)\n...\n"
            "RestException: NOT_FOUND: Access check failed due to: DOES_NOT_EXIST",
            None,
            "unknown/restexception:not_found",
        ),
    ],
)
def test_error_signature_v1(
    text: str | None, category: str | None, expected: str
) -> None:
    assert error_signature(text, category=category) == expected


# ---- evaluate: flags + findings ------------------------------------------------


def test_serious_job_rise_emits_active_finding_and_flag() -> None:
    cur = job_triplet(100, 8, 8.0)
    base = job_triplet(100, 1, 1.0, maker=prior)
    result = run(cur, base)
    (flag,) = result.flags
    assert flag.metric == FLAG_METRIC and flag.unit == "flag" and flag.value == 1.0
    assert flag.method_version == "reliability_rule_v1"
    assert flag.coverage == "complete" and flag.state == "measured"
    assert (flag.interval_start, flag.interval_end) == INTERVAL
    (f,) = result.findings
    key = concern_key("acme", "123", "job", "42", "job_failure_rise")
    assert f.finding_key == key and f.finding_id == finding_id(key)
    assert (f.state, f.severity, f.last_confirmed_severity) == (
        "active",
        "serious",
        "serious",
    )
    assert f.family == "reliability" and f.rule_id == "reliability_rule_v1"
    assert f.symptom_confidence == "confirmed" and f.cause_confidence == "unassessed"
    assert f.observation_ids[0] == flag.observation_id
    assert set(f.observation_ids[1:]) == {o.observation_id for o in cur}
    assert f.revision == 1 and f.revisions[0].reason == "detected"
    assert f.episode_id == episode_id(f.finding_id, CUR)


def test_no_baseline_at_eight_percent_is_watch() -> None:
    result = run(job_triplet(100, 8, 8.0), [])
    (f,) = result.findings
    assert (f.state, f.severity) == ("watch", "watch")


def test_below_threshold_emits_zero_flag_and_no_finding() -> None:
    result = run(job_triplet(49, 10, 20.0), [])
    (flag,) = result.flags
    assert flag.value == 0.0 and flag.state == "measured"
    assert result.findings == ()


def test_below_min_runs_with_open_prior_finding_emits_unknown_flag() -> None:
    p_cur = job_triplet(100, 8, 8.0, maker=prior)
    held = evaluate(
        p_cur, selection_for(p_cur, [], run_id=PRIOR), [], run_id=PRIOR, baselines=[]
    ).findings
    result = run(job_triplet(30, 20, 66.7), p_cur, held)
    (flag,) = result.flags
    assert (flag.state, flag.value, flag.coverage) == ("unknown", None, "unknown")
    assert flag.unknown_reason == BELOW_MIN_VOLUME
    assert result.findings == ()


def test_unmeasured_runs_emit_unknown_flag() -> None:
    result = run(job_triplet(None, 8, 8.0), [])
    (flag,) = result.flags
    assert flag.state == "unknown" and flag.value is None and flag.coverage == "unknown"
    assert flag.unknown_reason
    assert result.findings == ()


def test_partial_coverage_gives_probable_and_partial_flag() -> None:
    result = run(job_triplet(100, 8, 8.0, coverage="partial"), [])
    (flag,) = result.flags
    assert flag.coverage == "partial"
    assert result.findings[0].symptom_confidence == "probable"


def test_workspace_grain_uses_ws_concern_code() -> None:
    cur = job_triplet(500, 40, 8.0, entity_kind="workspace", entity_id="123")
    (f,) = run(cur, []).findings
    assert f.concern_code == "ws_job_failure_rise" and f.entity_kind == "workspace"


def test_non_reliability_families_have_no_concern_rules() -> None:
    cur = [
        obs(family=fam, metric="job_runs", value=999.0)
        for fam in ("consumption_trajectory", "adoption_breadth", "concentration")
    ]
    result = run(cur, [])
    assert result.findings == () and result.flags == ()


def test_missing_selected_baseline_raises() -> None:
    cur = job_triplet(100, 8, 8.0)
    base = job_triplet(100, 1, 1.0, maker=prior)
    with pytest.raises(ValueError, match="baseline"):
        evaluate(cur, selection_for(cur, base), [], run_id=CUR, baselines=[])


def test_internal_source_marks_flag_internal_only() -> None:
    cur = job_triplet(100, 8, 8.0)
    cur[0] = replace(
        cur[0], source_kind="internal_mirror", audience_class="internal_only"
    )
    (flag,) = run(cur, []).flags
    assert (
        flag.source_kind == "internal_mirror" and flag.audience_class == "internal_only"
    )


# ---- chaining ------------------------------------------------------------------


def test_reassessed_finding_chains_revision_and_keeps_episode() -> None:
    first = evaluate(
        job_triplet(100, 8, 8.0, maker=prior),
        selection_for(job_triplet(100, 8, 8.0, maker=prior), [], run_id=PRIOR),
        [],
        run_id=PRIOR,
        baselines=[],
    ).findings[0]
    held = replace(first, cause_confidence="supported")
    cur = job_triplet(100, 9, 9.0)
    second = run(cur, job_triplet(100, 8, 8.0, maker=prior), [held]).findings[0]
    assert second.finding_id == first.finding_id
    assert second.revision == 2 and [r.revision for r in second.revisions] == [1, 2]
    assert second.revisions[-1].reason == "reassessed"
    assert second.episode_id == first.episode_id
    assert second.episode_started_run_id == PRIOR
    assert second.cause_confidence == "supported"


def test_recovered_prior_starts_new_episode() -> None:
    first = evaluate(
        job_triplet(100, 8, 8.0, maker=prior),
        selection_for(job_triplet(100, 8, 8.0, maker=prior), [], run_id=PRIOR),
        [],
        run_id=PRIOR,
        baselines=[],
    ).findings[0]
    recovered = replace(first, state="recovered")
    second = run(job_triplet(100, 8, 8.0), [], [recovered]).findings[0]
    assert second.revision == 2
    assert second.episode_started_run_id == CUR
    assert second.episode_id == episode_id(second.finding_id, CUR)
    assert second.cause_confidence == "unassessed"


def test_flags_feed_finding_states_continuing() -> None:
    """WP3-10 path: re-select with flags, then finding_states keeps the chain."""
    p_cur = job_triplet(100, 8, 8.0, maker=prior)
    p_res = evaluate(
        p_cur, selection_for(p_cur, [], run_id=PRIOR), [], run_id=PRIOR, baselines=[]
    )
    cur = job_triplet(100, 9, 9.0)
    c_res = run(cur, p_cur, p_res.findings)
    sel = selection_for([*cur, *c_res.flags], [*p_cur, *p_res.flags])
    (out,) = finding_states(p_res.findings, sel, c_res.findings)
    assert out.finding_id == p_res.findings[0].finding_id
    assert out.revision == 2 and out.state == "watch"
    assert out.episode_started_run_id == PRIOR


# ---- review concerns (OD-1) ----------------------------------------------------


def manifest(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "2.0", "findings": list(entries)}


def present(eid: str, value: float = 1.0, **over: Any) -> Observation:
    return obs(
        family=over.pop("family", "efficiency"),
        entity_kind="finding",
        entity_id=eid,
        metric="finding_present",
        value=value,
        unit="flag",
        method_version="findings_manifest_v2",
        **over,
    )


def test_review_finding_maps_severity_and_records_origin() -> None:
    entry = {
        "composite_key": "warehouse_queueing::wh-1",
        "rule_id": "warehouse_queueing",
        "entity_id": "wh-1",
        "severity": "high",
    }
    result = run([present("warehouse_queueing::wh-1")], [], manifest=manifest(entry))
    (f,) = result.findings
    assert f.concern_code == "rule:warehouse_queueing"
    assert f.entity_kind == "warehouse" and f.entity_id == "wh-1"
    assert f.severity == "serious" and f.state == "active"
    assert f.rule_id == "warehouse_queueing"
    assert result.review_severities[f.finding_id] == "high"


@pytest.mark.parametrize(("review", "mapped"), [("low", "watch"), ("medium", "watch")])
def test_low_and_medium_map_to_watch(review: str, mapped: str) -> None:
    entry = {"rule_id": "warehouse_queueing", "entity_id": "wh-1", "severity": review}
    result = run([present("warehouse_queueing::wh-1")], [], manifest=manifest(entry))
    assert result.findings[0].severity == mapped
    assert result.review_severities[result.findings[0].finding_id] == review


def test_untriggered_or_unmatched_present_flag_is_ignored() -> None:
    entry = {"rule_id": "warehouse_queueing", "entity_id": "wh-1", "severity": "high"}
    cur = [present("warehouse_queueing::wh-1", value=0.0), present("other::x")]
    assert run(cur, [], manifest=manifest(entry)).findings == ()
