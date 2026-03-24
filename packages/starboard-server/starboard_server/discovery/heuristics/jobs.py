"""Job workload heuristic rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import polars as pl

from starboard_server.discovery.heuristics.base import (
    Dimension,
    HeuristicFinding,
    Severity,
    get_col,
    get_df,
)


@dataclass(frozen=True)
class JOB001HighFailureRate:
    """JOB-001: High Failure Rate — failure rate >10% over lookback period."""

    @property
    def rule_id(self) -> str:
        return "JOB-001"

    @property
    def domain(self) -> str:
        return "jobs"

    @property
    def name(self) -> str:
        return "High Failure Rate"

    @property
    def description(self) -> str:
        return "Failure rate >10% over lookback period"

    @property
    def severity(self) -> Severity:
        return "CRITICAL"

    @property
    def dimension(self) -> Dimension:
        return "reliability"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-J04")
        if df is None:
            return []

        rate_col = get_col(df, "failure_rate_pct")
        if rate_col is None:
            return []

        breachers = df.filter(rate_col > 10)
        if breachers.is_empty():
            return []

        entity_col = (
            "job_id"
            if "job_id" in df.columns
            else (df.columns[0] if df.columns else "")
        )
        if entity_col and entity_col in breachers.columns:
            entities = tuple(
                str(v)
                for v in breachers.get_column(entity_col).unique().to_list()
                if v is not None
            )
        else:
            entities = ()

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="Jobs with failure rate >10%",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-J04",
                threshold="failure_rate_pct > 10%",
                actual_value=f"{len(entities)} job(s) exceeding threshold",
                affected_entities=entities,
            )
        ]


@dataclass(frozen=True)
class JOB002ExcessiveRetryRatio:
    """JOB-002: Excessive Retry Ratio — retry ratio >20%."""

    @property
    def rule_id(self) -> str:
        return "JOB-002"

    @property
    def domain(self) -> str:
        return "jobs"

    @property
    def name(self) -> str:
        return "Excessive Retry Ratio"

    @property
    def description(self) -> str:
        return "Retry ratio >20% (retried_runs / total_runs)"

    @property
    def severity(self) -> Severity:
        return "HIGH"

    @property
    def dimension(self) -> Dimension:
        return "reliability"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-J04")
        if df is None:
            return []

        if "retried_runs" not in df.columns or "total_runs" not in df.columns:
            return []

        df_valid = df.filter(pl.col("total_runs") > 0)
        if df_valid.is_empty():
            return []

        ratio_expr = (
            (pl.col("retried_runs") / pl.col("total_runs")).fill_nan(0).fill_null(0)
        )
        breachers = df_valid.with_columns(ratio_expr.alias("_ratio")).filter(
            pl.col("_ratio") > 0.2
        )
        if breachers.is_empty():
            return []

        entity_col = (
            "job_id"
            if "job_id" in df.columns
            else (df.columns[0] if df.columns else "")
        )
        if entity_col and entity_col in breachers.columns:
            entities = tuple(
                str(v)
                for v in breachers.get_column(entity_col).unique().to_list()
                if v is not None
            )
        else:
            entities = ()

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="Jobs with retry ratio >20%",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-J04",
                threshold="retried_runs / total_runs > 20%",
                actual_value=f"{len(entities)} job(s) exceeding threshold",
                affected_entities=entities,
            )
        ]


@dataclass(frozen=True)
class JOB003RuntimeVariance:
    """JOB-003: Runtime Variance — CV >0.5 (stddev/avg)."""

    @property
    def rule_id(self) -> str:
        return "JOB-003"

    @property
    def domain(self) -> str:
        return "jobs"

    @property
    def name(self) -> str:
        return "Runtime Variance"

    @property
    def description(self) -> str:
        return "CV >0.5 (stddev/avg runtime)"

    @property
    def severity(self) -> Severity:
        return "MEDIUM"

    @property
    def dimension(self) -> Dimension:
        return "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-J03")
        if df is None:
            return []

        if (
            "stddev_runtime_mins" not in df.columns
            or "avg_runtime_mins" not in df.columns
        ):
            return []

        df_valid = df.filter(pl.col("avg_runtime_mins") > 0)
        if df_valid.is_empty():
            return []

        cv_expr = (
            (pl.col("stddev_runtime_mins") / pl.col("avg_runtime_mins"))
            .fill_nan(0)
            .fill_null(0)
        )
        breachers = df_valid.with_columns(cv_expr.alias("_cv")).filter(
            pl.col("_cv") > 0.5
        )
        if breachers.is_empty():
            return []

        entity_col = (
            "job_id"
            if "job_id" in df_valid.columns
            else (df_valid.columns[0] if df_valid.columns else "")
        )
        if entity_col and entity_col in breachers.columns:
            entities = tuple(
                str(v)
                for v in breachers.get_column(entity_col).unique().to_list()
                if v is not None
            )
        else:
            entities = ()

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="Jobs with runtime CV >0.5",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-J03",
                threshold="stddev_runtime_mins / avg_runtime_mins > 0.5",
                actual_value=f"{len(entities)} job(s) exceeding threshold",
                affected_entities=entities,
            )
        ]


@dataclass(frozen=True)
class JOB004DBUPerMinuteOutliers:
    """JOB-004: DBU-per-Minute Outliers — any job's DBU/min >3x the median."""

    @property
    def rule_id(self) -> str:
        return "JOB-004"

    @property
    def domain(self) -> str:
        return "jobs"

    @property
    def name(self) -> str:
        return "DBU-per-Minute Outliers"

    @property
    def description(self) -> str:
        return "Any job's DBU/min >3x the median across all jobs"

    @property
    def severity(self) -> Severity:
        return "MEDIUM"

    @property
    def dimension(self) -> Dimension:
        return "consumption"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-J03")
        if df is None:
            return []

        dbu_col = get_col(df, "avg_dbus_per_minute")
        if dbu_col is None:
            return []

        median_val = dbu_col.median()
        if median_val is None:
            return []
        median_f = float(cast(Any, median_val))
        if median_f <= 0:
            return []

        threshold = 3 * median_f
        breachers = df.filter(dbu_col > threshold)
        if breachers.is_empty():
            return []

        entity_col = (
            "job_id"
            if "job_id" in df.columns
            else (df.columns[0] if df.columns else "")
        )
        if entity_col and entity_col in breachers.columns:
            entities = tuple(
                str(v)
                for v in breachers.get_column(entity_col).unique().to_list()
                if v is not None
            )
        else:
            entities = ()

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="Jobs with DBU/min >3x median",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-J03",
                threshold=f"avg_dbus_per_minute > 3 * median ({threshold:.2f})",
                actual_value=f"{len(entities)} job(s) exceeding threshold",
                affected_entities=entities,
            )
        ]


@dataclass(frozen=True)
class JOB005DailyFailureRateSpike:
    """JOB-005: Daily Failure Rate Spike — any single day with failure rate >25%."""

    @property
    def rule_id(self) -> str:
        return "JOB-005"

    @property
    def domain(self) -> str:
        return "jobs"

    @property
    def name(self) -> str:
        return "Daily Failure Rate Spike"

    @property
    def description(self) -> str:
        return "Any single day with failure rate >25%"

    @property
    def severity(self) -> Severity:
        return "HIGH"

    @property
    def dimension(self) -> Dimension:
        return "reliability"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-J05")
        if df is None:
            return []

        rate_col = get_col(df, "failure_rate_pct")
        if rate_col is None:
            return []

        breachers = df.filter(rate_col > 25)
        if breachers.is_empty():
            return []

        entity_cols = ["job_id", "run_date", "date"]
        entity_col = next(
            (c for c in entity_cols if c in df.columns),
            df.columns[0] if df.columns else "",
        )
        if entity_col and entity_col in breachers.columns:
            entities = tuple(
                str(v)
                for v in breachers.get_column(entity_col).unique().to_list()
                if v is not None
            )
        else:
            entities = ()

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="Days with failure rate >25%",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-J05",
                threshold="failure_rate_pct > 25%",
                actual_value=f"{len(entities)} day(s)/job(s) exceeding threshold",
                affected_entities=entities,
            )
        ]


@dataclass(frozen=True)
class JOB006TaskLevelFailureConcentration:
    """JOB-006: Task-Level Failure Concentration — any task type >50% of all task failures."""

    @property
    def rule_id(self) -> str:
        return "JOB-006"

    @property
    def domain(self) -> str:
        return "jobs"

    @property
    def name(self) -> str:
        return "Task-Level Failure Concentration"

    @property
    def description(self) -> str:
        return "Any single task type >50% of all task failures"

    @property
    def severity(self) -> Severity:
        return "MEDIUM"

    @property
    def dimension(self) -> Dimension:
        return "reliability"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-J06")
        if df is None:
            return []

        failures_col = get_col(df, "failures")
        if failures_col is None:
            return []

        total_failures = failures_col.sum()
        if total_failures is None or float(total_failures) <= 0:
            return []

        total = float(total_failures)
        task_col = (
            "task_type"
            if "task_type" in df.columns
            else (df.columns[0] if df.columns else "")
        )
        if not task_col or task_col not in df.columns:
            return []

        agg = df.group_by(task_col).agg(pl.col("failures").sum().alias("_failures"))
        concentrated = agg.filter(pl.col("_failures") > 0.5 * total)
        if concentrated.is_empty():
            return []

        entities = tuple(
            str(v) for v in concentrated.get_column(task_col).to_list() if v is not None
        )

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="Task types with >50% of failures",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-J06",
                threshold="single task type failures > 50% of total",
                actual_value=f"{len(entities)} task type(s) concentrated",
                affected_entities=entities,
            )
        ]


@dataclass(frozen=True)
class JOB007DLTPipelineDegradation:
    """JOB-007: DLT Pipeline Degradation — failure rate >15%."""

    @property
    def rule_id(self) -> str:
        return "JOB-007"

    @property
    def domain(self) -> str:
        return "jobs"

    @property
    def name(self) -> str:
        return "DLT Pipeline Degradation"

    @property
    def description(self) -> str:
        return "DLT pipeline failure rate >15%"

    @property
    def severity(self) -> Severity:
        return "HIGH"

    @property
    def dimension(self) -> Dimension:
        return "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-J07")
        if df is None:
            return []

        rate_col = get_col(df, "failure_rate_pct")
        if rate_col is None:
            return []

        breachers = df.filter(rate_col > 15)
        if breachers.is_empty():
            return []

        entity_col = next(
            (c for c in ["pipeline_name", "pipeline_id", "name"] if c in df.columns),
            df.columns[0] if df.columns else "",
        )
        if entity_col and entity_col in breachers.columns:
            entities = tuple(
                str(v)
                for v in breachers.get_column(entity_col).unique().to_list()
                if v is not None
            )
        else:
            entities = ()

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="DLT pipelines with failure rate >15%",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-J07",
                threshold="failure_rate_pct > 15%",
                actual_value=f"{len(entities)} pipeline(s) exceeding threshold",
                affected_entities=entities,
            )
        ]


JOB_RULES: tuple[
    JOB001HighFailureRate,
    JOB002ExcessiveRetryRatio,
    JOB003RuntimeVariance,
    JOB004DBUPerMinuteOutliers,
    JOB005DailyFailureRateSpike,
    JOB006TaskLevelFailureConcentration,
    JOB007DLTPipelineDegradation,
] = (
    JOB001HighFailureRate(),
    JOB002ExcessiveRetryRatio(),
    JOB003RuntimeVariance(),
    JOB004DBUPerMinuteOutliers(),
    JOB005DailyFailureRateSpike(),
    JOB006TaskLevelFailureConcentration(),
    JOB007DLTPipelineDegradation(),
)
