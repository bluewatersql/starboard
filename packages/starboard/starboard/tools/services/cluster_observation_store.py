# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Durable multi-horizon cluster right-sizing history (Phase-2 09, decision D-2.4).

Persists a daily ``role_observations`` snapshot — one row per
``(observation_date, workspace_id, cluster_id, node_role, node_type)`` — via the
**Wave-3 UC-native state adapter** (:class:`UCStorageAdapter`). We reuse that
adapter's ``TableDef`` / read / upsert / delete building blocks rather than
inventing a new store: the snapshot is one more governed Delta table alongside
the conversation/memory tables.

On top of the snapshot this module derives a **multi-horizon (1d / 7d / 30d)
confidence model** (research/09 §4 Opt C):

* a single day of over-provision signal → ``LOW`` confidence (noisy),
* a 7-day window clearing the persistence gate (≥3 distinct days, ≥70% of the
  observations signalling over-provision) → ``MEDIUM`` (actionable),
* a full 30-day window that also clears the gate → ``HIGH`` (high-ROI).

The persistence gate + thresholds are the harvested defaults, sourced from the
one source of truth in :mod:`starboard_x.cluster` (``ClusterSizingThresholds``).

Graceful degradation: when **no** history exists for a cluster,
:meth:`ClusterObservationStore.compute_confidence` returns a ``LOW``-confidence,
``has_history=False`` verdict with the persistence gate left ``None`` — callers
fall back to single-window analysis rather than erroring.

This is server-tier code; it may import ``starboard`` internals and the pure
``starboard_x.cluster`` kernel logic (the reverse import is what kernel purity
forbids, not this direction).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from starboard_x.cluster import (
    ClusterSizingThresholds,
    Confidence,
    SizingReason,
)

from starboard.adapters.state.uc import _serde
from starboard.infra.observability.logging import get_logger
from starboard.infra.storage.table_registry import (
    ColumnDef,
    TableDef,
    TableRegistry,
)

logger = get_logger(__name__)

# Registry key + table name for the durable daily snapshot.
ROLE_OBSERVATIONS = "role_observations"

# Over-provision sizing_reason values that count toward the persistence signal
# (research/09 §1 persistence gate, lines 126-137). Sourced from the kernel enum
# so the set never drifts from the classifier.
_OVER_SIGNAL_REASONS: frozenset[str] = frozenset(
    {
        SizingReason.OVERPROVISIONED.value,
        SizingReason.SEVERELY_OVERPROVISIONED.value,
        SizingReason.AUTOSCALE_MIN_TOO_HIGH.value,
    }
)

_OPTIMIZE = {"delta.autoOptimize.optimizeWrite": "true"}


class UCStorageLike(Protocol):
    """Structural type for the UC-native storage adapter methods we use.

    Both :class:`starboard.infra.storage.uc_adapter.UCStorageAdapter` and the
    in-memory test fake satisfy this — the store never depends on the concrete
    class, only on the read/upsert/delete contract.
    """

    async def initialize(self) -> None: ...

    async def upsert(self, table_id: str, row: dict[str, Any]) -> None: ...

    async def read(
        self,
        table_id: str,
        filters: dict[str, Any] | None = ...,
        columns: list[str] | None = ...,
        order_by: str | None = ...,
        limit: int | None = ...,
    ) -> list[dict[str, Any]]: ...

    async def delete(self, table_id: str, filters: dict[str, Any]) -> int: ...


def _role_observations_table() -> TableDef:
    """Build the ``role_observations`` Delta table definition.

    The synthetic single-column ``observation_key`` primary key
    (``date|workspace|cluster|role|node_type``) makes a daily snapshot idempotent
    under MERGE upsert — re-recording the same grain replaces, never duplicates.
    """
    return TableDef(
        table_id=ROLE_OBSERVATIONS,
        table_name="cluster_role_observations",
        columns=(
            ColumnDef(
                "observation_key",
                "STRING",
                nullable=False,
                comment="date|workspace|cluster|node_role|node_type (idempotency key)",
            ),
            ColumnDef("observation_date", "STRING", nullable=False, comment="ISO date"),
            ColumnDef("workspace_id", "STRING", nullable=False),
            ColumnDef("cluster_id", "STRING", nullable=False),
            ColumnDef("node_role", "STRING", nullable=False),
            ColumnDef("node_type", "STRING"),
            ColumnDef("sizing_reason", "STRING", comment="cluster_role_features CASE"),
            ColumnDef("sizing_direction", "STRING"),
            ColumnDef("cpu_p95_pct", "DOUBLE"),
            ColumnDef("memory_p95_pct", "DOUBLE"),
            ColumnDef("reduction_pct", "DOUBLE"),
            ColumnDef("sample_count", "BIGINT"),
            ColumnDef("recorded_at", "TIMESTAMP", nullable=False),
        ),
        primary_key=("observation_key",),
        partition_by=("workspace_id",),
        comment="Daily cluster right-sizing role observations (multi-horizon history)",
        properties=dict(_OPTIMIZE),
    )


def build_observation_registry() -> TableRegistry:
    """Build a fresh registry populated with the ``role_observations`` table."""
    registry = TableRegistry()
    registry.register(_role_observations_table())
    return registry


class RoleObservation(BaseModel):
    """One daily per-role right-sizing snapshot row (research/09 §1 grain)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_date: date
    workspace_id: str
    cluster_id: str
    node_role: str = "WORKER"
    node_type: str | None = None
    sizing_reason: str | None = None
    sizing_direction: str | None = None
    cpu_p95_pct: float | None = None
    memory_p95_pct: float | None = None
    reduction_pct: float | None = None
    sample_count: int | None = None

    def observation_key(self) -> str:
        """Deterministic idempotency key for the snapshot grain."""
        return "|".join(
            [
                self.observation_date.isoformat(),
                self.workspace_id,
                self.cluster_id,
                self.node_role,
                self.node_type or "",
            ]
        )


class MultiHorizonConfidence(BaseModel):
    """Multi-horizon (1d/7d/30d) persistence + confidence verdict for a cluster."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster_id: str
    node_role: str | None = None
    as_of: date
    has_history: bool
    confidence: Confidence
    # Distinct observation days within each horizon.
    observed_days_1d: int = 0
    observed_days_7d: int = 0
    observed_days_30d: int = 0
    # Fraction of observations in each horizon signalling over-provision.
    over_signal_ratio_7d: float = 0.0
    over_signal_ratio_30d: float = 0.0
    # The 7-day persistence gate result (None when no history — degrade signal).
    persistence_gate_passed: bool | None = None
    # 7-day figures forwarded to ``synthesize_rightsizing_verdict`` if needed.
    persistence_ratio: float | None = None
    observed_days: int | None = None
    is_persistent: bool = False


class ClusterObservationStore:
    """Durable daily ``role_observations`` snapshot over the UC state adapter.

    Args:
        adapter: A UC-native storage adapter (real ``UCStorageAdapter`` in prod,
            an in-memory fake in tests) satisfying :class:`UCStorageLike`.
        thresholds: Right-sizing thresholds (persistence gate + horizons). Defaults
            to the harvested research/09 §1 values via ``ClusterSizingThresholds``.
    """

    def __init__(
        self,
        adapter: UCStorageLike,
        thresholds: ClusterSizingThresholds | None = None,
    ) -> None:
        self._adapter = adapter
        self._thresholds = thresholds or ClusterSizingThresholds()

    # -- lifecycle ---------------------------------------------------------
    async def connect(self) -> None:
        """Ensure the backing catalog/schema/table exist."""
        await self._adapter.initialize()

    # -- serialization -----------------------------------------------------
    @staticmethod
    def _to_row(obs: RoleObservation) -> dict[str, Any]:
        return {
            "observation_key": obs.observation_key(),
            "observation_date": obs.observation_date.isoformat(),
            "workspace_id": obs.workspace_id,
            "cluster_id": obs.cluster_id,
            "node_role": obs.node_role,
            "node_type": obs.node_type,
            "sizing_reason": obs.sizing_reason,
            "sizing_direction": obs.sizing_direction,
            "cpu_p95_pct": obs.cpu_p95_pct,
            "memory_p95_pct": obs.memory_p95_pct,
            "reduction_pct": obs.reduction_pct,
            "sample_count": obs.sample_count,
            "recorded_at": datetime.now(UTC),
        }

    @staticmethod
    def _from_row(row: dict[str, Any]) -> RoleObservation:
        return RoleObservation(
            observation_date=date.fromisoformat(str(row["observation_date"])),
            workspace_id=str(row["workspace_id"]),
            cluster_id=str(row["cluster_id"]),
            node_role=str(row.get("node_role") or "WORKER"),
            node_type=(row.get("node_type") or None),
            sizing_reason=(row.get("sizing_reason") or None),
            sizing_direction=(row.get("sizing_direction") or None),
            cpu_p95_pct=_serde.parse_float(row.get("cpu_p95_pct"))
            if row.get("cpu_p95_pct") not in (None, "")
            else None,
            memory_p95_pct=_serde.parse_float(row.get("memory_p95_pct"))
            if row.get("memory_p95_pct") not in (None, "")
            else None,
            reduction_pct=_serde.parse_float(row.get("reduction_pct"))
            if row.get("reduction_pct") not in (None, "")
            else None,
            sample_count=_serde.parse_int(row.get("sample_count"))
            if row.get("sample_count") not in (None, "")
            else None,
        )

    # -- writes ------------------------------------------------------------
    async def record_observation(self, obs: RoleObservation) -> None:
        """Persist a single role observation (MERGE upsert — idempotent by grain)."""
        await self._adapter.upsert(ROLE_OBSERVATIONS, self._to_row(obs))

    async def record_snapshot(self, observations: list[RoleObservation]) -> int:
        """Persist a day's snapshot idempotently.

        Every observation upserts on its ``observation_key``; re-running the same
        day (the idempotent backfill window) replaces rows in place rather than
        appending duplicates. Returns the number of rows written.
        """
        for obs in observations:
            await self.record_observation(obs)
        logger.debug("recorded_role_observations", count=len(observations))
        return len(observations)

    # -- reads -------------------------------------------------------------
    async def get_observations(
        self,
        cluster_id: str,
        node_role: str | None = None,
        workspace_id: str | None = None,
        since: date | None = None,
    ) -> list[RoleObservation]:
        """Read observations for a cluster, optionally scoped by role/workspace/date."""
        filters: dict[str, Any] = {"cluster_id": cluster_id}
        if node_role is not None:
            filters["node_role"] = node_role
        if workspace_id is not None:
            filters["workspace_id"] = workspace_id
        rows = await self._adapter.read(ROLE_OBSERVATIONS, filters=filters)
        observations = [self._from_row(r) for r in rows]
        if since is not None:
            observations = [o for o in observations if o.observation_date >= since]
        return observations

    # -- confidence model --------------------------------------------------
    async def compute_confidence(
        self,
        cluster_id: str,
        node_role: str | None = None,
        workspace_id: str | None = None,
        as_of: date | None = None,
    ) -> MultiHorizonConfidence:
        """Derive the multi-horizon persistence/confidence verdict for a cluster.

        Degrades gracefully: with no history the verdict is ``LOW`` /
        ``has_history=False`` and the persistence gate is ``None`` so the caller
        knows to fall back to single-window analysis.
        """
        as_of_date = as_of or datetime.now(UTC).date()
        observations = await self.get_observations(
            cluster_id, node_role=node_role, workspace_id=workspace_id
        )
        if not observations:
            return MultiHorizonConfidence(
                cluster_id=cluster_id,
                node_role=node_role,
                as_of=as_of_date,
                has_history=False,
                confidence=Confidence.LOW,
                persistence_gate_passed=None,
            )

        t = self._thresholds
        days_1d, _ratio_1d = self._window_stats(observations, as_of_date, 1)
        days_7d, ratio_7d = self._window_stats(observations, as_of_date, 7)
        days_30d, ratio_30d = self._window_stats(observations, as_of_date, 30)

        gate_7d = self._gate(days_7d, ratio_7d, t)
        gate_30d = self._gate(days_30d, ratio_30d, t)

        if gate_30d and days_30d >= t.high_confidence_min_days:
            confidence = Confidence.HIGH
        elif gate_7d:
            confidence = Confidence.MEDIUM
        else:
            confidence = Confidence.LOW

        return MultiHorizonConfidence(
            cluster_id=cluster_id,
            node_role=node_role,
            as_of=as_of_date,
            has_history=True,
            confidence=confidence,
            observed_days_1d=days_1d,
            observed_days_7d=days_7d,
            observed_days_30d=days_30d,
            over_signal_ratio_7d=ratio_7d,
            over_signal_ratio_30d=ratio_30d,
            persistence_gate_passed=gate_7d,
            persistence_ratio=ratio_7d,
            observed_days=days_7d,
            is_persistent=gate_7d,
        )

    @staticmethod
    def _window_stats(
        observations: list[RoleObservation], as_of: date, window_days: int
    ) -> tuple[int, float]:
        """Return ``(distinct_days, over_signal_ratio)`` within the window.

        The window is inclusive of ``as_of`` back through ``window_days - 1`` days
        (a 7-day window covers ``as_of - 6 .. as_of``).
        """
        start = as_of - timedelta(days=window_days - 1)
        in_window = [
            o for o in observations if start <= o.observation_date <= as_of
        ]
        if not in_window:
            return 0, 0.0
        distinct_days = len({o.observation_date for o in in_window})
        over = sum(
            1 for o in in_window if (o.sizing_reason or "") in _OVER_SIGNAL_REASONS
        )
        ratio = over / len(in_window)
        return distinct_days, ratio

    @staticmethod
    def _gate(
        distinct_days: int, ratio: float, thresholds: ClusterSizingThresholds
    ) -> bool:
        """Persistence gate: enough distinct days AND enough over-signal ratio."""
        return (
            distinct_days >= thresholds.persistence_min_days
            and ratio >= thresholds.persistence_min_ratio
        )
