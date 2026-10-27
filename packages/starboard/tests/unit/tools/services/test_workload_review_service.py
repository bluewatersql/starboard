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
    {"statement_id": "stmt-prune", "statement_text": "SELECT id FROM t", "shuffle_gb": 1.0, "pruning_ratio": 0.02, "read_partitions": 500},
    {"statement_id": "stmt-shuffle", "statement_text": "SELECT * FROM t", "shuffle_gb": 25.0, "pruning_ratio": 0.9, "read_partitions": 10},
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

    def test_context_queries_are_fetched_on_the_live_path(self) -> None:
        # warehouse_recent_resize reads W-W07 (evidence) + W-W01/W-W05 (context).
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        needed = service._needed_evidence_query_ids(["warehouse"])
        assert {"W-W01", "W-W02", "W-W05", "W-W07"} <= needed
        jobs = service._needed_evidence_query_ids(["jobs"])
        assert {"C-J08", "C-J09", "F-03"} <= jobs

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

@pytest.mark.unit
class TestWorkloadReviewProgress:
    """The service reports phase progress so a long scan is not silent."""

    def test_run_emits_scan_progress(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        events: list[str] = []
        _run(service.run(["warehouse"], progress=events.append))

        assert any("scanning" in e for e in events)
        assert any("scan complete" in e for e in events)

    def test_run_validated_emits_gate_progress(self) -> None:
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        events: list[str] = []
        _run(
            service.run_validated(
                ["warehouse"],
                gate=SeverityGate(min_severity=Severity.LOW),
                progress=events.append,
            )
        )

        assert any("severity gate" in e for e in events)


class _RoutingSource:
    """A ``QuerySource`` that routes every query to its own executor."""

    def __init__(self, executor) -> None:  # noqa: ANN001
        self.executor = executor
        self.prepared: list[str] = []

    def prepare(self, query, rendered_sql, render=None):  # noqa: ANN001, ARG002
        from starboard.discovery.sources import PreparedQuery

        self.prepared.append(query.query_id)
        return PreparedQuery(sql=rendered_sql, executor=self.executor)


class _F01Executor(_FakeSQLExecutor):
    async def execute_sql(self, sql: str, *args, **kwargs) -> pl.DataFrame:
        if "Window totals by product and usage_unit" in sql:
            self.executed.append(sql)
            return pl.DataFrame(
                [
                    {"billing_origin_product": "JOBS", "usage_unit": "DBU", "usage_quantity": 5.0},
                    {"billing_origin_product": "JOBS", "usage_unit": "DBU", "usage_quantity": 2.5},
                    {"billing_origin_product": "DATABASE", "usage_unit": "DSU", "usage_quantity": 9.0},
                ]
            )
        return await super().execute_sql(sql, *args, **kwargs)


@pytest.mark.unit
class TestWorkloadReviewServiceSource:
    def test_source_routes_every_query_and_bypasses_base_executor(self) -> None:
        class _Guard:
            async def execute_sql(self, sql: str):  # noqa: ARG002
                raise AssertionError("base executor must not run with a source")

        internal = _F01Executor()
        source = _RoutingSource(internal)
        service = WorkloadReviewService(
            _Guard(), enable_cache=False, workspace="ws-1", source=source
        )
        review = _run(service.run(["warehouse"]))

        assert "F-01" in source.prepared
        assert internal.executed
        assert not review.degraded
        assert any(rf.finding.id.endswith("::wh-idle") for rf in review.findings)
        # DBU only: the DSU row is excluded from products_dbu.
        assert service.products_dbu == {"JOBS": 7.5}

    def test_products_query_failure_does_not_degrade_review(self) -> None:
        service = WorkloadReviewService(
            _FakeSQLExecutor(fail_markers=("Window totals by product",)),
            enable_cache=False,
        )
        review = _run(service.run(["warehouse"]))
        assert service.products_dbu == {}
        assert not review.degraded


@pytest.mark.unit
class TestRound4EvidenceReport:
    def test_live_path_reports_unavailable_and_public_cost_basis(self) -> None:
        from starboard_core.domain.models.review import COST_BASIS_LABEL

        service = WorkloadReviewService(
            _FakeSQLExecutor(fail_markers=("auto_stop_waste_pct",)),
            enable_cache=False,
        )
        review = _run(service.run(["warehouse"]))
        assert "W-W02" in service.evidence_report["unavailable"]
        assert review.unavailable_queries == ("W-W02",)
        assert review.unavailable_domains == ("warehouse",)
        assert review.cost_basis == COST_BASIS_LABEL

    def test_non_public_source_uses_telemetry_cost_basis(self) -> None:
        service = WorkloadReviewService(
            _FakeSQLExecutor(),
            enable_cache=False,
            source=_RoutingSource(_FakeSQLExecutor()),
        )
        review = _run(service.run(["warehouse"]))
        assert "workspace telemetry" in review.cost_basis

    def test_attempts_surface_when_results_carry_them(self, monkeypatch) -> None:
        from starboard_core.domain.models.discovery.query import (
            PackResult,
            QueryResult,
        )

        async def _fake_execute_pack(self, pack):  # noqa: ANN001, ARG001
            return PackResult(
                pack_id="workload_review",
                domain="workload_review",
                results=(
                    QueryResult(
                        query_id="W-W02",
                        domain="warehouse",
                        data=None,
                        error="statement timed out",
                        attempts=2,
                    ),
                    QueryResult(
                        query_id="W-W01",
                        domain="warehouse",
                        data=pl.DataFrame(_W_W01_ROWS),
                        row_count=len(_W_W01_ROWS),
                        result_limit=len(_W_W01_ROWS),
                        attempts=1,
                    ),
                ),
            )

        monkeypatch.setattr(
            "starboard.tools.services.workload_review_service.QueryPackExecutor.execute_pack",
            _fake_execute_pack,
        )
        service = WorkloadReviewService(_FakeSQLExecutor(), enable_cache=False)
        review = _run(service.run(["warehouse"]))
        # Only retried statements (attempts > 1) are surfaced.
        assert service.evidence_report["query_attempts"] == {"W-W02": 2}
        assert service.evidence_report["limit_reached_query_ids"] == ["W-W01"]
        assert all(rf.metadata.get("evidence_capped") for rf in review.findings)
