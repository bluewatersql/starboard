"""Prediction models for what-if analysis.

This subpackage contains concrete prediction model implementations.
Models can be used with the ScenarioEvaluator.

Example:
    ```python
    from starboard_server.infra.whatif.models import (
        WarehouseCostModel,
        WarehouseLatencyModel,
        WarehouseQueueRiskModel,
    )

    evaluator = ScenarioEvaluator(models=[
        WarehouseCostModel(),
        WarehouseLatencyModel(),
        WarehouseQueueRiskModel(),
    ])
    ```
"""

from starboard_server.infra.whatif.models.warehouse_cost import WarehouseCostModel
from starboard_server.infra.whatif.models.warehouse_latency import WarehouseLatencyModel
from starboard_server.infra.whatif.models.warehouse_risk import WarehouseQueueRiskModel

__all__ = [
    "WarehouseCostModel",
    "WarehouseLatencyModel",
    "WarehouseQueueRiskModel",
]
