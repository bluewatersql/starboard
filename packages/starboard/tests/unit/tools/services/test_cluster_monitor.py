# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ClusterMonitor (autonomous, read-only right-sizing monitor).

Covers: the monitor loop over fixture clusters produces the expected
DRAFT/WARN/WATCH set; the multi-horizon confidence model gates single-day noise
(a 1-day overprovision does NOT reach DRAFT); the monitor NEVER calls a
workspace-mutating API (verified against a spy exposing forbidden mutators); and
graceful degradation with no history / no store / no data.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from starboard.tools.services.cluster_monitor import (
    ActionClass,
    ClusterMonitor,
)
from starboard.tools.services.cluster_observation_store import (
    ClusterObservationStore,
    RoleObservation,
)

from tests.unit.tools.services.test_cluster_observation_store import (
    InMemoryUCAdapter,
)

AS_OF = date(2026, 8, 28)


def _cluster(
    cluster_id: str,
    *,
    direction: str,
    reason: str,
    action: str,
    reduction_pct: float,
    savings: float,
    workspace_id: str = "ws1",
) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "cluster_id": cluster_id,
        "sizing_reason": reason,
        "sizing_direction": direction,
        "recommended_action": action,
        "target_cores_per_node": 4.0,
        "reduction_pct": reduction_pct,
        "list_price_estimate": {
            "cost_basis": "list-price DBU estimate",
            "estimated_monthly_savings_usd": savings,
        },
    }


class SpyRightsizingTool:
    """Read-only right-sizing tool spy that traps any mutating call.

    Exposes the real read verb (``get_cluster_rightsizing``) plus a set of
    workspace-mutating methods that record if the monitor ever touches them — it
    must not, this wave is read-only advisory.
    """

    #: Methods a right-sizing agent could plausibly (mis)use to mutate state.
    MUTATORS = (
        "edit_cluster",
        "edit_cluster_config",
        "resize_cluster",
        "delete_cluster",
        "permanent_delete_cluster",
        "start_cluster",
        "restart_cluster",
    )

    def __init__(self, clusters: list[dict[str, Any]] | None, found: bool = True) -> None:
        self._clusters = clusters
        self._found = found
        self.read_calls: list[dict[str, Any]] = []
        self.mutating_calls: list[str] = []
        for name in self.MUTATORS:
            setattr(self, name, self._make_trap(name))

    def _make_trap(self, name: str) -> Any:
        async def _trap(*args: Any, **kwargs: Any) -> None:
            self.mutating_calls.append(name)
            raise AssertionError(f"monitor invoked mutating API: {name}")

        return _trap

    async def get_cluster_rightsizing(
        self,
        cluster_id: str | None = None,
        lookback_days: int = 30,
        list_price_per_dbu: float | None = None,
    ) -> dict[str, Any]:
        self.read_calls.append(
            {"cluster_id": cluster_id, "lookback_days": lookback_days}
        )
        if not self._found:
            return {"found": False, "reason": "no executor"}
        return {
            "found": True,
            "lookback_days": lookback_days,
            "clusters": list(self._clusters or []),
        }


async def _seed_persistent(
    store: ClusterObservationStore, cluster_id: str, days: int = 7
) -> None:
    for i in range(days):
        await store.record_observation(
            RoleObservation(
                observation_date=AS_OF - timedelta(days=i),
                workspace_id="ws1",
                cluster_id=cluster_id,
                node_role="WORKER",
                sizing_reason="OVERPROVISIONED",
                sizing_direction="OVERPROVISIONED",
                reduction_pct=50.0,
            )
        )


@pytest.fixture
def store() -> ClusterObservationStore:
    return ClusterObservationStore(InMemoryUCAdapter())


class TestMonitorLoop:
    @pytest.mark.asyncio
    async def test_draft_warn_watch_classification(
        self, store: ClusterObservationStore
    ) -> None:
        clusters = [
            _cluster(
                "over-persistent",
                direction="OVERPROVISIONED",
                reason="OVERPROVISIONED",
                action="DOWNSIZE_CANDIDATE",
                reduction_pct=30.0,
                savings=100.0,
            ),
            _cluster(
                "over-noisy",
                direction="OVERPROVISIONED",
                reason="OVERPROVISIONED",
                action="DOWNSIZE_CANDIDATE",
                reduction_pct=25.0,
                savings=40.0,
            ),
            _cluster(
                "under-autoscale",
                direction="UNDERPROVISIONED",
                reason="AUTOSCALE_MAX_CONSTRAINED",
                action="RAISE_AUTOSCALE_MAX",
                reduction_pct=0.0,
                savings=0.0,
            ),
            _cluster(
                "under-cpu",
                direction="UNDERPROVISIONED",
                reason="WORKER_CPU_PRESSURE",
                action="UPSIZE_OR_COMPUTE_OPTIMIZED_SKU",
                reduction_pct=0.0,
                savings=0.0,
            ),
            _cluster(
                "balanced",
                direction="BALANCED",
                reason="BALANCED",
                action="NONE",
                reduction_pct=0.0,
                savings=0.0,
            ),
        ]
        # Only "over-persistent" has durable 7-day over-provision history.
        await _seed_persistent(store, "over-persistent")
        # "over-noisy" gets a single day → not persistent.
        await store.record_observation(
            RoleObservation(
                observation_date=AS_OF,
                workspace_id="ws1",
                cluster_id="over-noisy",
                sizing_reason="OVERPROVISIONED",
                sizing_direction="OVERPROVISIONED",
            )
        )

        tool = SpyRightsizingTool(clusters)
        monitor = ClusterMonitor(tool, observation_store=store)
        report = await monitor.run(as_of=AS_OF)

        by_id = {r.cluster_id: r for r in report.recommendations}
        assert by_id["over-persistent"].action_class == ActionClass.DRAFT
        assert by_id["over-noisy"].action_class == ActionClass.WATCH
        assert by_id["under-autoscale"].action_class == ActionClass.WARN
        # BALANCED and non-autoscale under-provision produce no recommendation.
        assert "balanced" not in by_id
        assert "under-cpu" not in by_id

        assert report.clusters_checked == 5
        # DRAFT ranks first.
        assert report.recommendations[0].action_class == ActionClass.DRAFT
        # Summary savings counts only DRAFT (the actionable proposals).
        assert report.summary["estimated_total_monthly_savings_usd"] == 100.0
        assert report.summary["by_action"]["DRAFT"] == 1

    @pytest.mark.asyncio
    async def test_single_day_overprovision_does_not_reach_draft(
        self, store: ClusterObservationStore
    ) -> None:
        clusters = [
            _cluster(
                "c1",
                direction="OVERPROVISIONED",
                reason="OVERPROVISIONED",
                action="DOWNSIZE_CANDIDATE",
                reduction_pct=45.0,
                savings=500.0,
            )
        ]
        # A single day of signal — noisy, must be gated.
        await store.record_observation(
            RoleObservation(
                observation_date=AS_OF,
                workspace_id="ws1",
                cluster_id="c1",
                sizing_reason="OVERPROVISIONED",
                sizing_direction="OVERPROVISIONED",
            )
        )

        monitor = ClusterMonitor(SpyRightsizingTool(clusters), observation_store=store)
        report = await monitor.run(as_of=AS_OF)

        rec = report.recommendations[0]
        assert rec.action_class == ActionClass.WATCH
        assert rec.action_class != ActionClass.DRAFT
        assert rec.persistence_gate_passed is False
        assert report.summary["by_action"].get("DRAFT") is None

    @pytest.mark.asyncio
    async def test_persistent_overprovision_reaches_draft(
        self, store: ClusterObservationStore
    ) -> None:
        clusters = [
            _cluster(
                "c1",
                direction="OVERPROVISIONED",
                reason="OVERPROVISIONED",
                action="DOWNSIZE_CANDIDATE",
                reduction_pct=45.0,
                savings=500.0,
            )
        ]
        await _seed_persistent(store, "c1", days=7)

        monitor = ClusterMonitor(SpyRightsizingTool(clusters), observation_store=store)
        report = await monitor.run(as_of=AS_OF)

        rec = report.recommendations[0]
        assert rec.action_class == ActionClass.DRAFT
        assert rec.persistence_gate_passed is True
        assert rec.estimated_monthly_savings_usd == 500.0


class TestReportOnlyInvariant:
    @pytest.mark.asyncio
    async def test_monitor_never_calls_mutating_api(
        self, store: ClusterObservationStore
    ) -> None:
        clusters = [
            _cluster(
                "over-persistent",
                direction="OVERPROVISIONED",
                reason="OVERPROVISIONED",
                action="DOWNSIZE_CANDIDATE",
                reduction_pct=30.0,
                savings=100.0,
            ),
            _cluster(
                "under-autoscale",
                direction="UNDERPROVISIONED",
                reason="AUTOSCALE_MAX_CONSTRAINED",
                action="RAISE_AUTOSCALE_MAX",
                reduction_pct=0.0,
                savings=0.0,
            ),
        ]
        await _seed_persistent(store, "over-persistent")

        tool = SpyRightsizingTool(clusters)
        monitor = ClusterMonitor(tool, observation_store=store)
        report = await monitor.run(as_of=AS_OF)

        # No mutating verb was ever touched — the invariant that matters.
        assert tool.mutating_calls == []
        # Only the read verb was called.
        assert len(tool.read_calls) == 1
        # The report and every recommendation are explicitly report-only.
        assert report.report_only is True
        assert all(not r.mutation_applied for r in report.recommendations)
        assert report.cost_basis == "list-price DBU estimate"


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_no_store_degrades_overprovision_to_watch(self) -> None:
        clusters = [
            _cluster(
                "c1",
                direction="OVERPROVISIONED",
                reason="OVERPROVISIONED",
                action="DOWNSIZE_CANDIDATE",
                reduction_pct=60.0,
                savings=900.0,
            )
        ]
        # No observation store at all → single-window analysis, no DRAFT.
        monitor = ClusterMonitor(SpyRightsizingTool(clusters), observation_store=None)
        report = await monitor.run(as_of=AS_OF)

        assert report.degraded is True
        rec = report.recommendations[0]
        assert rec.action_class == ActionClass.WATCH
        assert rec.persistence_gate_passed is None

    @pytest.mark.asyncio
    async def test_no_data_returns_degraded_empty_report(
        self, store: ClusterObservationStore
    ) -> None:
        monitor = ClusterMonitor(
            SpyRightsizingTool(None, found=False), observation_store=store
        )
        report = await monitor.run(as_of=AS_OF)

        assert report.clusters_checked == 0
        assert report.recommendations == []
        assert report.degraded is True
        assert report.reason == "no executor"
