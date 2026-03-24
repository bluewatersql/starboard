"""Scenario evaluator for what-if analysis.

This module provides the ScenarioEvaluator class that orchestrates
multiple prediction models to evaluate scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from starboard_server.infra.whatif.historical import HistoricalData
from starboard_server.infra.whatif.prediction import PredictionModel, PredictionResult
from starboard_server.infra.whatif.scenario import Scenario


@dataclass(frozen=True)
class ScenarioEvaluation:
    """Complete evaluation of a scenario.

    Contains predictions from all applicable models along with
    recommendations and comparative analysis.

    Attributes:
        scenario: The evaluated scenario.
        cost_prediction: Cost model prediction if available.
        performance_prediction: Performance model prediction if available.
        risk_prediction: Risk model prediction if available.
        recommended: Whether this scenario is recommended.
        recommendation_rationale: Explanation for the recommendation.
        cost_change_pct: Percentage change in cost vs baseline.
        latency_change_pct: Percentage change in latency vs baseline.
        overall_confidence: Minimum confidence across all predictions.
        key_findings: Summary of key findings.
        trade_offs: Identified trade-offs.
        risks: Identified risks.
    """

    scenario: Scenario

    # Predictions by category
    cost_prediction: PredictionResult | None
    performance_prediction: PredictionResult | None
    risk_prediction: PredictionResult | None

    # Summary
    recommended: bool
    recommendation_rationale: str

    # Comparison to baseline
    cost_change_pct: float | None
    latency_change_pct: float | None

    # Confidence
    overall_confidence: Literal["low", "medium", "high"]

    # Evidence rollup
    key_findings: tuple[str, ...]
    trade_offs: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioComparison:
    """Comparison of multiple scenarios.

    Contains evaluations for all scenarios and ranking information.

    Attributes:
        evaluations: Tuple of all scenario evaluations.
        ranked_scenarios: Scenarios sorted by overall score (best first).
        best_scenario_id: ID of the best scenario.
        comparison_summary: Text summary of the comparison.
    """

    evaluations: tuple[ScenarioEvaluation, ...]
    ranked_scenarios: tuple[ScenarioEvaluation, ...]
    best_scenario_id: str | None
    comparison_summary: str


class ScenarioEvaluator:
    """Evaluates scenarios using multiple prediction models.

    Orchestrates model execution and aggregates results into a
    comprehensive evaluation with recommendations.

    Attributes:
        models: List of prediction models to use.

    Example:
        ```python
        evaluator = ScenarioEvaluator(models=[
            WarehouseCostModel(),
            LatencyPredictionModel(),
            QueueRiskModel(),
        ])

        result = await evaluator.evaluate(scenario, historical_data)

        if result.recommended:
            print(f"Recommended: {result.recommendation_rationale}")
        ```
    """

    def __init__(
        self,
        models: list[PredictionModel] | None = None,
    ) -> None:
        """Initialize the evaluator.

        Args:
            models: List of prediction models. If None, no predictions are made.
        """
        self.models: list[PredictionModel] = models or []

    async def evaluate(
        self,
        scenario: Scenario,
        historical_data: HistoricalData,
    ) -> ScenarioEvaluation:
        """Evaluate a scenario against all applicable models.

        Args:
            scenario: Scenario to evaluate.
            historical_data: Historical data for context.

        Returns:
            Complete scenario evaluation.
        """
        # Run applicable models
        cost_prediction: PredictionResult | None = None
        performance_prediction: PredictionResult | None = None
        risk_prediction: PredictionResult | None = None

        for model in self.models:
            if not model.can_predict(scenario):
                continue

            prediction = await model.predict(scenario, historical_data)

            # Categorize by model type
            model_name_lower = model.model_name.lower()
            if "cost" in model_name_lower:
                cost_prediction = prediction
            elif "latency" in model_name_lower or "performance" in model_name_lower:
                performance_prediction = prediction
            elif "risk" in model_name_lower:
                risk_prediction = prediction

        # Calculate changes vs baseline
        cost_change_pct = self._calculate_cost_change(cost_prediction, historical_data)
        latency_change_pct = self._calculate_latency_change(
            performance_prediction, historical_data
        )

        # Generate recommendation
        recommended, rationale = self._generate_recommendation(
            risk_prediction,
            cost_change_pct,
            latency_change_pct,
        )

        # Aggregate findings
        key_findings = self._aggregate_evidence(
            cost_prediction,
            performance_prediction,
            risk_prediction,
        )

        trade_offs = self._identify_tradeoffs(
            cost_change_pct,
            latency_change_pct,
        )

        risks = self._aggregate_risks(
            cost_prediction,
            performance_prediction,
            risk_prediction,
        )

        # Determine overall confidence
        overall_confidence = self._determine_overall_confidence(
            cost_prediction,
            performance_prediction,
            risk_prediction,
        )

        return ScenarioEvaluation(
            scenario=scenario,
            cost_prediction=cost_prediction,
            performance_prediction=performance_prediction,
            risk_prediction=risk_prediction,
            recommended=recommended,
            recommendation_rationale=rationale,
            cost_change_pct=cost_change_pct,
            latency_change_pct=latency_change_pct,
            overall_confidence=overall_confidence,
            key_findings=tuple(key_findings),
            trade_offs=tuple(trade_offs),
            risks=tuple(risks),
        )

    async def compare_scenarios(
        self,
        scenarios: list[Scenario],
        historical_data: HistoricalData,
    ) -> ScenarioComparison:
        """Evaluate and compare multiple scenarios.

        Args:
            scenarios: List of scenarios to compare.
            historical_data: Historical data for context.

        Returns:
            Comparison with ranked scenarios.
        """
        evaluations = []
        for scenario in scenarios:
            eval_result = await self.evaluate(scenario, historical_data)
            evaluations.append(eval_result)

        # Rank scenarios
        ranked = self._rank_scenarios(evaluations)

        return ScenarioComparison(
            evaluations=tuple(evaluations),
            ranked_scenarios=tuple(ranked),
            best_scenario_id=ranked[0].scenario.scenario_id if ranked else None,
            comparison_summary=self._generate_comparison_summary(evaluations),
        )

    def _calculate_cost_change(
        self,
        cost_prediction: PredictionResult | None,
        historical_data: HistoricalData,
    ) -> float | None:
        """Calculate cost change percentage."""
        if cost_prediction is None:
            return None

        baseline_cost = historical_data.get_aggregate("monthly_cost_usd")
        if baseline_cost <= 0:
            return None

        return ((cost_prediction.value - baseline_cost) / baseline_cost) * 100

    def _calculate_latency_change(
        self,
        performance_prediction: PredictionResult | None,
        historical_data: HistoricalData,
    ) -> float | None:
        """Calculate latency change percentage."""
        if performance_prediction is None:
            return None

        baseline_latency = historical_data.get_aggregate("p95_runtime_sec")
        if baseline_latency <= 0:
            return None

        return (
            (performance_prediction.value - baseline_latency) / baseline_latency
        ) * 100

    def _generate_recommendation(
        self,
        risk_pred: PredictionResult | None,
        cost_change_pct: float | None,
        latency_change_pct: float | None,
    ) -> tuple[bool, str]:
        """Generate recommendation based on predictions."""
        # Don't recommend high-risk scenarios
        if risk_pred and risk_pred.value > 0.7:
            return False, "Not recommended: High queue/capacity risk"

        # Recommend if cost savings > 10% without SLO risk
        has_cost_savings = cost_change_pct is not None and cost_change_pct < -10
        acceptable_latency = latency_change_pct is None or latency_change_pct < 20
        acceptable_risk = risk_pred is None or risk_pred.value < 0.7

        if has_cost_savings and acceptable_latency and acceptable_risk:
            # cost_change_pct is guaranteed non-None here due to has_cost_savings check
            savings = abs(cost_change_pct) if cost_change_pct is not None else 0
            return (
                True,
                f"Recommended: {savings:.0f}% cost savings "
                "with acceptable performance impact",
            )

        # Recommend if performance improves significantly
        has_perf_improvement = (
            latency_change_pct is not None and latency_change_pct < -15
        )
        acceptable_cost = cost_change_pct is None or cost_change_pct < 30

        if has_perf_improvement and acceptable_cost:
            # latency_change_pct is guaranteed non-None here due to has_perf_improvement check
            improvement = (
                abs(latency_change_pct) if latency_change_pct is not None else 0
            )
            return (
                True,
                f"Recommended: {improvement:.0f}% latency improvement",
            )

        return False, "Neutral: No significant improvement in cost or performance"

    def _aggregate_evidence(
        self,
        cost_pred: PredictionResult | None,
        perf_pred: PredictionResult | None,
        risk_pred: PredictionResult | None,
    ) -> list[str]:
        """Aggregate evidence from all predictions."""
        findings: list[str] = []

        for pred in [cost_pred, perf_pred, risk_pred]:
            if pred:
                findings.extend(pred.evidence)

        return findings

    def _identify_tradeoffs(
        self,
        cost_change_pct: float | None,
        latency_change_pct: float | None,
    ) -> list[str]:
        """Identify trade-offs in the scenario."""
        trade_offs: list[str] = []

        # Cost vs Performance trade-off
        if cost_change_pct is not None and latency_change_pct is not None:
            if cost_change_pct < 0 and latency_change_pct > 0:
                trade_offs.append(
                    f"Cost savings ({abs(cost_change_pct):.0f}%) may increase "
                    f"latency ({latency_change_pct:.0f}%)"
                )
            elif cost_change_pct > 0 and latency_change_pct < 0:
                trade_offs.append(
                    f"Performance improvement ({abs(latency_change_pct):.0f}%) "
                    f"comes at additional cost ({cost_change_pct:.0f}%)"
                )

        return trade_offs

    def _aggregate_risks(
        self,
        cost_pred: PredictionResult | None,
        perf_pred: PredictionResult | None,
        risk_pred: PredictionResult | None,
    ) -> list[str]:
        """Aggregate risks from predictions."""
        risks: list[str] = []

        for pred in [cost_pred, perf_pred, risk_pred]:
            if pred:
                risks.extend(pred.limitations)

        if risk_pred and risk_pred.value > 0.5:
            risks.append(f"Elevated risk score: {risk_pred.value:.2f}")

        return risks

    def _determine_overall_confidence(
        self,
        cost_pred: PredictionResult | None,
        perf_pred: PredictionResult | None,
        risk_pred: PredictionResult | None,
    ) -> Literal["low", "medium", "high"]:
        """Determine overall confidence (minimum of all predictions)."""
        confidence_order = {"low": 0, "medium": 1, "high": 2}

        confidences = [
            p.confidence for p in [cost_pred, perf_pred, risk_pred] if p is not None
        ]

        if not confidences:
            return "low"

        return min(confidences, key=lambda c: confidence_order[c])

    def _rank_scenarios(
        self,
        evaluations: list[ScenarioEvaluation],
    ) -> list[ScenarioEvaluation]:
        """Rank scenarios by overall value."""

        def score(eval_result: ScenarioEvaluation) -> float:
            result_score = 0.0

            # Cost savings are good (negative change = positive score)
            if eval_result.cost_change_pct is not None:
                result_score -= eval_result.cost_change_pct * 0.4  # 40% weight

            # Latency improvements are good
            if eval_result.latency_change_pct is not None:
                result_score -= eval_result.latency_change_pct * 0.3  # 30% weight

            # Low risk is good
            if eval_result.risk_prediction:
                result_score -= eval_result.risk_prediction.value * 30  # 30% weight

            return result_score

        return sorted(evaluations, key=score, reverse=True)

    def _generate_comparison_summary(
        self,
        evaluations: list[ScenarioEvaluation],
    ) -> str:
        """Generate a summary of the scenario comparison."""
        if not evaluations:
            return "No scenarios to compare."

        recommended = [e for e in evaluations if e.recommended]

        if not recommended:
            return f"Evaluated {len(evaluations)} scenarios. None recommended."

        return (
            f"Evaluated {len(evaluations)} scenarios. {len(recommended)} recommended."
        )
