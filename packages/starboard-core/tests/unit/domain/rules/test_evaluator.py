# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Golden tests for the Workload Review engine (Phase-3 D1b).

Proves the pure engine (:mod:`starboard_core.domain.rules.evaluator`) turns
query-pack rows + the seed :class:`RuleRegistry` into a ranked, evidence-cited
set of findings:

* a golden fixture over a small ``system.*``-shaped dataset yields the expected
  ranked finding ids, ordering, and evidence citations;
* empty / degraded evidence degrades gracefully (no crash, partial/empty findings);
* ``domains`` filters correctly (only the requested domains contribute).
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.finding import Severity
from starboard_core.domain.rules.evaluator import build_review
from starboard_core.domain.rules.registry import RuleRegistry

# --- Golden fixture: rows shaped like the real evidence-query outputs ------ #
# W-W02 (auto-stop waste): one wasteful warehouse.
_W_W02_ROWS = [
    {
        "warehouse_id": "wh-idle",
        "running_hours": 20.0,
        "idle_running_hours": 12.0,
        "auto_stop_waste_pct": 80.0,  # >= 50 → fires warehouse_auto_stop_disabled
    },
    {
        "warehouse_id": "wh-busy",
        "running_hours": 20.0,
        "idle_running_hours": 1.0,
        "auto_stop_waste_pct": 5.0,  # below threshold → no finding
    },
]

# W-W01 (utilization bands): one under-utilized warehouse + one optimal.
_W_W01_ROWS = [
    {
        "warehouse_id": "wh-lazy",
        "running_seconds": 3600,
        "total_queries": 10,
        "utilization_ratio": 0.12,
        "utilization_band": "Under-utilized",  # fires under-utilized rule
    },
    {
        "warehouse_id": "wh-ok",
        "running_seconds": 3600,
        "total_queries": 500,
        "utilization_ratio": 0.55,
        "utilization_band": "Optimal",  # no finding
    },
]

# C-Q02 (optimization candidates): one wide-shuffle, one poor-pruning, one clean.
_C_Q02_ROWS = [
    {
        "statement_id": "stmt-shuffle",
        "statement_text": "SELECT * FROM sales_orders",
        "shuffle_gb": 25.0,  # >= 10 + SELECT * text → fires select_star_projection
        "pruning_ratio": 0.90,
        "read_partitions": 10,
    },
    {
        "statement_id": "stmt-prune",
        "statement_text": "SELECT id FROM events WHERE CAST(d AS STRING) = '1'",
        "shuffle_gb": 1.0,
        "pruning_ratio": 0.02,  # < 0.10 and many partitions → non_sargable
        "read_partitions": 500,
    },
    {
        "statement_id": "stmt-clean",
        "statement_text": "SELECT a, b FROM t",
        "shuffle_gb": 0.5,
        "pruning_ratio": 0.95,
        "read_partitions": 5,
    },
]

_GOLDEN_ROWS = {
    "W-W02": _W_W02_ROWS,
    "W-W01": _W_W01_ROWS,
    "C-Q02": _C_Q02_ROWS,
    "W-W07": [],  # warehouse_recent_resize evidence: ran, no config changes
}
# Catalog-alignment jobs evidence (C-J08 overlap, C-J09 wait tasks, F-03 daily
# DBU): present and empty = ran cleanly, nothing to flag.
_JOBS_EXTRA_EMPTY: dict[str, list] = {"C-J08": [], "C-J09": [], "F-03": []}

# Expected ranked order (score desc, severity desc, id asc):
#   warehouse_auto_stop_disabled          high×4 / XS(1) = 12.0
#   non_sargable_partition_filter         high×4 / S(2)  =  6.0
#   select_star_projection                med×3  / XS(1) =  6.0
#   warehouse_persistently_underutilized  med×3  / S(2)  =  3.0
_EXPECTED_ORDER = [
    "warehouse_auto_stop_disabled::wh-idle",
    "non_sargable_partition_filter::stmt-prune",
    "select_star_projection::stmt-shuffle",
    "warehouse_persistently_underutilized::wh-lazy",
]


@pytest.fixture
def registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


@pytest.mark.unit
class TestGoldenReview:
    def test_ranked_finding_ids_and_order(self, registry: RuleRegistry) -> None:
        review = build_review(
            registry=registry,
            domains=["sql", "warehouse"],
            rows_by_query_id=_GOLDEN_ROWS,
            workspace="golden-ws",
        )
        assert [rf.finding.id for rf in review.findings] == _EXPECTED_ORDER
        assert review.workspace == "golden-ws"
        assert review.finding_count == 4
        assert review.degraded is False

    def test_scores_and_severities(self, registry: RuleRegistry) -> None:
        review = build_review(
            registry=registry,
            domains=["sql", "warehouse"],
            rows_by_query_id=_GOLDEN_ROWS,
        )
        by_id = {rf.finding.id: rf.finding for rf in review.findings}
        assert by_id["warehouse_auto_stop_disabled::wh-idle"].score == 12.0
        assert by_id["warehouse_auto_stop_disabled::wh-idle"].severity == Severity.HIGH
        assert by_id["non_sargable_partition_filter::stmt-prune"].score == 6.0
        assert by_id["select_star_projection::stmt-shuffle"].score == 6.0
        assert (
            by_id["warehouse_persistently_underutilized::wh-lazy"].score == 3.0
        )

    def test_evidence_citations_reference_query_and_row(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["sql", "warehouse"],
            rows_by_query_id=_GOLDEN_ROWS,
        )
        by_id = {rf.finding.id: rf for rf in review.findings}

        auto_stop = by_id["warehouse_auto_stop_disabled::wh-idle"]
        assert len(auto_stop.evidence) == 1
        assert auto_stop.evidence[0].query_id == "W-W02"
        assert auto_stop.evidence[0].row_index == 0
        assert auto_stop.evidence[0].row["warehouse_id"] == "wh-idle"

        non_sargable = by_id["non_sargable_partition_filter::stmt-prune"]
        assert non_sargable.evidence[0].query_id == "C-Q02"
        assert non_sargable.evidence[0].row_index == 1
        assert non_sargable.evidence[0].row["statement_id"] == "stmt-prune"

    def test_findings_carry_rule_metadata_and_remediation(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["warehouse"],
            rows_by_query_id=_GOLDEN_ROWS,
        )
        finding = next(
            rf.finding
            for rf in review.findings
            if rf.finding.rule_id == "warehouse_auto_stop_disabled"
        )
        assert finding.suggested_fix  # paraphrased remediation present
        assert finding.rationale
        assert finding.current_state  # observed state referencing the row
        assert "wh-idle" in finding.current_state


@pytest.mark.unit
class TestDomainFilter:
    def test_only_requested_domains_contribute(self, registry: RuleRegistry) -> None:
        review = build_review(
            registry=registry,
            domains=["warehouse"],
            rows_by_query_id=_GOLDEN_ROWS,
        )
        # Only warehouse findings, even though C-Q02 rows are present.
        assert {rf.finding.category for rf in review.findings} == {"warehouse"}
        assert review.finding_count == 2

    def test_jobs_domain_rules_fire_on_jobs_evidence(
        self, registry: RuleRegistry
    ) -> None:
        # C-J04: one unreliable, DBU-wasting job. C-J03: one high-variance job.
        rows = {
            "C-J04": [
                {
                    "job_id": "job-flaky",
                    "job_name": "nightly_etl",
                    "total_runs": 50,
                    "failure_rate_pct": 40.0,  # >= 20 → high failure rate
                    "wasted_dbu_pct": 35.0,  # >= 25 → wasted DBU on retries
                },
            ],
            "C-J03": [
                {
                    "job_id": "job-spiky",
                    "name": "hourly_agg",
                    "total_runs": 20,
                    "max_min_ratio": 6.0,  # >= 3 → high runtime variance
                },
            ],
            **_JOBS_EXTRA_EMPTY,
        }
        review = build_review(
            registry=registry,
            domains=["jobs"],
            rows_by_query_id=rows,
        )
        rule_ids = {rf.finding.rule_id for rf in review.findings}
        assert rule_ids == {
            "job_high_failure_rate",
            "job_wasted_dbu_on_failures_retries",
            "job_high_runtime_variance",
        }
        jobs_report = review.domain_reports[0]
        assert jobs_report.domain == "jobs"
        assert jobs_report.rule_domain == "jobs"
        assert set(jobs_report.evidence_query_ids) == {
            "C-J03", "C-J04", "C-J08", "C-J09", "F-03"
        }
        # Every evidence query ran → not degraded.
        assert jobs_report.degraded is False

    def test_jobs_domain_degrades_when_evidence_absent(
        self, registry: RuleRegistry
    ) -> None:
        # No jobs evidence rows at all → no findings, domain marked degraded.
        review = build_review(
            registry=registry,
            domains=["jobs"],
            rows_by_query_id=_GOLDEN_ROWS,  # only warehouse/query evidence
        )
        assert review.finding_count == 0
        jobs_report = review.domain_reports[0]
        assert jobs_report.domain == "jobs"
        assert jobs_report.degraded is True


@pytest.mark.unit
class TestGracefulDegradation:
    def test_empty_rows_produce_no_findings_and_mark_degraded(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["sql", "warehouse"],
            rows_by_query_id={},  # no evidence at all
        )
        assert review.finding_count == 0
        # Both domains reference evidence queries that never ran → degraded.
        assert review.degraded is True
        assert all(r.degraded for r in review.domain_reports)

    def test_failed_query_marks_domain_degraded_but_keeps_other_findings(
        self, registry: RuleRegistry
    ) -> None:
        # W-W02 errored; W-W01 still returned rows.
        rows = {"W-W01": _W_W01_ROWS, "C-Q02": _C_Q02_ROWS}
        review = build_review(
            registry=registry,
            domains=["warehouse"],
            rows_by_query_id=rows,
            failed_query_ids={"W-W02"},
        )
        warehouse_report = next(
            r for r in review.domain_reports if r.domain == "warehouse"
        )
        assert warehouse_report.degraded is True
        assert "W-W02" in (warehouse_report.degraded_reason or "")
        # The under-utilized finding (from W-W01) still surfaces.
        assert any(
            rf.finding.rule_id == "warehouse_persistently_underutilized"
            for rf in review.findings
        )

    def test_empty_evidence_list_is_not_degraded(
        self, registry: RuleRegistry
    ) -> None:
        # Query ran cleanly but flagged nothing → present key, empty list.
        rows = {"W-W01": [], "W-W02": [], "W-W07": []}
        review = build_review(
            registry=registry,
            domains=["warehouse"],
            rows_by_query_id=rows,
        )
        assert review.finding_count == 0
        warehouse_report = review.domain_reports[0]
        assert warehouse_report.degraded is False

    def test_unknown_domain_is_reported_not_raised(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["not-a-domain"],
            rows_by_query_id=_GOLDEN_ROWS,
        )
        assert review.finding_count == 0
        report = review.domain_reports[0]
        assert report.degraded is True
        assert "unknown review domain" in (report.degraded_reason or "")


# --- Round-4: evidence-quality guards (A3 / A4 / A5) ----------------------- #
def _strip_text(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "statement_text"} for r in rows]


@pytest.mark.unit
class TestSelectStarRequiresStatementText:
    def test_suppressed_and_recorded_when_no_row_carries_text(
        self, registry: RuleRegistry
    ) -> None:
        rows = {"C-Q02": [dict(r, statement_text=None) for r in _C_Q02_ROWS]}
        review = build_review(registry=registry, domains=["sql"], rows_by_query_id=rows)
        rule_ids = {rf.finding.rule_id for rf in review.findings}
        assert "select_star_projection" not in rule_ids
        # Other C-Q02 rules still evaluate (pruning needs no statement text).
        assert "non_sargable_partition_filter" in rule_ids
        report = review.domain_reports[0]
        assert "statement_text" in report.suppressed_rules["select_star_projection"]
        assert report.degraded is False

    def test_absent_column_is_suppressed_too(self, registry: RuleRegistry) -> None:
        review = build_review(
            registry=registry,
            domains=["sql"],
            rows_by_query_id={"C-Q02": _strip_text(_C_Q02_ROWS)},
        )
        assert "select_star_projection" in review.domain_reports[0].suppressed_rules

    def test_large_shuffle_without_select_star_text_does_not_fire(
        self, registry: RuleRegistry
    ) -> None:
        rows = {
            "C-Q02": [
                {
                    "statement_id": "s1",
                    "statement_text": "SELECT COUNT(*) FROM t",
                    "shuffle_gb": 99.0,
                },
                {"statement_id": "s2", "statement_text": None, "shuffle_gb": 99.0},
            ]
        }
        review = build_review(registry=registry, domains=["sql"], rows_by_query_id=rows)
        assert review.finding_count == 0
        assert review.domain_reports[0].suppressed_rules == {}


@pytest.mark.unit
class TestPerRuleCapAndEvidenceCapped:
    @staticmethod
    def _variance_rows(n: int) -> list[dict]:
        return [
            {"job_id": f"job-{i}", "total_runs": 10, "max_min_ratio": 10.0 + i}
            for i in range(n)
        ]

    def test_cap_limits_one_rule_and_records_dropped(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["jobs"],
            rows_by_query_id={"C-J03": self._variance_rows(50), "C-J04": []},
        )
        variance = [
            rf for rf in review.findings
            if rf.finding.rule_id == "job_high_runtime_variance"
        ]
        assert len(variance) == 20
        assert review.domain_reports[0].capped_rules == {
            "job_high_runtime_variance": 30
        }

    def test_duplicate_entities_are_deduped(self, registry: RuleRegistry) -> None:
        rows = self._variance_rows(2) + self._variance_rows(2)
        review = build_review(
            registry=registry,
            domains=["jobs"],
            rows_by_query_id={"C-J03": rows, "C-J04": []},
        )
        ids = [rf.finding.id for rf in review.findings]
        assert len(ids) == len(set(ids)) == 2

    def test_limit_reached_evidence_marks_findings(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["jobs"],
            rows_by_query_id={"C-J03": self._variance_rows(3), "C-J04": []},
            limit_reached_query_ids={"C-J03"},
        )
        assert review.findings
        assert all(rf.metadata.get("evidence_capped") for rf in review.findings)
        assert review.domain_reports[0].evidence_capped_query_ids == ("C-J03",)

    def test_uncapped_evidence_has_empty_metadata(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["jobs"],
            rows_by_query_id={"C-J03": self._variance_rows(1), "C-J04": []},
        )
        assert review.findings[0].metadata == {}


@pytest.mark.unit
class TestUnavailableAndCostBasis:
    def test_unavailable_queries_and_domains(self, registry: RuleRegistry) -> None:
        review = build_review(
            registry=registry,
            domains=["warehouse", "jobs"],
            rows_by_query_id={
                "W-W01": _W_W01_ROWS, "C-J03": [], "C-J04": [], **_JOBS_EXTRA_EMPTY
            },
            failed_query_ids={"W-W02"},
        )
        assert review.degraded is True
        assert "W-W02" in review.unavailable_queries
        assert review.unavailable_domains == ("warehouse",)
        dumped = review.model_dump(mode="json")
        assert dumped["unavailable_domains"] == ["warehouse"]
        assert "W-W02" in dumped["unavailable_queries"]

    def test_cost_basis_default_and_override(self, registry: RuleRegistry) -> None:
        from starboard_core.domain.models.review import (
            COST_BASIS_LABEL,
            TELEMETRY_COST_BASIS_LABEL,
        )

        default = build_review(registry=registry, domains=["jobs"], rows_by_query_id={})
        assert default.cost_basis == COST_BASIS_LABEL
        telemetry = build_review(
            registry=registry,
            domains=["jobs"],
            rows_by_query_id={},
            cost_basis=TELEMETRY_COST_BASIS_LABEL,
        )
        assert "workspace telemetry" in telemetry.cost_basis
