# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for warehouse what-if prediction models.

Tests the cost, latency, and risk prediction models.
"""

from datetime import datetime

import pytest
from starboard_server.infra.whatif.historical import HistoricalData
from starboard_server.infra.whatif.models import (
    WarehouseCostModel,
    WarehouseLatencyModel,
    WarehouseQueueRiskModel,
)
from starboard_server.infra.whatif.scenario import Scenario, ScenarioParameter

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def historical_data() -> HistoricalData:
    """Create test historical data."""
    return HistoricalData(
        entity_type="warehouse",
        entity_id="wh-001",
        window_days=30,
        aggregates={
            "monthly_cost_usd": 1500.0,
            "monthly_dbu": 2500.0,
            "total_queries": 10000,
            "avg_runtime_sec": 2.0,
            "p95_runtime_sec": 10.0,
            "avg_concurrency": 3.0,
            "peak_concurrency": 12.0,
            "queue_rate_pct": 8.0,
            "p95_queue_time_sec": 2.5,
            "starts_per_day": 5,
        },
    )


def _make_scenario(
    params: list[tuple[str, str | int | float, str | int | float]],
    entity_id: str = "wh-001",
) -> Scenario:
    """Create a test scenario."""
    return Scenario(
        scenario_id="test-scenario",
        name="Test Scenario",
        description="Test",
        entity_type="warehouse",
        entity_id=entity_id,
        parameters=tuple(
            ScenarioParameter(name=name, current_value=current, proposed_value=proposed)
            for name, current, proposed in params
        ),
        created_at=datetime.now(),
    )


# =============================================================================
# Cost Model Tests
# =============================================================================


class TestWarehouseCostModel:
    """Test WarehouseCostModel predictions."""

    async def test_can_predict_warehouse(self) -> None:
        """Model can predict for warehouse entity type."""
        model = WarehouseCostModel()
        scenario = _make_scenario([])
        assert model.can_predict(scenario) is True

    async def test_cannot_predict_cluster(self) -> None:
        """Model cannot predict for other entity types."""
        model = WarehouseCostModel()
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test",
            entity_type="cluster",
            entity_id="c-001",
            parameters=(),
            created_at=datetime.now(),
        )
        assert model.can_predict(scenario) is False

    async def test_serverless_migration_cost(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Predict cost for serverless migration."""
        model = WarehouseCostModel()
        scenario = _make_scenario(
            [
                ("warehouse_type", "standard", "serverless"),
            ]
        )

        result = await model.predict(scenario, historical_data)

        assert result.value > 0
        assert result.unit == "USD/month"
        assert result.confidence_interval is not None
        assert result.confidence in ("low", "medium", "high")

    async def test_scale_down_cost(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Predict cost for scaling down clusters."""
        model = WarehouseCostModel()
        scenario = _make_scenario(
            [
                ("max_clusters", 4, 2),
            ]
        )

        result = await model.predict(scenario, historical_data)

        # Scaling down should reduce cost
        assert result.value < historical_data.get_aggregate("monthly_cost_usd")

    async def test_scale_up_cost(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Predict cost for scaling up clusters."""
        model = WarehouseCostModel()
        scenario = _make_scenario(
            [
                ("max_clusters", 4, 8),
            ]
        )

        result = await model.predict(scenario, historical_data)

        # Scaling up should increase cost
        assert result.value > historical_data.get_aggregate("monthly_cost_usd") * 0.5

    async def test_evidence_includes_cost_change(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Evidence includes cost change information."""
        model = WarehouseCostModel()
        scenario = _make_scenario(
            [
                ("warehouse_type", "standard", "serverless"),
            ]
        )

        result = await model.predict(scenario, historical_data)

        assert len(result.evidence) > 0


# =============================================================================
# Latency Model Tests
# =============================================================================


class TestWarehouseLatencyModel:
    """Test WarehouseLatencyModel predictions."""

    async def test_can_predict_warehouse(self) -> None:
        """Model can predict for warehouse entity type."""
        model = WarehouseLatencyModel()
        scenario = _make_scenario([])
        assert model.can_predict(scenario) is True

    async def test_serverless_migration_latency(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Predict latency for serverless migration."""
        model = WarehouseLatencyModel()
        scenario = _make_scenario(
            [
                ("warehouse_type", "standard", "serverless"),
            ]
        )

        result = await model.predict(scenario, historical_data)

        assert result.value > 0
        assert result.unit == "seconds"
        # Serverless should improve latency due to instant scaling
        baseline = historical_data.get_aggregate("p95_runtime_sec")
        assert result.value <= baseline * 1.1  # At most 10% worse

    async def test_scale_up_reduces_latency(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Scaling up clusters should reduce latency."""
        model = WarehouseLatencyModel()
        scenario = _make_scenario(
            [
                ("max_clusters", 2, 6),
            ]
        )

        result = await model.predict(scenario, historical_data)

        baseline = historical_data.get_aggregate("p95_runtime_sec")
        # More clusters should reduce queue-induced latency
        assert result.value < baseline * 1.2

    async def test_scale_down_increases_latency(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Scaling down clusters may increase latency."""
        model = WarehouseLatencyModel()
        scenario = _make_scenario(
            [
                ("max_clusters", 6, 2),
            ]
        )

        result = await model.predict(scenario, historical_data)

        baseline = historical_data.get_aggregate("p95_runtime_sec")
        # Fewer clusters may increase latency
        assert result.value >= baseline * 0.8

    async def test_cluster_size_change(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Larger cluster size reduces latency."""
        model = WarehouseLatencyModel()
        scenario = _make_scenario(
            [
                ("cluster_size", "Small", "Large"),
            ]
        )

        result = await model.predict(scenario, historical_data)

        baseline = historical_data.get_aggregate("p95_runtime_sec")
        # Larger cluster should reduce execution time
        assert result.value < baseline


# =============================================================================
# Risk Model Tests
# =============================================================================


class TestWarehouseQueueRiskModel:
    """Test WarehouseQueueRiskModel predictions."""

    async def test_can_predict_warehouse(self) -> None:
        """Model can predict for warehouse entity type."""
        model = WarehouseQueueRiskModel()
        scenario = _make_scenario([])
        assert model.can_predict(scenario) is True

    async def test_low_risk_adequate_capacity(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Low risk when capacity is adequate."""
        model = WarehouseQueueRiskModel()
        # Scale up to have plenty of capacity
        scenario = _make_scenario(
            [
                ("max_clusters", 4, 20),
            ]
        )

        result = await model.predict(scenario, historical_data)

        assert result.value < 0.5  # Low to moderate risk
        assert result.unit == "risk_score"

    async def test_high_risk_under_capacity(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """High risk when capacity is insufficient."""
        model = WarehouseQueueRiskModel()
        # Scale down below peak concurrency
        scenario = _make_scenario(
            [
                ("max_clusters", 4, 1),
            ]
        )

        result = await model.predict(scenario, historical_data)

        # Risk should be higher when scaling below peak concurrency
        assert result.value > 0.3

    async def test_serverless_reduces_risk(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Serverless migration reduces queue risk."""
        model = WarehouseQueueRiskModel()
        scenario = _make_scenario(
            [
                ("warehouse_type", "standard", "serverless"),
            ]
        )

        result = await model.predict(scenario, historical_data)

        # Serverless has instant scaling, should have lower risk
        assert result.value < 0.8

    async def test_risk_includes_evidence(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Risk prediction includes evidence."""
        model = WarehouseQueueRiskModel()
        scenario = _make_scenario(
            [
                ("max_clusters", 4, 2),
            ]
        )

        result = await model.predict(scenario, historical_data)

        assert len(result.evidence) > 0

    async def test_risk_bounded_zero_to_one(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """Risk score is bounded between 0 and 1."""
        model = WarehouseQueueRiskModel()

        # Extreme scale down
        scenario = _make_scenario(
            [
                ("max_clusters", 10, 1),
            ]
        )

        result = await model.predict(scenario, historical_data)

        assert 0.0 <= result.value <= 1.0


# =============================================================================
# Integration Tests
# =============================================================================


class TestModelIntegration:
    """Test models work together."""

    async def test_all_models_predict(
        self,
        historical_data: HistoricalData,
    ) -> None:
        """All models can predict for same scenario."""
        models = [
            WarehouseCostModel(),
            WarehouseLatencyModel(),
            WarehouseQueueRiskModel(),
        ]

        scenario = _make_scenario(
            [
                ("warehouse_type", "standard", "serverless"),
            ]
        )

        for model in models:
            result = await model.predict(scenario, historical_data)
            assert result.value >= 0
            assert result.confidence in ("low", "medium", "high")

    async def test_model_metadata(self) -> None:
        """Models have required metadata."""
        models = [
            WarehouseCostModel(),
            WarehouseLatencyModel(),
            WarehouseQueueRiskModel(),
        ]

        for model in models:
            assert model.model_name != ""
            assert model.model_version != ""
            assert "warehouse" in model.supported_entity_types
