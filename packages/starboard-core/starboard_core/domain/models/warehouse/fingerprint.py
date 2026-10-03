# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Warehouse fingerprint models.

Detailed analysis models for individual warehouse workload characterization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class QueryTypeDistribution:
    """Distribution of queries by type.

    Attributes:
        select_pct: Percentage of SELECT queries.
        insert_pct: Percentage of INSERT queries.
        update_pct: Percentage of UPDATE queries.
        delete_pct: Percentage of DELETE queries.
        merge_pct: Percentage of MERGE queries.
        ddl_pct: Percentage of DDL queries.
        other_pct: Percentage of other query types.
    """

    select_pct: float
    insert_pct: float = 0.0
    update_pct: float = 0.0
    delete_pct: float = 0.0
    merge_pct: float = 0.0
    ddl_pct: float = 0.0
    other_pct: float = 0.0


@dataclass(frozen=True)
class TimeDistribution:
    """Distribution of queries by time of day.

    Attributes:
        hourly_distribution: Query counts by hour (0-23).
        peak_hours: Hours with highest activity.
        quiet_hours: Hours with minimal activity.
    """

    hourly_distribution: tuple[int, ...]  # 24 values, one per hour
    peak_hours: tuple[int, ...]
    quiet_hours: tuple[int, ...]

    @property
    def is_business_hours_heavy(self) -> bool:
        """Check if majority of traffic is during business hours (8-18)."""
        if len(self.hourly_distribution) != 24:
            return False
        business_hours_total = sum(self.hourly_distribution[8:18])
        all_hours_total = sum(self.hourly_distribution)
        if all_hours_total == 0:
            return False
        return business_hours_total / all_hours_total > 0.6


@dataclass(frozen=True)
class WorkloadPattern:
    """Workload pattern classification.

    Attributes:
        pattern_type: Classified pattern type.
        confidence: Confidence in classification (0.0-1.0).
        description: Human-readable description.
        evidence: Supporting evidence for classification.
    """

    pattern_type: Literal[
        "interactive",  # Low latency, variable concurrency
        "batch",  # High throughput, predictable timing
        "mixed",  # Combination of patterns
        "reporting",  # Dashboard/BI workloads
        "ad_hoc",  # Unpredictable queries
    ]
    confidence: float
    description: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class WarehouseFingerprint:
    """Complete fingerprint for a warehouse.

    Comprehensive analysis of a warehouse's workload characteristics,
    performance baseline, and usage patterns.

    Attributes:
        warehouse_id: Warehouse identifier.
        warehouse_name: Human-readable name.
        analysis_window_days: Days of data analyzed.
        analyzed_at: When the fingerprint was generated.

        # Volume metrics
        total_queries: Total query count in window.
        total_bytes_read: Total bytes read.
        total_bytes_written: Total bytes written.

        # Performance baseline
        p50_runtime_sec: Median query runtime.
        p75_runtime_sec: 75th percentile runtime.
        p90_runtime_sec: 90th percentile runtime.
        p95_runtime_sec: 95th percentile runtime.
        p99_runtime_sec: 99th percentile runtime.

        # Concurrency
        avg_concurrency: Average concurrent queries.
        peak_concurrency: Maximum concurrent queries observed.

        # Queue metrics
        avg_queue_time_sec: Average time in queue.
        p95_queue_time_sec: 95th percentile queue time.
        queue_rate_pct: Percentage of queries that queued.

        # Distributions
        query_type_distribution: Distribution by query type.
        time_distribution: Distribution by time of day.

        # Patterns
        workload_pattern: Classified workload pattern.
    """

    warehouse_id: str
    warehouse_name: str
    analysis_window_days: int
    analyzed_at: datetime

    # Volume metrics
    total_queries: int
    total_bytes_read: int
    total_bytes_written: int

    # Performance baseline
    p50_runtime_sec: float
    p75_runtime_sec: float
    p90_runtime_sec: float
    p95_runtime_sec: float
    p99_runtime_sec: float

    # Concurrency
    avg_concurrency: float
    peak_concurrency: int

    # Queue metrics
    avg_queue_time_sec: float
    p95_queue_time_sec: float
    queue_rate_pct: float

    # Distributions
    query_type_distribution: QueryTypeDistribution
    time_distribution: TimeDistribution

    # Patterns
    workload_pattern: WorkloadPattern

    @property
    def queries_per_day(self) -> float:
        """Calculate average queries per day."""
        if self.analysis_window_days == 0:
            return 0.0
        return self.total_queries / self.analysis_window_days

    @property
    def has_queue_issues(self) -> bool:
        """Check if warehouse has significant queuing."""
        return self.queue_rate_pct > 10 or self.p95_queue_time_sec > 30
