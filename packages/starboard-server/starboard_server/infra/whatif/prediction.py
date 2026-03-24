"""Prediction model abstractions for what-if analysis.

This module provides the core abstractions for prediction models:
- PredictionModel protocol for implementing custom models
- PredictionResult for model outputs
- ConfidenceInterval for uncertainty quantification
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from starboard_server.infra.whatif.historical import HistoricalData
    from starboard_server.infra.whatif.scenario import Scenario

__all__ = [
    "ConfidenceInterval",
    "PredictionModel",
    "PredictionResult",
    "ValidationResult",
]


@dataclass(frozen=True)
class ConfidenceInterval:
    """Statistical confidence interval.

    Represents uncertainty bounds around a prediction.

    Attributes:
        lower: Lower bound of the interval.
        upper: Upper bound of the interval.
        confidence_level: Confidence level (e.g., 0.95 for 95% CI).

    Example:
        ```python
        ci = ConfidenceInterval(
            lower=800.0,
            upper=1200.0,
            confidence_level=0.95,
        )
        print(f"Width: {ci.width}")  # 400.0
        print(f"Midpoint: {ci.midpoint}")  # 1000.0
        ```
    """

    lower: float
    upper: float
    confidence_level: float

    @property
    def width(self) -> float:
        """Calculate the width of the interval."""
        return self.upper - self.lower

    @property
    def midpoint(self) -> float:
        """Calculate the midpoint of the interval."""
        return (self.lower + self.upper) / 2


@dataclass(frozen=True)
class PredictionResult:
    """Result from a prediction model.

    Contains the predicted value along with confidence information,
    evidence, and model metadata.

    Attributes:
        value: Predicted value.
        unit: Unit of the value (e.g., "USD", "seconds", "risk_score").
        confidence_interval: Optional statistical bounds.
        confidence: Categorical confidence level.
        evidence: Supporting evidence for the prediction.
        assumptions: Assumptions made by the model.
        limitations: Known limitations of the prediction.
        model_name: Name of the model that made the prediction.
        model_version: Version of the model.

    Example:
        ```python
        result = PredictionResult(
            value=1000.0,
            unit="USD",
            confidence_interval=ConfidenceInterval(800, 1200, 0.95),
            confidence="high",
            evidence=("Based on 30 days of data", "Query volume is stable"),
            model_name="warehouse_cost_v1",
        )
        ```
    """

    # Predicted value
    value: float
    unit: str

    # Confidence
    confidence_interval: ConfidenceInterval | None = None
    confidence: Literal["low", "medium", "high"] = "medium"

    # Evidence and reasoning
    evidence: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    # Model metadata
    model_name: str = ""
    model_version: str = "1.0"


class PredictionModel(Protocol):
    """Protocol for what-if prediction models.

    Implement this protocol to create custom prediction models that can
    be used with the ScenarioEvaluator.

    Attributes:
        model_name: Unique name for this model.
        model_version: Version string.
        supported_entity_types: Entity types this model can predict for.

    Example:
        ```python
        class MyCostModel:
            model_name = "my_cost_v1"
            model_version = "1.0"
            supported_entity_types = ("warehouse",)

            def can_predict(self, scenario: Scenario) -> bool:
                return scenario.entity_type in self.supported_entity_types

            async def predict(
                self,
                scenario: Scenario,
                historical_data: HistoricalData,
            ) -> PredictionResult:
                # Calculate prediction...
                return PredictionResult(value=1000.0, unit="USD")
        ```
    """

    model_name: str
    model_version: str
    supported_entity_types: tuple[str, ...]

    def can_predict(self, scenario: Scenario) -> bool:
        """Check if this model can make predictions for a scenario.

        Args:
            scenario: The scenario to check.

        Returns:
            True if this model can predict for the scenario.
        """
        ...

    async def predict(
        self,
        scenario: Scenario,
        historical_data: HistoricalData,
    ) -> PredictionResult:
        """Generate prediction for a scenario.

        Args:
            scenario: Scenario to evaluate.
            historical_data: Historical data for the entity.

        Returns:
            Prediction with confidence bounds and evidence.
        """
        ...


@dataclass(frozen=True)
class ValidationResult:
    """Result from validating a prediction against actual outcome.

    Used for model accuracy tracking and improvement.

    Attributes:
        predicted_value: The original predicted value.
        actual_value: The actual observed value.
        error: Difference (actual - predicted).
        error_pct: Percentage error.
        within_confidence: Whether actual was within confidence interval.
    """

    predicted_value: float
    actual_value: float
    error: float
    error_pct: float
    within_confidence: bool
