# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Job-failure materiality grading (C5) + the warehouse-queueing rule (C6).

C5: ``job_high_failure_rate`` / ``job_wasted_dbu_on_failures_retries`` used to
flag every 1-run, 100%-failure, ~0.01-DBU job as ``high``. They now grade by run
count (``min_runs``) and failure-DBU materiality (``material_failure_dbu``), both
rule params in the jobs seed YAML.

C6: ``warehouse_queueing`` (catalog OPP-WH-QUEUE) flags warehouses whose queries
queue at capacity, from the W-W01 ``queued_query_pct`` / ``avg_capacity_wait_secs``
/ ``total_queries`` columns, and degrades to no finding when they are absent.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.finding import Severity
from starboard_core.domain.rules.detectors import (
    DETECTORS,
    detect_job_high_failure_rate,
    detect_job_wasted_dbu_on_failures_retries,
    detect_warehouse_queueing,
)
from starboard_core.domain.rules.evaluator import build_review
from starboard_core.domain.rules.loader import RuleLoadError, load_ruleset_from_string
from starboard_core.domain.rules.registry import RuleRegistry


def _job(job_id: str, runs: object, rate: object, failure_dbus: object) -> dict:
    row = {
        "job_id": job_id,
        "total_runs": runs,
        "failure_rate_pct": rate,
        "wasted_dbu_pct": rate,
    }
    if failure_dbus is not None:
        row["failure_dbus"] = failure_dbus
    return row


@pytest.fixture
def registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


@pytest.mark.unit
class TestJobFailureGrading:
    def test_single_cheap_failed_run_is_not_reported(self) -> None:
        rows = [_job("tiny", "1", "100.0", "0.01")]
        assert detect_job_high_failure_rate(rows) == []
        assert detect_job_wasted_dbu_on_failures_retries(rows) == []

    def test_enough_runs_and_material_is_high(self) -> None:
        [m] = detect_job_high_failure_rate([_job("j", 16, 50.0, 37.71)])
        assert m.severity == Severity.HIGH
        assert m.impact == 4
        assert "37.71 DBU" in m.current_state

    def test_major_failure_dbu_raises_impact(self) -> None:
        [m] = detect_job_high_failure_rate([_job("j", 90, 20.0, 138.35)])
        assert (m.severity, m.impact) == (Severity.HIGH, 5)
        [w] = detect_job_wasted_dbu_on_failures_retries([_job("j", 90, 30.0, 138.35)])
        assert (w.severity, w.impact) == (Severity.HIGH, 4)

    def test_few_runs_but_material_is_medium(self) -> None:
        [m] = detect_job_high_failure_rate([_job("j", 1, 100.0, 491.06)])
        assert (m.severity, m.impact) == (Severity.MEDIUM, 3)

    def test_enough_runs_but_immaterial_is_low(self) -> None:
        [m] = detect_job_high_failure_rate([_job("j", 20, 60.0, 1.56)])
        assert (m.severity, m.impact) == (Severity.LOW, 2)

    def test_unknown_failure_dbu_is_medium_not_dropped(self) -> None:
        [m] = detect_job_high_failure_rate([_job("j", 50, 40.0, None)])
        assert (m.severity, m.impact) == (Severity.MEDIUM, 3)

    def test_missing_runs_column_does_not_drop(self) -> None:
        row = {"job_id": "j", "failure_rate_pct": 40.0, "failure_dbus": 50.0}
        [m] = detect_job_high_failure_rate([row])
        assert m.severity == Severity.HIGH

    def test_below_rate_threshold_is_ignored(self) -> None:
        assert detect_job_high_failure_rate([_job("j", 50, 5.0, 500.0)]) == []

    def test_params_override_defaults(self) -> None:
        rows = [_job("j", 2, 50.0, 5.0)]
        assert detect_job_high_failure_rate(rows) == []  # 2 < 3 runs, 5 < 10 DBU
        [m] = detect_job_high_failure_rate(
            rows, {"min_runs": 2, "material_failure_dbu": 5.0}
        )
        assert m.severity == Severity.HIGH

    def test_seed_rules_carry_params(self, registry: RuleRegistry) -> None:
        rules = {r.id: r for r in registry.rules_for("jobs")}
        for rule_id in ("job_high_failure_rate", "job_wasted_dbu_on_failures_retries"):
            params = rules[rule_id].params
            assert params["min_runs"] == 3
            assert params["material_failure_dbu"] == 10.0

    def test_review_no_longer_floods_high(self, registry: RuleRegistry) -> None:
        # 20 one-run, ~0.01-DBU failed jobs (the prompt-test flood) + 1 real one.
        rows = [_job(f"tiny-{i}", "1", "100.0", "0.01") for i in range(20)]
        rows.append(_job("real", "16", "50.0", "37.71"))
        review = build_review(
            registry=registry, domains=["jobs"], rows_by_query_id={"C-J04": rows}
        )
        high = [rf for rf in review.findings if rf.finding.severity == Severity.HIGH]
        assert {rf.finding.id for rf in high} == {
            "job_high_failure_rate::real",
            "job_wasted_dbu_on_failures_retries::real",
        }
        assert review.finding_count == 2
        top = review.findings[0].finding
        assert top.id == "job_high_failure_rate::real"
        assert top.score == 6.0  # high(3) x 4 / S(2)


def _wh(wid: str, queries: object, queued: object, wait: object) -> dict:
    row: dict = {"warehouse_id": wid, "total_queries": queries}
    if queued is not None:
        row["queued_query_pct"] = queued
    if wait is not None:
        row["avg_capacity_wait_secs"] = wait
    return row


@pytest.mark.unit
class TestWarehouseQueueing:
    def test_registered_and_seeded(self, registry: RuleRegistry) -> None:
        assert "warehouse_queueing" in DETECTORS
        rule = {r.id: r for r in registry.rules_for("warehouse")}["warehouse_queueing"]
        assert rule.evidence_query == "W-W01"
        assert rule.severity == Severity.MEDIUM
        assert "max_clusters" in rule.suggested_fix
        assert rule.params["queued_pct"] == 10.0
        assert rule.params["min_queries"] == 1000

    def test_heavy_queueing_on_busy_warehouse_is_high(self) -> None:
        [m] = detect_warehouse_queueing([_wh("wh", "145844", "45.40", "67.607")])
        assert (m.severity, m.impact) == (Severity.HIGH, 4)
        assert m.location.entity_type == "warehouse"
        assert "45.4%" in m.current_state

    def test_share_trigger_with_long_wait_is_high_at_volume(self) -> None:
        [m] = detect_warehouse_queueing([_wh("wh", 10768, 13.06, 47.075)])
        assert m.severity == Severity.HIGH

    def test_moderate_queueing_uses_rule_default(self) -> None:
        [m] = detect_warehouse_queueing([_wh("wh", 5000, 12.0, 3.0)])
        assert m.severity is None and m.impact is None

    def test_wait_only_trigger(self) -> None:
        [m] = detect_warehouse_queueing([_wh("wh", 1045, 4.98, 11.244)])
        assert m.severity is None

    def test_wait_only_needs_a_minimal_queued_share(self) -> None:
        # Long average wait over a handful of queued queries is not capacity pressure.
        assert detect_warehouse_queueing([_wh("wh", 16399, 0.01, 12.0)]) == []

    def test_low_volume_is_ignored(self) -> None:
        assert detect_warehouse_queueing([_wh("wh", 500, 50.0, 60.0)]) == []

    def test_no_queueing_is_ignored(self) -> None:
        assert detect_warehouse_queueing([_wh("wh", 191908, 0.02, 0.0)]) == []

    def test_missing_columns_degrade_to_no_finding(self) -> None:
        assert detect_warehouse_queueing([_wh("wh", 50000, None, None)]) == []
        assert detect_warehouse_queueing([{"warehouse_id": "wh"}]) == []
        assert detect_warehouse_queueing([{"queued_query_pct": None}]) == []

    def test_params_override_defaults(self) -> None:
        rows = [_wh("wh", 200, 12.0, 1.0)]
        assert detect_warehouse_queueing(rows) == []
        assert len(detect_warehouse_queueing(rows, {"min_queries": 100})) == 1

    def test_review_emits_queueing_finding(self, registry: RuleRegistry) -> None:
        rows = {
            "W-W01": [
                _wh("wh-starved", 145844, 45.4, 67.6),
                _wh("wh-fine", 191908, 0.02, 0.0),
            ],
            "W-W02": [],
            "W-W07": [],
        }
        review = build_review(
            registry=registry, domains=["warehouse"], rows_by_query_id=rows
        )
        ids = [rf.finding.id for rf in review.findings]
        assert ids == ["warehouse_queueing::wh-starved"]
        finding = review.findings[0]
        assert finding.finding.severity == Severity.HIGH
        assert finding.evidence[0].query_id == "W-W01"
        assert review.degraded is False

    def test_review_without_queue_columns_does_not_crash(
        self, registry: RuleRegistry
    ) -> None:
        # Older / internal W-W01 shapes without the queueing columns.
        rows = {
            "W-W01": [
                {
                    "warehouse_id": "wh",
                    "total_queries": 9000,
                    "utilization_band": "Optimal",
                }
            ],
            "W-W02": [],
        }
        review = build_review(
            registry=registry, domains=["warehouse"], rows_by_query_id=rows
        )
        assert review.finding_count == 0


@pytest.mark.unit
def test_rule_params_schema_defaults_and_validation() -> None:
    base = (
        "version: '1.0.0'\ndomain: jobs\nrules:\n"
        "  - id: r\n    name: R\n    category: jobs\n    short_description: s\n"
        "    rationale: r\n    severity: high\n    default_effort: S\n"
        "    default_impact: 3\n    suggested_fix: f\n"
    )
    assert load_ruleset_from_string(base).rules[0].params == {}
    with_params = (
        base + "    params:\n      min_runs: 5\n      material_failure_dbu: 2.5\n"
    )
    assert load_ruleset_from_string(with_params).rules[0].params == {
        "min_runs": 5,
        "material_failure_dbu": 2.5,
    }
    with pytest.raises(RuleLoadError):
        load_ruleset_from_string(base + "    params: [1, 2]\n")
