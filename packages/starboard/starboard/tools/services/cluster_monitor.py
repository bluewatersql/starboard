# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Autonomous cluster right-sizing monitor (Phase-2 09, research/09 §4 Opt B/C).

The "art of the possible" surface: a scheduled loop that **observes and reports**
cluster right-sizing opportunities, built on the durable multi-horizon history in
:mod:`cluster_observation_store`.

**READ-ONLY ADVISORY (Wave-4 invariant).** The monitor proposes DRAFT / WARN
recommendations and MUST NEVER call a workspace-mutating API. Write-back /
auto-remediation (decision D-b) is owner-deferred to the next wave. The monitor's
only collaborator is the right-sizing **read** tool (``get_cluster_rightsizing``)
plus the observation store; it holds no mutating client and applies nothing.

Loop (research/09 §4 Opt B decision logic):

* enumerate clusters via ``get_cluster_rightsizing`` (CRS-06 read),
* for each **OVERPROVISIONED** cluster with ``reduction_pct ≥ 20%``, consult the
  multi-horizon confidence model:
    - persistence gate passed (``PERSISTENT``) → **DRAFT** downsize,
    - otherwise → **WATCH** (report-only; a single-day/no-history spike is *not*
      promoted to DRAFT — the confidence model gates the noise),
* for each **UNDERPROVISIONED** cluster that is autoscale-constrained → **WARN**,
* emit a ranked, evidence-cited report with a labelled **list-price DBU** savings
  estimate. Nothing is applied.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from starboard_x.cluster import (
    Confidence,
    RecommendedAction,
    SizingDirection,
    SizingReason,
)

from starboard.infra.observability.logging import get_logger
from starboard.tools.services.cluster_observation_store import (
    ClusterObservationStore,
    MultiHorizonConfidence,
)

logger = get_logger(__name__)

_LIST_PRICE_DISCLAIMER = (
    "list-price DBU estimate; actual billed cost differs under contracted rates"
)

# Autoscale-constrained under-provision signals that justify a WARN.
_AUTOSCALE_CONSTRAINED_SIGNALS: frozenset[str] = frozenset(
    {
        RecommendedAction.RAISE_AUTOSCALE_MAX.value,
        SizingReason.AUTOSCALE_MAX_CONSTRAINED.value,
    }
)


class ActionClass(StrEnum):
    """Advisory recommendation class — never a mutation instruction."""

    DRAFT = "DRAFT"  # persistent over-provision: proposed downsize (report-only)
    WARN = "WARN"  # under-provision + autoscale-constrained: capacity risk
    WATCH = "WATCH"  # over-provision without persistence: needs more history


class RightsizingToolLike(Protocol):
    """Structural type for the read-only right-sizing tool the monitor calls.

    Only the read verb is part of the contract; the monitor deliberately has no
    handle on any mutating method.
    """

    async def get_cluster_rightsizing(
        self,
        cluster_id: str | None = ...,
        lookback_days: int = ...,
        list_price_per_dbu: float | None = ...,
    ) -> dict[str, Any]: ...


class ClusterMonitorConfig(BaseModel):
    """Monitor decision thresholds (config-driven — no magic numbers)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    draft_min_reduction_pct: float = Field(
        default=20.0,
        description="reduction_pct at/above which a persistent over-provision drafts.",
    )


class MonitorRecommendation(BaseModel):
    """A single ranked, evidence-cited, report-only recommendation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str | None
    cluster_id: str | None
    action_class: ActionClass
    sizing_direction: str | None
    sizing_reason: str | None
    recommended_action: str | None
    reduction_pct: float | None
    confidence: str
    persistence_gate_passed: bool | None
    observed_days_7d: int
    evidence: list[str]
    list_price_estimate: dict[str, Any]
    estimated_monthly_savings_usd: float
    # The invariant, made explicit on every recommendation.
    mutation_applied: bool = False


class MonitorReport(BaseModel):
    """The monitor's ranked output. ``report_only`` is always ``True`` this wave."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    clusters_checked: int
    recommendations: list[MonitorRecommendation]
    summary: dict[str, Any]
    degraded: bool = False
    reason: str | None = None
    report_only: bool = True
    cost_basis: str = "list-price DBU estimate"
    disclaimer: str = _LIST_PRICE_DISCLAIMER


# Rank: DRAFT before WARN before WATCH (then by savings, handled at sort time).
_ACTION_RANK: dict[ActionClass, int] = {
    ActionClass.DRAFT: 0,
    ActionClass.WARN: 1,
    ActionClass.WATCH: 2,
}


class ClusterMonitor:
    """Autonomous, report-only cluster right-sizing monitor.

    Args:
        rightsizing_tool: The read-only right-sizing tool (``ClusterTools``-shaped,
            exposing ``get_cluster_rightsizing``). The monitor holds no mutating
            client and never applies a change.
        observation_store: Optional durable history. When omitted (or empty for a
            cluster), the confidence model degrades to ``LOW`` and over-provision
            never reaches DRAFT — it is reported as WATCH.
        config: Decision thresholds.
    """

    def __init__(
        self,
        rightsizing_tool: RightsizingToolLike,
        observation_store: ClusterObservationStore | None = None,
        config: ClusterMonitorConfig | None = None,
    ) -> None:
        self._tool = rightsizing_tool
        self._store = observation_store
        self._config = config or ClusterMonitorConfig()

    async def run(
        self,
        lookback_days: int = 30,
        list_price_per_dbu: float | None = None,
        as_of: date | None = None,
    ) -> MonitorReport:
        """Run one monitoring pass and return a ranked, report-only result."""
        as_of_date = as_of or datetime.now(UTC).date()
        result = await self._tool.get_cluster_rightsizing(
            lookback_days=lookback_days,
            list_price_per_dbu=list_price_per_dbu,
        )
        if not result.get("found"):
            return MonitorReport(
                generated_at=datetime.now(UTC),
                clusters_checked=0,
                recommendations=[],
                summary={"by_action": {}, "estimated_total_monthly_savings_usd": 0.0},
                degraded=True,
                reason=str(result.get("reason") or "right-sizing data unavailable"),
            )

        clusters: list[dict[str, Any]] = list(result.get("clusters") or [])
        recommendations: list[MonitorRecommendation] = []
        for row in clusters:
            rec = await self._classify_cluster(row, as_of_date)
            if rec is not None:
                recommendations.append(rec)

        recommendations.sort(
            key=lambda r: (
                _ACTION_RANK[r.action_class],
                -r.estimated_monthly_savings_usd,
            )
        )

        by_action: dict[str, int] = {}
        for rec in recommendations:
            by_action[rec.action_class.value] = (
                by_action.get(rec.action_class.value, 0) + 1
            )
        total_draft_savings = round(
            sum(
                r.estimated_monthly_savings_usd
                for r in recommendations
                if r.action_class == ActionClass.DRAFT
            ),
            2,
        )

        return MonitorReport(
            generated_at=datetime.now(UTC),
            clusters_checked=len(clusters),
            recommendations=recommendations,
            summary={
                "by_action": by_action,
                "estimated_total_monthly_savings_usd": total_draft_savings,
            },
            degraded=self._store is None,
        )

    async def _classify_cluster(
        self, row: dict[str, Any], as_of: date
    ) -> MonitorRecommendation | None:
        """Classify one cluster row into a recommendation, or ``None`` to skip."""
        direction = str(row.get("sizing_direction") or "")
        reason = row.get("sizing_reason")
        action = row.get("recommended_action")
        reduction = _as_float(row.get("reduction_pct"))
        list_price = dict(row.get("list_price_estimate") or {})
        savings = _as_float(list_price.get("estimated_monthly_savings_usd"))
        cluster_id = row.get("cluster_id")
        workspace_id = row.get("workspace_id")

        if direction == SizingDirection.OVERPROVISIONED.value:
            if reduction < self._config.draft_min_reduction_pct:
                return None  # below the material-savings floor — not worth surfacing
            confidence = await self._confidence(cluster_id, workspace_id, as_of)
            persistent = bool(confidence.persistence_gate_passed)
            evidence = [
                f"sizing_reason={reason}; reduction_pct={reduction:.1f}% "
                f"(≥ {self._config.draft_min_reduction_pct:.0f}% draft floor)",
                (
                    f"multi-horizon confidence={confidence.confidence.value}; "
                    f"7d days={confidence.observed_days_7d}, "
                    f"over-signal ratio={confidence.over_signal_ratio_7d:.2f}; "
                    f"persistence gate="
                    + (
                        "n/a (no history)"
                        if confidence.persistence_gate_passed is None
                        else ("passed" if persistent else "not met")
                    )
                ),
            ]
            action_class = ActionClass.DRAFT if persistent else ActionClass.WATCH
            if not persistent:
                evidence.append(
                    "not promoted to DRAFT: over-provision not persistent across the "
                    "7-day horizon (single-day noise gated)."
                )
            return self._build(
                row,
                action_class,
                reduction,
                confidence,
                evidence,
                list_price,
                savings,
            )

        if direction == SizingDirection.UNDERPROVISIONED.value:
            autoscale_constrained = (
                str(action or "") in _AUTOSCALE_CONSTRAINED_SIGNALS
                or str(reason or "") in _AUTOSCALE_CONSTRAINED_SIGNALS
            )
            if not autoscale_constrained:
                return None
            confidence = await self._confidence(cluster_id, workspace_id, as_of)
            evidence = [
                f"sizing_reason={reason}; recommended_action={action}",
                "under-provisioned and autoscale-constrained — capacity risk (WARN).",
            ]
            return self._build(
                row,
                ActionClass.WARN,
                reduction,
                confidence,
                evidence,
                list_price,
                savings,
            )

        return None  # BALANCED / REVIEW — nothing to recommend

    async def _confidence(
        self, cluster_id: Any, workspace_id: Any, as_of: date
    ) -> MultiHorizonConfidence:
        """Fetch the multi-horizon confidence, degrading when no store/history."""
        if self._store is None or cluster_id is None:
            return MultiHorizonConfidence(
                cluster_id=str(cluster_id) if cluster_id is not None else "",
                as_of=as_of,
                has_history=False,
                confidence=Confidence.LOW,
                persistence_gate_passed=None,
            )
        return await self._store.compute_confidence(
            str(cluster_id),
            workspace_id=str(workspace_id) if workspace_id is not None else None,
            as_of=as_of,
        )

    @staticmethod
    def _build(
        row: dict[str, Any],
        action_class: ActionClass,
        reduction: float,
        confidence: MultiHorizonConfidence,
        evidence: list[str],
        list_price: dict[str, Any],
        savings: float,
    ) -> MonitorRecommendation:
        return MonitorRecommendation(
            workspace_id=row.get("workspace_id"),
            cluster_id=row.get("cluster_id"),
            action_class=action_class,
            sizing_direction=row.get("sizing_direction"),
            sizing_reason=row.get("sizing_reason"),
            recommended_action=row.get("recommended_action"),
            reduction_pct=reduction,
            confidence=confidence.confidence.value,
            persistence_gate_passed=confidence.persistence_gate_passed,
            observed_days_7d=confidence.observed_days_7d,
            evidence=evidence,
            list_price_estimate=list_price,
            estimated_monthly_savings_usd=savings,
        )


def _as_float(value: Any) -> float:
    """Best-effort float coercion (None/blank → 0.0)."""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
