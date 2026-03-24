"""Scenario models for what-if analysis.

This module provides data structures for defining hypothetical scenarios
that can be evaluated by prediction models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ScenarioParameter:
    """Single parameter change in a scenario.

    Represents a configuration change from current to proposed value.

    Attributes:
        name: Parameter name (e.g., "warehouse_type", "min_num_clusters").
        current_value: Current/baseline value.
        proposed_value: Proposed value in the scenario.
        unit: Optional unit for the value (e.g., "minutes", "USD").

    Example:
        ```python
        # Type change
        param = ScenarioParameter(
            name="warehouse_type",
            current_value="standard",
            proposed_value="serverless",
        )

        # Sizing change with percentage
        param = ScenarioParameter(
            name="max_clusters",
            current_value=4,
            proposed_value=2,
        )
        print(f"Change: {param.change_pct}%")  # -50.0
        ```
    """

    name: str
    current_value: Any
    proposed_value: Any
    unit: str | None = None

    @property
    def change_pct(self) -> float | None:
        """Calculate percentage change if numeric.

        Returns:
            Percentage change from current to proposed, or None if not numeric
            or current value is zero.
        """
        if not isinstance(self.current_value, (int, float)):
            return None
        if not isinstance(self.proposed_value, (int, float)):
            return None
        if self.current_value == 0:
            return None

        return ((self.proposed_value - self.current_value) / self.current_value) * 100


@dataclass(frozen=True)
class Scenario:
    """What-if scenario definition.

    Generic container for scenario parameters that can be used
    across different domains (warehouse, cluster, job).

    Attributes:
        scenario_id: Unique identifier for this scenario.
        name: Human-readable name.
        description: Description of what this scenario represents.
        entity_type: Type of entity being modified ("warehouse", "cluster", "job").
        entity_id: ID of the entity being evaluated.
        parameters: Tuple of parameter changes in this scenario.
        created_at: When the scenario was created.
        created_by: Optional user who created the scenario.
        compare_to_baseline: Whether to compare against baseline.
        baseline_window_days: Number of days of historical data for baseline.

    Example:
        ```python
        scenario = Scenario(
            scenario_id="serverless-migration",
            name="Serverless Migration",
            description="Evaluate moving to serverless",
            entity_type="warehouse",
            entity_id="wh-123",
            parameters=(
                ScenarioParameter("warehouse_type", "standard", "serverless"),
            ),
        )
        ```
    """

    scenario_id: str
    name: str
    description: str

    # Entity being modified
    entity_type: str  # "warehouse", "cluster", "job", etc.
    entity_id: str

    # Parameter changes
    parameters: tuple[ScenarioParameter, ...]

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str | None = None

    # Comparison options
    compare_to_baseline: bool = True
    baseline_window_days: int = 30

    def get_parameter(self, name: str) -> ScenarioParameter | None:
        """Get a specific parameter by name.

        Args:
            name: Parameter name to look for.

        Returns:
            ScenarioParameter if found, None otherwise.
        """
        for p in self.parameters:
            if p.name == name:
                return p
        return None

    def get_proposed_config(self) -> dict[str, Any]:
        """Get proposed configuration as dict.

        Returns:
            Dictionary mapping parameter names to proposed values.
        """
        return {p.name: p.proposed_value for p in self.parameters}


def create_warehouse_scenario(
    scenario_id: str,
    warehouse_id: str,
    current_config: dict[str, Any],
    new_warehouse_type: str | None = None,
    new_min_size: int | None = None,
    new_max_size: int | None = None,
    new_auto_stop_minutes: int | None = None,
) -> Scenario:
    """Create a warehouse configuration scenario.

    Factory function for creating common warehouse scenarios.

    Args:
        scenario_id: Unique identifier for the scenario.
        warehouse_id: ID of the warehouse to evaluate.
        current_config: Current warehouse configuration.
        new_warehouse_type: New type ("standard" or "serverless").
        new_min_size: New minimum cluster count.
        new_max_size: New maximum cluster count.
        new_auto_stop_minutes: New auto-stop timeout in minutes.

    Returns:
        Scenario configured for warehouse evaluation.

    Example:
        ```python
        scenario = create_warehouse_scenario(
            scenario_id="to-serverless",
            warehouse_id="wh-123",
            current_config={"warehouse_type": "standard", "min_num_clusters": 2},
            new_warehouse_type="serverless",
        )
        ```
    """
    parameters: list[ScenarioParameter] = []

    if new_warehouse_type is not None:
        parameters.append(
            ScenarioParameter(
                name="warehouse_type",
                current_value=current_config.get("warehouse_type"),
                proposed_value=new_warehouse_type,
            )
        )

    if new_min_size is not None:
        parameters.append(
            ScenarioParameter(
                name="min_num_clusters",
                current_value=current_config.get("min_num_clusters"),
                proposed_value=new_min_size,
            )
        )

    if new_max_size is not None:
        parameters.append(
            ScenarioParameter(
                name="max_num_clusters",
                current_value=current_config.get("max_num_clusters"),
                proposed_value=new_max_size,
            )
        )

    if new_auto_stop_minutes is not None:
        parameters.append(
            ScenarioParameter(
                name="auto_stop_mins",
                current_value=current_config.get("auto_stop_mins"),
                proposed_value=new_auto_stop_minutes,
                unit="minutes",
            )
        )

    return Scenario(
        scenario_id=scenario_id,
        name=f"Warehouse config change: {scenario_id}",
        description=f"Evaluate configuration changes for warehouse {warehouse_id}",
        entity_type="warehouse",
        entity_id=warehouse_id,
        parameters=tuple(parameters),
    )
