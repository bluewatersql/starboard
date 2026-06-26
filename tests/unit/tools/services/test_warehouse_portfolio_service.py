# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for WarehousePortfolioService.

Tests the service orchestration layer for warehouse portfolio analysis.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from starboard_core.domain.models.warehouse import (
    SLOConfig,
    SLOTarget,
    WarehouseFingerprint,
)
from starboard_server.tools.services.warehouse_portfolio_service import (
    WarehousePortfolioService,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_analytics_executor() -> AsyncMock:
    """Create mock analytics executor."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_warehouse_data() -> AsyncMock:
    """Create mock warehouse data provider."""
    mock = AsyncMock()
    mock.list_warehouses.return_value = [
        {
            "id": "wh-001",
            "name": "Analytics Warehouse",
            "warehouse_type": "serverless",
            "state": "RUNNING",
        },
        {
            "id": "wh-002",
            "name": "ETL Warehouse",
            "warehouse_type": "standard",
            "state": "RUNNING",
        },
    ]
    mock.get_warehouse.return_value = {
        "id": "wh-001",
        "name": "Analytics Warehouse",
        "warehouse_type": "serverless",
        "state": "RUNNING",
    }
    return mock


@pytest.fixture
def mock_slo_store() -> AsyncMock:
    """Create mock SLO store."""
    mock = AsyncMock()
    mock.get_slo_config.return_value = None
    mock.save_slo_config.return_value = None
    return mock


@pytest.fixture
def service(
    mock_analytics_executor: AsyncMock,
    mock_warehouse_data: AsyncMock,
    mock_slo_store: AsyncMock,
) -> WarehousePortfolioService:
    """Create service with mocked dependencies."""
    return WarehousePortfolioService(
        analytics_executor=mock_analytics_executor,
        warehouse_data=mock_warehouse_data,
        slo_store=mock_slo_store,
    )


def _make_portfolio_row(
    warehouse_id: str,
    total_queries: int = 1000,
    avg_duration_ms: float = 1500.0,
    p95_duration_ms: float = 5000.0,
    queued_query_pct: float = 5.0,
) -> dict[str, Any]:
    """Create a test portfolio query result row."""
    return {
        "warehouse_id": warehouse_id,
        "total_queries": total_queries,
        "unique_users": 10,
        "avg_duration_ms": avg_duration_ms,
        "p50_duration_ms": avg_duration_ms * 0.5,
        "p95_duration_ms": p95_duration_ms,
        "p99_duration_ms": p95_duration_ms * 1.5,
        "avg_queue_time_ms": 500.0,
        "queued_query_pct": queued_query_pct,
        "total_bytes_read": 10_000_000_000,
        "error_count": 10,
        "error_rate_pct": 1.0,
    }


def _make_fingerprint_rows(
    warehouse_id: str,
    count: int = 100,
) -> list[dict[str, Any]]:
    """Create test fingerprint query result rows."""
    return [
        {
            "statement_id": f"stmt-{i:04d}",
            "warehouse_id": warehouse_id,
            "statement_type": "SELECT",
            "total_duration_ms": 1000 + i * 10,
            "waiting_in_queue_ms": 50,
            "read_bytes": 1_000_000,
            "written_bytes": 0,
            "start_time": datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC),
            "read_rows": 1000,
            "executed_by": "user@example.com",
        }
        for i in range(count)
    ]


# =============================================================================
# Portfolio Tests
# =============================================================================


class TestGetPortfolio:
    """Test portfolio retrieval."""

    async def test_get_portfolio_returns_warehouses(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Portfolio returns list of warehouses."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": [
                _make_portfolio_row("wh-001"),
                _make_portfolio_row("wh-002"),
            ]
        }

        result = await service.get_portfolio(window_days=7)

        assert "warehouses" in result
        assert len(result["warehouses"]) == 2
        assert result["warehouses"][0]["warehouse_id"] == "wh-001"
        assert result["warehouses"][1]["warehouse_id"] == "wh-002"

    async def test_get_portfolio_includes_summary(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Portfolio includes summary statistics."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": [
                _make_portfolio_row("wh-001", total_queries=500),
                _make_portfolio_row("wh-002", total_queries=300),
            ]
        }

        result = await service.get_portfolio(window_days=7)

        assert "portfolio_summary" in result
        summary = result["portfolio_summary"]
        assert summary["total_warehouses"] == 2
        assert summary["total_queries"] == 800

    async def test_get_portfolio_calculates_health_scores(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Portfolio includes health scores for each warehouse."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": [
                _make_portfolio_row("wh-001", p95_duration_ms=5000),  # Healthy
                _make_portfolio_row("wh-002", p95_duration_ms=100000),  # Critical
            ]
        }

        result = await service.get_portfolio(window_days=7)

        # First warehouse should be healthier
        assert (
            result["warehouses"][0]["health_score"]
            > result["warehouses"][1]["health_score"]
        )

    async def test_get_portfolio_counts_health_statuses(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Portfolio summary counts healthy/warning/critical."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": [
                _make_portfolio_row(
                    "wh-001", p95_duration_ms=5000, queued_query_pct=2
                ),  # Healthy
                _make_portfolio_row(
                    "wh-002", p95_duration_ms=25000, queued_query_pct=15
                ),  # Warning
                _make_portfolio_row(
                    "wh-003", p95_duration_ms=100000, queued_query_pct=60
                ),  # Critical
            ]
        }

        result = await service.get_portfolio(window_days=7)

        summary = result["portfolio_summary"]
        assert summary["healthy_count"] >= 1
        assert summary["total_warehouses"] == 3

    async def test_get_portfolio_uses_correct_parameters(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Portfolio calls analytics with correct parameters."""
        mock_analytics_executor.execute_query.return_value = {"rows": []}

        await service.get_portfolio(window_days=30, include_inactive=True)

        mock_analytics_executor.execute_query.assert_called_once_with(
            query_id="warehouse_portfolio_summary_v1",
            parameters={
                "window_days": 30,
                "min_queries": None,  # include_inactive=True
                "limit": 100,
            },
        )


# =============================================================================
# Fingerprint Tests
# =============================================================================


class TestGetFingerprint:
    """Test fingerprint generation."""

    async def test_get_fingerprint_returns_fingerprint(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Fingerprint returns WarehouseFingerprint."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": _make_fingerprint_rows("wh-001", count=100)
        }

        result = await service.get_fingerprint("wh-001", window_days=7)

        assert isinstance(result, WarehouseFingerprint)
        assert result.warehouse_id == "wh-001"
        assert result.total_queries == 100

    async def test_get_fingerprint_calculates_percentiles(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Fingerprint includes calculated percentiles."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": _make_fingerprint_rows("wh-001", count=100)
        }

        result = await service.get_fingerprint("wh-001", window_days=7)

        assert result.p50_runtime_sec > 0
        assert result.p95_runtime_sec > 0
        assert result.p99_runtime_sec > 0
        # Percentiles should be ordered
        assert (
            result.p50_runtime_sec <= result.p95_runtime_sec <= result.p99_runtime_sec
        )

    async def test_get_fingerprint_classifies_workload(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Fingerprint includes workload classification."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": _make_fingerprint_rows("wh-001", count=100)
        }

        result = await service.get_fingerprint("wh-001", window_days=7)

        assert result.workload_pattern is not None
        assert result.workload_pattern.pattern_type in (
            "interactive",
            "batch",
            "reporting",
            "ad_hoc",
            "mixed",
        )

    async def test_get_fingerprint_uses_warehouse_name(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
        mock_warehouse_data: AsyncMock,
    ) -> None:
        """Fingerprint uses warehouse name from config."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": _make_fingerprint_rows("wh-001", count=10)
        }
        mock_warehouse_data.get_warehouse.return_value = {"name": "My Custom Name"}

        result = await service.get_fingerprint("wh-001", window_days=7)

        assert result.warehouse_name == "My Custom Name"


# =============================================================================
# Health Tests
# =============================================================================


class TestGetHealth:
    """Test health calculation."""

    async def test_get_health_returns_health_summary(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Health returns HealthSummary."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": _make_fingerprint_rows("wh-001", count=100)
        }

        result = await service.get_health("wh-001", window_days=7)

        from starboard_core.domain.models.warehouse import HealthSummary

        assert isinstance(result, HealthSummary)
        assert result.warehouse_id == "wh-001"

    async def test_get_health_calculates_score(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Health includes calculated score."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": _make_fingerprint_rows("wh-001", count=100)
        }

        result = await service.get_health("wh-001", window_days=7)

        assert 0 <= result.health_score <= 100
        assert result.health_status in ("healthy", "warning", "critical", "unknown")

    async def test_get_health_identifies_risks(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Health identifies risk factors."""
        # Create rows with high queue times
        rows = _make_fingerprint_rows("wh-001", count=100)
        for row in rows:
            row["waiting_in_queue_ms"] = 30000  # 30s queue time

        mock_analytics_executor.execute_query.return_value = {"rows": rows}

        result = await service.get_health("wh-001", window_days=7)

        # Should have some risk factors due to high queue time
        assert isinstance(result.risk_factors, tuple)

    async def test_get_health_uses_slo_config(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
        mock_slo_store: AsyncMock,
    ) -> None:
        """Health uses SLO config when available."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": _make_fingerprint_rows("wh-001", count=100)
        }
        mock_slo_store.get_slo_config.return_value = SLOConfig(
            warehouse_id="wh-001",
            targets=(
                SLOTarget(
                    slo_type="p95_latency",
                    target_value=5.0,
                    unit="seconds",
                ),
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        result = await service.get_health("wh-001", window_days=7)

        # Should have SLO statuses
        assert isinstance(result.slo_statuses, tuple)


# =============================================================================
# SLO Configuration Tests
# =============================================================================


class TestConfigureSLO:
    """Test SLO configuration."""

    async def test_configure_slo_saves_config(
        self,
        service: WarehousePortfolioService,
        mock_slo_store: AsyncMock,
    ) -> None:
        """Configure SLO saves to store."""
        result = await service.configure_slo(
            warehouse_id="wh-001",
            slo_profile="interactive",
        )

        assert isinstance(result, SLOConfig)
        assert result.warehouse_id == "wh-001"
        mock_slo_store.save_slo_config.assert_called_once()

    async def test_configure_slo_uses_profile_defaults(
        self,
        service: WarehousePortfolioService,
        mock_slo_store: AsyncMock,
    ) -> None:
        """Configure SLO uses profile defaults."""
        result = await service.configure_slo(
            warehouse_id="wh-001",
            slo_profile="interactive",
        )

        # Interactive profile has p95 target of 15s
        p95_target = next(
            (t for t in result.targets if t.slo_type == "p95_latency"), None
        )
        assert p95_target is not None
        assert p95_target.target_value == 15.0

    async def test_configure_slo_custom_overrides_profile(
        self,
        service: WarehousePortfolioService,
        mock_slo_store: AsyncMock,
    ) -> None:
        """Custom values override profile defaults."""
        result = await service.configure_slo(
            warehouse_id="wh-001",
            slo_profile="interactive",
            p95_latency_target_sec=30.0,  # Override default 15
        )

        p95_target = next(
            (t for t in result.targets if t.slo_type == "p95_latency"), None
        )
        assert p95_target is not None
        assert p95_target.target_value == 30.0

    async def test_configure_slo_without_store_raises(
        self,
        mock_analytics_executor: AsyncMock,
        mock_warehouse_data: AsyncMock,
    ) -> None:
        """Configure SLO without store raises error."""
        service = WarehousePortfolioService(
            analytics_executor=mock_analytics_executor,
            warehouse_data=mock_warehouse_data,
            slo_store=None,  # No store
        )

        with pytest.raises(ValueError, match="SLO storage not configured"):
            await service.configure_slo(warehouse_id="wh-001")


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    async def test_empty_portfolio(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Handle empty portfolio gracefully."""
        mock_analytics_executor.execute_query.return_value = {"rows": []}

        result = await service.get_portfolio(window_days=7)

        assert result["warehouses"] == []
        assert result["portfolio_summary"]["total_warehouses"] == 0

    async def test_empty_fingerprint_data(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
    ) -> None:
        """Handle empty fingerprint data gracefully."""
        mock_analytics_executor.execute_query.return_value = {"rows": []}

        result = await service.get_fingerprint("wh-001", window_days=7)

        assert result.total_queries == 0

    async def test_missing_warehouse_config(
        self,
        service: WarehousePortfolioService,
        mock_analytics_executor: AsyncMock,
        mock_warehouse_data: AsyncMock,
    ) -> None:
        """Handle missing warehouse config gracefully."""
        mock_analytics_executor.execute_query.return_value = {
            "rows": _make_fingerprint_rows("wh-unknown", count=10)
        }
        mock_warehouse_data.get_warehouse.return_value = None

        result = await service.get_fingerprint("wh-unknown", window_days=7)

        # Should use warehouse_id as name
        assert result.warehouse_name == "wh-unknown"
