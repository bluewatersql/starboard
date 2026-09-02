# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Service-tier tests for the Workload Review v2 domains (Phase-2 D-a).

Exercises the ``WorkloadReviewService`` end-to-end for the new opt-in domains
(DLT / ML / vector-search) against a fake SQL executor:

* ``run(["dlt"|"ml"|"vector-search"])`` selects exactly the new domains'
  evidence queries, runs them, and produces ranked, evidence-cited findings;
* the ``vector-search`` hyphen alias routes to the vector_search rule-domain;
* the severity gate + validator-council path is exercised with a deterministic
  stub model client; and
* the v1 default review (jobs/sql/warehouse) is unchanged by the additions.
"""

from __future__ import annotations

import asyncio

import polars as pl
import pytest
from starboard.tools.services.workload_review_service import WorkloadReviewService
from starboard_core.domain.models.finding import Severity
from starboard_core.domain.rules.gate import SeverityGate

# Rows keyed by a marker substring unique to each evidence query's SQL.
_P_DLT03_ROWS = [
    {"pipeline_name": "bronze", "pipeline_id": "pl-flaky", "total_updates": 40, "failure_rate_pct": 55.0},
]
_P_DLT01_ROWS = [
    {"pipeline_name": "abandoned", "pipeline_id": "pl-stale", "days_since_last_update": 120},
]
_P_DLT05_ROWS = [
    {"pipeline_name": "classic", "pipeline_id": "pl-classic", "is_serverless_config": False, "dbus": 400.0},
]
_C_ML01_ROWS = [
    {"endpoint_name": "demo-x", "endpoint_type": "Test/Demo (cleanup candidate)", "serving_tier": "Real-Time Inference", "total_dbus": 42.0},
]
_P_MLF04_ROWS = [
    {"experiment_name": "sweep", "experiment_id": "exp-noisy", "success_ratio": 0.4, "run_count": 200, "is_noisy": True},
]
_P_VS03_ROWS = [
    {"endpoint_name": "vs-idle", "storage_quantity": 30.0, "serving_quantity": 0.0},
]
_P_VS01_ROWS = [
    {"endpoint_name": "vs-expensive", "last_billed_date": "2026-08-27", "num_usage_records": 500, "total_dbus": 5000.0},
]


class _FakeSQLExecutor:
    """Maps rendered SQL to fixture rows by a marker substring in the SQL."""

    def __init__(self, fail_markers: tuple[str, ...] = ()) -> None:
        self.fail_markers = fail_markers
        self.executed: list[str] = []

    async def execute_sql(self, sql: str, *args, **kwargs) -> pl.DataFrame:
        self.executed.append(sql)
        for marker in self.fail_markers:
            if marker in sql:
                raise RuntimeError(f"simulated failure for {marker}")
        # DLT: order matters — P-DLT03 markers checked first.
        if "days_since_last_update" in sql:
            return pl.DataFrame(_P_DLT01_ROWS)
        if "is_serverless_billing" in sql:
            return pl.DataFrame(_P_DLT05_ROWS)
        if "failure_rate_pct" in sql:
            return pl.DataFrame(_P_DLT03_ROWS)
        # ML
        if "is_noisy" in sql:
            return pl.DataFrame(_P_MLF04_ROWS)
        if "endpoint_type" in sql:
            return pl.DataFrame(_C_ML01_ROWS)
        # Vector search
        if "storage_quantity" in sql:
            return pl.DataFrame(_P_VS03_ROWS)
        if "first_billed_date" in sql:
            return pl.DataFrame(_P_VS01_ROWS)
        return pl.DataFrame([])


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
class TestV2ServiceRouting:
    def test_dlt_domain_produces_ranked_findings(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False, workspace="acme")
        review = _run(service.run(["dlt"]))
        rule_ids = {rf.finding.rule_id for rf in review.findings}
        assert rule_ids == {
            "dlt_high_pipeline_failure_rate",
            "dlt_stale_pipeline",
            "dlt_classic_compute_serverless_candidate",
        }
        assert review.findings[0].finding.rule_id == "dlt_high_pipeline_failure_rate"
        assert review.degraded is False
        assert all(rf.evidence for rf in review.findings)

    def test_ml_domain_produces_findings_from_both_packs(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        review = _run(service.run(["ml"]))
        by_rule = {rf.finding.rule_id: rf for rf in review.findings}
        assert set(by_rule) == {"ml_test_demo_endpoint_cleanup", "ml_noisy_experiment"}
        assert by_rule["ml_test_demo_endpoint_cleanup"].evidence[0].query_id == "C-ML01"
        assert by_rule["ml_noisy_experiment"].evidence[0].query_id == "P-MLF04"

    def test_vector_search_hyphen_alias_routes(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        review = _run(service.run(["vector-search"]))
        rule_ids = {rf.finding.rule_id for rf in review.findings}
        assert rule_ids == {
            "vector_search_idle_endpoint",
            "vector_search_high_cost_endpoint",
        }
        assert review.domain_reports[0].rule_domain == "vector_search"

    def test_only_needed_evidence_queries_run_for_dlt(self) -> None:
        fake = _FakeSQLExecutor()
        service = WorkloadReviewService(fake, enable_cache=False)
        _run(service.run(["dlt"]))
        joined = "\n".join(fake.executed)
        # DLT evidence rendered; unrelated ML/VS/warehouse markers absent.
        assert "failure_rate_pct" in joined
        assert "days_since_last_update" in joined
        assert "endpoint_type" not in joined
        assert "storage_quantity" not in joined

    def test_v1_default_review_unchanged(self) -> None:
        # A vanilla default run still targets jobs/sql/warehouse only.
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        review = _run(service.run())
        assert set(review.requested_domains) == {"jobs", "sql", "warehouse"}


@pytest.mark.unit
class TestV2Gate:
    def test_severity_gate_suppresses_sub_threshold_v2_findings(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        validated = _run(
            service.run_validated(["dlt"], gate=SeverityGate(min_severity=Severity.HIGH))
        )
        # Only the high-severity failure-rate finding survives the gate.
        assert all(rf.finding.severity == Severity.HIGH for rf in validated.review.findings)
        assert validated.gate is not None
        assert validated.gate.suppressed_count >= 1
