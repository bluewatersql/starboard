"""Warehouse latency prediction model.

Predicts p95 latency impact for warehouse configuration changes including:
- Serverless vs Standard migration
- Cluster sizing changes (scaling up/down)
- Query workload changes
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


class WarehouseLatencyModel:
    """Predicts latency impact of warehouse configuration changes.

    Implements the PredictionModel protocol for latency predictions.

    Supports scenarios:
    - warehouse_type: serverless has instant scaling, no cold starts
    - max_clusters: more clusters reduce queue-induced latency
    - cluster_size: larger clusters reduce execution time

    The model uses historical p95 runtime as baseline and estimates
    the impact of configuration changes on that metric.

    Example:
        ```python
        model = WarehouseLatencyModel()

        scenario = Scenario(
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(
                ScenarioParameter("max_clusters", 2, 4),
            ),
        )

        result = await model.predict(scenario, historical_data)
        print(f"Predicted p95 latency: {result.value:.1f}s")
        ```
    """

    model_name = "warehouse_latency_v1"
    model_version = "1.0"
    supported_entity_types = ("warehouse",)

    # Cluster size factors (relative performance multipliers)
    CLUSTER_SIZE_FACTORS = {
        "2X-Small": 0.25,
        "X-Small": 0.5,
        "Small": 1.0,
        "Medium": 2.0,
        "Large": 4.0,
        "X-Large": 8.0,
        "2X-Large": 16.0,
        "3X-Large": 32.0,
        "4X-Large": 64.0,
    }

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
        """Predict latency impact for a warehouse scenario.

        Args:
            scenario: Warehouse configuration scenario.
            historical_data: Historical performance data.

        Returns:
            Latency prediction (p95) with confidence interval.
        """
        # Get baseline metrics
        baseline_p95 = historical_data.get_aggregate("p95_runtime_sec", 10.0)
        queue_rate = historical_data.get_aggregate("queue_rate_pct", 5.0)
        avg_concurrency = historical_data.get_aggregate("avg_concurrency", 2.0)

        # Get configuration changes
        current_type = self._get_param_value(scenario, "warehouse_type", "standard")
        proposed_type = self._get_proposed_value(
            scenario, "warehouse_type", current_type
        )

        current_max = self._get_param_value(scenario, "max_clusters", 4)
        proposed_max = self._get_proposed_value(scenario, "max_clusters", current_max)

        current_size = self._get_param_value(scenario, "cluster_size", "Small")
        proposed_size = self._get_proposed_value(scenario, "cluster_size", current_size)

        # Calculate latency impact factors
        type_factor = self._calculate_type_factor(
            current_type, proposed_type, queue_rate
        )
        cluster_factor = self._calculate_cluster_factor(
            current_max, proposed_max, avg_concurrency
        )
        size_factor = self._calculate_size_factor(current_size, proposed_size)

        # Combine factors (multiplicative)
        total_factor = type_factor * cluster_factor * size_factor

        # Predict new p95 latency
        predicted_p95 = baseline_p95 * total_factor

        # Calculate confidence interval (wider for larger changes)
        change_magnitude = abs(1 - total_factor)
        confidence_width = 0.15 + (change_magnitude * 0.3)

        ci = ConfidenceInterval(
            lower=predicted_p95 * (1 - confidence_width),
            upper=predicted_p95 * (1 + confidence_width),
            confidence_level=0.90,
        )

        # Generate evidence
        evidence = self._generate_evidence(
            baseline_p95=baseline_p95,
            predicted_p95=predicted_p95,
            type_factor=type_factor,
            cluster_factor=cluster_factor,
            size_factor=size_factor,
            current_type=current_type,
            proposed_type=proposed_type,
        )

        # Determine confidence level based on data quality
        total_queries = historical_data.get_aggregate("total_queries", 0)
        confidence: Literal["low", "medium", "high"]
        if total_queries > 1000 and avg_concurrency > 1:
            confidence = "high"
        elif total_queries > 100:
            confidence = "medium"
        else:
            confidence = "low"

        return PredictionResult(
            value=predicted_p95,
            unit="seconds",
            confidence_interval=ci,
            confidence=confidence,
            evidence=tuple(evidence),
            assumptions=self._get_assumptions(),
            limitations=self._get_limitations(current_type != proposed_type),
            model_name=self.model_name,
            model_version=self.model_version,
        )

    def _calculate_type_factor(
        self,
        current_type: str | int | float,
        proposed_type: str | int | float,
        queue_rate: float,
    ) -> float:
        """Calculate latency factor for warehouse type change.

        Serverless has instant scaling which reduces queue-induced latency.
        """
        if current_type == proposed_type:
            return 1.0

        if proposed_type == "serverless":
            # Serverless reduces queue-related latency
            # Higher queue rate = bigger improvement
            queue_improvement = 1 - (queue_rate / 200)  # Up to 50% improvement
            return max(0.7, queue_improvement)
        else:
            # Moving to standard may increase queue latency
            return 1.0 + (queue_rate / 100)  # Up to 50% increase

    def _calculate_cluster_factor(
        self,
        current_max: int | float | str,
        proposed_max: int | float | str,
        avg_concurrency: float,
    ) -> float:
        """Calculate latency factor for cluster count change.

        More clusters reduce queue time when concurrency is high.
        """
        current = float(current_max)
        proposed = float(proposed_max)

        if current == proposed:
            return 1.0

        # Calculate capacity utilization
        # If avg concurrency > max clusters, queries queue
        current_utilization = avg_concurrency / max(current, 1)
        proposed_utilization = avg_concurrency / max(proposed, 1)

        # Queuing starts affecting latency above ~70% utilization
        if current_utilization > 0.7 and proposed_utilization < 0.7:
            # Scaling up to reduce queuing
            return 0.8  # 20% improvement
        elif current_utilization < 0.7 and proposed_utilization > 0.7:
            # Scaling down into queue zone
            return 1.3  # 30% degradation

        # Linear interpolation for smaller changes
        if proposed > current:
            return max(0.7, 1 - (proposed - current) * 0.05)
        else:
            return min(1.5, 1 + (current - proposed) * 0.1)

    def _calculate_size_factor(
        self,
        current_size: str | int | float,
        proposed_size: str | int | float,
    ) -> float:
        """Calculate latency factor for cluster size change.

        Larger clusters execute queries faster (for compute-bound queries).
        """
        current_factor = self.CLUSTER_SIZE_FACTORS.get(str(current_size), 1.0)
        proposed_factor = self.CLUSTER_SIZE_FACTORS.get(str(proposed_size), 1.0)

        if current_factor == proposed_factor:
            return 1.0

        # Latency improvement is inverse of size increase
        # (bigger cluster = faster, but not linearly)
        size_ratio = proposed_factor / current_factor

        # Apply diminishing returns
        if size_ratio > 1:
            # Scaling up: sqrt of ratio improvement
            return 1.0 / (size_ratio**0.5)
        else:
            # Scaling down: linear degradation
            return 1.0 / size_ratio

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
        baseline_p95: float,
        predicted_p95: float,
        type_factor: float,
        cluster_factor: float,
        size_factor: float,
        current_type: str | int | float,
        proposed_type: str | int | float,
    ) -> list[str]:
        """Generate evidence strings for the prediction."""
        evidence = []

        # Overall change
        change_pct = ((predicted_p95 - baseline_p95) / baseline_p95) * 100
        if abs(change_pct) > 5:
            direction = "improvement" if change_pct < 0 else "increase"
            evidence.append(
                f"Expected {abs(change_pct):.0f}% latency {direction} "
                f"({baseline_p95:.1f}s -> {predicted_p95:.1f}s p95)"
            )
        else:
            evidence.append("No significant latency change expected")

        # Type change evidence
        if type_factor != 1.0 and current_type != proposed_type:
            if proposed_type == "serverless":
                evidence.append("Serverless instant scaling reduces queue wait times")
            else:
                evidence.append("Standard warehouses may have startup delays")

        # Cluster change evidence
        if cluster_factor < 1.0:
            evidence.append("Additional clusters reduce queue-induced latency")
        elif cluster_factor > 1.0:
            evidence.append("Fewer clusters may increase queue-induced latency")

        # Size change evidence
        if size_factor < 1.0:
            evidence.append("Larger cluster size reduces query execution time")
        elif size_factor > 1.0:
            evidence.append("Smaller cluster size may increase execution time")

        return evidence

    def _get_assumptions(self) -> tuple[str, ...]:
        """Get assumptions for the prediction."""
        return (
            "Query patterns remain similar to historical data",
            "No significant changes in data volume or complexity",
            "System is not experiencing external performance issues",
        )

    def _get_limitations(self, is_type_change: bool) -> tuple[str, ...]:
        """Get limitations for the prediction."""
        limitations = [
            "Latency predictions depend on query type mix",
            "Complex queries may scale differently than simple ones",
        ]

        if is_type_change:
            limitations.append(
                "Type migration latency impact depends on workload characteristics"
            )

        return tuple(limitations)
