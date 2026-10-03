# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Review rules aligned with the action-plan catalog (round 5 #5, #7).

``job_cron_overlap`` (C-J08), ``job_wait_tasks`` (C-J09), ``spend_step_change``
(F-03) and ``warehouse_recent_resize`` (W-W07 + W-W01/W-W05 context), plus the
manifest ``discovery_skipped`` / ``coverage_note`` scope fields.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from starboard_core.domain.models.finding import Severity
from starboard_core.domain.rules.action_rate import FindingsManifest, coverage_note
from starboard_core.domain.rules.detectors import (
    detect_job_cron_overlap,
    detect_job_wait_tasks,
    detect_spend_step_change,
    detect_warehouse_recent_resize,
)
from starboard_core.domain.rules.evaluator import build_review
from starboard_core.domain.rules.registry import RuleRegistry


@pytest.fixture
def registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


def _params(registry: RuleRegistry, rule_id: str) -> dict:
    rule = next(r for r in registry.rules if r.id == rule_id)
    return {k: v for k, v in rule.params.items() if k != "max_findings"}


# --- job_cron_overlap (C-J08) --------------------------------------------- #
def _overlap(job, trigger="CRON", runs=732, started=575, peak=5, avg=90.5):
    return {
        "job_id": job, "trigger_type": trigger, "total_runs": str(runs),
        "runs_started_while_running": str(started), "max_concurrent_runs": str(peak),
        "avg_run_mins": str(avg),
    }


@pytest.mark.unit
class TestJobCronOverlap:
    def test_cron_overlap_fires_high(self, registry) -> None:
        [m] = detect_job_cron_overlap([_overlap("421")], _params(registry, "job_cron_overlap"))
        assert m.entity_key == "421" and m.severity == Severity.HIGH
        assert "575 of 732 CRON runs (78.6%)" in m.current_state

    def test_non_cron_and_thresholds_do_not_fire(self, registry) -> None:
        p = _params(registry, "job_cron_overlap")
        rows = [
            _overlap("a", trigger="ONETIME"),  # backfill burst, not scheduler pile-up
            _overlap("b", runs=4, started=3),  # below min_runs
            _overlap("c", peak=1),  # never two at once
            _overlap("d", runs=100, started=5),  # 5% < 10%
            {"job_id": "e", "trigger_type": "CRON"},  # columns missing → degrade
        ]
        assert detect_job_cron_overlap(rows, p) == []

    def test_moderate_share_uses_rule_default_severity(self, registry) -> None:
        p = _params(registry, "job_cron_overlap")
        [m] = detect_job_cron_overlap([_overlap("j", runs=100, started=20)], p)
        assert m.severity is None  # rule default (medium)

    def test_trigger_types_param(self) -> None:
        rows = [_overlap("p", trigger="PERIODIC")]
        assert detect_job_cron_overlap(rows, {"trigger_types": "CRON, PERIODIC"})


# --- job_wait_tasks (C-J09) ------------------------------------------------ #
@pytest.mark.unit
class TestJobWaitTasks:
    def test_wait_task_with_material_hours(self, registry) -> None:
        rows = [
            {"job_id": "421", "task_key": "wait_for_vote_processing_readiness",
             "task_runs": "744", "p50_duration_mins": "30.4", "total_task_hours": "449.4"},
            {"job_id": "421", "task_key": "compute_votes", "total_task_hours": "900"},
            {"job_id": "9", "task_key": "poll_upstream", "total_task_hours": "2.0"},
        ]
        [m] = detect_job_wait_tasks(rows, _params(registry, "job_wait_tasks"))
        assert m.entity_key == "421:wait_for_vote_processing_readiness"
        assert m.severity == Severity.HIGH  # >= high_task_hours

    def test_bad_pattern_falls_back(self) -> None:
        rows = [{"job_id": "1", "task_key": "sensor_x", "total_task_hours": 12}]
        assert detect_job_wait_tasks(rows, {"task_key_pattern": "("})


# --- spend_step_change (F-03) ---------------------------------------------- #
def _daily(start: date, values: list[float], window_from: int = 7, ws: str = "w1"):
    return [
        {"workspace_id": ws, "usage_date": (start + timedelta(days=i)).isoformat(),
         "dbus": str(v), "in_window": "true" if i >= window_from else "false"}
        for i, v in enumerate(values)
    ]


@pytest.mark.unit
class TestSpendStepChange:
    def test_step_detected_like_facts(self, registry) -> None:
        start = date(2026, 8, 26)
        values = [1000.0] * 19 + [2000.0] * 18  # 37 days; step on day 19
        [m] = detect_spend_step_change(_daily(start, values), _params(registry, "spend_step_change"))
        assert m.entity_key == "w1"
        assert m.row["usage_date"] == (start + timedelta(days=19)).isoformat()
        assert "+100%" in m.current_state and m.severity == Severity.HIGH

    def test_flat_or_small_lift_does_not_fire(self, registry) -> None:
        p = _params(registry, "spend_step_change")
        start = date(2026, 8, 26)
        assert detect_spend_step_change(_daily(start, [1000.0] * 37), p) == []
        small = [1000.0] * 19 + [1100.0] * 18  # +10% < 20%
        assert detect_spend_step_change(_daily(start, small), p) == []

    def test_without_in_window_flag_uses_first_days_as_baseline(self) -> None:
        rows = [
            {k: v for k, v in r.items() if k != "in_window"}
            for r in _daily(date(2026, 8, 26), [100.0] * 15 + [400.0] * 15)
        ]
        [m] = detect_spend_step_change(rows)
        assert m.row["usage_date"] == "2026-09-10"

    def test_garbage_rows_degrade(self) -> None:
        assert detect_spend_step_change([{"usage_date": None, "dbus": "x"}]) == []


# --- warehouse_recent_resize (W-W07 + context) ----------------------------- #
_AS_OF = "2026-10-01"


def _change(wid: str, when: str = "2026-09-30T23:53:39Z") -> dict:
    return {
        "warehouse_id": wid, "last_change_time": when, "delete_time": None,
        "recent_changes": '["2026-09-30 23:53:39 clusters 1-1->1-3"]',
    }


@pytest.mark.unit
class TestWarehouseRecentResize:
    def _p(self, registry) -> dict:
        return {**_params(registry, "warehouse_recent_resize"), "as_of": _AS_OF}

    def test_recent_change_with_queueing_fires(self, registry) -> None:
        context = {
            "W-W01": [{"warehouse_id": "q", "queued_query_pct": "45.3", "avg_capacity_wait_secs": "68"}],
            "W-W05": [],
        }
        [m] = detect_warehouse_recent_resize([_change("q")], self._p(registry), context)
        assert m.severity is None and "45.3% of queries queued" in m.current_state
        assert "clusters 1-1->1-3" in m.current_state

    def test_recent_change_with_exec_change_fires(self, registry) -> None:
        context = {
            "W-W01": [{"warehouse_id": "e", "queued_query_pct": "0", "avg_capacity_wait_secs": "0"}],
            "W-W05": [{"warehouse_id": "e", "exec_secs_t7": "700", "exec_secs_t28": "1400"}],
        }
        [m] = detect_warehouse_recent_resize([_change("e")], self._p(registry), context)
        assert "+100% (last 7 vs 28 days)" in m.current_state

    def test_quiet_or_old_changes_do_not_fire(self, registry) -> None:
        context = {
            "W-W01": [{"warehouse_id": "calm", "queued_query_pct": "0.02", "avg_capacity_wait_secs": "0"}],
            "W-W05": [{"warehouse_id": "calm", "exec_secs_t7": "250", "exec_secs_t28": "1000"}],
        }
        rows = [_change("calm"), _change("old", when="2026-07-10T00:00:00Z")]
        assert detect_warehouse_recent_resize(rows, self._p(registry), context) == []

    def test_missing_context_degrades_to_low(self, registry) -> None:
        [m] = detect_warehouse_recent_resize([_change("x")], self._p(registry), {})
        assert m.severity == Severity.LOW and "not measured" in m.current_state

    def test_evaluator_passes_context_rows(self, registry) -> None:
        rows = {
            "W-W07": [_change("q", when=date.today().isoformat())],
            "W-W01": [{"warehouse_id": "q", "queued_query_pct": "45", "avg_capacity_wait_secs": "60",
                       "total_queries": "10"}],
            "W-W02": [],
            "W-W05": [],
        }
        review = build_review(registry=registry, domains=["warehouse"], rows_by_query_id=rows)
        resize = [rf for rf in review.findings if rf.finding.rule_id == "warehouse_recent_resize"]
        assert len(resize) == 1 and resize[0].finding.severity == Severity.MEDIUM
        assert resize[0].evidence[0].query_id == "W-W07"
        assert review.degraded is False

    def test_missing_context_query_does_not_degrade_domain(self, registry) -> None:
        rows = {"W-W07": [], "W-W01": [], "W-W02": []}  # W-W05 never ran
        review = build_review(
            registry=registry, domains=["warehouse"], rows_by_query_id=rows,
            failed_query_ids={"W-W05"},
        )
        assert review.degraded is False


# --- coverage scope (#7) -------------------------------------------------- #
@pytest.mark.unit
class TestCoverageNote:
    def test_skipped_none_used(self) -> None:
        note = coverage_note([], ["C-Q03", "N-L01"])
        assert note == (
            "2 discovery queries skipped; none used by review rules; all evidence used "
            "by review rules is present."
        )

    def test_skipped_and_used(self) -> None:
        note = coverage_note(["C-J08"], ["C-J08", "N-L01"])
        assert note.startswith("2 discovery queries skipped; 1 used by review rules (C-J08)")

    def test_live(self) -> None:
        assert coverage_note([], None).startswith("Review ran its own evidence queries")
        assert "W-W02" in coverage_note(["W-W02"], None)

    def test_manifest_carries_scope(self, registry) -> None:
        review = build_review(registry=registry, domains=["sql"], rows_by_query_id={"C-Q02": []})
        m = FindingsManifest.from_review(review, discovery_skipped=["N-L02", "C-Q03"])
        assert m.discovery_skipped == ("C-Q03", "N-L02")
        assert m.unavailable_queries == ()
        assert m.coverage_note and "none used by review rules" in m.coverage_note
        live = FindingsManifest.from_review(review)
        assert live.discovery_skipped == ()
        assert live.coverage_note and live.coverage_note.startswith("Review ran its own")


@pytest.mark.unit
def test_context_queries_are_real_pack_ids(registry) -> None:
    from starboard.discovery.query_packs import create_default_registry

    real = {q.query_id for p in create_default_registry().all_packs for q in p.queries}
    assert registry.context_query_ids() == {"W-W01", "W-W05"}
    assert registry.context_query_ids() <= real
