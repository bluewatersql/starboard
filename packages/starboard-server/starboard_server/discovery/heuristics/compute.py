# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Compute and cluster heuristic rules."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from starboard_server.discovery.heuristics.base import (
    Dimension,
    HeuristicFinding,
    Severity,
)


@dataclass(frozen=True)
class CMP001ExcessiveAutoTermination:
    """CMP-001: Excessive Auto-Termination."""

    rule_id: str = "CMP-001"
    domain: str = "compute"
    name: str = "Excessive Auto-Termination"
    description: str = "Clusters with auto_termination_minutes > 120"
    severity: Severity = "HIGH"
    dimension: Dimension = "consumption"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-C02"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "auto_termination_minutes" not in df.columns:
            return []
        violators = df.filter(pl.col("auto_termination_minutes") > 120)
        if violators.is_empty():
            return []
        ids = (
            violators["cluster_id"].to_list()
            if "cluster_id" in df.columns
            else [f"row_{i}" for i in range(len(violators))]
        )
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} clusters exceed 120 min auto-termination.",
                evidence_query_id=query_id,
                threshold="auto_termination_minutes > 120",
                actual_value=f"{violators['auto_termination_minutes'].max()!r} min max",
                affected_entities=tuple(str(x) for x in ids),
            )
        ]


@dataclass(frozen=True)
class CMP002HighIdlePercentage:
    """CMP-002: High Idle Percentage."""

    rule_id: str = "CMP-002"
    domain: str = "compute"
    name: str = "High Idle Percentage"
    description: str = "Clusters with idle_minutes > ~40% of total possible"
    severity: Severity = "HIGH"
    dimension: Dimension = "consumption"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-C02"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "idle_minutes" not in df.columns:
            return []
        threshold = 0.4 * 30 * 24 * 60
        violators = df.filter(pl.col("idle_minutes") > threshold)
        if violators.is_empty():
            return []
        ids = (
            violators["cluster_id"].to_list()
            if "cluster_id" in df.columns
            else [f"row_{i}" for i in range(len(violators))]
        )
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} clusters exceed 40% idle.",
                evidence_query_id=query_id,
                threshold="idle_minutes > 17280 (~40% of 30d)",
                actual_value=f"max idle_minutes={violators['idle_minutes'].max()!r}",
                affected_entities=tuple(str(x) for x in ids),
            )
        ]


@dataclass(frozen=True)
class CMP003NoAutoScalingOnInteractive:
    """CMP-003: No Auto-Scaling on Interactive."""

    rule_id: str = "CMP-003"
    domain: str = "compute"
    name: str = "No Auto-Scaling on Interactive"
    description: str = "Fixed-size interactive clusters from UI/API"
    severity: Severity = "MEDIUM"
    dimension: Dimension = "configuration"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-C01"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        required = {"cluster_type", "cluster_source"}
        if not required.issubset(df.columns):
            return []
        violators = df.filter(
            (pl.col("cluster_type") == "Fixed Size")
            & (pl.col("cluster_source").is_in(["UI", "API"]))
        )
        if violators.is_empty():
            return []
        ids = (
            violators["cluster_id"].to_list()
            if "cluster_id" in df.columns
            else [f"row_{i}" for i in range(len(violators))]
        )
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} fixed-size interactive clusters.",
                evidence_query_id=query_id,
                threshold="cluster_type=='Fixed Size' AND cluster_source IN ('UI','API')",
                actual_value=f"{len(violators)} clusters",
                affected_entities=tuple(str(x) for x in ids),
            )
        ]


@dataclass(frozen=True)
class CMP004OverProvisionedClusters:
    """CMP-004: Over-Provisioned Clusters."""

    rule_id: str = "CMP-004"
    domain: str = "compute"
    name: str = "Over-Provisioned Clusters"
    description: str = "Clusters with avg_cpu_pct or avg_mem_pct < 20"
    severity: Severity = "MEDIUM"
    dimension: Dimension = "consumption"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-C01"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        has_cpu = "avg_cpu_pct" in df.columns
        has_mem = "avg_mem_pct" in df.columns
        if not has_cpu and not has_mem:
            return []
        if has_cpu and has_mem:
            violators = df.filter(
                (pl.col("avg_cpu_pct") < 20) | (pl.col("avg_mem_pct") < 20)
            )
        elif has_cpu:
            violators = df.filter(pl.col("avg_cpu_pct") < 20)
        else:
            violators = df.filter(pl.col("avg_mem_pct") < 20)
        if violators.is_empty():
            return []
        ids = (
            violators["cluster_id"].to_list()
            if "cluster_id" in df.columns
            else [f"row_{i}" for i in range(len(violators))]
        )
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} clusters under-utilized.",
                evidence_query_id=query_id,
                threshold="avg_cpu_pct < 20 OR avg_mem_pct < 20",
                actual_value=f"{len(violators)} clusters",
                affected_entities=tuple(str(x) for x in ids),
            )
        ]


@dataclass(frozen=True)
class CMP005MissingAutoTermination:
    """CMP-005: Missing Auto-Termination."""

    rule_id: str = "CMP-005"
    domain: str = "compute"
    name: str = "Missing Auto-Termination"
    description: str = "Clusters with no auto-termination configured"
    severity: Severity = "CRITICAL"
    dimension: Dimension = "configuration"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-C02"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        has_termination_risk = "termination_risk" in df.columns
        has_auto_term = "auto_termination_minutes" in df.columns
        if not has_termination_risk and not has_auto_term:
            return []
        if has_termination_risk and has_auto_term:
            violators = df.filter(
                (pl.col("auto_termination_minutes").is_null())
                | (pl.col("termination_risk") == "NO AUTO-TERMINATE")
            )
        elif has_termination_risk:
            violators = df.filter(pl.col("termination_risk") == "NO AUTO-TERMINATE")
        else:
            violators = df.filter(pl.col("auto_termination_minutes").is_null())
        if violators.is_empty():
            return []
        ids = (
            violators["cluster_id"].to_list()
            if "cluster_id" in df.columns
            else [f"row_{i}" for i in range(len(violators))]
        )
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} clusters without auto-termination.",
                evidence_query_id=query_id,
                threshold="auto_termination_minutes IS NULL or termination_risk=='NO AUTO-TERMINATE'",
                actual_value=f"{len(violators)} clusters",
                affected_entities=tuple(str(x) for x in ids),
            )
        ]


@dataclass(frozen=True)
class CMP006SqlWarehouseQueuePressure:
    """CMP-006: SQL Warehouse Queue Pressure."""

    rule_id: str = "CMP-006"
    domain: str = "compute"
    name: str = "SQL Warehouse Queue Pressure"
    description: str = "Warehouses with avg_queue_secs > 30"
    severity: Severity = "HIGH"
    dimension: Dimension = "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-C03"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "avg_queue_secs" not in df.columns:
            return []
        violators = df.filter(pl.col("avg_queue_secs") > 30)
        if violators.is_empty():
            return []
        ids = (
            violators["warehouse_id"].to_list()
            if "warehouse_id" in df.columns
            else [f"row_{i}" for i in range(len(violators))]
        )
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} warehouse-hour buckets exceed 30s queue.",
                evidence_query_id=query_id,
                threshold="avg_queue_secs > 30",
                actual_value=f"max avg_queue_secs={violators['avg_queue_secs'].max()!r}",
                affected_entities=tuple(str(x) for x in ids),
            )
        ]


COMPUTE_RULES: tuple[
    CMP001ExcessiveAutoTermination,
    CMP002HighIdlePercentage,
    CMP003NoAutoScalingOnInteractive,
    CMP004OverProvisionedClusters,
    CMP005MissingAutoTermination,
    CMP006SqlWarehouseQueuePressure,
] = (
    CMP001ExcessiveAutoTermination(),
    CMP002HighIdlePercentage(),
    CMP003NoAutoScalingOnInteractive(),
    CMP004OverProvisionedClusters(),
    CMP005MissingAutoTermination(),
    CMP006SqlWarehouseQueuePressure(),
)
