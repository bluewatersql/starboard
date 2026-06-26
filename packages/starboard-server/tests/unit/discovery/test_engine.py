# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for DiscoveryEngine.

Tests cover:
- run: data_only mode, full pipeline, no LLM client
- _extract_products: success, failed audit
- _group_by_domain: excludes audit, includes billing/jobs
- EngineConfig defaults
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest
from starboard_core.domain.models.discovery.query import (
    PackResult,
    QueryPack,
    QueryResult,
    SystemQuery,
)
from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.discovery.engine import DiscoveryEngine, EngineConfig


def _valid_domain_analysis_dict(domain: str = "billing") -> dict:
    """Valid DomainAnalysis dict matching the schema."""
    return {
        "domain": domain,
        "grade": "B",
        "score": 78,
        "summary": f"{domain} summary",
        "observations": ["obs1"],
        "patterns": ["pattern1"],
        "findings": [],
        "recommended_actions": ["action1"],
        "data_coverage": {
            "queries_executed": 3,
            "queries_succeeded": 3,
            "time_range_start": None,
            "time_range_end": None,
            "gaps": [],
        },
    }


def _audit_df() -> pl.DataFrame:
    """Audit DataFrame with billing_origin_product column (used in tests)."""
    return pl.DataFrame(
        {
            "billing_origin_product": ["JOBS", "SQL", "ALL_PURPOSE"],
            "total_dbus": [1000.0, 500.0, 300.0],
        }
    )


class MockSQLExecutor:
    """Mock SQL executor returning configurable DataFrames by pattern."""

    def __init__(
        self,
        audit_df: pl.DataFrame | None = None,
        domain_df: pl.DataFrame | None = None,
    ) -> None:
        self.audit_df = _audit_df() if audit_df is None else audit_df
        self.domain_df = pl.DataFrame() if domain_df is None else domain_df

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        # Audit SQL contains usage_unit; domain packs use different patterns
        if "usage_unit" in sql:
            return self.audit_df
        return self.domain_df


class MinimalQueryRegistry:
    """Minimal registry for tests: audit pack + one domain pack."""

    def __init__(self) -> None:
        from starboard_server.discovery.query_packs.audit import AUDIT_PACK

        self._audit_pack = AUDIT_PACK
        self._minimal_query = SystemQuery(
            query_id="TEST-Q01",
            name="Test",
            description="Test",
            sql_template="SELECT 1 AS x FROM system.test WHERE ts > INTERVAL {lookback_days} DAYS",
            required_tables=(),
            domain="billing",
        )
        self._billing_pack = QueryPack(
            pack_id="billing",
            domain="billing",
            name="Billing",
            description="Test",
            queries=(self._minimal_query,),
            gating_products=frozenset(),
        )

    @property
    def all_packs(self) -> list[QueryPack]:
        return [self._audit_pack]

    def get_packs_for_products(
        self,
        active_products: set[str] | dict[str, float],
        min_dbu_threshold: float = 0.0,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[QueryPack]:
        return [self._billing_pack]


@pytest.mark.asyncio
async def test_run_data_only_mode() -> None:
    """Engine with data_only=True: pack_results populated, no report, no domain_analyses."""
    executor = MockSQLExecutor()
    registry = MinimalQueryRegistry()
    config = EngineConfig(data_only=True)
    engine = DiscoveryEngine(
        sql_executor=executor,
        llm_client=None,
        config=config,
        query_registry=registry,
    )

    result = await engine.run()

    assert result.pack_results
    assert result.report is None
    assert result.domain_analyses == []
    assert result.errors == []


@pytest.mark.asyncio
async def test_run_full_pipeline(tmp_path: Path) -> None:
    """Full pipeline with mock LLM: report and domain_analyses populated, output files exist."""
    executor = MockSQLExecutor(domain_df=pl.DataFrame({"col": [1]}))
    registry = MinimalQueryRegistry()
    mock_llm = MagicMock(spec=BaseLLMClient)
    mock_llm.json_response = AsyncMock(
        side_effect=[
            _valid_domain_analysis_dict(domain="billing"),
            ValueError("synthesis fail"),  # Triggers synthesizer fallback
        ]
    )
    config = EngineConfig(data_only=False, output_dir=str(tmp_path))
    engine = DiscoveryEngine(
        sql_executor=executor,
        llm_client=mock_llm,
        config=config,
        query_registry=registry,
    )

    result = await engine.run()

    assert result.report is not None
    assert result.domain_analyses
    assert result.output_files
    for p in result.output_files:
        assert Path(p).exists()


@pytest.mark.asyncio
async def test_run_no_llm_client() -> None:
    """Engine with data_only=False and no LLM: errors contain message, report is None."""
    executor = MockSQLExecutor()
    registry = MinimalQueryRegistry()
    config = EngineConfig(data_only=False)
    engine = DiscoveryEngine(
        sql_executor=executor,
        llm_client=None,
        config=config,
        query_registry=registry,
    )

    result = await engine.run()

    assert any("LLM client not provided" in e for e in result.errors)
    assert result.report is None


@pytest.mark.asyncio
async def test_extract_products_success() -> None:
    """_extract_products returns product -> dbu dict from successful audit."""
    executor = MockSQLExecutor()
    registry = MinimalQueryRegistry()
    engine = DiscoveryEngine(
        sql_executor=executor,
        query_registry=registry,
    )

    audit_result = QueryResult(
        query_id="P-AUDIT01",
        domain="audit",
        data=pl.DataFrame(
            {
                "billing_origin_product": ["JOBS", "SQL", "NOTEBOOKS", "JOBS"],
                "total_dbus": [100.0, 50.0, 25.0, 80.0],
            }
        ),
        row_count=4,
        execution_time_ms=10.0,
    )

    products = engine._extract_products(audit_result)

    assert isinstance(products, dict)
    assert sorted(products.keys()) == ["JOBS", "NOTEBOOKS", "SQL"]
    assert products["JOBS"] == 180.0  # 100 + 80
    assert products["SQL"] == 50.0
    assert products["NOTEBOOKS"] == 25.0


@pytest.mark.asyncio
async def test_extract_products_failed_audit() -> None:
    """_extract_products returns empty dict when audit failed."""
    executor = MockSQLExecutor()
    registry = MinimalQueryRegistry()
    engine = DiscoveryEngine(
        sql_executor=executor,
        query_registry=registry,
    )

    audit_result = QueryResult(
        query_id="P-AUDIT01",
        domain="audit",
        data=None,
        error="Table not found",
        execution_time_ms=0.0,
    )

    products = engine._extract_products(audit_result)

    assert products == {}


@pytest.mark.asyncio
async def test_group_by_domain() -> None:
    """_group_by_domain excludes audit, includes billing and jobs."""
    executor = MockSQLExecutor()
    registry = MinimalQueryRegistry()
    engine = DiscoveryEngine(
        sql_executor=executor,
        query_registry=registry,
    )

    qr = QueryResult(
        query_id="C-B01",
        domain="billing",
        data=pl.DataFrame(),
        row_count=0,
    )
    pack_billing = PackResult("billing", "billing", (qr,))
    pack_jobs = PackResult("jobs", "jobs", (qr,))
    pack_audit = PackResult("audit", "audit", (qr,))

    grouped = engine._group_by_domain([pack_billing, pack_jobs, pack_audit])

    assert "audit" not in grouped
    assert "billing" in grouped
    assert "jobs" in grouped
    assert len(grouped["billing"]) == 1
    assert len(grouped["jobs"]) == 1


def test_engine_config_defaults() -> None:
    """EngineConfig has expected default values."""
    config = EngineConfig()
    assert config.lookback_days == 30
    assert config.max_parallelism == 4
    assert config.data_only is False
    assert config.min_dbu_threshold == 10.0
