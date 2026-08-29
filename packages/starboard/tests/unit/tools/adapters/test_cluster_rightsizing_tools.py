# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for the Task-09 cluster right-sizing tool surface.

Covers:
- The enriched ``rightsizing`` block on ``get_cluster_metrics`` /
  ``get_cluster_health`` (reuses the pure ``starboard_x.cluster`` logic).
- The two new tools ``get_cluster_rightsizing`` (CRS-06) and
  ``get_workload_rightsizing`` (CRS-07/08): each returns a sizing verdict plus a
  labelled **list-price DBU** cost exposure. The query pack is mocked (a fake
  SQL executor returns canned DataFrames keyed by query fingerprint).
- The DOC-12 tool-count invariant (registry grew to 59, both tools present).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest
from starboard.tools.adapters.cluster_tools import ClusterTools
from starboard_x.cluster import LIST_PRICE_DISCLAIMER

_MODULE = "starboard.tools.adapters.cluster_tools"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _overprovisioned_summary() -> dict:
    """An analyzed cluster summary (ClusterSummary.to_dict shape) that is clearly
    over-provisioned (low CPU/memory p95) so the enrichment yields a downsize."""
    return {
        "config": {
            "cluster_id": "c-1",
            "node_type": "i3.xlarge",
            "worker_count": 4,
            "autoscale": {"min_workers": 2, "max_workers": 8},
        },
        "resources": {
            "driver": {"instances": 1, "cores_total": 4.0, "memory_total_GB": 30.5},
            "worker": {"instances": 4, "cores_total": 16.0, "memory_total_GB": 122.0},
        },
        "usage": {
            "compute_utilization": {
                "driver": {"cpu_total_max": 15.0, "cpu_total_avg": 8.0, "mem_used_max": 25.0},
                "worker": {"cpu_total_max": 20.0, "cpu_total_avg": 10.0, "mem_used_max": 30.0},
            },
        },
    }


class _FakeSQLExecutor:
    """Routes rendered SQL to a canned DataFrame by query fingerprint."""

    def __init__(self, *, crs06=None, crs07=None, crs08=None) -> None:
        self._crs06 = crs06
        self._crs07 = crs07
        self._crs08 = crs08
        self.calls: list[str] = []

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        self.calls.append(sql)
        if "pipeline_workloads" in sql:
            return self._crs08 if self._crs08 is not None else pl.DataFrame()
        if "job_signals" in sql:
            return self._crs07 if self._crs07 is not None else pl.DataFrame()
        if "target_cores_per_node" in sql:
            return self._crs06 if self._crs06 is not None else pl.DataFrame()
        return pl.DataFrame()


def _crs06_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "workspace_id": ["ws-1", "ws-1"],
            "cluster_id": ["c-1", "c-2"],
            "sizing_reason": ["SEVERELY_OVERPROVISIONED", "WORKER_CPU_PRESSURE"],
            "sizing_direction": ["OVERPROVISIONED", "UNDERPROVISIONED"],
            "recommended_action": ["DOWNSIZE_WORKERS", "UPSIZE_OR_COMPUTE_OPTIMIZED_SKU"],
            "target_cores_per_node": [4.0, 8.0],
            "reduction_pct": [50.0, 0.0],
            "dbus_per_day": [100.0, 40.0],
            "total_samples": [500, 480],
        }
    )


def _crs07_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "workspace_id": ["ws-1"],
            "job_id": ["job-9"],
            "cluster_sizing_reason": ["SEVERELY_OVERPROVISIONED"],
            "job_sizing_direction": ["OVERPROVISIONED"],
            "total_runs": [30],
            "succeeded_runs": [29],
            "success_rate_pct": [96.7],
            "runtime_p95_minutes": [12.3],
        }
    )


def _crs08_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "workspace_id": ["ws-1", "ws-1"],
            "workload_type": ["JOB", "PIPELINE"],
            "workload_id": ["job-9", "pipe-3"],
            "sizing_direction": ["OVERPROVISIONED", "BALANCED"],
            "priority_score": [2, 1],
        }
    )


# --------------------------------------------------------------------------- #
# Enriched get_cluster_metrics / get_cluster_health
# --------------------------------------------------------------------------- #
_ENRICHED_KEYS = {
    "target_cores_per_node",
    "reduction_pct",
    "binding_resource",
    "autoscale_constrained",
    "queue_pressure",
}


@pytest.mark.asyncio
async def test_get_cluster_metrics_enriched_with_rightsizing() -> None:
    tools = ClusterTools(provider=MagicMock())
    with patch(
        f"{_MODULE}.analyze_cluster_metrics",
        new=AsyncMock(return_value=[_overprovisioned_summary()]),
    ):
        result = await tools.get_cluster_metrics("c-1")

    assert result["found"] is True
    rs = result["metrics"]["rightsizing"]
    assert set(rs) >= _ENRICHED_KEYS
    assert rs["available"] is True
    # Over-provisioned worker → a concrete downsize target + reduction.
    assert rs["sizing_direction"] == "OVERPROVISIONED"
    assert rs["target_cores_per_node"] is not None
    assert rs["reduction_pct"] is not None
    assert rs["binding_resource"] in {"CPU", "MEMORY"}
    assert rs["queue_pressure"] is False


@pytest.mark.asyncio
async def test_get_cluster_health_enriched_with_rightsizing() -> None:
    tools = ClusterTools(provider=MagicMock())

    health_report = MagicMock()
    health_report.cluster_name = "test-cluster"
    health_report.health_status = "GOOD"
    health_report.risks = []
    health_report.critical_risks = []
    health_report.high_priority_risks = []
    health_report.summary = "ok"
    health_report.generated_at = datetime(2026, 1, 1, tzinfo=UTC)

    with (
        patch(f"{_MODULE}.get_transformed", new=AsyncMock(return_value={"cluster_id": "c-1"})),
        patch(
            f"{_MODULE}.analyze_cluster_metrics",
            new=AsyncMock(return_value=[_overprovisioned_summary()]),
        ),
        patch(f"{_MODULE}.build_cluster_fingerprint", return_value=object()),
        patch(f"{_MODULE}.analyze_cluster_health", return_value=health_report),
    ):
        result = await tools.get_cluster_health("c-1")

    assert result["found"] is True
    rs = result["health"]["rightsizing"]
    assert set(rs) >= _ENRICHED_KEYS
    assert rs["available"] is True
    assert rs["sizing_direction"] == "OVERPROVISIONED"


# --------------------------------------------------------------------------- #
# get_cluster_rightsizing (CRS-06)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_cluster_rightsizing_returns_verdict_and_list_price() -> None:
    executor = _FakeSQLExecutor(crs06=_crs06_df())
    tools = ClusterTools(provider=MagicMock(), sql_executor=executor)

    result = await tools.get_cluster_rightsizing(lookback_days=30)

    assert result["found"] is True
    assert result["query_id"] == "CRS-06"
    assert len(result["clusters"]) == 2

    first = result["clusters"][0]
    # Verdict fields present.
    assert first["sizing_direction"] == "OVERPROVISIONED"
    assert first["recommended_action"] == "DOWNSIZE_WORKERS"
    assert first["target_cores_per_node"] == 4.0
    # List-price DBU cost exposure present + labelled.
    lp = first["list_price_estimate"]
    assert lp["cost_basis"] == "list-price DBU estimate"
    assert lp["disclaimer"] == LIST_PRICE_DISCLAIMER
    # 100 DBU/day * 30 * 0.55 = 1650 ; 50% reduction => 825 savings.
    assert lp["estimated_monthly_cost_usd"] == pytest.approx(1650.0)
    assert lp["estimated_monthly_savings_usd"] == pytest.approx(825.0)

    assert result["summary"]["cluster_count"] == 2
    assert result["summary"]["by_direction"]["OVERPROVISIONED"] == 1


@pytest.mark.asyncio
async def test_get_cluster_rightsizing_scopes_to_cluster_id() -> None:
    executor = _FakeSQLExecutor(crs06=_crs06_df())
    tools = ClusterTools(provider=MagicMock(), sql_executor=executor)

    result = await tools.get_cluster_rightsizing(cluster_id="c-2")
    assert result["found"] is True
    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["cluster_id"] == "c-2"


@pytest.mark.asyncio
async def test_get_cluster_rightsizing_custom_list_price() -> None:
    executor = _FakeSQLExecutor(crs06=_crs06_df())
    tools = ClusterTools(provider=MagicMock(), sql_executor=executor)

    result = await tools.get_cluster_rightsizing(cluster_id="c-1", list_price_per_dbu=1.0)
    lp = result["clusters"][0]["list_price_estimate"]
    assert lp["list_price_per_dbu_usd"] == 1.0
    assert lp["estimated_monthly_cost_usd"] == pytest.approx(3000.0)


@pytest.mark.asyncio
async def test_get_cluster_rightsizing_degrades_without_executor() -> None:
    tools = ClusterTools(provider=MagicMock(), sql_executor=None)
    result = await tools.get_cluster_rightsizing()
    assert result["found"] is False
    assert "unavailable" in result["reason"].lower()


# --------------------------------------------------------------------------- #
# get_workload_rightsizing (CRS-07 / CRS-08)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_workload_rightsizing_returns_verdict_and_list_price() -> None:
    executor = _FakeSQLExecutor(
        crs06=_crs06_df(), crs07=_crs07_df(), crs08=_crs08_df()
    )
    tools = ClusterTools(provider=MagicMock(), sql_executor=executor)

    result = await tools.get_workload_rightsizing(lookback_days=30)

    assert result["found"] is True
    assert result["query_ids"] == ["CRS-08", "CRS-07"]
    # Verdicts (CRS-08) present, ranked set surfaced.
    assert len(result["workloads"]) == 2
    directions = {w["workload_id"]: w["sizing_direction"] for w in result["workloads"]}
    assert directions["job-9"] == "OVERPROVISIONED"
    # Per-job reliability (CRS-07) present.
    assert result["jobs"][0]["job_id"] == "job-9"
    assert result["jobs"][0]["success_rate_pct"] == 96.7
    # Fleet list-price DBU cost exposure present + labelled.
    lp = result["list_price_estimate"]
    assert lp["cost_basis"] == "list-price DBU estimate"
    # (100 + 40) DBU/day * 30 * 0.55 = 2310.
    assert lp["estimated_monthly_cost_usd"] == pytest.approx(2310.0)


@pytest.mark.asyncio
async def test_get_workload_rightsizing_filters_by_type() -> None:
    executor = _FakeSQLExecutor(
        crs06=_crs06_df(), crs07=_crs07_df(), crs08=_crs08_df()
    )
    tools = ClusterTools(provider=MagicMock(), sql_executor=executor)

    result = await tools.get_workload_rightsizing(workload_type="PIPELINE")
    assert result["found"] is True
    assert all(w["workload_type"] == "PIPELINE" for w in result["workloads"])
    # A PIPELINE filter drops the job detail rows.
    assert result["jobs"] == []


@pytest.mark.asyncio
async def test_get_workload_rightsizing_degrades_without_executor() -> None:
    tools = ClusterTools(provider=MagicMock(), sql_executor=None)
    result = await tools.get_workload_rightsizing()
    assert result["found"] is False


# --------------------------------------------------------------------------- #
# Governance + registry (DOC-12)
# --------------------------------------------------------------------------- #
def test_new_tools_registered_and_count_is_59() -> None:
    from starboard.agents.tools.registry import ALL_TOOL_METADATA

    assert "get_cluster_rightsizing" in ALL_TOOL_METADATA
    assert "get_workload_rightsizing" in ALL_TOOL_METADATA
    assert len(ALL_TOOL_METADATA) == 59


def test_rightsizing_outputs_are_free_of_internal_namespaces() -> None:
    import starboard.tools.adapters.cluster_tools as mod

    banned = (
        "centralized_system_tables",
        "fin_live_gold",
        "logfood",
        "hmr_stack_hash",
    )
    src = mod.__file__
    with open(src, encoding="utf-8") as fh:
        text = fh.read().lower()
    for token in banned:
        assert token not in text
