# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Service-tier tests for the Portfolio Readiness review domain (Phase-2 X4).

Exercises the ``WorkloadReviewService`` end-to-end for the opt-in
``portfolio-readiness`` workload-maturity domain against a fake SQL executor:

* ``run(["portfolio-readiness"])`` selects exactly the domain's evidence queries
  (``C-B01`` / ``C-J01`` / ``C-J04`` over the billing + jobs packs), runs them,
  and produces ranked, evidence-cited findings;
* only the needed evidence queries run (no unrelated pack queries);
* the domain is advertised via ``available_domains`` / ``OPT_IN_DOMAINS``; and
* the v1 default review (jobs/sql/warehouse) is unchanged by the addition.
"""

from __future__ import annotations

import asyncio

import polars as pl
import pytest
from starboard.tools.services.workload_review_service import (
    OPT_IN_DOMAINS,
    WorkloadReviewService,
    available_domains,
)

# Rows keyed by a marker substring unique to each evidence query's SQL.
_C_B01_ROWS = [
    {
        "workspace_id": "1234567890",
        "billing_origin_product": "JOBS",
        "user_type": "Unattributed",
        "dbus_consumed": 800.0,
    },
]
_C_J01_ROWS = [
    {
        "name": "nightly_elt",
        "job_id": "j-unowned",
        "run_as": None,
        "total_dbus": 420.0,
        "avg_dbus_per_run": 14.0,
    },
]
_C_J04_ROWS = [
    {
        "job_name": "fragile_prod",
        "job_id": "j-fragile",
        "total_runs": 100,
        "failure_rate_pct": 30.0,
        "total_dbus": 300.0,
        "wasted_dbu_pct": 25.0,
    },
]


class _FakeSQLExecutor:
    """Maps rendered SQL to fixture rows by a marker substring in the SQL."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute_sql(self, sql: str, *args, **kwargs) -> pl.DataFrame:
        self.executed.append(sql)
        if "wasted_dbu_pct" in sql:  # C-J04 reliability scorecard
            return pl.DataFrame(_C_J04_ROWS)
        if "avg_dbus_per_run" in sql:  # C-J01 job DBU leaderboard
            return pl.DataFrame(_C_J01_ROWS)
        if "dbus_consumed" in sql:  # C-B01 consumption by identity
            return pl.DataFrame(_C_B01_ROWS)
        return pl.DataFrame([])


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
class TestPortfolioReadinessService:
    def test_domain_produces_ranked_findings(self) -> None:
        service = WorkloadReviewService(
            _FakeSQLExecutor(), enable_cache=False, workspace="acme"
        )
        review = _run(service.run(["portfolio-readiness"]))
        rule_ids = {rf.finding.rule_id for rf in review.findings}
        assert rule_ids == {
            "portfolio_untracked_production_consumption",
            "portfolio_unattended_production_job",
            "portfolio_unreliable_production_workload",
        }
        # Untracked production consumption (high) ranks first.
        assert (
            review.findings[0].finding.rule_id
            == "portfolio_untracked_production_consumption"
        )
        assert review.degraded is False
        assert all(rf.evidence for rf in review.findings)
        assert {rf.finding.category for rf in review.findings} == {
            "portfolio_readiness"
        }

    def test_only_needed_evidence_queries_run(self) -> None:
        fake = _FakeSQLExecutor()
        service = WorkloadReviewService(fake, enable_cache=False)
        _run(service.run(["portfolio-readiness"]))
        joined = "\n".join(fake.executed)
        # The three portfolio-readiness evidence queries rendered ...
        assert "dbus_consumed" in joined
        assert "avg_dbus_per_run" in joined
        assert "wasted_dbu_pct" in joined
        # ... and unrelated domain markers did not.
        assert "storage_quantity" not in joined  # vector search
        assert "is_noisy" not in joined  # mlflow

    def test_domain_is_advertised(self) -> None:
        assert "portfolio-readiness" in OPT_IN_DOMAINS
        assert "portfolio-readiness" in available_domains()

    def test_v1_default_review_unchanged(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        review = _run(service.run())
        assert set(review.requested_domains) == {"jobs", "sql", "warehouse"}
