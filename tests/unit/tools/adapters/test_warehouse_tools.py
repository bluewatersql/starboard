"""Unit tests for WarehouseTools adapter.

Tests the tool adapter that provides LLM-friendly interface to warehouse operations.
Includes tests for migrated config/metrics tools (from ClusterTools).
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from starboard_core.domain.models.warehouse import (
    HealthSummary,
    QueryTypeDistribution,
    RiskFactor,
    SLOConfig,
    SLOStatus,
    SLOTarget,
    TimeDistribution,
    WarehouseFingerprint,
    WorkloadPattern,
)
from starboard_server.tools.adapters.base import collect_tool_schemas
from starboard_server.tools.adapters.warehouse_tools import (
    WarehouseTools,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_service() -> AsyncMock:
    """Create mock WarehousePortfolioService."""
    return AsyncMock()


@pytest.fixture
def mock_provider() -> AsyncMock:
    """Create mock SharedContextProvider."""
    return AsyncMock()


@pytest.fixture
def tools(mock_service: AsyncMock) -> WarehouseTools:
    """Create WarehouseTools with mocked service (no provider)."""
    return WarehouseTools(warehouse_service=mock_service)


@pytest.fixture
def tools_with_provider(
    mock_service: AsyncMock, mock_provider: AsyncMock
) -> WarehouseTools:
    """Create WarehouseTools with mocked service and provider."""
    return WarehouseTools(warehouse_service=mock_service, provider=mock_provider)


def _make_fingerprint() -> WarehouseFingerprint:
    """Create a test fingerprint."""
    return WarehouseFingerprint(
        warehouse_id="wh-001",
        warehouse_name="Test Warehouse",
        analysis_window_days=7,
        analyzed_at=datetime.now(UTC),
        total_queries=1000,
        total_bytes_read=10_000_000_000,
        total_bytes_written=1_000_000_000,
        p50_runtime_sec=1.0,
        p75_runtime_sec=2.0,
        p90_runtime_sec=5.0,
        p95_runtime_sec=10.0,
        p99_runtime_sec=20.0,
        avg_concurrency=5.0,
        peak_concurrency=20,
        avg_queue_time_sec=0.5,
        p95_queue_time_sec=2.0,
        queue_rate_pct=5.0,
        query_type_distribution=QueryTypeDistribution(
            select_pct=80.0,
            insert_pct=10.0,
            update_pct=5.0,
            delete_pct=5.0,
        ),
        time_distribution=TimeDistribution(
            hourly_distribution=tuple([100] * 24),
            peak_hours=(10, 11, 14, 15),
            quiet_hours=(0, 1, 2, 3, 4, 5),
        ),
        workload_pattern=WorkloadPattern(
            pattern_type="interactive",
            confidence=0.9,
            description="Interactive workload",
            evidence=("Fast queries", "Low variance"),
        ),
    )


def _make_health_summary() -> HealthSummary:
    """Create a test health summary."""
    return HealthSummary(
        warehouse_id="wh-001",
        warehouse_name="Test Warehouse",
        health_score=85.0,
        health_status="healthy",
        health_trend="stable",
        slo_statuses=(
            SLOStatus(
                slo_type="p95_latency",
                target=15.0,
                actual=10.0,
                compliant=True,
                compliance_pct=100.0,
                trend="stable",
            ),
        ),
        overall_slo_compliance=100.0,
        risk_factors=(
            RiskFactor(
                factor_id="elevated_queue_rate",
                name="Elevated Queue Rate",
                description="Queue rate is above threshold",
                severity="medium",
                impact_score=10.0,
                recommendation="Monitor queue trends",
            ),
        ),
        risk_level="medium",
        immediate_actions=(),
        optimization_opportunities=("Consider auto-scaling",),
    )


def _make_slo_config() -> SLOConfig:
    """Create a test SLO config."""
    return SLOConfig(
        warehouse_id="wh-001",
        targets=(
            SLOTarget(
                slo_type="p95_latency",
                target_value=15.0,
                unit="seconds",
                warning_threshold=22.5,
                critical_threshold=30.0,
            ),
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# =============================================================================
# Portfolio Tests
# =============================================================================


class TestGetWarehousePortfolio:
    """Test get_warehouse_portfolio tool."""

    async def test_returns_portfolio_dict(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Returns portfolio as dictionary."""
        mock_service.get_portfolio.return_value = {
            "warehouses": [{"warehouse_id": "wh-001"}],
            "portfolio_summary": {"total_warehouses": 1},
        }

        result = await tools.get_warehouse_portfolio(window_days=7)

        assert isinstance(result, dict)
        assert "warehouses" in result

    async def test_passes_parameters(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Passes parameters to service."""
        mock_service.get_portfolio.return_value = {"warehouses": []}

        await tools.get_warehouse_portfolio(window_days=30, include_inactive=True)

        mock_service.get_portfolio.assert_called_once_with(
            window_days=30,
            include_inactive=True,
        )


# =============================================================================
# Fingerprint Tests
# =============================================================================


class TestFetchWarehouseFingerprint:
    """Test get_warehouse_fingerprint tool."""

    async def test_returns_fingerprint_dict(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Returns fingerprint as dictionary."""
        mock_service.get_fingerprint.return_value = _make_fingerprint()

        result = await tools.get_warehouse_fingerprint("wh-001")

        assert isinstance(result, dict)
        assert result["warehouse_id"] == "wh-001"

    async def test_includes_all_fingerprint_fields(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Includes all expected fingerprint fields."""
        mock_service.get_fingerprint.return_value = _make_fingerprint()

        result = await tools.get_warehouse_fingerprint("wh-001")

        # Check key fields are present
        assert "warehouse_id" in result
        assert "warehouse_name" in result
        assert "total_queries" in result
        assert "p95_runtime_sec" in result
        assert "workload_pattern" in result
        assert "query_type_distribution" in result
        assert "time_distribution" in result

    async def test_converts_nested_objects(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Converts nested objects to dicts."""
        mock_service.get_fingerprint.return_value = _make_fingerprint()

        result = await tools.get_warehouse_fingerprint("wh-001")

        # Nested objects should be dicts
        assert isinstance(result["workload_pattern"], dict)
        assert result["workload_pattern"]["pattern_type"] == "interactive"
        assert isinstance(result["query_type_distribution"], dict)
        assert isinstance(result["time_distribution"], dict)


# =============================================================================
# Health Tests
# =============================================================================


class TestGetWarehouseHealth:
    """Test get_warehouse_health tool."""

    async def test_returns_health_dict(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Returns health summary as dictionary."""
        mock_service.get_health.return_value = _make_health_summary()

        result = await tools.get_warehouse_health("wh-001")

        assert isinstance(result, dict)
        assert result["warehouse_id"] == "wh-001"

    async def test_includes_health_fields(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Includes all health fields."""
        mock_service.get_health.return_value = _make_health_summary()

        result = await tools.get_warehouse_health("wh-001")

        assert "health_score" in result
        assert "health_status" in result
        assert "risk_factors" in result
        assert "immediate_actions" in result
        assert "slo_statuses" in result

    async def test_converts_risk_factors(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Converts risk factors to list of dicts."""
        mock_service.get_health.return_value = _make_health_summary()

        result = await tools.get_warehouse_health("wh-001")

        assert isinstance(result["risk_factors"], list)
        if result["risk_factors"]:
            risk = result["risk_factors"][0]
            assert "factor_id" in risk
            assert "severity" in risk


# =============================================================================
# SLO Configuration Tests
# =============================================================================


class TestConfigureWarehouseSLO:
    """Test configure_warehouse_slo tool."""

    async def test_returns_config_dict(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Returns SLO config as dictionary."""
        mock_service.configure_slo.return_value = _make_slo_config()

        result = await tools.configure_warehouse_slo(
            warehouse_id="wh-001",
            slo_profile="interactive",
        )

        assert isinstance(result, dict)
        assert result["warehouse_id"] == "wh-001"

    async def test_includes_targets(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Includes SLO targets."""
        mock_service.configure_slo.return_value = _make_slo_config()

        result = await tools.configure_warehouse_slo(warehouse_id="wh-001")

        assert "targets" in result
        assert isinstance(result["targets"], list)
        if result["targets"]:
            target = result["targets"][0]
            assert "slo_type" in target
            assert "target_value" in target

    async def test_passes_custom_values(
        self,
        tools: WarehouseTools,
        mock_service: AsyncMock,
    ) -> None:
        """Passes custom values to service."""
        mock_service.configure_slo.return_value = _make_slo_config()

        await tools.configure_warehouse_slo(
            warehouse_id="wh-001",
            slo_profile="interactive",
            p95_latency_target_sec=20.0,
        )

        mock_service.configure_slo.assert_called_once_with(
            warehouse_id="wh-001",
            slo_profile="interactive",
            p95_latency_target_sec=20.0,
            availability_target_pct=None,
            queue_time_target_sec=None,
        )


# =============================================================================
# Tool Schema Tests
# =============================================================================


class TestToolSchemas:
    """Test tool schemas auto-generated via @tool_schema decorator."""

    @pytest.fixture
    def schemas(self, mock_service: AsyncMock) -> list:
        """Collect schemas from a WarehouseTools instance."""
        wt = WarehouseTools(warehouse_service=mock_service)
        return collect_tool_schemas(wt)

    def test_has_eleven_schemas(self, schemas: list) -> None:
        """Has schemas for all eleven tool methods."""
        assert len(schemas) == 11

    def test_schema_structure(self, schemas: list) -> None:
        """Schemas have correct structure."""
        for schema in schemas:
            assert "type" in schema
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]

    def test_portfolio_schema(self, schemas: list) -> None:
        """Portfolio schema is correct."""
        schema = next(
            s for s in schemas if s["function"]["name"] == "get_warehouse_portfolio"
        )
        params = schema["function"]["parameters"]
        assert "window_days" in params["properties"]
        assert "include_inactive" in params["properties"]

    def test_fingerprint_schema_requires_warehouse_id(self, schemas: list) -> None:
        """Fingerprint schema requires warehouse_id."""
        schema = next(
            s for s in schemas if s["function"]["name"] == "get_warehouse_fingerprint"
        )
        assert "warehouse_id" in schema["function"]["parameters"]["required"]

    def test_health_schema_requires_warehouse_id(self, schemas: list) -> None:
        """Health schema requires warehouse_id."""
        schema = next(
            s for s in schemas if s["function"]["name"] == "get_warehouse_health"
        )
        assert "warehouse_id" in schema["function"]["parameters"]["required"]

    def test_slo_schema_requires_warehouse_id(self, schemas: list) -> None:
        """SLO schema requires warehouse_id."""
        schema = next(
            s for s in schemas if s["function"]["name"] == "configure_warehouse_slo"
        )
        assert "warehouse_id" in schema["function"]["parameters"]["required"]


# =============================================================================
# Basic Config/Metrics Tests (Migrated from ClusterTools)
# =============================================================================


class TestGetWarehouseConfig:
    """Test get_warehouse_config tool (migrated from ClusterTools)."""

    async def test_returns_config_when_found(
        self,
        tools_with_provider: WarehouseTools,
    ) -> None:
        """Returns config when warehouse exists."""
        with patch(
            "starboard_server.tools.adapters.warehouse_tools.get_transformed",
            new_callable=AsyncMock,
        ) as mock_get_transformed:
            mock_get_transformed.return_value = {
                "id": "wh-001",
                "name": "Test Warehouse",
                "size": "Medium",
            }

            result = await tools_with_provider.get_warehouse_config("wh-001")

            assert result["found"] is True
            assert result["warehouse_id"] == "wh-001"
            assert result["config"]["name"] == "Test Warehouse"

    async def test_returns_not_found_when_missing(
        self,
        tools_with_provider: WarehouseTools,
    ) -> None:
        """Returns found=False when warehouse doesn't exist."""
        with patch(
            "starboard_server.tools.adapters.warehouse_tools.get_transformed",
            new_callable=AsyncMock,
        ) as mock_get_transformed:
            mock_get_transformed.return_value = None

            result = await tools_with_provider.get_warehouse_config("nonexistent")

            assert result["found"] is False
            assert "not found" in result["reason"].lower()

    async def test_returns_error_without_provider(
        self,
        tools: WarehouseTools,
    ) -> None:
        """Returns error when provider not configured."""
        result = await tools.get_warehouse_config("wh-001")

        assert result["found"] is False
        assert "provider not configured" in result["reason"].lower()


class TestGetWarehouseMetrics:
    """Test get_warehouse_metrics tool (migrated from ClusterTools)."""

    async def test_returns_metrics_when_found(
        self,
        tools_with_provider: WarehouseTools,
    ) -> None:
        """Returns metrics when warehouse exists."""
        with patch(
            "starboard_server.tools.adapters.warehouse_tools.analyze_warehouse_queries",
            new_callable=AsyncMock,
        ) as mock_analyze:
            mock_analyze.return_value = {
                "total_queries": 1000,
                "avg_runtime_sec": 2.5,
                "p95_runtime_sec": 10.0,
            }

            result = await tools_with_provider.get_warehouse_metrics("wh-001")

            assert result["found"] is True
            assert result["warehouse_id"] == "wh-001"
            assert result["metrics"]["total_queries"] == 1000

    async def test_returns_not_found_when_missing(
        self,
        tools_with_provider: WarehouseTools,
    ) -> None:
        """Returns found=False when metrics unavailable."""
        with patch(
            "starboard_server.tools.adapters.warehouse_tools.analyze_warehouse_queries",
            new_callable=AsyncMock,
        ) as mock_analyze:
            mock_analyze.return_value = None

            result = await tools_with_provider.get_warehouse_metrics("nonexistent")

            assert result["found"] is False
            assert "unavailable" in result["reason"].lower()

    async def test_returns_error_without_provider(
        self,
        tools: WarehouseTools,
    ) -> None:
        """Returns error when provider not configured."""
        result = await tools.get_warehouse_metrics("wh-001")

        assert result["found"] is False
        assert "provider not configured" in result["reason"].lower()


class TestGetQueryRuntimeMetrics:
    """Test get_query_runtime_metrics tool (migrated from ClusterTools)."""

    async def test_returns_metrics_when_found(
        self,
        tools_with_provider: WarehouseTools,
    ) -> None:
        """Returns metrics when statement exists."""
        with patch(
            "starboard_server.tools.adapters.warehouse_tools.get_transformed",
            new_callable=AsyncMock,
        ) as mock_get_transformed:
            mock_get_transformed.return_value = {
                "statement_id": "stmt-001",
                "duration_ms": 2500,
                "rows_produced": 10000,
            }

            result = await tools_with_provider.get_query_runtime_metrics("stmt-001")

            assert result["found"] is True
            assert result["statement_id"] == "stmt-001"
            assert result["metrics"]["duration_ms"] == 2500

    async def test_returns_not_found_when_missing(
        self,
        tools_with_provider: WarehouseTools,
    ) -> None:
        """Returns found=False when statement doesn't exist."""
        with patch(
            "starboard_server.tools.adapters.warehouse_tools.get_transformed",
            new_callable=AsyncMock,
        ) as mock_get_transformed:
            mock_get_transformed.return_value = None

            result = await tools_with_provider.get_query_runtime_metrics("nonexistent")

            assert result["found"] is False
            assert "unavailable" in result["reason"].lower()

    async def test_returns_error_without_provider(
        self,
        tools: WarehouseTools,
    ) -> None:
        """Returns error when provider not configured."""
        result = await tools.get_query_runtime_metrics("stmt-001")

        assert result["found"] is False
        assert "provider not configured" in result["reason"].lower()
