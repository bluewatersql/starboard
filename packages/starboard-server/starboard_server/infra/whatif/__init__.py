"""Generalized What-If Engine.

This module provides a framework for statistical simulation, pattern analysis,
and prediction across domain agents. Features include:

- Pluggable prediction models (cost, performance, risk)
- Confidence intervals on all predictions
- Scenario comparison and ranking
- Reusable across warehouse, cluster, job agents

Example:
    ```python
    from starboard_server.infra.whatif import (
        Scenario,
        ScenarioEvaluator,
        ScenarioParameter,
        create_warehouse_scenario,
    )

    # Create a scenario
    scenario = create_warehouse_scenario(
        scenario_id="serverless-migration",
        warehouse_id="wh-123",
        current_config=current_config,
        new_warehouse_type="serverless",
    )

    # Evaluate scenario
    evaluator = ScenarioEvaluator()
    result = await evaluator.evaluate(scenario, historical_data)

    if result.recommended:
        print(f"Recommended: {result.recommendation_rationale}")
    ```
"""

from starboard_server.infra.whatif.evaluator import (
    ScenarioComparison,
    ScenarioEvaluation,
    ScenarioEvaluator,
)
from starboard_server.infra.whatif.historical import (
    HistoricalData,
    TimeSeriesData,
)
from starboard_server.infra.whatif.prediction import (
    ConfidenceInterval,
    PredictionModel,
    PredictionResult,
)
from starboard_server.infra.whatif.scenario import (
    Scenario,
    ScenarioParameter,
    create_warehouse_scenario,
)

__all__ = [
    # Scenario
    "Scenario",
    "ScenarioParameter",
    "create_warehouse_scenario",
    # Models
    "ConfidenceInterval",
    "PredictionModel",
    "PredictionResult",
    # Evaluator
    "ScenarioComparison",
    "ScenarioEvaluation",
    "ScenarioEvaluator",
    # Historical
    "HistoricalData",
    "TimeSeriesData",
]
