# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Query performance heuristic rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import polars as pl

from starboard.discovery.heuristics.base import (
    Dimension,
    HeuristicFinding,
    Severity,
)


def _take_ids(df: pl.DataFrame, id_col: str, limit: int) -> tuple[str, ...]:
    if id_col not in df.columns:
        return tuple(f"row_{i}" for i in range(min(limit, len(df))))
    vals = df[id_col].head(limit).to_list()
    return tuple(str(x) for x in vals)


@dataclass(frozen=True)
class QPF001ExcessiveSpill:
    """QPF-001: Excessive Spill."""

    rule_id: str = "QPF-001"
    domain: str = "query_perf"
    name: str = "Excessive Spill"
    description: str = "Queries with spill_gb > 1.0"
    severity: Severity = "HIGH"
    dimension: Dimension = "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-Q02"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "spill_gb" not in df.columns:
            return []
        violators = df.filter(pl.col("spill_gb") > 1.0)
        if violators.is_empty():
            return []
        ids = _take_ids(violators, "statement_id", 10)
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} queries exceed 1.0 GB spill.",
                evidence_query_id=query_id,
                threshold="spill_gb > 1.0",
                actual_value=f"max spill_gb={violators['spill_gb'].max()!r}",
                affected_entities=ids,
            )
        ]


@dataclass(frozen=True)
class QPF002DataSkew:
    """QPF-002: Data Skew."""

    rule_id: str = "QPF-002"
    domain: str = "query_perf"
    name: str = "Data Skew"
    description: str = "Queries with task_to_exec_ratio > 10"
    severity: Severity = "HIGH"
    dimension: Dimension = "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-Q02"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "task_to_exec_ratio" not in df.columns:
            return []
        violators = df.filter(pl.col("task_to_exec_ratio") > 10)
        if violators.is_empty():
            return []
        ids = _take_ids(violators, "statement_id", 10)
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} queries show skew (task_to_exec_ratio > 10).",
                evidence_query_id=query_id,
                threshold="task_to_exec_ratio > 10",
                actual_value=f"max ratio={violators['task_to_exec_ratio'].max()!r}",
                affected_entities=ids,
            )
        ]


@dataclass(frozen=True)
class QPF003RepeatedQueryRate:
    """QPF-003: Repeated Query Rate."""

    rule_id: str = "QPF-003"
    domain: str = "query_perf"
    name: str = "Repeated Query Rate"
    description: str = ">20% of queries are duplicates"
    severity: Severity = "MEDIUM"
    dimension: Dimension = "consumption"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-Q03"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "execution_count" not in df.columns:
            return []
        total = df["execution_count"].sum()
        if total is None or total == 0:
            return []
        dup_rows = df.filter(pl.col("execution_count") >= 5)
        dup_sum = dup_rows["execution_count"].sum()
        if dup_sum is None:
            dup_sum = 0
        ratio = float(dup_sum) / float(total)
        if ratio <= 0.2:
            return []
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{ratio:.1%} of query volume from repeated queries (exec_count>=5).",
                evidence_query_id=query_id,
                threshold=">20% duplicate rate",
                actual_value=f"{ratio:.1%}",
                affected_entities=(),
            )
        ]


@dataclass(frozen=True)
class QPF004LowCacheHitRate:
    """QPF-004: Low Cache Hit Rate."""

    rule_id: str = "QPF-004"
    domain: str = "query_perf"
    name: str = "Low Cache Hit Rate"
    description: str = "Average cache_hit_pct < 20"
    severity: Severity = "MEDIUM"
    dimension: Dimension = "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-Q03"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "cache_hit_pct" not in df.columns:
            return []
        if "execution_count" in df.columns:
            total_weight = df["execution_count"].sum()
            if total_weight is not None and total_weight > 0:
                weighted_sum = (df["cache_hit_pct"] * df["execution_count"]).sum()
                if weighted_sum is not None:
                    avg = float(weighted_sum) / float(total_weight)
                else:
                    mean_raw = df["cache_hit_pct"].mean()
                    avg = float(cast(Any, mean_raw)) if mean_raw is not None else 0.0
            else:
                mean_raw = df["cache_hit_pct"].mean()
                avg = float(cast(Any, mean_raw)) if mean_raw is not None else 0.0
        else:
            mean_raw = df["cache_hit_pct"].mean()
            avg = float(cast(Any, mean_raw)) if mean_raw is not None else 0.0
        if avg is None or avg >= 20:
            return []
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"Weighted avg cache_hit_pct={avg:.1f}%.",
                evidence_query_id=query_id,
                threshold="cache_hit_pct < 20",
                actual_value=f"{avg:.1f}%",
                affected_entities=(),
            )
        ]


@dataclass(frozen=True)
class QPF005P95LatencyOutliers:
    """QPF-005: P95 Latency Outliers."""

    rule_id: str = "QPF-005"
    domain: str = "query_perf"
    name: str = "P95 Latency Outliers"
    description: str = "p95 > 10x median (p50)"
    severity: Severity = "MEDIUM"
    dimension: Dimension = "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-Q01"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        required = {"p95_total_secs", "p50_total_secs"}
        if not required.issubset(df.columns):
            return []
        violators = df.filter(
            (pl.col("p50_total_secs") > 0)
            & (pl.col("p95_total_secs") / pl.col("p50_total_secs") > 10)
        )
        if violators.is_empty():
            return []
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} query patterns have p95 > 10x p50.",
                evidence_query_id=query_id,
                threshold="p95/p50 > 10",
                actual_value=f"{len(violators)} patterns",
                affected_entities=(),
            )
        ]


@dataclass(frozen=True)
class QPF006HighErrorRate:
    """QPF-006: High Error Rate."""

    rule_id: str = "QPF-006"
    domain: str = "query_perf"
    name: str = "High Error Rate"
    description: str = "Total errors > 5% of query volume"
    severity: Severity = "HIGH"
    dimension: Dimension = "reliability"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        q04_id = "C-Q04"
        q01_id = "C-Q01"
        if q04_id not in results or q01_id not in results:
            return []
        df_err = results[q04_id]
        df_vol = results[q01_id]
        if df_err.is_empty():
            return []
        occ_col = "occurrences" if "occurrences" in df_err.columns else None
        if occ_col is None:
            for c in ("count", "error_count", "total"):
                if c in df_err.columns:
                    occ_col = c
                    break
        if occ_col is None:
            return []
        total_errors = df_err[occ_col].sum()
        if total_errors is None or total_errors == 0:
            return []
        total_queries = 0
        if not df_vol.is_empty():
            if "total_queries" in df_vol.columns:
                total_queries = int(df_vol["total_queries"].sum() or 0)
            elif "execution_count" in df_vol.columns:
                total_queries = int(df_vol["execution_count"].sum() or 0)
            elif "query_count" in df_vol.columns:
                total_queries = int(df_vol["query_count"].sum() or 0)
        if total_queries == 0:
            return []
        rate = total_errors / total_queries
        if rate <= 0.05:
            return []
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"Error rate {rate:.1%} exceeds 5%.",
                evidence_query_id=q04_id,
                threshold="errors > 5% of query volume",
                actual_value=f"{rate:.1%} ({total_errors} errors / {total_queries} queries)",
                affected_entities=(),
            )
        ]


@dataclass(frozen=True)
class QPF007ConcurrencySaturation:
    """QPF-007: Concurrency Saturation."""

    rule_id: str = "QPF-007"
    domain: str = "query_perf"
    name: str = "Concurrency Saturation"
    description: str = "queries_queued_30s_plus > 10% of concurrent"
    severity: Severity = "HIGH"
    dimension: Dimension = "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "C-Q05"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        required = {"queries_queued_30s_plus", "concurrent_queries"}
        if not required.issubset(df.columns):
            return []
        violators = df.filter(
            (pl.col("concurrent_queries") > 0)
            & (pl.col("queries_queued_30s_plus") / pl.col("concurrent_queries") > 0.1)
        )
        if violators.is_empty():
            return []
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} periods with >10% queue pressure.",
                evidence_query_id=query_id,
                threshold="queries_queued_30s_plus / concurrent_queries > 0.1",
                actual_value=f"{len(violators)} periods",
                affected_entities=(),
            )
        ]


QUERY_PERF_RULES: tuple[
    QPF001ExcessiveSpill,
    QPF002DataSkew,
    QPF003RepeatedQueryRate,
    QPF004LowCacheHitRate,
    QPF005P95LatencyOutliers,
    QPF006HighErrorRate,
    QPF007ConcurrencySaturation,
] = (
    QPF001ExcessiveSpill(),
    QPF002DataSkew(),
    QPF003RepeatedQueryRate(),
    QPF004LowCacheHitRate(),
    QPF005P95LatencyOutliers(),
    QPF006HighErrorRate(),
    QPF007ConcurrencySaturation(),
)
