# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Stdlib-only diagnostic models re-homed into ``starboard_x`` (Phase-1 B2).

This is the ``diagnostics-core`` subset of the diagnostic domain models — the
pieces the pure trio (``ExitCodeTriager``, ``EvidenceWindowExtractor``,
``RootCauseSynthesizer``) needs. It depends on the standard library only (no
pydantic, no pyyaml, no databricks-sdk), so ``pip install starboard-core`` gives
the trio with zero heavy dependencies.

The full diagnostic model surface still lives at
``starboard.tools.domain.diagnostic.models``; that module now re-imports
``PrimarySymptom``, ``ExplorationSummary`` and ``_PATTERN_TO_SYMPTOM`` from here
so there is a single source of truth (no divergence).

Design reference: changes/2026_26_25_agents/progressive_helpers/technical.md §3.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PrimarySymptom(Enum):
    """Classification of the primary symptom detected.

    Used for handoff routing and pattern-to-symptom mapping.
    """

    EXECUTOR_LOST = "executor_lost"
    """Spark executor was lost during job execution."""

    OOM = "oom"
    """Out of memory error (Java heap, GC overhead)."""

    PERMISSION = "permission"
    """Access denied or permission-related error."""

    PARSE_ERROR = "parse_error"
    """SQL/code parsing or analysis error."""

    TIMEOUT = "timeout"
    """Query or operation timed out."""

    CONNECTION_ERROR = "connection_error"
    """Network connectivity or connection issues."""

    SERIALIZATION_ERROR = "serialization_error"
    """Task not serializable or serialization failure."""

    DATA_SKEW = "data_skew"
    """Data skew causing performance issues."""

    SHUFFLE_FAILURE = "shuffle_failure"
    """Shuffle fetch failed or shuffle-related error."""

    DRIVER_CRASH = "driver_crash"
    """Spark driver process crashed."""

    DELTA_ERROR = "delta_error"
    """Delta Lake-specific error (concurrent write, corruption)."""

    UC_ERROR = "uc_error"
    """Unity Catalog-related error."""

    UNKNOWN = "unknown"
    """Could not determine primary symptom."""


# Mapping from pattern IDs to symptoms
_PATTERN_TO_SYMPTOM: dict[str, PrimarySymptom] = {
    "java_heap_space": PrimarySymptom.OOM,
    "gc_overhead": PrimarySymptom.OOM,
    "container_killed": PrimarySymptom.OOM,
    "shuffle_fetch_failed": PrimarySymptom.SHUFFLE_FAILURE,
    "shuffle_spill": PrimarySymptom.SHUFFLE_FAILURE,
    "data_skew": PrimarySymptom.DATA_SKEW,
    "executor_lost": PrimarySymptom.EXECUTOR_LOST,
    "task_not_serializable": PrimarySymptom.SERIALIZATION_ERROR,
    "uc_permission_denied": PrimarySymptom.PERMISSION,
    "uc_not_found": PrimarySymptom.UC_ERROR,
    "delta_concurrent_write": PrimarySymptom.DELTA_ERROR,
    "delta_corruption": PrimarySymptom.DELTA_ERROR,
    "python_worker_crash": PrimarySymptom.DRIVER_CRASH,
    "network_throttling": PrimarySymptom.CONNECTION_ERROR,
}


@dataclass
class ExplorationSummary:
    """Summary of the diagnostic exploration process.

    Captures metadata about how the diagnosis was reached.
    """

    steps_completed: int
    """Number of exploration steps executed."""

    final_confidence: float
    """Final confidence level (0.0 to 1.0)."""

    strategies_used: list[str]
    """List of exploration strategies that were executed."""

    patterns_matched: list[str] | None = None
    """Pattern IDs that matched during exploration."""

    tool_calls_made: list[str] | None = None
    """Tool names called during ONLINE exploration."""

    total_duration_ms: int | None = None
    """Total exploration duration in milliseconds."""


__all__ = [
    "PrimarySymptom",
    "ExplorationSummary",
    "_PATTERN_TO_SYMPTOM",
]
