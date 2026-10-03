# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.cluster`` — pure cluster right-sizing CLI (Phase-2 X2).

Thin ``argparse`` wrapper over the SDK-free analyzer in
:mod:`starboard_x.cluster`. Every invocation emits the stable JSON envelope
(:mod:`starboard_x.contract`) and uses the Phase-0 exit-code contract
(``0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error``).

Example::

    python -m starboard_x.cluster --cpu-p95 40 --memory-p95 45 --cpu-avg 25 \
        --node-role WORKER --persistence-ratio 0.8 --observed-days 30

The classify path is I/O-free: it builds a :class:`~starboard_x.cluster.ClusterMetricsInput`
from the flags, classifies compute sizing, optionally folds in streaming signals,
applies the persistence gate, and prints the :class:`~starboard_x.cluster.RightsizingVerdict`.
"""

from __future__ import annotations

import argparse
from typing import Any

from starboard_x import _cli

_DOMAIN = "cluster"


def _cmd_classify(args: argparse.Namespace) -> dict[str, Any]:
    # Import the pure analyzer lazily so the arg-error path never needs it and
    # the import stays visibly SDK-free.
    from starboard_x.cluster import (
        ClusterMetricsInput,
        StreamingMetricsInput,
        classify_compute_sizing,
        classify_streaming_capacity,
        synthesize_rightsizing_verdict,
    )

    metrics = ClusterMetricsInput(
        cpu_p95_pct=args.cpu_p95,
        memory_p95_pct=args.memory_p95,
        io_wait_p95_pct=args.io_wait_p95,
        swap_p95_pct=args.swap_p95,
        cpu_avg_pct=args.cpu_avg,
        cores_per_node=args.cores_per_node,
        memory_gb_per_node=args.memory_gb_per_node,
        min_autoscale_workers=args.min_autoscale_workers,
        max_autoscale_workers=args.max_autoscale_workers,
        observed_workers_p95=args.observed_workers_p95,
    )
    compute_signal = classify_compute_sizing(metrics, node_role=args.node_role)

    streaming_signal = None
    if args.slot_utilization_p95 is not None or args.autoscale_constrained_pct:
        streaming = StreamingMetricsInput(
            task_slot_utilization_p95=args.slot_utilization_p95 or 0.0,
            avg_queued_tasks_p95=args.queued_tasks_p95,
            autoscale_constrained_pct=args.autoscale_constrained_pct,
            event_time_lag_p95_seconds=args.event_lag_seconds,
            freshness_sla_sec=args.freshness_sla_sec,
        )
        streaming_signal = classify_streaming_capacity(streaming)

    verdict = synthesize_rightsizing_verdict(
        compute_signal,
        streaming_signal=streaming_signal,
        persistence_ratio=args.persistence_ratio,
        observed_days=args.observed_days,
    )
    return verdict.model_dump(mode="json")


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.cluster",
        description="Pure cluster right-sizing verdict from utilization percentiles.",
    )
    parser.add_argument("--format", choices=["json"], default="json")

    # Compute metrics.
    parser.add_argument(
        "--cpu-p95", type=float, required=True, dest="cpu_p95",
        help="CPU utilization p95 (%%).",
    )
    parser.add_argument(
        "--memory-p95", type=float, required=True, dest="memory_p95",
        help="Memory utilization p95 (%%).",
    )
    parser.add_argument(
        "--io-wait-p95", type=float, default=0.0, dest="io_wait_p95",
        help="IO-wait p95 (%%).",
    )
    parser.add_argument(
        "--swap-p95", type=float, default=0.0, dest="swap_p95",
        help="Swap p95 (%%).",
    )
    parser.add_argument(
        "--cpu-avg", type=float, default=0.0, dest="cpu_avg",
        help="CPU utilization average (%%).",
    )
    parser.add_argument(
        "--cores-per-node", type=float, default=0.0, dest="cores_per_node",
        help="Cores per node (enables target-core / reduction derivation).",
    )
    parser.add_argument(
        "--memory-gb-per-node", type=float, default=0.0, dest="memory_gb_per_node",
        help="Memory GB per node (enables target-GB / reduction derivation).",
    )
    parser.add_argument(
        "--node-role", choices=["WORKER", "DRIVER"], default="WORKER",
        dest="node_role", help="Node role to classify.",
    )

    # Autoscale.
    parser.add_argument(
        "--min-autoscale-workers", type=int, default=None,
        dest="min_autoscale_workers",
    )
    parser.add_argument(
        "--max-autoscale-workers", type=int, default=None,
        dest="max_autoscale_workers",
    )
    parser.add_argument(
        "--observed-workers-p95", type=float, default=0.0,
        dest="observed_workers_p95",
    )

    # Streaming (optional).
    parser.add_argument(
        "--slot-utilization-p95", type=float, default=None,
        dest="slot_utilization_p95",
        help="Task-slot utilization p95 (0-1); enables streaming classification.",
    )
    parser.add_argument(
        "--queued-tasks-p95", type=float, default=0.0, dest="queued_tasks_p95",
    )
    parser.add_argument(
        "--autoscale-constrained-pct", type=float, default=0.0,
        dest="autoscale_constrained_pct",
    )
    parser.add_argument(
        "--event-lag-seconds", type=float, default=None, dest="event_lag_seconds",
    )
    parser.add_argument(
        "--freshness-sla-sec", type=int, default=None, dest="freshness_sla_sec",
    )

    # Persistence gate.
    parser.add_argument(
        "--persistence-ratio", type=float, default=None, dest="persistence_ratio",
        help="Fraction of observed days signalling over-provision (0-1).",
    )
    parser.add_argument(
        "--observed-days", type=int, default=None, dest="observed_days",
        help="Distinct observation days backing the persistence gate.",
    )

    parser.set_defaults(func=_cmd_classify, command="classify")
    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
