# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for scenario evaluator.

Tests cover:
- Scenario evaluation with multiple models
- Recommendation generation
- Scenario comparison and ranking
"""

from __future__ import annotations

import pytest
from starboard_server.infra.whatif.evaluator import (
    ScenarioComparison,
    ScenarioEvaluation,
    ScenarioEvaluator,
)
from starboard_server.infra.whatif.historical import HistoricalData
from starboard_server.infra.whatif.prediction import (
    ConfidenceInterval,
    PredictionResult,
)
from starboard_server.infra.whatif.scenario import Scenario, ScenarioParameter


class MockCostModel:
    """Mock cost prediction model for testing."""

    model_name = "mock_cost_v1"
    model_version = "1.0"
    supported_entity_types = ("warehouse",)

    def __init__(self, predicted_cost: float = 1000.0) -> None:
        self.predicted_cost = predicted_cost

    def can_predict(self, scenario: Scenario) -> bool:
        return scenario.entity_type in self.supported_entity_types

    async def predict(
        self,
        scenario: Scenario,
        historical_data: HistoricalData,
    ) -> PredictionResult:
        return PredictionResult(
            value=self.predicted_cost,
            unit="USD",
            confidence="medium",
            evidence=("Mock cost prediction",),
            model_name=self.model_name,
        )


class MockLatencyModel:
    """Mock latency prediction model for testing."""

    model_name = "mock_latency_v1"
    model_version = "1.0"
    supported_entity_types = ("warehouse",)

    def __init__(self, predicted_latency: float = 5.0) -> None:
        self.predicted_latency = predicted_latency

    def can_predict(self, scenario: Scenario) -> bool:
        return scenario.entity_type in self.supported_entity_types

    async def predict(
        self,
        scenario: Scenario,
        historical_data: HistoricalData,
    ) -> PredictionResult:
        return PredictionResult(
            value=self.predicted_latency,
            unit="seconds",
            confidence="high",
            evidence=("Mock latency prediction",),
            model_name=self.model_name,
        )


class MockRiskModel:
    """Mock risk prediction model for testing."""

    model_name = "mock_risk_v1"
    model_version = "1.0"
    supported_entity_types = ("warehouse",)

    def __init__(self, risk_score: float = 0.3) -> None:
        self.risk_score = risk_score

    def can_predict(self, scenario: Scenario) -> bool:
        return scenario.entity_type in self.supported_entity_types

    async def predict(
        self,
        scenario: Scenario,
        historical_data: HistoricalData,
    ) -> PredictionResult:
        return PredictionResult(
            value=self.risk_score,
            unit="risk_score",
            confidence="medium",
            evidence=("Mock risk prediction",),
            model_name=self.model_name,
        )


@pytest.fixture
def sample_scenario() -> Scenario:
    """Create a sample scenario for testing."""
    return Scenario(
        scenario_id="test-scenario",
        name="Test Scenario",
        description="A test scenario",
        entity_type="warehouse",
        entity_id="wh-123",
        parameters=(ScenarioParameter("warehouse_type", "standard", "serverless"),),
    )


@pytest.fixture
def sample_historical_data() -> HistoricalData:
    """Create sample historical data for testing."""
    return HistoricalData(
        entity_type="warehouse",
        entity_id="wh-123",
        window_days=30,
        aggregates={
            "monthly_cost_usd": 1500.0,
            "p95_runtime_sec": 10.0,
            "total_queries": 10000,
            "avg_concurrency": 5.0,
        },
    )


class TestScenarioEvaluator:
    """Tests for ScenarioEvaluator."""

    @pytest.mark.asyncio
    async def test_evaluate_with_models(
        self,
        sample_scenario: Scenario,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test evaluating a scenario with multiple models."""
        evaluator = ScenarioEvaluator(
            models=[
                MockCostModel(predicted_cost=1200.0),
                MockLatencyModel(predicted_latency=8.0),
                MockRiskModel(risk_score=0.4),
            ]
        )

        result = await evaluator.evaluate(sample_scenario, sample_historical_data)

        assert isinstance(result, ScenarioEvaluation)
        assert result.scenario == sample_scenario

        # Check predictions were made
        assert result.cost_prediction is not None
        assert result.cost_prediction.value == 1200.0

        assert result.performance_prediction is not None
        assert result.performance_prediction.value == 8.0

        assert result.risk_prediction is not None
        assert result.risk_prediction.value == 0.4

    @pytest.mark.asyncio
    async def test_evaluate_cost_change_calculation(
        self,
        sample_scenario: Scenario,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test cost change percentage calculation."""
        # Current cost: 1500, Predicted: 1200 = -20% change
        evaluator = ScenarioEvaluator(models=[MockCostModel(predicted_cost=1200.0)])

        result = await evaluator.evaluate(sample_scenario, sample_historical_data)

        assert result.cost_change_pct is not None
        assert result.cost_change_pct == pytest.approx(-20.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_evaluate_latency_change_calculation(
        self,
        sample_scenario: Scenario,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test latency change percentage calculation."""
        # Current p95: 10s, Predicted: 8s = -20% change
        evaluator = ScenarioEvaluator(models=[MockLatencyModel(predicted_latency=8.0)])

        result = await evaluator.evaluate(sample_scenario, sample_historical_data)

        assert result.latency_change_pct is not None
        assert result.latency_change_pct == pytest.approx(-20.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_recommend_cost_savings(
        self,
        sample_scenario: Scenario,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test recommendation for significant cost savings."""
        # 20% cost savings with acceptable latency
        evaluator = ScenarioEvaluator(
            models=[
                MockCostModel(predicted_cost=1200.0),  # -20% cost
                MockLatencyModel(predicted_latency=11.0),  # +10% latency
                MockRiskModel(risk_score=0.3),  # Low risk
            ]
        )

        result = await evaluator.evaluate(sample_scenario, sample_historical_data)

        assert result.recommended is True
        assert "cost savings" in result.recommendation_rationale.lower()

    @pytest.mark.asyncio
    async def test_recommend_performance_improvement(
        self,
        sample_scenario: Scenario,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test recommendation for performance improvement."""
        # 25% latency improvement with moderate cost increase
        evaluator = ScenarioEvaluator(
            models=[
                MockCostModel(predicted_cost=1800.0),  # +20% cost
                MockLatencyModel(predicted_latency=7.5),  # -25% latency
                MockRiskModel(risk_score=0.3),
            ]
        )

        result = await evaluator.evaluate(sample_scenario, sample_historical_data)

        assert result.recommended is True
        assert "latency" in result.recommendation_rationale.lower()

    @pytest.mark.asyncio
    async def test_not_recommend_high_risk(
        self,
        sample_scenario: Scenario,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test not recommending high-risk scenarios."""
        evaluator = ScenarioEvaluator(
            models=[
                MockCostModel(predicted_cost=1200.0),
                MockLatencyModel(predicted_latency=8.0),
                MockRiskModel(risk_score=0.9),  # High risk
            ]
        )

        result = await evaluator.evaluate(sample_scenario, sample_historical_data)

        assert result.recommended is False
        assert "risk" in result.recommendation_rationale.lower()

    @pytest.mark.asyncio
    async def test_compare_scenarios(
        self,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test comparing multiple scenarios."""
        scenarios = [
            Scenario(
                scenario_id="scenario-a",
                name="Scenario A",
                description="Cost savings",
                entity_type="warehouse",
                entity_id="wh-123",
                parameters=(),
            ),
            Scenario(
                scenario_id="scenario-b",
                name="Scenario B",
                description="Performance boost",
                entity_type="warehouse",
                entity_id="wh-123",
                parameters=(),
            ),
        ]

        evaluator = ScenarioEvaluator(
            models=[
                MockCostModel(predicted_cost=1000.0),
                MockLatencyModel(predicted_latency=10.0),
            ]
        )

        comparison = await evaluator.compare_scenarios(
            scenarios, sample_historical_data
        )

        assert isinstance(comparison, ScenarioComparison)
        assert len(comparison.evaluations) == 2
        assert len(comparison.ranked_scenarios) == 2
        assert comparison.best_scenario_id is not None

    @pytest.mark.asyncio
    async def test_overall_confidence_is_minimum(
        self,
        sample_scenario: Scenario,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test that overall confidence is the minimum of all predictions."""
        # Cost has low confidence, others are high
        cost_model = MockCostModel(predicted_cost=1200.0)
        latency_model = MockLatencyModel(predicted_latency=8.0)

        evaluator = ScenarioEvaluator(models=[cost_model, latency_model])

        result = await evaluator.evaluate(sample_scenario, sample_historical_data)

        # Cost is medium, latency is high, so overall should be medium
        assert result.overall_confidence in ("low", "medium", "high")

    @pytest.mark.asyncio
    async def test_evaluate_with_no_models(
        self,
        sample_scenario: Scenario,
        sample_historical_data: HistoricalData,
    ) -> None:
        """Test evaluation with no models."""
        evaluator = ScenarioEvaluator(models=[])

        result = await evaluator.evaluate(sample_scenario, sample_historical_data)

        assert result.cost_prediction is None
        assert result.performance_prediction is None
        assert result.risk_prediction is None
        assert result.recommended is False


class TestPredictionResult:
    """Tests for PredictionResult."""

    def test_create_basic_result(self) -> None:
        """Test creating a basic prediction result."""
        result = PredictionResult(
            value=1000.0,
            unit="USD",
        )

        assert result.value == 1000.0
        assert result.unit == "USD"
        assert result.confidence == "medium"  # default
        assert result.confidence_interval is None

    def test_create_result_with_confidence_interval(self) -> None:
        """Test creating result with confidence interval."""
        ci = ConfidenceInterval(
            lower=800.0,
            upper=1200.0,
            confidence_level=0.95,
        )

        result = PredictionResult(
            value=1000.0,
            unit="USD",
            confidence_interval=ci,
            confidence="high",
        )

        assert result.confidence_interval is not None
        assert result.confidence_interval.lower == 800.0
        assert result.confidence_interval.upper == 1200.0
        assert result.confidence == "high"


class TestConfidenceInterval:
    """Tests for ConfidenceInterval."""

    def test_width(self) -> None:
        """Test width calculation."""
        ci = ConfidenceInterval(lower=800.0, upper=1200.0, confidence_level=0.95)

        assert ci.width == 400.0

    def test_midpoint(self) -> None:
        """Test midpoint calculation."""
        ci = ConfidenceInterval(lower=800.0, upper=1200.0, confidence_level=0.95)

        assert ci.midpoint == 1000.0
