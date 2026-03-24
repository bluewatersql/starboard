"""Warehouse queue risk prediction model.

Predicts risk of queue issues and capacity problems for warehouse
configuration changes. Outputs a risk score between 0 and 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from starboard_server.infra.whatif.prediction import (
    ConfidenceInterval,
    PredictionResult,
)

if TYPE_CHECKING:
    from starboard_server.infra.whatif.historical import HistoricalData
    from starboard_server.infra.whatif.scenario import Scenario


class WarehouseQueueRiskModel:
    """Predicts queue and capacity risk for warehouse configuration changes.

    Implements the PredictionModel protocol for risk predictions.

    Risk factors considered:
    - Cluster count vs workload concurrency
    - Historical queue rates
    - Peak hour utilization
    - Workload burstiness

    The model outputs a risk score between 0 and 1:
    - 0.0-0.3: Low risk
    - 0.3-0.7: Medium risk
    - 0.7-1.0: High risk

    Example:
        ```python
        model = WarehouseQueueRiskModel()

        scenario = Scenario(
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(
                ScenarioParameter("max_clusters", 4, 2),  # Scaling down
            ),
        )

        result = await model.predict(scenario, historical_data)
        if result.value > 0.7:
            print("WARNING: High queue risk!")
        ```
    """

    model_name = "warehouse_queue_risk_v1"
    model_version = "1.0"
    supported_entity_types = ("warehouse",)

    # Risk thresholds
    HIGH_UTILIZATION_THRESHOLD = 0.8  # 80% utilization is risky
    HIGH_QUEUE_RATE_THRESHOLD = 15.0  # 15% queue rate is concerning
    HIGH_BURSTINESS_THRESHOLD = 3.0  # Peak/avg ratio > 3x is bursty

    def can_predict(self, scenario: Scenario) -> bool:
        """Check if this model can predict for a scenario.

        Args:
            scenario: Scenario to evaluate.

        Returns:
            True if entity_type is 'warehouse'.
        """
        return scenario.entity_type in self.supported_entity_types

    async def predict(
        self,
        scenario: Scenario,
        historical_data: HistoricalData,
    ) -> PredictionResult:
        """Predict queue risk for a warehouse scenario.

        Args:
            scenario: Warehouse configuration scenario.
            historical_data: Historical usage data.

        Returns:
            Risk prediction (0-1) with evidence.
        """
        # Get baseline metrics
        avg_concurrency = historical_data.get_aggregate("avg_concurrency", 2.0)
        peak_concurrency = historical_data.get_aggregate("peak_concurrency", 10.0)
        queue_rate = historical_data.get_aggregate("queue_rate_pct", 5.0)

        # Get configuration parameters
        current_type = self._get_param_value(scenario, "warehouse_type", "standard")
        proposed_type = self._get_proposed_value(
            scenario, "warehouse_type", current_type
        )

        current_max = self._get_param_value(scenario, "max_clusters", 4)
        proposed_max = self._get_proposed_value(scenario, "max_clusters", current_max)

        # Calculate risk components
        utilization_risk = self._calculate_utilization_risk(
            avg_concurrency, peak_concurrency, float(proposed_max)
        )
        queue_risk = self._calculate_queue_risk(
            queue_rate, float(current_max), float(proposed_max)
        )
        burstiness_risk = self._calculate_burstiness_risk(
            avg_concurrency, peak_concurrency, float(proposed_max)
        )
        type_risk = self._calculate_type_risk(current_type, proposed_type, queue_rate)

        # Combine risks (weighted average)
        risk_score = (
            utilization_risk * 0.35
            + queue_risk * 0.30
            + burstiness_risk * 0.20
            + type_risk * 0.15
        )

        # Clamp to [0, 1]
        risk_score = max(0.0, min(1.0, risk_score))

        # Calculate confidence interval
        # Risk predictions have inherent uncertainty
        ci = ConfidenceInterval(
            lower=max(0.0, risk_score - 0.15),
            upper=min(1.0, risk_score + 0.15),
            confidence_level=0.85,
        )

        # Generate evidence
        evidence = self._generate_evidence(
            risk_score=risk_score,
            utilization_risk=utilization_risk,
            queue_risk=queue_risk,
            burstiness_risk=burstiness_risk,
            type_risk=type_risk,
            proposed_max=float(proposed_max),
            peak_concurrency=peak_concurrency,
            queue_rate=queue_rate,
        )

        # Determine confidence based on data quality
        total_queries = historical_data.get_aggregate("total_queries", 0)
        confidence: Literal["low", "medium", "high"]
        if total_queries > 1000:
            confidence = "high"
        elif total_queries > 100:
            confidence = "medium"
        else:
            confidence = "low"

        return PredictionResult(
            value=risk_score,
            unit="risk_score",
            confidence_interval=ci,
            confidence=confidence,
            evidence=tuple(evidence),
            assumptions=self._get_assumptions(),
            limitations=self._get_limitations(),
            model_name=self.model_name,
            model_version=self.model_version,
        )

    def _calculate_utilization_risk(
        self,
        avg_concurrency: float,
        peak_concurrency: float,
        max_clusters: float,
    ) -> float:
        """Calculate risk from capacity utilization.

        High utilization leaves no headroom for bursts.
        """
        # Calculate average and peak utilization
        avg_utilization = avg_concurrency / max(max_clusters, 1)
        peak_utilization = peak_concurrency / max(max_clusters, 1)

        # Risk increases sharply above threshold
        if peak_utilization > 1.0:
            # Already exceeding capacity at peaks
            return min(1.0, 0.7 + (peak_utilization - 1.0) * 0.3)
        elif avg_utilization > self.HIGH_UTILIZATION_THRESHOLD:
            # High sustained utilization
            return 0.5 + (avg_utilization - self.HIGH_UTILIZATION_THRESHOLD) * 2.5
        else:
            # Low risk at low utilization
            return avg_utilization * 0.5

    def _calculate_queue_risk(
        self,
        current_queue_rate: float,
        current_max: float,
        proposed_max: float,
    ) -> float:
        """Calculate risk from queue metrics.

        Uses historical queue rate and extrapolates for new configuration.
        """
        # Scale queue rate based on cluster change
        if proposed_max >= current_max:
            # More clusters should reduce queue rate
            scale_factor = current_max / max(proposed_max, 1)
            projected_queue_rate = current_queue_rate * scale_factor
        else:
            # Fewer clusters will likely increase queue rate
            scale_factor = (current_max / max(proposed_max, 1)) ** 1.5
            projected_queue_rate = min(100, current_queue_rate * scale_factor)

        # Risk based on projected queue rate
        if projected_queue_rate > 30:
            return 1.0  # Critical queue rate
        elif projected_queue_rate > self.HIGH_QUEUE_RATE_THRESHOLD:
            return 0.5 + (projected_queue_rate - self.HIGH_QUEUE_RATE_THRESHOLD) / 30
        else:
            return projected_queue_rate / 30

    def _calculate_burstiness_risk(
        self,
        avg_concurrency: float,
        peak_concurrency: float,
        max_clusters: float,
    ) -> float:
        """Calculate risk from workload burstiness.

        Bursty workloads need headroom for spikes.
        """
        if avg_concurrency == 0:
            return 0.0

        burstiness = peak_concurrency / avg_concurrency

        # Check if bursts would exceed capacity
        if peak_concurrency > max_clusters:
            burst_overflow = (peak_concurrency - max_clusters) / max_clusters
            return min(1.0, 0.5 + burst_overflow * 0.5)
        elif burstiness > self.HIGH_BURSTINESS_THRESHOLD:
            # Bursty workload with tight capacity
            return 0.3 + (burstiness - self.HIGH_BURSTINESS_THRESHOLD) * 0.1
        else:
            return burstiness * 0.1

    def _calculate_type_risk(
        self,
        current_type: str | int | float,
        proposed_type: str | int | float,
        queue_rate: float,
    ) -> float:
        """Calculate risk from warehouse type.

        Serverless has instant scaling but different behavior.
        Standard has potential cold start issues.
        """
        if current_type == proposed_type:
            return 0.0  # No type change, no additional risk

        if proposed_type == "serverless":
            # Serverless generally reduces queue risk
            return 0.1  # Small risk from behavior change
        else:
            # Standard has more queue risk, especially with current queue issues
            return min(0.5, queue_rate / 100 + 0.1)

    def _get_param_value(
        self,
        scenario: Scenario,
        param_name: str,
        default: str | int | float,
    ) -> str | int | float:
        """Get current value for a parameter."""
        for param in scenario.parameters:
            if param.name == param_name:
                return param.current_value
        return default

    def _get_proposed_value(
        self,
        scenario: Scenario,
        param_name: str,
        default: str | int | float,
    ) -> str | int | float:
        """Get proposed value for a parameter."""
        for param in scenario.parameters:
            if param.name == param_name:
                return param.proposed_value
        return default

    def _generate_evidence(
        self,
        risk_score: float,
        utilization_risk: float,
        queue_risk: float,
        burstiness_risk: float,
        type_risk: float,
        proposed_max: float,
        peak_concurrency: float,
        queue_rate: float,
    ) -> list[str]:
        """Generate evidence strings for the risk prediction."""
        evidence = []

        # Overall risk level
        if risk_score > 0.7:
            evidence.append(
                f"HIGH RISK: Score {risk_score:.2f} indicates significant queue concerns"
            )
        elif risk_score > 0.3:
            evidence.append(
                f"MODERATE RISK: Score {risk_score:.2f} suggests monitoring needed"
            )
        else:
            evidence.append(
                f"LOW RISK: Score {risk_score:.2f} indicates acceptable queue behavior"
            )

        # Dominant risk factors
        risks = [
            ("utilization", utilization_risk),
            ("queue_history", queue_risk),
            ("burstiness", burstiness_risk),
            ("type_change", type_risk),
        ]
        top_risk = max(risks, key=lambda x: x[1])

        if top_risk[1] > 0.5:
            evidence.append(
                f"Primary concern: {top_risk[0]} (factor: {top_risk[1]:.2f})"
            )

        # Specific insights
        if peak_concurrency > proposed_max:
            evidence.append(
                f"Peak concurrency ({peak_concurrency:.0f}) exceeds "
                f"max clusters ({proposed_max:.0f})"
            )

        if queue_rate > self.HIGH_QUEUE_RATE_THRESHOLD:
            evidence.append(
                f"Historical queue rate ({queue_rate:.1f}%) is above threshold"
            )

        return evidence

    def _get_assumptions(self) -> tuple[str, ...]:
        """Get assumptions for the prediction."""
        return (
            "Workload patterns remain similar to historical data",
            "No external capacity constraints",
            "Query complexity distribution unchanged",
        )

    def _get_limitations(self) -> tuple[str, ...]:
        """Get limitations for the prediction."""
        return (
            "Risk predictions are probabilistic estimates",
            "Actual risk depends on real-time workload",
            "Cannot predict external factors (maintenance, etc.)",
        )
