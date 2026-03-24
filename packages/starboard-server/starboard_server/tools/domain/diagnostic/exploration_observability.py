# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Exploration observability for diagnostic agent.

This module provides telemetry and metrics collection for diagnostic
exploration, enabling monitoring of:
- Step latency per strategy
- Confidence progression
- Step count distribution
- Error rates

Design reference: changes/diagnostic_agent/UNIFIED_DESIGN.md
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


@dataclass
class StepMetrics:
    """Metrics for a single exploration step.

    Captures timing, confidence changes, and findings for each step.
    """

    strategy: str
    """The exploration strategy executed."""

    latency_ms: int
    """Execution time in milliseconds."""

    confidence_before: float
    """Confidence level before this step."""

    confidence_after: float
    """Confidence level after this step."""

    findings_count: int
    """Number of findings produced by this step."""

    error: str | None = None
    """Error message if step failed."""

    @property
    def confidence_delta(self) -> float:
        """Calculate confidence change from this step."""
        return self.confidence_after - self.confidence_before


@dataclass
class ExplorationMetrics:
    """Aggregate metrics for a complete exploration.

    Collects all step metrics and provides summary statistics.
    """

    exploration_id: str
    """Unique identifier for this exploration."""

    artifact_type: str
    """Type of artifact being explored."""

    steps: list[StepMetrics] = field(default_factory=list)
    """Metrics for each step in the exploration."""

    @property
    def total_latency_ms(self) -> int:
        """Total latency across all steps."""
        return sum(step.latency_ms for step in self.steps)

    @property
    def final_confidence(self) -> float:
        """Final confidence level after all steps."""
        if not self.steps:
            return 0.0
        return self.steps[-1].confidence_after

    @property
    def confidence_progression(self) -> list[float]:
        """Track confidence at each step.

        Returns list starting with initial confidence (0.0) and
        including confidence after each step.
        """
        if not self.steps:
            return [0.0]
        progression = [self.steps[0].confidence_before]
        for step in self.steps:
            progression.append(step.confidence_after)
        return progression

    @property
    def step_count(self) -> int:
        """Number of steps executed."""
        return len(self.steps)

    @property
    def strategies_used(self) -> list[str]:
        """List of strategies used in order."""
        return [step.strategy for step in self.steps]

    @property
    def error_count(self) -> int:
        """Number of steps that had errors."""
        return sum(1 for step in self.steps if step.error is not None)

    def to_dict(self) -> dict:
        """Serialize to dictionary for logging/export.

        Returns:
            Dictionary with exploration metrics.
        """
        return {
            "exploration_id": self.exploration_id,
            "artifact_type": self.artifact_type,
            "step_count": self.step_count,
            "total_latency_ms": self.total_latency_ms,
            "final_confidence": self.final_confidence,
            "confidence_progression": self.confidence_progression,
            "strategies_used": self.strategies_used,
            "error_count": self.error_count,
            "steps": [
                {
                    "strategy": step.strategy,
                    "latency_ms": step.latency_ms,
                    "confidence_before": step.confidence_before,
                    "confidence_after": step.confidence_after,
                    "confidence_delta": step.confidence_delta,
                    "findings_count": step.findings_count,
                    "error": step.error,
                }
                for step in self.steps
            ],
        }


@dataclass
class ExplorationTelemetry:
    """Telemetry collector for exploration events.

    Tracks exploration sessions, step metrics, and provides
    aggregate statistics for monitoring and optimization.
    """

    _current_exploration: ExplorationMetrics | None = field(default=None)
    """Currently active exploration."""

    _history: list[ExplorationMetrics] = field(default_factory=list)
    """Completed explorations."""

    _latency_samples: dict[str, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    """Latency samples per strategy for percentile calculations."""

    @property
    def current_exploration_id(self) -> str | None:
        """Get the current exploration ID."""
        if self._current_exploration is None:
            return None
        return self._current_exploration.exploration_id

    def start_exploration(self, artifact_type: str) -> str:
        """Start tracking a new exploration.

        Args:
            artifact_type: Type of artifact being explored.

        Returns:
            Unique exploration ID.
        """
        exploration_id = f"exp_{uuid.uuid4().hex[:12]}"
        self._current_exploration = ExplorationMetrics(
            exploration_id=exploration_id,
            artifact_type=artifact_type,
        )
        return exploration_id

    def record_step(
        self,
        strategy: str,
        latency_ms: int,
        confidence_before: float,
        confidence_after: float,
        findings_count: int,
        error: str | None = None,
    ) -> None:
        """Record metrics for a completed step.

        Args:
            strategy: The strategy that was executed.
            latency_ms: Execution time in milliseconds.
            confidence_before: Confidence before this step.
            confidence_after: Confidence after this step.
            findings_count: Number of findings produced.
            error: Error message if step failed.
        """
        if self._current_exploration is None:
            return

        step = StepMetrics(
            strategy=strategy,
            latency_ms=latency_ms,
            confidence_before=confidence_before,
            confidence_after=confidence_after,
            findings_count=findings_count,
            error=error,
        )
        self._current_exploration.steps.append(step)

        # Track latency for percentile calculations
        self._latency_samples[strategy].append(latency_ms)

    def get_current_metrics(self) -> ExplorationMetrics | None:
        """Get metrics for the current exploration.

        Returns:
            Current exploration metrics or None if no active exploration.
        """
        return self._current_exploration

    def end_exploration(self) -> ExplorationMetrics | None:
        """End the current exploration and add to history.

        Returns:
            Completed exploration metrics.
        """
        if self._current_exploration is None:
            return None

        metrics = self._current_exploration
        self._history.append(metrics)
        self._current_exploration = None
        return metrics

    def get_history(self) -> list[ExplorationMetrics]:
        """Get all completed explorations.

        Returns:
            List of completed exploration metrics.
        """
        return self._history.copy()

    def get_aggregate_stats(self) -> dict:
        """Compute aggregate statistics across all explorations.

        Returns:
            Dictionary with aggregate metrics.
        """
        if not self._history:
            return {
                "exploration_count": 0,
                "avg_step_count": 0.0,
                "avg_latency_ms": 0.0,
                "avg_final_confidence": 0.0,
            }

        total_steps = sum(m.step_count for m in self._history)
        total_latency = sum(m.total_latency_ms for m in self._history)
        total_confidence = sum(m.final_confidence for m in self._history)
        count = len(self._history)

        return {
            "exploration_count": count,
            "avg_step_count": total_steps / count,
            "avg_latency_ms": total_latency / count,
            "avg_final_confidence": total_confidence / count,
        }

    def get_latency_by_strategy(self) -> dict[str, list[int]]:
        """Get latency samples grouped by strategy.

        Returns:
            Dictionary mapping strategy names to latency samples.
        """
        return dict(self._latency_samples)

    def get_latency_percentiles(self, strategy: str) -> dict[str, float]:
        """Compute latency percentiles for a strategy.

        Args:
            strategy: The strategy to analyze.

        Returns:
            Dictionary with p50, p95, p99 latencies.
        """
        samples = self._latency_samples.get(strategy, [])
        if not samples:
            return {}

        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        def percentile(p: float) -> float:
            k = (n - 1) * p
            f = int(k)
            c = f + 1
            if c >= n:
                return float(sorted_samples[-1])
            return sorted_samples[f] + (k - f) * (sorted_samples[c] - sorted_samples[f])

        return {
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
        }

    @contextmanager
    def exploration(self, artifact_type: str) -> Generator[str, None, None]:
        """Context manager for exploration tracking.

        Usage:
            with telemetry.exploration("logs") as exp_id:
                telemetry.record_step(...)

        Args:
            artifact_type: Type of artifact being explored.

        Yields:
            Exploration ID.
        """
        exp_id = self.start_exploration(artifact_type)
        try:
            yield exp_id
        finally:
            self.end_exploration()

    def reset(self) -> None:
        """Reset all telemetry state."""
        self._current_exploration = None
        self._history = []
        self._latency_samples = defaultdict(list)
