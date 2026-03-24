"""Warehouse cost prediction model.

Predicts cost impact for warehouse configuration changes including:
- Serverless vs Standard migration
- Cluster sizing changes
- Auto-stop configuration changes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from starboard_server.infra.whatif.prediction import (
    ConfidenceInterval,
    PredictionResult,
)

if TYPE_CHECKING:
    from starboard_server.infra.whatif.historical import HistoricalData
    from starboard_server.infra.whatif.scenario import Scenario


# Databricks pricing (USD per DBU)
# These are approximate and should be configurable in production
SERVERLESS_DBU_PRICE = 0.70  # Premium serverless
STANDARD_DBU_PRICE = 0.55  # Standard Pro


@dataclass(frozen=True)
class CostBreakdown:
    """Detailed cost breakdown for a warehouse configuration.

    Attributes:
        compute_cost_usd: DBU compute costs.
        idle_cost_usd: Cost of idle time (standard only).
        startup_cost_usd: Cost of cluster starts (standard only).
        total_monthly_usd: Total monthly cost estimate.
    """

    compute_cost_usd: float
    idle_cost_usd: float
    startup_cost_usd: float
    total_monthly_usd: float


class WarehouseCostModel:
    """Predicts cost impact of warehouse configuration changes.

    Implements the PredictionModel protocol for cost predictions.

    Supports scenarios:
    - warehouse_type: serverless <-> standard migration
    - max_clusters: scaling up or down
    - auto_stop_mins: changing auto-stop timeout

    Example:
        ```python
        model = WarehouseCostModel()

        scenario = Scenario(
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(
                ScenarioParameter("warehouse_type", "standard", "serverless"),
            ),
        )

        result = await model.predict(scenario, historical_data)
        print(f"Estimated monthly cost: ${result.value:.2f}")
        ```
    """

    model_name = "warehouse_cost_v1"
    model_version = "1.0"
    supported_entity_types = ("warehouse",)

    def __init__(
        self,
        serverless_dbu_price: float = SERVERLESS_DBU_PRICE,
        standard_dbu_price: float = STANDARD_DBU_PRICE,
    ) -> None:
        """Initialize the cost model.

        Args:
            serverless_dbu_price: Price per DBU for serverless.
            standard_dbu_price: Price per DBU for standard.
        """
        self.serverless_dbu_price = serverless_dbu_price
        self.standard_dbu_price = standard_dbu_price

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
        """Predict cost for a warehouse scenario.

        Args:
            scenario: Warehouse configuration scenario.
            historical_data: Historical usage data.

        Returns:
            Cost prediction with confidence interval.
        """
        # Get baseline metrics
        baseline_cost = historical_data.get_aggregate("monthly_cost_usd", 0.0)
        monthly_dbu = historical_data.get_aggregate("monthly_dbu", 0.0)
        total_queries = historical_data.get_aggregate("total_queries", 0.0)
        avg_runtime_sec = historical_data.get_aggregate("avg_runtime_sec", 1.0)

        # Determine current and proposed warehouse type
        current_type = self._get_param_value(scenario, "warehouse_type", "standard")
        proposed_type = self._get_proposed_value(
            scenario, "warehouse_type", current_type
        )

        # Calculate estimated cost
        if proposed_type == "serverless":
            predicted_cost = self._estimate_serverless_cost(
                monthly_dbu=monthly_dbu,
                total_queries=total_queries,
                avg_runtime_sec=avg_runtime_sec,
            )
        else:
            predicted_cost = self._estimate_standard_cost(
                monthly_dbu=monthly_dbu,
                scenario=scenario,
                historical_data=historical_data,
            )

        # Calculate confidence interval
        # Wider interval if converting between types
        is_type_change = current_type != proposed_type
        confidence_width = 0.25 if is_type_change else 0.15

        ci = ConfidenceInterval(
            lower=predicted_cost * (1 - confidence_width),
            upper=predicted_cost * (1 + confidence_width),
            confidence_level=0.90,
        )

        # Generate evidence
        evidence = self._generate_evidence(
            baseline_cost=baseline_cost,
            predicted_cost=predicted_cost,
            current_type=current_type,
            proposed_type=proposed_type,
            historical_data=historical_data,
        )

        # Determine confidence level
        confidence: Literal["low", "medium", "high"]
        if monthly_dbu > 0 and total_queries > 100:
            confidence = "high"
        elif monthly_dbu > 0 or total_queries > 10:
            confidence = "medium"
        else:
            confidence = "low"

        return PredictionResult(
            value=predicted_cost,
            unit="USD/month",
            confidence_interval=ci,
            confidence=confidence,
            evidence=tuple(evidence),
            assumptions=self._get_assumptions(proposed_type),
            limitations=self._get_limitations(is_type_change),
            model_name=self.model_name,
            model_version=self.model_version,
        )

    def _estimate_serverless_cost(
        self,
        monthly_dbu: float,
        total_queries: float,
        avg_runtime_sec: float,
    ) -> float:
        """Estimate monthly cost for serverless configuration.

        Serverless charges only for actual compute time with instant scaling.
        """
        if monthly_dbu > 0:
            # Use DBU consumption directly
            compute_cost = monthly_dbu * self.serverless_dbu_price
        else:
            # Estimate from query volume and runtime
            # Assume 0.0025 DBU per query-second (rough estimate)
            total_runtime_hours = (total_queries * avg_runtime_sec) / 3600
            estimated_dbu = total_runtime_hours * 2.5  # Approximate DBU per hour
            compute_cost = estimated_dbu * self.serverless_dbu_price

        # Serverless has no idle costs or startup costs
        return compute_cost

    def _estimate_standard_cost(
        self,
        monthly_dbu: float,
        scenario: Scenario,
        historical_data: HistoricalData,
    ) -> float:
        """Estimate monthly cost for standard configuration.

        Standard has compute cost plus idle time and startup overhead.
        """
        # Get cluster sizing parameters
        current_max_raw = self._get_param_value(scenario, "max_clusters", 4)
        proposed_max_raw = self._get_proposed_value(
            scenario, "max_clusters", current_max_raw
        )
        current_max = (
            float(current_max_raw) if not isinstance(current_max_raw, str) else 4.0
        )
        proposed_max = (
            float(proposed_max_raw) if not isinstance(proposed_max_raw, str) else 4.0
        )

        current_auto_stop_raw = self._get_param_value(scenario, "auto_stop_mins", 10)
        proposed_auto_stop_raw = self._get_proposed_value(
            scenario, "auto_stop_mins", current_auto_stop_raw
        )
        proposed_auto_stop = (
            float(proposed_auto_stop_raw)
            if not isinstance(proposed_auto_stop_raw, str)
            else 10.0
        )

        # Calculate compute cost (scaled by cluster change)
        scale_factor = proposed_max / max(current_max, 1)
        compute_cost = (monthly_dbu or 500) * self.standard_dbu_price * scale_factor

        # Estimate idle cost (longer auto-stop = more idle time)
        # Rough estimate: 10% of compute time is idle at 10min auto-stop
        idle_pct = 0.10 * (proposed_auto_stop / 10)
        idle_cost = compute_cost * idle_pct

        # Startup cost (each start costs ~30 seconds at full cluster)
        starts_per_day = historical_data.get_aggregate("starts_per_day", 5)
        startup_dbu = starts_per_day * 30 * proposed_max * 0.5 / 3600  # DBU per start
        startup_cost = startup_dbu * 30 * self.standard_dbu_price  # Monthly

        return compute_cost + idle_cost + startup_cost

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
        baseline_cost: float,
        predicted_cost: float,
        current_type: str | int | float,
        proposed_type: str | int | float,
        historical_data: HistoricalData,
    ) -> list[str]:
        """Generate evidence strings for the prediction."""
        evidence = []

        # Cost comparison
        if baseline_cost > 0:
            change_pct = ((predicted_cost - baseline_cost) / baseline_cost) * 100
            if change_pct < 0:
                evidence.append(
                    f"Estimated {abs(change_pct):.0f}% cost reduction "
                    f"(${baseline_cost:.0f} -> ${predicted_cost:.0f}/month)"
                )
            elif change_pct > 0:
                evidence.append(
                    f"Estimated {change_pct:.0f}% cost increase "
                    f"(${baseline_cost:.0f} -> ${predicted_cost:.0f}/month)"
                )
            else:
                evidence.append("No significant cost change expected")

        # Type-specific evidence
        if current_type != proposed_type:
            if proposed_type == "serverless":
                evidence.append("Serverless eliminates idle time and startup costs")
                evidence.append(
                    "Serverless has instant scaling but higher per-DBU price"
                )
            else:
                evidence.append(
                    "Standard provides predictable pricing for sustained workloads"
                )

        # Volume evidence
        total_queries = historical_data.get_aggregate("total_queries", 0)
        if total_queries > 0:
            evidence.append(
                f"Based on {total_queries:.0f} queries "
                f"over {historical_data.window_days} days"
            )

        return evidence

    def _get_assumptions(
        self,
        warehouse_type: str | int | float,
    ) -> tuple[str, ...]:
        """Get assumptions for the prediction."""
        assumptions = [
            "Query volume remains consistent with historical data",
            "No significant workload pattern changes",
        ]

        if warehouse_type == "serverless":
            assumptions.append("Using Databricks Premium serverless pricing")
        else:
            assumptions.append("Using Databricks Pro standard pricing")

        return tuple(assumptions)

    def _get_limitations(self, is_type_change: bool) -> tuple[str, ...]:
        """Get limitations for the prediction."""
        limitations = [
            "Actual costs may vary based on query complexity",
            "Network and storage costs not included",
        ]

        if is_type_change:
            limitations.append("Type migration predictions have wider uncertainty")

        return tuple(limitations)
