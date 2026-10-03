# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ClusterObservationStore (durable multi-horizon right-sizing history).

Covers: round-trip persistence via an in-memory UC state adapter, idempotent
daily snapshots, the multi-horizon (1d/7d/30d) confidence model, the persistence
gate that suppresses single-day noise, and graceful degradation with no history.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from starboard.tools.services.cluster_observation_store import (
    ROLE_OBSERVATIONS,
    ClusterObservationStore,
    RoleObservation,
)
from starboard_x.cluster import Confidence


class InMemoryUCAdapter:
    """Deterministic in-memory stand-in for ``UCStorageAdapter``.

    Mirrors the UC-native adapter test fake: reads return **stringified** cells
    (as the Statement Execution API does), so the store's (de)serialization is
    genuinely exercised on the round trip.
    """

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.initialized = False

    @staticmethod
    def _stringify(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    async def initialize(self) -> None:
        self.initialized = True

    async def upsert(self, table_id: str, row: dict[str, Any]) -> None:
        srow = {k: self._stringify(v) for k, v in row.items()}
        rows = self.tables.setdefault(table_id, [])
        pk = next(iter(row))  # first column is the (synthetic) primary key
        for i, existing in enumerate(rows):
            if existing.get(pk) == srow.get(pk):
                rows[i] = srow
                return
        rows.append(srow)

    def _match(self, row: dict[str, Any], filters: dict[str, Any]) -> bool:
        return all(row.get(k) == self._stringify(v) for k, v in filters.items())

    async def read(
        self,
        table_id: str,
        filters: dict[str, Any] | None = None,
        columns: list[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self.tables.get(table_id, []))
        if filters:
            rows = [r for r in rows if self._match(r, filters)]
        if limit is not None:
            rows = rows[:limit]
        return [dict(r) for r in rows]

    async def delete(self, table_id: str, filters: dict[str, Any]) -> int:
        rows = self.tables.get(table_id, [])
        kept = [r for r in rows if not self._match(r, filters)]
        removed = len(rows) - len(kept)
        self.tables[table_id] = kept
        return removed


@pytest.fixture
def adapter() -> InMemoryUCAdapter:
    return InMemoryUCAdapter()


@pytest.fixture
def store(adapter: InMemoryUCAdapter) -> ClusterObservationStore:
    return ClusterObservationStore(adapter)


def _obs(
    observation_date: date,
    *,
    cluster_id: str = "c1",
    workspace_id: str = "ws1",
    node_role: str = "WORKER",
    sizing_reason: str = "OVERPROVISIONED",
) -> RoleObservation:
    return RoleObservation(
        observation_date=observation_date,
        workspace_id=workspace_id,
        cluster_id=cluster_id,
        node_role=node_role,
        node_type="i3.xlarge",
        sizing_reason=sizing_reason,
        sizing_direction="OVERPROVISIONED",
        cpu_p95_pct=22.0,
        memory_p95_pct=31.0,
        reduction_pct=50.0,
        sample_count=1440,
    )


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_connect_initializes_adapter(
        self, store: ClusterObservationStore, adapter: InMemoryUCAdapter
    ) -> None:
        await store.connect()
        assert adapter.initialized is True

    @pytest.mark.asyncio
    async def test_record_and_read_round_trip(
        self, store: ClusterObservationStore
    ) -> None:
        today = date(2026, 8, 28)
        await store.record_observation(_obs(today))

        rows = await store.get_observations("c1")
        assert len(rows) == 1
        got = rows[0]
        assert got.observation_date == today
        assert got.cluster_id == "c1"
        assert got.workspace_id == "ws1"
        assert got.sizing_reason == "OVERPROVISIONED"
        assert got.cpu_p95_pct == 22.0
        assert got.sample_count == 1440

    @pytest.mark.asyncio
    async def test_snapshot_is_idempotent_by_grain(
        self, store: ClusterObservationStore, adapter: InMemoryUCAdapter
    ) -> None:
        today = date(2026, 8, 28)
        obs = _obs(today)
        # Re-running the same day's snapshot must not duplicate rows.
        await store.record_snapshot([obs])
        await store.record_snapshot([obs])
        assert len(adapter.tables[ROLE_OBSERVATIONS]) == 1

    @pytest.mark.asyncio
    async def test_get_observations_filters_by_role_and_since(
        self, store: ClusterObservationStore
    ) -> None:
        base = date(2026, 8, 28)
        await store.record_observation(_obs(base, node_role="WORKER"))
        await store.record_observation(_obs(base, node_role="DRIVER"))
        await store.record_observation(_obs(base - timedelta(days=10)))

        workers = await store.get_observations("c1", node_role="WORKER")
        assert all(o.node_role == "WORKER" for o in workers)

        recent = await store.get_observations("c1", since=base - timedelta(days=2))
        assert all(o.observation_date >= base - timedelta(days=2) for o in recent)


class TestConfidenceModel:
    @pytest.mark.asyncio
    async def test_no_history_degrades_gracefully(
        self, store: ClusterObservationStore
    ) -> None:
        conf = await store.compute_confidence("missing", as_of=date(2026, 8, 28))
        assert conf.has_history is False
        assert conf.confidence == Confidence.LOW
        assert conf.persistence_gate_passed is None
        assert conf.is_persistent is False

    @pytest.mark.asyncio
    async def test_single_day_is_low_confidence_and_gate_not_met(
        self, store: ClusterObservationStore
    ) -> None:
        as_of = date(2026, 8, 28)
        await store.record_observation(_obs(as_of))

        conf = await store.compute_confidence("c1", as_of=as_of)
        assert conf.has_history is True
        assert conf.observed_days_7d == 1
        assert conf.confidence == Confidence.LOW
        assert conf.persistence_gate_passed is False  # < 3 distinct days
        assert conf.is_persistent is False

    @pytest.mark.asyncio
    async def test_seven_day_persistence_reaches_medium(
        self, store: ClusterObservationStore
    ) -> None:
        as_of = date(2026, 8, 28)
        for i in range(7):
            await store.record_observation(_obs(as_of - timedelta(days=i)))

        conf = await store.compute_confidence("c1", as_of=as_of)
        assert conf.observed_days_7d == 7
        assert conf.over_signal_ratio_7d == pytest.approx(1.0)
        assert conf.persistence_gate_passed is True
        assert conf.is_persistent is True
        assert conf.confidence == Confidence.MEDIUM

    @pytest.mark.asyncio
    async def test_sub_threshold_ratio_does_not_pass_gate(
        self, store: ClusterObservationStore
    ) -> None:
        as_of = date(2026, 8, 28)
        # 5 days: 2 over-provision, 3 balanced → ratio 0.4 < 0.7 gate.
        reasons = ["OVERPROVISIONED", "OVERPROVISIONED", "BALANCED", "BALANCED", "BALANCED"]
        for i, reason in enumerate(reasons):
            await store.record_observation(
                _obs(as_of - timedelta(days=i), sizing_reason=reason)
            )

        conf = await store.compute_confidence("c1", as_of=as_of)
        assert conf.observed_days_7d == 5
        assert conf.over_signal_ratio_7d == pytest.approx(0.4)
        assert conf.persistence_gate_passed is False
        assert conf.confidence == Confidence.LOW

    @pytest.mark.asyncio
    async def test_thirty_day_persistence_reaches_high(
        self, store: ClusterObservationStore
    ) -> None:
        as_of = date(2026, 8, 28)
        for i in range(30):
            await store.record_observation(_obs(as_of - timedelta(days=i)))

        conf = await store.compute_confidence("c1", as_of=as_of)
        assert conf.observed_days_30d == 30
        assert conf.confidence == Confidence.HIGH
        assert conf.persistence_gate_passed is True

    @pytest.mark.asyncio
    async def test_workspace_scoping(self, store: ClusterObservationStore) -> None:
        as_of = date(2026, 8, 28)
        for i in range(7):
            await store.record_observation(
                _obs(as_of - timedelta(days=i), workspace_id="ws1")
            )
        conf = await store.compute_confidence("c1", workspace_id="ws1", as_of=as_of)
        assert conf.observed_days_7d == 7
        # A different workspace has no history for this cluster.
        other = await store.compute_confidence("c1", workspace_id="ws2", as_of=as_of)
        assert other.has_history is False
