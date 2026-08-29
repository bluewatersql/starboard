# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for :mod:`starboard_x.cluster` — the SDK-free right-sizing analyzer.

The golden fixtures below encode the heuristic threshold table from
``changes/2026_26_27_agents/research/09_cluster_health.md`` §1 (the harvested
``cluster_role_features`` decision logic). Each ``sizing_reason`` /
``recommended_action`` assertion is the single source of truth for the backport
(decision D-2.3): if a threshold moves, the golden here must move with it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from starboard_x.cluster import (
    ClusterMetricsInput,
    ClusterSizingThresholds,
    RightsizingVerdict,
    StreamingMetricsInput,
    classify_compute_sizing,
    classify_streaming_capacity,
    synthesize_rightsizing_verdict,
)

_CORE_DIR = Path(__file__).parents[3]


def _worker(**overrides: float | int | None) -> ClusterMetricsInput:
    """Build a WORKER metrics input with balanced defaults, patched per test."""
    base: dict[str, float | int | None] = {
        "cpu_p95_pct": 60.0,
        "memory_p95_pct": 60.0,
        "io_wait_p95_pct": 5.0,
        "swap_p95_pct": 0.0,
        "cpu_avg_pct": 40.0,
        "cores_per_node": 16.0,
        "memory_gb_per_node": 64.0,
        "configured_fixed_workers": 4,
        "min_autoscale_workers": None,
        "max_autoscale_workers": None,
        "observed_workers_p95": 4.0,
    }
    base.update(overrides)
    return ClusterMetricsInput(**base)  # type: ignore[arg-type]


@pytest.mark.unit
class TestComputeSizingGolden:
    """Golden metric-profile → sizing_reason mappings (research/09 §1)."""

    def test_balanced_worker(self) -> None:
        sig = classify_compute_sizing(_worker(), node_role="WORKER")
        assert sig.sizing_reason == "BALANCED"
        assert sig.sizing_direction == "BALANCED"

    def test_worker_cpu_pressure(self) -> None:
        sig = classify_compute_sizing(
            _worker(cpu_p95_pct=95.0, cpu_avg_pct=60.0), node_role="WORKER"
        )
        assert sig.sizing_reason == "WORKER_CPU_PRESSURE"
        assert sig.sizing_direction == "UNDERPROVISIONED"
        assert sig.recommended_action == "UPSIZE_OR_COMPUTE_OPTIMIZED_SKU"

    def test_worker_memory_pressure_high_p95(self) -> None:
        sig = classify_compute_sizing(
            _worker(memory_p95_pct=92.0), node_role="WORKER"
        )
        assert sig.sizing_reason == "WORKER_MEMORY_PRESSURE"
        assert sig.recommended_action == "MEMORY_OPTIMIZED_SKU_OR_UPSIZE"

    def test_worker_memory_pressure_swap_variant(self) -> None:
        # swap_p95 >= 2 AND memory_p95 >= 80  → worker memory pressure
        sig = classify_compute_sizing(
            _worker(memory_p95_pct=82.0, swap_p95_pct=3.0), node_role="WORKER"
        )
        assert sig.sizing_reason == "WORKER_MEMORY_PRESSURE"

    def test_worker_io_bound(self) -> None:
        sig = classify_compute_sizing(
            _worker(io_wait_p95_pct=30.0), node_role="WORKER"
        )
        assert sig.sizing_reason == "WORKER_IO_BOUND"
        assert sig.recommended_action == "ADD_LOCAL_DISK_OR_IO_OPTIMIZED_SKU"

    def test_driver_memory_pressure_swap_variant(self) -> None:
        # driver: swap_p95 >= 2 AND memory_p95 >= 75
        sig = classify_compute_sizing(
            _worker(memory_p95_pct=76.0, swap_p95_pct=3.0), node_role="DRIVER"
        )
        assert sig.sizing_reason == "DRIVER_MEMORY_PRESSURE"

    def test_driver_cpu_pressure(self) -> None:
        sig = classify_compute_sizing(
            _worker(cpu_p95_pct=95.0, cpu_avg_pct=55.0), node_role="DRIVER"
        )
        assert sig.sizing_reason == "DRIVER_CPU_PRESSURE"

    def test_autoscale_max_constrained(self) -> None:
        sig = classify_compute_sizing(
            _worker(
                cpu_p95_pct=85.0,
                memory_p95_pct=70.0,
                max_autoscale_workers=8,
                observed_workers_p95=8.0,
            ),
            node_role="WORKER",
        )
        assert sig.sizing_reason == "AUTOSCALE_MAX_CONSTRAINED"
        assert sig.sizing_direction == "UNDERPROVISIONED"
        assert sig.recommended_action == "RAISE_AUTOSCALE_MAX"

    def test_autoscale_min_too_high(self) -> None:
        sig = classify_compute_sizing(
            _worker(
                cpu_p95_pct=30.0,
                memory_p95_pct=45.0,
                cpu_avg_pct=15.0,
                min_autoscale_workers=4,
                observed_workers_p95=4.0,
            ),
            node_role="WORKER",
        )
        assert sig.sizing_reason == "AUTOSCALE_MIN_TOO_HIGH"
        assert sig.sizing_direction == "OVERPROVISIONED"
        assert sig.recommended_action == "LOWER_AUTOSCALE_MIN"

    def test_severely_overprovisioned(self) -> None:
        sig = classify_compute_sizing(
            _worker(cpu_p95_pct=20.0, memory_p95_pct=25.0, cpu_avg_pct=10.0),
            node_role="WORKER",
        )
        assert sig.sizing_reason == "SEVERELY_OVERPROVISIONED"
        assert sig.sizing_direction == "OVERPROVISIONED"
        assert sig.recommended_action == "DOWNSIZE_OR_SMALLER_SKU"

    def test_overprovisioned(self) -> None:
        sig = classify_compute_sizing(
            _worker(cpu_p95_pct=40.0, memory_p95_pct=45.0, cpu_avg_pct=25.0),
            node_role="WORKER",
        )
        assert sig.sizing_reason == "OVERPROVISIONED"
        assert sig.sizing_direction == "OVERPROVISIONED"
        assert sig.recommended_action == "DOWNSIZE_CANDIDATE"


@pytest.mark.unit
class TestCostExposure:
    """Target-core / binding-resource derivation (research/09 §1 lines 209-224)."""

    def test_overprovisioned_target_and_binding(self) -> None:
        # cpu_p95=40, cores=16 → 16*0.40/0.7=9.14 → band 0.75 → 12 cores (25%).
        # mem_p95=45, gb=64  → 64*0.45/0.7=41.1 → band 0.75 → 48 gb  (25%).
        sig = classify_compute_sizing(
            _worker(cpu_p95_pct=40.0, memory_p95_pct=45.0, cpu_avg_pct=25.0),
            node_role="WORKER",
        )
        assert sig.target_cores_per_node == 12.0
        assert sig.target_gb_per_node == 48.0
        assert sig.reduction_pct == 25.0
        assert sig.binding_resource == "CPU"

    def test_pressure_has_no_downsize_target(self) -> None:
        sig = classify_compute_sizing(
            _worker(cpu_p95_pct=95.0, cpu_avg_pct=60.0), node_role="WORKER"
        )
        assert sig.target_cores_per_node is None
        assert sig.reduction_pct is None
        assert sig.binding_resource is None

    def test_missing_memory_metric_does_not_suppress_cpu_downsize(self) -> None:
        """A missing resource metric must not zero out a real downsize on the other.

        Regression: treating an absent memory metric (gb_per_node=0 → no
        reduction) as a 0% reduction previously forced reduction_pct=0 and
        mislabelled binding_resource='MEMORY', silently dropping a genuine CPU
        downsize. The present metric must govern instead.
        """
        sig = classify_compute_sizing(
            _worker(
                cpu_p95_pct=40.0,
                memory_p95_pct=45.0,
                cpu_avg_pct=25.0,
                memory_gb_per_node=0.0,  # memory metric absent
            ),
            node_role="WORKER",
        )
        assert sig.reduction_pct == 25.0, "CPU downsize must survive a missing memory metric"
        assert sig.binding_resource == "CPU"


@pytest.mark.unit
class TestConfigDrivenThresholds:
    """Thresholds are config-driven (D-2.3): overriding one changes the verdict."""

    def test_default_thresholds_match_research(self) -> None:
        t = ClusterSizingThresholds()
        assert t.cpu_pressure_p95_pct == 90.0
        assert t.cpu_pressure_avg_pct == 50.0
        assert t.io_wait_p95_pct == 25.0
        assert t.overprovisioned_cpu_p95_pct == 50.0
        assert t.severely_overprovisioned_cpu_p95_pct == 30.0
        assert t.persistence_min_days == 3
        assert t.persistence_min_ratio == 0.7

    def test_custom_threshold_reclassifies(self) -> None:
        # A stricter IO threshold turns a previously-balanced profile IO-bound.
        strict = ClusterSizingThresholds(io_wait_p95_pct=3.0)
        sig = classify_compute_sizing(
            _worker(io_wait_p95_pct=5.0), node_role="WORKER", thresholds=strict
        )
        assert sig.sizing_reason == "WORKER_IO_BOUND"


@pytest.mark.unit
class TestPersistenceGate:
    """3-day minimum + 70% ratio gate (research/09 §1 lines 116-137)."""

    def _over(self) -> ClusterMetricsInput:
        return _worker(cpu_p95_pct=40.0, memory_p95_pct=45.0, cpu_avg_pct=25.0)

    def test_gate_passed_upgrades_to_downsize_workers(self) -> None:
        sig = classify_compute_sizing(self._over(), node_role="WORKER")
        verdict = synthesize_rightsizing_verdict(
            sig, persistence_ratio=0.8, observed_days=7
        )
        assert verdict.persistence_gate_passed is True
        assert verdict.recommended_action == "DOWNSIZE_WORKERS"
        assert verdict.confidence == "MEDIUM"

    def test_gate_passed_30d_is_high_confidence(self) -> None:
        sig = classify_compute_sizing(self._over(), node_role="WORKER")
        verdict = synthesize_rightsizing_verdict(
            sig, persistence_ratio=0.9, observed_days=30
        )
        assert verdict.confidence == "HIGH"
        assert verdict.recommended_action == "DOWNSIZE_WORKERS"

    def test_gate_failed_ratio_stays_candidate(self) -> None:
        sig = classify_compute_sizing(self._over(), node_role="WORKER")
        verdict = synthesize_rightsizing_verdict(
            sig, persistence_ratio=0.4, observed_days=7
        )
        assert verdict.persistence_gate_passed is False
        assert verdict.recommended_action == "DOWNSIZE_CANDIDATE"
        assert verdict.confidence == "LOW"

    def test_gate_failed_too_few_days(self) -> None:
        sig = classify_compute_sizing(self._over(), node_role="WORKER")
        verdict = synthesize_rightsizing_verdict(
            sig, persistence_ratio=0.9, observed_days=2
        )
        assert verdict.persistence_gate_passed is False
        assert verdict.recommended_action == "DOWNSIZE_CANDIDATE"

    def test_no_history_is_single_window_low_confidence(self) -> None:
        sig = classify_compute_sizing(self._over(), node_role="WORKER")
        verdict = synthesize_rightsizing_verdict(sig)
        assert verdict.persistence_gate_passed is None
        assert verdict.confidence == "LOW"
        assert verdict.recommended_action == "DOWNSIZE_CANDIDATE"


@pytest.mark.unit
class TestStreamingCapacity:
    """Streaming service-level thresholds (research/09 §1 recommended actions)."""

    def _stream(self, **overrides: float | int | None) -> StreamingMetricsInput:
        base: dict[str, float | int | None] = {
            "task_slot_utilization_p95": 0.3,
            "avg_queued_tasks_p95": 0.0,
            "autoscale_constrained_pct": 0.0,
            "backlog_bytes_p95": None,
            "backlog_records_p95": None,
            "event_time_lag_p95_seconds": None,
            "freshness_sla_sec": None,
        }
        base.update(overrides)
        return StreamingMetricsInput(**base)  # type: ignore[arg-type]

    def test_balanced_stream(self) -> None:
        sig = classify_streaming_capacity(self._stream())
        assert sig.capacity_status == "BALANCED"
        assert sig.sizing_direction == "BALANCED"

    def test_freshness_sla_breach(self) -> None:
        sig = classify_streaming_capacity(
            self._stream(event_time_lag_p95_seconds=600.0, freshness_sla_sec=300)
        )
        assert sig.capacity_status == "FRESHNESS_SLA_BREACH"
        assert sig.recommended_action == "INVESTIGATE_STREAM_LATENCY"

    def test_autoscale_bound(self) -> None:
        sig = classify_streaming_capacity(
            self._stream(autoscale_constrained_pct=25.0, backlog_records_p95=1000)
        )
        assert sig.capacity_status == "UNDERPROVISIONED_AUTOSCALE_BOUND"
        assert sig.sizing_direction == "UNDERPROVISIONED"
        assert sig.recommended_action == "RAISE_AUTOSCALE_MAX"

    def test_task_capacity(self) -> None:
        sig = classify_streaming_capacity(
            self._stream(avg_queued_tasks_p95=5.0, task_slot_utilization_p95=0.9)
        )
        assert sig.capacity_status == "UNDERPROVISIONED_TASK_CAPACITY"
        assert sig.recommended_action == "ADD_WORKERS"

    def test_backlog_pressure(self) -> None:
        sig = classify_streaming_capacity(
            self._stream(backlog_records_p95=500, task_slot_utilization_p95=0.82)
        )
        assert sig.capacity_status == "UNDERPROVISIONED_BACKLOG_PRESSURE"
        assert sig.recommended_action == "ADD_WORKERS"


@pytest.mark.unit
class TestSynthesis:
    """Merging compute + streaming signals (most-urgent wins, research §1)."""

    def test_streaming_underprovision_overrides_compute_overprovision(self) -> None:
        compute = classify_compute_sizing(
            _worker(cpu_p95_pct=40.0, memory_p95_pct=45.0, cpu_avg_pct=25.0),
            node_role="WORKER",
        )
        streaming = classify_streaming_capacity(
            StreamingMetricsInput(
                task_slot_utilization_p95=0.9,
                avg_queued_tasks_p95=5.0,
                autoscale_constrained_pct=0.0,
                backlog_bytes_p95=None,
                backlog_records_p95=None,
                event_time_lag_p95_seconds=None,
                freshness_sla_sec=None,
            )
        )
        verdict = synthesize_rightsizing_verdict(compute, streaming_signal=streaming)
        assert verdict.sizing_direction == "UNDERPROVISIONED"
        assert verdict.sizing_status == "UNDERPROVISIONED_TASK_CAPACITY"
        assert verdict.recommended_action == "ADD_WORKERS"

    def test_compute_verdict_when_no_streaming(self) -> None:
        compute = classify_compute_sizing(
            _worker(cpu_p95_pct=95.0, cpu_avg_pct=60.0), node_role="WORKER"
        )
        verdict = synthesize_rightsizing_verdict(compute)
        assert isinstance(verdict, RightsizingVerdict)
        assert verdict.sizing_status == "WORKER_CPU_PRESSURE"
        assert verdict.recommended_action == "UPSIZE_OR_COMPUTE_OPTIMIZED_SKU"

    def test_verdict_is_json_serializable(self) -> None:
        compute = classify_compute_sizing(_worker(), node_role="WORKER")
        payload = synthesize_rightsizing_verdict(compute).model_dump(mode="json")
        assert payload["sizing_direction"] == "BALANCED"
        assert set(payload) >= {
            "sizing_direction",
            "sizing_status",
            "recommended_action",
            "target_cores_per_node",
            "target_gb_per_node",
            "binding_resource",
            "reduction_pct",
            "confidence",
            "persistence_gate_passed",
        }


@pytest.mark.unit
class TestClusterCli:
    """The ``python -m starboard_x.cluster`` envelope + exit-code contract."""

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "starboard_x.cluster", *args],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )

    def test_help_smoke(self) -> None:
        proc = self._run("--help")
        assert proc.returncode == 0, proc.stderr
        assert "cpu-p95" in proc.stdout

    def test_classify_emits_envelope(self) -> None:
        proc = self._run(
            "--cpu-p95", "40", "--memory-p95", "45", "--cpu-avg", "25",
            "--node-role", "WORKER",
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert set(payload) >= {"ok", "domain", "command", "data", "error", "meta"}
        assert payload["ok"] is True
        assert payload["domain"] == "cluster"
        assert payload["data"]["sizing_direction"] == "OVERPROVISIONED"

    def test_persistence_flags_gate_downsize(self) -> None:
        proc = self._run(
            "--cpu-p95", "40", "--memory-p95", "45", "--cpu-avg", "25",
            "--persistence-ratio", "0.8", "--observed-days", "30",
        )
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)["data"]
        assert data["recommended_action"] == "DOWNSIZE_WORKERS"
        assert data["confidence"] == "HIGH"

    def test_bad_args_is_arg_error(self) -> None:
        proc = self._run("--cpu-p95", "not-a-number")
        assert proc.returncode == 4, proc.stdout


@pytest.mark.unit
class TestSdkFree:
    """Importing the analyzer must pull no databricks-sdk (kernel boundary)."""

    def test_import_pulls_no_sdk(self) -> None:
        body = (
            "import sys\n"
            "import starboard_x.cluster  # noqa: F401\n"
            "sdk = sorted(m for m in sys.modules "
            "if m == 'databricks' or m.startswith('databricks.'))\n"
            "assert not sdk, sdk\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", body],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "OK" in result.stdout
