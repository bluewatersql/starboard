# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the server-tier ``WorkloadReviewService`` (Phase-3 D1b).

Exercises the full packs → rows → rules → ranked findings flow against a fake
SQL executor (no Databricks connection): the service selects exactly the
evidence queries the requested domains need, runs them, materializes the Polars
rows, and hands them to the pure kernel engine. Also covers graceful
degradation when an evidence query fails, and ``--domains`` filtering.
"""

from __future__ import annotations

import asyncio

import polars as pl
import pytest
from starboard.tools.services.validator_council import (
    CouncilConfig,
    CritiqueRequest,
    ValidatorCouncil,
    Verdict,
)
from starboard.tools.services.workload_review_service import (
    WorkloadReviewService,
)
from starboard_core.domain.models.finding import Severity
from starboard_core.domain.rules.gate import SeverityGate

# Rows returned per evidence query, matched by a marker column in the rendered SQL.
_W_W02_ROWS = [
    {"warehouse_id": "wh-idle", "idle_running_hours": 12.0, "auto_stop_waste_pct": 80.0},
]
_W_W01_ROWS = [
    {
        "warehouse_id": "wh-lazy",
        "utilization_ratio": 0.12,
        "utilization_band": "Under-utilized",
    },
]
_C_Q02_ROWS = [
    {"statement_id": "stmt-prune", "shuffle_gb": 1.0, "pruning_ratio": 0.02, "read_partitions": 500},
    {"statement_id": "stmt-shuffle", "shuffle_gb": 25.0, "pruning_ratio": 0.9, "read_partitions": 10},
]


class _FakeSQLExecutor:
    """Maps rendered SQL to a fixture DataFrame by a marker substring.

    Satisfies the discovery ``SQLExecutor`` protocol (``execute_sql`` returns a
    Polars DataFrame). ``fail_markers`` forces a raise for the matching query.
    """

    def __init__(self, fail_markers: tuple[str, ...] = ()) -> None:
        self.fail_markers = fail_markers
        self.executed: list[str] = []

    async def execute_sql(self, sql: str, *args, **kwargs) -> pl.DataFrame:
        self.executed.append(sql)
        for marker in self.fail_markers:
            if marker in sql:
                raise RuntimeError(f"simulated failure for {marker}")
        if "auto_stop_waste_pct" in sql:
            return pl.DataFrame(_W_W02_ROWS)
        if "utilization_band" in sql:
            return pl.DataFrame(_W_W01_ROWS)
        if "optimization_score" in sql:
            return pl.DataFrame(_C_Q02_ROWS)
        return pl.DataFrame([])


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.unit
class TestWorkloadReviewService:
    def test_default_review_produces_ranked_findings(self) -> None:
        service = WorkloadReviewService(
            _FakeSQLExecutor(), enable_cache=False, workspace="acme"
        )
        review = _run(service.run())  # default domains: jobs, sql, warehouse

        ids = [rf.finding.id for rf in review.findings]
        assert ids[0] == "warehouse_auto_stop_disabled::wh-idle"  # score 12.0
        assert "non_sargable_partition_filter::stmt-prune" in ids
        assert "select_star_projection::stmt-shuffle" in ids
        assert "warehouse_persistently_underutilized::wh-lazy" in ids
        assert review.workspace == "acme"
        assert review.degraded is False

    def test_only_needed_evidence_queries_run(self) -> None:
        fake = _FakeSQLExecutor()
        service = WorkloadReviewService(fake, enable_cache=False)
        _run(service.run(["warehouse"]))
        # Warehouse rules need W-W01 + W-W02 only (not C-Q02).
        joined = "\n".join(fake.executed)
        assert "auto_stop_waste_pct" in joined
        assert "utilization_band" in joined
        assert "optimization_score" not in joined

    def test_domains_filter_limits_findings(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        review = _run(service.run(["warehouse"]))
        assert {rf.finding.category for rf in review.findings} == {"warehouse"}

    def test_failed_query_degrades_domain_gracefully(self) -> None:
        # W-W02 fails; W-W01 still returns its under-utilized warehouse.
        service = WorkloadReviewService(
            _FakeSQLExecutor(fail_markers=("auto_stop_waste_pct",)),
            enable_cache=False,
        )
        review = _run(service.run(["warehouse"]))
        warehouse_report = next(
            r for r in review.domain_reports if r.domain == "warehouse"
        )
        assert warehouse_report.degraded is True
        assert any(
            rf.finding.rule_id == "warehouse_persistently_underutilized"
            for rf in review.findings
        )
        # The auto-stop finding is absent because its evidence failed.
        assert not any(
            rf.finding.rule_id == "warehouse_auto_stop_disabled"
            for rf in review.findings
        )


class _DropByIdModel:
    """Fake council model that drops findings whose id is in ``drop_ids``."""

    def __init__(self, drop_ids: frozenset[str]) -> None:
        self._drop_ids = drop_ids

    @property
    def model_id(self) -> str:
        return "fake"

    async def critique(
        self, request: CritiqueRequest, *, seed: int
    ) -> tuple[Verdict, float]:
        if request.finding_id in self._drop_ids:
            return (Verdict.DROP, 0.9)
        return (Verdict.KEEP, 0.9)


@pytest.mark.unit
class TestRunValidated:
    def test_no_gate_no_validator_matches_plain_run(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        plain = _run(service.run(["warehouse"]))
        validated = _run(service.run_validated(["warehouse"]))
        assert [rf.finding.id for rf in validated.review.findings] == [
            rf.finding.id for rf in plain.findings
        ]
        assert validated.gate is None
        assert validated.council is None

    def test_severity_gate_suppresses_sub_threshold_findings(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        validated = _run(
            service.run_validated(
                gate=SeverityGate(min_severity=Severity.HIGH),
            )
        )
        # Only high-severity findings survive the gate.
        assert all(
            rf.finding.severity == Severity.HIGH
            for rf in validated.review.findings
        )
        assert validated.gate is not None
        assert validated.gate.suppressed_count >= 1

    def test_council_suppresses_rejected_findings(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        council = ValidatorCouncil(
            [_DropByIdModel(frozenset({"warehouse_auto_stop_disabled::wh-idle"}))],
            config=CouncilConfig(model_ids=("fake",)),
        )
        validated = _run(service.run_validated(["warehouse"], validator=council))
        ids = [rf.finding.id for rf in validated.review.findings]
        assert "warehouse_auto_stop_disabled::wh-idle" not in ids
        assert validated.council is not None
        assert validated.council.suppressed_count == 1
        # Spend stays under the council's bounded ceiling.
        assert (
            validated.council.total_model_calls
            <= validated.council.max_possible_calls
        )
