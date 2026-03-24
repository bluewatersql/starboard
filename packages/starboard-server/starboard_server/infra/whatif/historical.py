"""Historical data abstractions for what-if analysis.

This module provides data structures for representing historical data
used by prediction models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TimeSeriesData:
    """Time series data for analysis.

    Represents a sequence of values over time with statistical helpers.

    Attributes:
        timestamps: Tuple of timestamps for each data point.
        values: Tuple of values corresponding to timestamps.
        unit: Unit of the values (e.g., "USD", "seconds").

    Example:
        ```python
        ts = TimeSeriesData(
            timestamps=(dt1, dt2, dt3),
            values=(100.0, 150.0, 120.0),
            unit="queries",
        )
        print(f"Mean: {ts.mean}")
        print(f"Std: {ts.std}")
        ```
    """

    timestamps: tuple[datetime, ...]
    values: tuple[float, ...]
    unit: str

    @property
    def mean(self) -> float:
        """Calculate mean of values."""
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)

    @property
    def std(self) -> float:
        """Calculate standard deviation of values."""
        if len(self.values) < 2:
            return 0.0
        mean = self.mean
        variance = sum((x - mean) ** 2 for x in self.values) / len(self.values)
        return variance**0.5

    def percentile(self, p: float) -> float:
        """Calculate percentile of values.

        Args:
            p: Percentile as decimal (e.g., 0.95 for 95th percentile).

        Returns:
            Value at the given percentile.
        """
        if not self.values:
            return 0.0
        sorted_values = sorted(self.values)
        index = int(p * (len(sorted_values) - 1))
        return sorted_values[index]

    def recent(self, n: int) -> TimeSeriesData:
        """Get last n data points.

        Args:
            n: Number of recent points to return.

        Returns:
            New TimeSeriesData with only the last n points.
        """
        return TimeSeriesData(
            timestamps=self.timestamps[-n:],
            values=self.values[-n:],
            unit=self.unit,
        )


@dataclass
class HistoricalData:
    """Container for historical data used in predictions.

    Aggregates various historical metrics and patterns for an entity.

    Attributes:
        entity_type: Type of entity ("warehouse", "cluster", "job").
        entity_id: ID of the entity.
        window_days: Number of days of historical data.
        metrics: Dictionary of time series metrics.
        aggregates: Pre-computed aggregate statistics.
        hourly_pattern: Optional hourly usage pattern (hour -> avg value).
        daily_pattern: Optional daily usage pattern (day of week -> avg value).
        collected_at: When this data was collected.

    Example:
        ```python
        historical = HistoricalData(
            entity_type="warehouse",
            entity_id="wh-123",
            window_days=30,
            aggregates={
                "monthly_cost_usd": 1500.0,
                "p95_runtime_sec": 10.0,
                "total_queries": 10000,
            },
        )

        cost = historical.get_aggregate("monthly_cost_usd")
        ```
    """

    entity_type: str
    entity_id: str
    window_days: int

    # Time series metrics
    metrics: dict[str, TimeSeriesData] = field(default_factory=dict)

    # Aggregate statistics
    aggregates: dict[str, float] = field(default_factory=dict)

    # Patterns
    hourly_pattern: dict[int, float] | None = None
    daily_pattern: dict[int, float] | None = None

    # Metadata
    collected_at: datetime = field(default_factory=datetime.now)

    def get_metric(self, name: str) -> TimeSeriesData | None:
        """Get a time series metric by name.

        Args:
            name: Metric name.

        Returns:
            TimeSeriesData if found, None otherwise.
        """
        return self.metrics.get(name)

    def get_aggregate(self, name: str, default: float = 0.0) -> float:
        """Get an aggregate statistic by name.

        Args:
            name: Aggregate name.
            default: Default value if not found.

        Returns:
            Aggregate value or default.
        """
        return self.aggregates.get(name, default)
