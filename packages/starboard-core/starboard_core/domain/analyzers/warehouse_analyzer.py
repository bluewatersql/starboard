# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Warehouse analyzers.

Pure domain logic for calculating warehouse fingerprints and health scores.
This module contains stateless analyzers for:
- FingerprintCalculator: Transforms raw query history into fingerprints
- HealthScorer: Evaluates warehouse health from fingerprints

All methods are stateless and can be called independently.
No I/O operations - only computation on provided data.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from starboard_core.domain.models.warehouse import (
    HealthSummary,
    QueryTypeDistribution,
    RiskFactor,
    SLOStatus,
    TimeDistribution,
    WarehouseFingerprint,
    WorkloadPattern,
)

if TYPE_CHECKING:
    from starboard_core.domain.models.warehouse import SLOConfig


# =============================================================================
# Percentile Helper
# =============================================================================


def _percentile(values: list[float], p: float) -> float:
    """Calculate inclusive percentile (0-100).

    Args:
        values: List of values to calculate percentile from.
        p: Percentile (0-100).

    Returns:
        Value at the given percentile, or NaN if empty.
    """
    if not values:
        return float("nan")
    v = sorted(values)
    if p <= 0:
        return v[0]
    if p >= 100:
        return v[-1]
    k = (len(v) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return v[int(k)]
    return v[f] + (v[c] - v[f]) * (k - f)


# =============================================================================
# Query Record
# =============================================================================


@dataclass(frozen=True)
class QueryRecord:
    """Parsed query record with typed fields.

    Attributes:
        statement_id: Unique query identifier.
        warehouse_id: Target warehouse ID.
        statement_type: SQL statement type (SELECT, INSERT, etc.).
        duration_ms: Total query duration in milliseconds.
        queue_time_ms: Time spent waiting in queue.
        bytes_read: Bytes read during query execution.
        bytes_written: Bytes written during query execution.
        start_time: Query start timestamp.
        user_name: User who executed the query.
    """

    statement_id: str
    warehouse_id: str
    statement_type: str
    duration_ms: float
    queue_time_ms: float
    bytes_read: int
    bytes_written: int
    start_time: datetime | None
    user_name: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> QueryRecord:
        """Parse a raw query record dictionary.

        Args:
            raw: Dictionary with query record fields.

        Returns:
            Typed QueryRecord instance.
        """
        # Handle start_time parsing
        start_time = raw.get("start_time")
        if isinstance(start_time, str):
            # Try parsing ISO format
            try:
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                start_time = None

        return cls(
            statement_id=raw.get("statement_id") or "",
            warehouse_id=raw.get("warehouse_id") or "",
            statement_type=raw.get("statement_type") or "UNKNOWN",
            duration_ms=raw.get("total_duration_ms") or 0.0,
            queue_time_ms=raw.get("waiting_in_queue_ms") or 0.0,
            bytes_read=raw.get("read_bytes") or 0,
            bytes_written=raw.get("written_bytes") or 0,
            start_time=start_time,
            user_name=raw.get("executed_by") or "",
        )


# =============================================================================
# Fingerprint Calculator
# =============================================================================


class FingerprintCalculator:
    """Calculator for warehouse fingerprints from query history.

    Transforms raw query records into a comprehensive WarehouseFingerprint
    with performance metrics, distributions, and pattern classification.

    Example:
        >>> records = [{"statement_id": "s1", ...}, ...]
        >>> calc = FingerprintCalculator(records, warehouse_id="wh-123")
        >>> fingerprint = calc.calculate()
        >>> print(f"P95 runtime: {fingerprint.p95_runtime_sec}s")

    Performance:
        - Latency: Sub-ms for small datasets, linear scaling
        - Memory: O(n) where n = number of records for target warehouse
    """

    # DDL statement types
    DDL_TYPES = frozenset(
        {
            "CREATE",
            "CREATE TABLE",
            "CREATE VIEW",
            "CREATE SCHEMA",
            "CREATE DATABASE",
            "ALTER",
            "ALTER TABLE",
            "DROP",
            "DROP TABLE",
            "TRUNCATE",
        }
    )

    # DML types mapping
    DML_TYPE_MAP = {
        "SELECT": "select",
        "INSERT": "insert",
        "UPDATE": "update",
        "DELETE": "delete",
        "MERGE": "merge",
    }

    def __init__(
        self,
        records: list[dict[str, Any]],
        *,
        warehouse_id: str,
        warehouse_name: str = "",
        analysis_window_days: int = 7,
    ) -> None:
        """Initialize calculator with raw query records.

        Args:
            records: List of raw query record dictionaries.
            warehouse_id: Target warehouse ID to analyze.
            warehouse_name: Human-readable warehouse name.
            analysis_window_days: Days of data in the analysis window.
        """
        self._warehouse_id = warehouse_id
        self._warehouse_name = warehouse_name or warehouse_id
        self._analysis_window_days = analysis_window_days

        # Parse and filter records for target warehouse
        self._records: list[QueryRecord] = []
        for raw in records:
            record = QueryRecord.from_dict(raw)
            if record.warehouse_id == warehouse_id:
                self._records.append(record)

    def calculate(self) -> WarehouseFingerprint:
        """Calculate the warehouse fingerprint.

        Returns:
            Complete WarehouseFingerprint with all metrics and distributions.
        """
        if not self._records:
            return self._empty_fingerprint()

        # Extract values for calculations
        durations_ms = [r.duration_ms for r in self._records if r.duration_ms >= 0]
        queue_times_ms = [r.queue_time_ms for r in self._records]
        bytes_read = [r.bytes_read for r in self._records]
        bytes_written = [r.bytes_written for r in self._records]
        statement_types = [r.statement_type.upper() for r in self._records]
        hours = [r.start_time.hour for r in self._records if r.start_time is not None]

        # Calculate percentiles (convert ms to seconds)
        p50 = _percentile(durations_ms, 50) / 1000.0
        p75 = _percentile(durations_ms, 75) / 1000.0
        p90 = _percentile(durations_ms, 90) / 1000.0
        p95 = _percentile(durations_ms, 95) / 1000.0
        p99 = _percentile(durations_ms, 99) / 1000.0

        # Queue metrics
        avg_queue_sec = (
            (sum(queue_times_ms) / len(queue_times_ms)) / 1000.0
            if queue_times_ms
            else 0.0
        )
        p95_queue_sec = _percentile(queue_times_ms, 95) / 1000.0
        queued_count = sum(1 for qt in queue_times_ms if qt > 0)
        queue_rate_pct = (
            (queued_count / len(queue_times_ms) * 100.0) if queue_times_ms else 0.0
        )

        # Calculate distributions
        query_type_dist = self._calculate_query_type_distribution(statement_types)
        time_dist = self._calculate_time_distribution(hours)

        # Calculate concurrency
        avg_concurrency, peak_concurrency = self._calculate_concurrency()

        # Classify workload pattern
        workload_pattern = self._classify_workload_pattern(
            durations_ms=durations_ms,
            query_type_dist=query_type_dist,
            time_dist=time_dist,
        )

        return WarehouseFingerprint(
            warehouse_id=self._warehouse_id,
            warehouse_name=self._warehouse_name,
            analysis_window_days=self._analysis_window_days,
            analyzed_at=datetime.now(UTC),
            # Volume metrics
            total_queries=len(self._records),
            total_bytes_read=sum(bytes_read),
            total_bytes_written=sum(bytes_written),
            # Performance percentiles
            p50_runtime_sec=p50,
            p75_runtime_sec=p75,
            p90_runtime_sec=p90,
            p95_runtime_sec=p95,
            p99_runtime_sec=p99,
            # Concurrency
            avg_concurrency=avg_concurrency,
            peak_concurrency=peak_concurrency,
            # Queue metrics
            avg_queue_time_sec=avg_queue_sec,
            p95_queue_time_sec=p95_queue_sec,
            queue_rate_pct=queue_rate_pct,
            # Distributions
            query_type_distribution=query_type_dist,
            time_distribution=time_dist,
            # Pattern
            workload_pattern=workload_pattern,
        )

    def _empty_fingerprint(self) -> WarehouseFingerprint:
        """Create an empty fingerprint for no records."""
        return WarehouseFingerprint(
            warehouse_id=self._warehouse_id,
            warehouse_name=self._warehouse_name,
            analysis_window_days=self._analysis_window_days,
            analyzed_at=datetime.now(UTC),
            total_queries=0,
            total_bytes_read=0,
            total_bytes_written=0,
            p50_runtime_sec=float("nan"),
            p75_runtime_sec=float("nan"),
            p90_runtime_sec=float("nan"),
            p95_runtime_sec=float("nan"),
            p99_runtime_sec=float("nan"),
            avg_concurrency=0.0,
            peak_concurrency=0,
            avg_queue_time_sec=0.0,
            p95_queue_time_sec=float("nan"),
            queue_rate_pct=0.0,
            query_type_distribution=QueryTypeDistribution(select_pct=0.0),
            time_distribution=TimeDistribution(
                hourly_distribution=(0,) * 24,
                peak_hours=(),
                quiet_hours=tuple(range(24)),
            ),
            workload_pattern=WorkloadPattern(
                pattern_type="ad_hoc",
                confidence=0.0,
                description="No query data available",
                evidence=("No records in analysis window",),
            ),
        )

    def _calculate_query_type_distribution(
        self,
        statement_types: list[str],
    ) -> QueryTypeDistribution:
        """Calculate query type distribution percentages.

        Args:
            statement_types: List of statement types (uppercase).

        Returns:
            QueryTypeDistribution with percentages for each type.
        """
        if not statement_types:
            return QueryTypeDistribution(select_pct=0.0)

        total = len(statement_types)
        counts: dict[str, int] = Counter(statement_types)

        # Map types to categories
        select_count = counts.get("SELECT", 0)
        insert_count = counts.get("INSERT", 0)
        update_count = counts.get("UPDATE", 0)
        delete_count = counts.get("DELETE", 0)
        merge_count = counts.get("MERGE", 0)

        # DDL types
        ddl_count = sum(counts.get(t, 0) for t in self.DDL_TYPES)

        # Other = total - known types
        known = (
            select_count
            + insert_count
            + update_count
            + delete_count
            + merge_count
            + ddl_count
        )
        other_count = total - known

        return QueryTypeDistribution(
            select_pct=(select_count / total) * 100.0,
            insert_pct=(insert_count / total) * 100.0,
            update_pct=(update_count / total) * 100.0,
            delete_pct=(delete_count / total) * 100.0,
            merge_pct=(merge_count / total) * 100.0,
            ddl_pct=(ddl_count / total) * 100.0,
            other_pct=(other_count / total) * 100.0,
        )

    def _calculate_time_distribution(
        self,
        hours: list[int],
    ) -> TimeDistribution:
        """Calculate time-of-day distribution.

        Args:
            hours: List of hours (0-23) when queries were executed.

        Returns:
            TimeDistribution with hourly counts and peak/quiet hours.
        """
        if not hours:
            return TimeDistribution(
                hourly_distribution=(0,) * 24,
                peak_hours=(),
                quiet_hours=tuple(range(24)),
            )

        # Count queries per hour
        hour_counts = Counter(hours)
        hourly_dist = tuple(hour_counts.get(h, 0) for h in range(24))

        # Identify peak hours (top 25% by query count)
        total_queries = sum(hourly_dist)
        if total_queries == 0:
            return TimeDistribution(
                hourly_distribution=hourly_dist,
                peak_hours=(),
                quiet_hours=tuple(range(24)),
            )

        # Sort hours by count descending
        sorted_hours = sorted(range(24), key=lambda h: hourly_dist[h], reverse=True)

        # Peak hours: hours that account for top 60% of queries
        cumulative = 0
        peak_hours: list[int] = []
        for h in sorted_hours:
            if cumulative >= total_queries * 0.6:
                break
            peak_hours.append(h)
            cumulative += hourly_dist[h]

        # Quiet hours: hours with 0 queries or < 5% of avg
        avg_queries_per_hour = total_queries / 24
        threshold = avg_queries_per_hour * 0.1
        quiet_hours = tuple(h for h in range(24) if hourly_dist[h] <= threshold)

        return TimeDistribution(
            hourly_distribution=hourly_dist,
            peak_hours=tuple(sorted(peak_hours)),
            quiet_hours=quiet_hours,
        )

    def _calculate_concurrency(self) -> tuple[float, int]:
        """Calculate average and peak concurrent queries.

        Uses a sweep-line algorithm to count overlapping query time ranges.

        Returns:
            Tuple of (avg_concurrency, peak_concurrency).
        """
        if not self._records:
            return (0.0, 0)

        # Build events: (timestamp, +1 for start, -1 for end)
        events: list[tuple[datetime, int]] = []
        for r in self._records:
            if r.start_time is not None and r.duration_ms > 0:
                start = r.start_time
                end = start + timedelta(milliseconds=r.duration_ms)
                events.append((start, 1))  # Query starts
                events.append((end, -1))  # Query ends

        if not events:
            return (1.0, 1)  # If no timing data, assume 1

        # Sort by timestamp, with starts before ends at same time
        events.sort(key=lambda x: (x[0], x[1]))

        # Sweep through events
        current = 0
        peak = 0
        concurrency_sum = 0.0
        prev_time = events[0][0]

        for time, delta in events:
            # Add weighted concurrency for time segment
            if time > prev_time:
                duration_sec = (time - prev_time).total_seconds()
                concurrency_sum += current * duration_sec
            current += delta
            peak = max(peak, current)
            prev_time = time

        # Calculate total duration and average
        if events:
            total_duration = (events[-1][0] - events[0][0]).total_seconds()
            avg = concurrency_sum / total_duration if total_duration > 0 else 1.0
        else:
            avg = 1.0

        return (max(avg, 1.0), max(peak, 1))

    def _classify_workload_pattern(
        self,
        durations_ms: list[float],
        query_type_dist: QueryTypeDistribution,
        time_dist: TimeDistribution,
    ) -> WorkloadPattern:
        """Classify the workload pattern based on metrics.

        Uses heuristics to classify workload as:
        - interactive: Low latency, high frequency
        - batch: High latency, scheduled timing, high data volume
        - reporting: BI/dashboard pattern, business hours, SELECT-heavy
        - ad_hoc: High variance, many users, unpredictable
        - mixed: Combination of patterns

        Args:
            durations_ms: Query duration in milliseconds.
            query_type_dist: Query type distribution.
            time_dist: Time distribution.

        Returns:
            Classified WorkloadPattern with confidence and evidence.
        """
        if not durations_ms:
            return WorkloadPattern(
                pattern_type="ad_hoc",
                confidence=0.0,
                description="No query data for classification",
                evidence=(),
            )

        evidence: list[str] = []

        # Calculate metrics for classification
        avg_duration_ms = sum(durations_ms) / len(durations_ms)
        std_duration_ms = (
            (sum((d - avg_duration_ms) ** 2 for d in durations_ms) / len(durations_ms))
            ** 0.5
            if len(durations_ms) > 1
            else 0.0
        )
        cv = (
            std_duration_ms / avg_duration_ms if avg_duration_ms > 0 else 0.0
        )  # Coefficient of variation

        p95_duration_ms = _percentile(durations_ms, 95)
        is_select_heavy = query_type_dist.select_pct > 80
        is_business_hours = time_dist.is_business_hours_heavy

        # Unique users
        unique_users = len({r.user_name for r in self._records if r.user_name})

        # Total bytes (for batch detection)
        total_bytes = sum(r.bytes_read + r.bytes_written for r in self._records)
        avg_bytes_per_query = total_bytes / len(self._records) if self._records else 0

        # Score each pattern
        scores: dict[
            Literal["interactive", "batch", "reporting", "ad_hoc", "mixed"], float
        ] = {
            "interactive": 0.0,
            "batch": 0.0,
            "reporting": 0.0,
            "ad_hoc": 0.0,
            "mixed": 0.0,
        }

        # Interactive pattern: fast queries, low variance
        if avg_duration_ms < 1000:  # < 1s average
            scores["interactive"] += 0.3
            evidence.append(f"Fast queries (avg {avg_duration_ms:.0f}ms)")
        if p95_duration_ms < 5000:  # p95 < 5s
            scores["interactive"] += 0.2
            evidence.append(f"Low p95 latency ({p95_duration_ms:.0f}ms)")
        if cv < 1.0:  # Low variance
            scores["interactive"] += 0.1
            evidence.append(f"Low variance (CV={cv:.2f})")

        # Batch pattern: slow queries, high data volume, off-hours
        if avg_duration_ms > 60_000:  # > 1 minute average
            scores["batch"] += 0.3
            evidence.append(f"Long queries (avg {avg_duration_ms / 1000:.1f}s)")
        if avg_bytes_per_query > 1_000_000_000:  # > 1GB per query avg
            scores["batch"] += 0.3
            evidence.append(
                f"High data volume ({avg_bytes_per_query / 1e9:.1f}GB/query)"
            )
        if not is_business_hours:
            scores["batch"] += 0.1
            evidence.append("Off-hours execution")

        # Reporting pattern: SELECT-heavy, business hours, moderate duration
        if is_select_heavy:
            scores["reporting"] += 0.2
            evidence.append(f"SELECT-heavy ({query_type_dist.select_pct:.0f}%)")
        if is_business_hours:
            scores["reporting"] += 0.2
            evidence.append("Business hours traffic")
        if 1000 <= avg_duration_ms <= 30_000:  # 1-30s typical for dashboards
            scores["reporting"] += 0.2
            evidence.append(
                f"Dashboard-typical duration ({avg_duration_ms / 1000:.1f}s)"
            )

        # Ad-hoc pattern: high variance, many users
        if cv > 2.0:  # High variance
            scores["ad_hoc"] += 0.3
            evidence.append(f"High variance (CV={cv:.2f})")
        if unique_users > 10:
            scores["ad_hoc"] += 0.2
            evidence.append(f"Many users ({unique_users})")

        # Mixed pattern: competing high scores
        top_scores = sorted(scores.values(), reverse=True)
        if (
            top_scores[0] > 0
            and top_scores[1] > 0
            and top_scores[1] / top_scores[0] > 0.6  # Second score is close to first
        ):
            scores["mixed"] += 0.4
            evidence.append("Multiple workload patterns detected")

        # Select pattern with highest score
        pattern_type = max(scores, key=lambda k: scores[k])
        confidence = min(scores[pattern_type] / 0.6, 1.0)  # Normalize to 0-1

        # Generate description
        descriptions = {
            "interactive": "Low-latency interactive workload with fast query response times",
            "batch": "Batch processing workload with long-running data-intensive queries",
            "reporting": "BI/reporting workload with dashboard-style queries during business hours",
            "ad_hoc": "Ad-hoc exploration workload with unpredictable query patterns",
            "mixed": "Mixed workload combining multiple usage patterns",
        }

        return WorkloadPattern(
            pattern_type=pattern_type,
            confidence=round(confidence, 2),
            description=descriptions[pattern_type],
            evidence=tuple(evidence[:5]),  # Keep top 5 evidence items
        )


# =============================================================================
# Default Thresholds (used when no SLO configured)
# =============================================================================


@dataclass(frozen=True)
class DefaultThresholds:
    """Default performance thresholds for health scoring."""

    # P95 latency thresholds (seconds)
    p95_healthy: float = 15.0
    p95_warning: float = 30.0
    p95_critical: float = 60.0

    # Queue time thresholds (seconds)
    queue_time_healthy: float = 5.0
    queue_time_warning: float = 15.0
    queue_time_critical: float = 30.0

    # Queue rate thresholds (percentage)
    queue_rate_healthy: float = 10.0
    queue_rate_warning: float = 25.0
    queue_rate_critical: float = 50.0

    # Latency variance (p99/p50 ratio)
    variance_healthy: float = 10.0
    variance_warning: float = 25.0
    variance_critical: float = 50.0


DEFAULT_THRESHOLDS = DefaultThresholds()


# =============================================================================
# Health Scorer
# =============================================================================


class HealthScorer:
    """Calculator for warehouse health scores from fingerprint data.

    Evaluates warehouse health based on performance metrics, SLO compliance,
    and risk factors. Produces a comprehensive HealthSummary with scores,
    status, and recommendations.

    Example:
        >>> fingerprint = fetch_fingerprint(warehouse_id)
        >>> slo_config = get_slo_config(warehouse_id)
        >>> scorer = HealthScorer(fingerprint, slo_config)
        >>> health = scorer.calculate()
        >>> print(f"Health: {health.health_score}/100 ({health.health_status})")

    Attributes:
        fingerprint: Current warehouse fingerprint.
        slo_config: Optional SLO configuration for the warehouse.
        previous_fingerprint: Optional previous period fingerprint for trend.
    """

    def __init__(
        self,
        fingerprint: WarehouseFingerprint,
        slo_config: SLOConfig | None,
        previous_fingerprint: WarehouseFingerprint | None = None,
    ) -> None:
        """Initialize health scorer.

        Args:
            fingerprint: Current warehouse fingerprint.
            slo_config: Optional SLO configuration.
            previous_fingerprint: Optional previous period fingerprint.
        """
        self._fingerprint = fingerprint
        self._slo_config = slo_config
        self._previous = previous_fingerprint
        self._thresholds = DEFAULT_THRESHOLDS

    def calculate(self) -> HealthSummary:
        """Calculate comprehensive health summary.

        Returns:
            HealthSummary with scores, status, risks, and recommendations.
        """
        # Handle empty/inactive fingerprint (no queries in window)
        if self._fingerprint.total_queries == 0:
            return self._inactive_health_summary()

        # Calculate component scores
        performance_score = self._calculate_performance_score()
        queue_score = self._calculate_queue_score()
        slo_score, slo_statuses = self._calculate_slo_compliance()

        # Weighted average for overall score
        # Performance: 40%, Queue: 30%, SLO: 30%
        if self._slo_config and self._slo_config.targets:
            overall_score = (
                performance_score * 0.35 + queue_score * 0.25 + slo_score * 0.40
            )
        else:
            # No SLO configured, weight performance and queue more
            overall_score = performance_score * 0.55 + queue_score * 0.45

        # Clamp to 0-100
        overall_score = max(0.0, min(100.0, overall_score))

        # Determine status
        health_status = self._score_to_status(overall_score)

        # Calculate trend
        health_trend = self._calculate_trend()

        # Identify risk factors
        risk_factors = self._identify_risk_factors()

        # Calculate aggregate risk level
        risk_level = self._calculate_risk_level(risk_factors)

        # Generate recommendations
        immediate_actions, optimizations = self._generate_recommendations(
            health_status, risk_factors
        )

        return HealthSummary(
            warehouse_id=self._fingerprint.warehouse_id,
            warehouse_name=self._fingerprint.warehouse_name,
            health_score=round(overall_score, 1),
            health_status=health_status,
            health_trend=health_trend,
            slo_statuses=tuple(slo_statuses),
            overall_slo_compliance=slo_score,
            risk_factors=tuple(risk_factors),
            risk_level=risk_level,
            immediate_actions=tuple(immediate_actions),
            optimization_opportunities=tuple(optimizations),
        )

    def _inactive_health_summary(self) -> HealthSummary:
        """Create health summary for inactive warehouse (no queries).

        Returns:
            HealthSummary with inactive status and appropriate recommendations.
        """
        return HealthSummary(
            warehouse_id=self._fingerprint.warehouse_id,
            warehouse_name=self._fingerprint.warehouse_name,
            health_score=0.0,
            health_status="inactive",
            health_trend="stable",
            slo_statuses=(),
            overall_slo_compliance=0.0,
            risk_factors=(
                RiskFactor(
                    factor_id="no_activity",
                    name="No Query Activity",
                    description=f"No queries executed in the past {self._fingerprint.analysis_window_days} days",
                    severity="medium",
                    impact_score=0.0,
                    recommendation="Review if this warehouse is still needed or if workloads should be migrated here",
                ),
            ),
            risk_level="medium",
            immediate_actions=(),
            optimization_opportunities=(
                "Consider decommissioning if warehouse is no longer needed",
                "Review billing to confirm no costs are being incurred",
                "Check if workload has moved to another warehouse",
            ),
        )

    def _calculate_performance_score(self) -> float:
        """Calculate performance score based on latency metrics.

        Returns:
            Score from 0-100 based on latency performance.
        """
        p95 = self._fingerprint.p95_runtime_sec

        # Handle NaN
        if math.isnan(p95):
            return 50.0  # Unknown, neutral score

        # Score based on thresholds
        if p95 <= self._thresholds.p95_healthy:
            return 100.0
        if p95 <= self._thresholds.p95_warning:
            # Linear interpolation between healthy and warning
            ratio = (p95 - self._thresholds.p95_healthy) / (
                self._thresholds.p95_warning - self._thresholds.p95_healthy
            )
            return 100.0 - (ratio * 30.0)  # 100 -> 70
        if p95 <= self._thresholds.p95_critical:
            # Linear interpolation between warning and critical
            ratio = (p95 - self._thresholds.p95_warning) / (
                self._thresholds.p95_critical - self._thresholds.p95_warning
            )
            return 70.0 - (ratio * 40.0)  # 70 -> 30
        # Beyond critical
        return max(0.0, 30.0 - ((p95 - self._thresholds.p95_critical) / 10.0) * 10.0)

    def _calculate_queue_score(self) -> float:
        """Calculate queue health score.

        Returns:
            Score from 0-100 based on queue metrics.
        """
        queue_rate = self._fingerprint.queue_rate_pct
        p95_queue = self._fingerprint.p95_queue_time_sec

        # Handle NaN
        if math.isnan(p95_queue):
            p95_queue = 0.0

        # Score queue rate component (60% weight)
        if queue_rate <= self._thresholds.queue_rate_healthy:
            rate_score = 100.0
        elif queue_rate <= self._thresholds.queue_rate_warning:
            ratio = (queue_rate - self._thresholds.queue_rate_healthy) / (
                self._thresholds.queue_rate_warning
                - self._thresholds.queue_rate_healthy
            )
            rate_score = 100.0 - (ratio * 30.0)
        elif queue_rate <= self._thresholds.queue_rate_critical:
            ratio = (queue_rate - self._thresholds.queue_rate_warning) / (
                self._thresholds.queue_rate_critical
                - self._thresholds.queue_rate_warning
            )
            rate_score = 70.0 - (ratio * 40.0)
        else:
            rate_score = max(
                0.0,
                30.0
                - ((queue_rate - self._thresholds.queue_rate_critical) / 20.0) * 20.0,
            )

        # Score queue time component (40% weight)
        if p95_queue <= self._thresholds.queue_time_healthy:
            time_score = 100.0
        elif p95_queue <= self._thresholds.queue_time_warning:
            ratio = (p95_queue - self._thresholds.queue_time_healthy) / (
                self._thresholds.queue_time_warning
                - self._thresholds.queue_time_healthy
            )
            time_score = 100.0 - (ratio * 30.0)
        elif p95_queue <= self._thresholds.queue_time_critical:
            ratio = (p95_queue - self._thresholds.queue_time_warning) / (
                self._thresholds.queue_time_critical
                - self._thresholds.queue_time_warning
            )
            time_score = 70.0 - (ratio * 40.0)
        else:
            time_score = max(
                0.0,
                30.0
                - ((p95_queue - self._thresholds.queue_time_critical) / 15.0) * 15.0,
            )

        return rate_score * 0.6 + time_score * 0.4

    def _calculate_slo_compliance(self) -> tuple[float, list[SLOStatus]]:
        """Calculate SLO compliance score and status for each SLO.

        Returns:
            Tuple of (overall compliance score, list of SLO statuses).
        """
        if not self._slo_config or not self._slo_config.targets:
            return (100.0, [])  # No SLOs to violate

        statuses: list[SLOStatus] = []
        compliant_count = 0
        total_targets = 0

        for target in self._slo_config.enabled_targets:
            actual = self._get_metric_for_slo(target.slo_type)
            if actual is None:
                continue

            total_targets += 1
            compliant = target.is_met(actual)
            if compliant:
                compliant_count += 1

            # Determine trend (stable without historical data)
            trend: Literal["improving", "stable", "degrading"] = "stable"
            if self._previous:
                prev_actual = self._get_metric_for_slo(
                    target.slo_type, use_previous=True
                )
                if prev_actual is not None:
                    # For latency/queue metrics, lower is better
                    is_lower_better = target.slo_type in (
                        "p95_latency",
                        "p99_latency",
                        "queue_time",
                        "error_rate",
                    )
                    if is_lower_better:
                        if actual < prev_actual * 0.9:
                            trend = "improving"
                        elif actual > prev_actual * 1.1:
                            trend = "degrading"
                    else:
                        if actual > prev_actual * 1.01:
                            trend = "improving"
                        elif actual < prev_actual * 0.99:
                            trend = "degrading"

            # Calculate compliance percentage (simplified - would need historical data)
            compliance_pct = (
                100.0
                if compliant
                else (target.target_value / actual * 100.0 if actual > 0 else 0.0)
            )
            compliance_pct = min(100.0, max(0.0, compliance_pct))

            statuses.append(
                SLOStatus(
                    slo_type=target.slo_type,
                    target=target.target_value,
                    actual=actual,
                    compliant=compliant,
                    compliance_pct=compliance_pct,
                    trend=trend,
                )
            )

        # Overall compliance score
        if total_targets == 0:
            return (100.0, statuses)

        compliance_score = (compliant_count / total_targets) * 100.0
        return (compliance_score, statuses)

    def _get_metric_for_slo(
        self,
        slo_type: str,
        use_previous: bool = False,
    ) -> float | None:
        """Get the metric value for a given SLO type.

        Args:
            slo_type: Type of SLO.
            use_previous: If True, use previous fingerprint.

        Returns:
            Metric value or None if not available.
        """
        fp = self._previous if use_previous else self._fingerprint
        if fp is None:
            return None

        metric_map = {
            "p95_latency": fp.p95_runtime_sec,
            "p99_latency": fp.p99_runtime_sec,
            "queue_time": fp.p95_queue_time_sec,
            # availability and error_rate would need additional data
        }
        value = metric_map.get(slo_type)
        if value is not None and math.isnan(value):
            return None
        return value

    def _score_to_status(
        self,
        score: float,
    ) -> Literal["healthy", "warning", "critical", "unknown"]:
        """Convert health score to status category.

        Args:
            score: Health score (0-100).

        Returns:
            Status category.
        """
        if score >= 80:
            return "healthy"
        if score >= 40:
            return "warning"
        return "critical"

    def _calculate_trend(self) -> Literal["improving", "stable", "degrading"]:
        """Calculate overall health trend.

        Returns:
            Trend direction.
        """
        if not self._previous:
            return "stable"

        # Compare key metrics
        current_p95 = self._fingerprint.p95_runtime_sec
        prev_p95 = self._previous.p95_runtime_sec

        if math.isnan(current_p95) or math.isnan(prev_p95):
            return "stable"

        # 10% improvement/degradation threshold
        if current_p95 < prev_p95 * 0.9:
            return "improving"
        if current_p95 > prev_p95 * 1.1:
            return "degrading"
        return "stable"

    def _identify_risk_factors(self) -> list[RiskFactor]:
        """Identify risk factors affecting warehouse health.

        Returns:
            List of identified risk factors.
        """
        risks: list[RiskFactor] = []

        # High queue rate risk
        queue_rate = self._fingerprint.queue_rate_pct
        if queue_rate > self._thresholds.queue_rate_critical:
            risks.append(
                RiskFactor(
                    factor_id="high_queue_rate_critical",
                    name="Critical Queue Rate",
                    description=f"Queue rate is critically high at {queue_rate:.1f}%",
                    severity="critical",
                    impact_score=30.0,
                    recommendation="Consider scaling warehouse size or optimizing query patterns",
                )
            )
        elif queue_rate > self._thresholds.queue_rate_warning:
            risks.append(
                RiskFactor(
                    factor_id="high_queue_rate_warning",
                    name="High Queue Rate",
                    description=f"Queue rate is elevated at {queue_rate:.1f}%",
                    severity="high",
                    impact_score=20.0,
                    recommendation="Monitor queue trends and consider proactive scaling",
                )
            )
        elif queue_rate > self._thresholds.queue_rate_healthy:
            risks.append(
                RiskFactor(
                    factor_id="elevated_queue_rate",
                    name="Elevated Queue Rate",
                    description=f"Queue rate is above healthy threshold at {queue_rate:.1f}%",
                    severity="medium",
                    impact_score=10.0,
                    recommendation="Review peak usage patterns",
                )
            )

        # High latency variance risk
        p50 = self._fingerprint.p50_runtime_sec
        p99 = self._fingerprint.p99_runtime_sec
        if not math.isnan(p50) and not math.isnan(p99) and p50 > 0:
            variance_ratio = p99 / p50
            if variance_ratio > self._thresholds.variance_critical:
                risks.append(
                    RiskFactor(
                        factor_id="high_latency_variance_critical",
                        name="Critical Latency Variance",
                        description=f"P99/P50 ratio is {variance_ratio:.0f}x (critical)",
                        severity="critical",
                        impact_score=25.0,
                        recommendation="Investigate outlier queries causing latency spikes",
                    )
                )
            elif variance_ratio > self._thresholds.variance_warning:
                risks.append(
                    RiskFactor(
                        factor_id="high_latency_variance_warning",
                        name="High Latency Variance",
                        description=f"P99/P50 ratio is {variance_ratio:.0f}x (high)",
                        severity="high",
                        impact_score=15.0,
                        recommendation="Review query patterns for potential optimization",
                    )
                )

        # High P95 latency risk
        p95 = self._fingerprint.p95_runtime_sec
        if not math.isnan(p95):
            if p95 > self._thresholds.p95_critical:
                risks.append(
                    RiskFactor(
                        factor_id="high_p95_latency_critical",
                        name="Critical P95 Latency",
                        description=f"P95 latency is {p95:.1f}s (exceeds {self._thresholds.p95_critical}s)",
                        severity="critical",
                        impact_score=25.0,
                        recommendation="Immediate investigation required for slow queries",
                    )
                )
            elif p95 > self._thresholds.p95_warning:
                risks.append(
                    RiskFactor(
                        factor_id="high_p95_latency_warning",
                        name="Elevated P95 Latency",
                        description=f"P95 latency is {p95:.1f}s (above warning threshold)",
                        severity="high",
                        impact_score=15.0,
                        recommendation="Review slow queries and optimize as needed",
                    )
                )

        # SLO violations as risks
        if self._slo_config:
            for target in self._slo_config.enabled_targets:
                actual = self._get_metric_for_slo(target.slo_type)
                if actual is not None and not target.is_met(actual):
                    status = target.get_status(actual)
                    severity: Literal["low", "medium", "high", "critical"] = (
                        "critical"
                        if status == "critical"
                        else "high"
                        if status == "warning"
                        else "medium"
                    )
                    risks.append(
                        RiskFactor(
                            factor_id=f"slo_violation_{target.slo_type}",
                            name=f"SLO Violation: {target.slo_type}",
                            description=f"{target.slo_type} is {actual:.2f} (target: {target.target_value})",
                            severity=severity,
                            impact_score=20.0 if severity == "critical" else 15.0,
                            recommendation=f"Address {target.slo_type} to meet SLO target",
                        )
                    )

        return risks

    def _calculate_risk_level(
        self,
        risks: list[RiskFactor],
    ) -> Literal["low", "medium", "high", "critical"]:
        """Calculate aggregate risk level from risk factors.

        Args:
            risks: List of identified risk factors.

        Returns:
            Aggregate risk level.
        """
        if not risks:
            return "low"

        severities = [r.severity for r in risks]
        if "critical" in severities:
            return "critical"
        if severities.count("high") >= 2:
            return "critical"
        if "high" in severities:
            return "high"
        if "medium" in severities:
            return "medium"
        return "low"

    def _generate_recommendations(
        self,
        health_status: Literal["healthy", "warning", "critical", "unknown"],
        risks: list[RiskFactor],
    ) -> tuple[list[str], list[str]]:
        """Generate recommendations based on health status and risks.

        Args:
            health_status: Current health status.
            risks: Identified risk factors.

        Returns:
            Tuple of (immediate_actions, optimization_opportunities).
        """
        immediate: list[str] = []
        optimizations: list[str] = []

        # Add recommendations from critical/high risks
        for risk in risks:
            if risk.severity in ("critical", "high"):
                immediate.append(risk.recommendation)
            else:
                optimizations.append(risk.recommendation)

        # Add general recommendations based on status
        if health_status == "critical" and not immediate:
            immediate.append("Investigate warehouse performance immediately")
        elif health_status == "warning" and not optimizations:
            optimizations.append(
                "Review warehouse configuration for potential improvements"
            )

        # Add optimization suggestions for healthy warehouses
        if health_status == "healthy" and not optimizations:
            if self._fingerprint.queue_rate_pct > 5:
                optimizations.append(
                    "Consider auto-scaling configuration for improved queue handling"
                )
            if self._fingerprint.workload_pattern.pattern_type == "mixed":
                optimizations.append(
                    "Consider separating workloads into dedicated warehouses"
                )

        return (immediate, optimizations)
