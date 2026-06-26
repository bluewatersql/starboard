# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Billing and resource consumption heuristic rules."""

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
class BIL001DBUConcentration:
    """BIL-001: DBU Concentration — any single job/identity consuming >50% of total DBUs."""

    @property
    def rule_id(self) -> str:
        return "BIL-001"

    @property
    def domain(self) -> str:
        return "billing"

    @property
    def name(self) -> str:
        return "DBU Concentration"

    @property
    def description(self) -> str:
        return "Any single job or identity consuming >50% of total DBUs"

    @property
    def severity(self) -> Severity:
        return "HIGH"

    @property
    def dimension(self) -> Dimension:
        return "consumption"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-B01")
        if df is None:
            return []

        dbus_col = get_col(df, "dbus_consumed")
        if dbus_col is None:
            return []

        total = dbus_col.sum()
        if total is None or float(total) <= 0:
            return []

        max_val = dbus_col.max()
        if max_val is None:
            return []
        total_f = float(cast(Any, total))
        max_f = float(cast(Any, max_val))
        if max_f / total_f <= 0.5:
            return []

        entity_col = "run_as" if "run_as" in df.columns else "job_id"
        if entity_col not in df.columns and df.columns:
            entity_col = df.columns[0]

        top_rows = df.filter(df.get_column("dbus_consumed") == max_val)
        if entity_col in df.columns:
            entities = tuple(
                str(v)
                for v in top_rows.get_column(entity_col).unique().to_list()
                if v is not None
            )
        else:
            entities = ()

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="Single entity consumes >50% of total DBUs",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-B01",
                threshold="max entity DBUs / total DBUs > 50%",
                actual_value=f"{100.0 * max_f / total_f:.1f}%",
                affected_entities=entities,
            )
        ]


@dataclass(frozen=True)
class BIL002WeekOverWeekDBUGrowth:
    """BIL-002: Week-over-Week DBU Growth — WoW DBU growth >25% for any single job."""

    @property
    def rule_id(self) -> str:
        return "BIL-002"

    @property
    def domain(self) -> str:
        return "billing"

    @property
    def name(self) -> str:
        return "Week-over-Week DBU Growth"

    @property
    def description(self) -> str:
        return "WoW DBU growth >25% for any single job"

    @property
    def severity(self) -> Severity:
        return "MEDIUM"

    @property
    def dimension(self) -> Dimension:
        return "consumption"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-B03")
        if df is None:
            return []

        wow_col = get_col(df, "wow_growth_pct")
        if wow_col is None:
            return []

        breachers = df.filter(wow_col > 25)
        if breachers.is_empty():
            return []

        entity_col = "job_name" if "job_name" in df.columns else "job_id"
        if entity_col not in df.columns and df.columns:
            entity_col = df.columns[0]

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
                title="Jobs with WoW DBU growth >25%",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-B03",
                threshold="wow_growth_pct > 25%",
                actual_value=f"{len(entities)} job(s) exceeding threshold",
                affected_entities=entities,
            )
        ]


@dataclass(frozen=True)
class BIL003UntaggedConsumption:
    """BIL-003: Untagged Consumption — >30% of DBUs have no team/project/cost_center tag."""

    @property
    def rule_id(self) -> str:
        return "BIL-003"

    @property
    def domain(self) -> str:
        return "billing"

    @property
    def name(self) -> str:
        return "Untagged Consumption"

    @property
    def description(self) -> str:
        return ">30% of DBUs have no team/project/cost_center tag"

    @property
    def severity(self) -> Severity:
        return "MEDIUM"

    @property
    def dimension(self) -> Dimension:
        return "governance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-B04")
        if df is None:
            return []

        untagged_col = get_col(df, "untagged_dbus")
        dbus_col = get_col(df, "dbus")
        if untagged_col is None or dbus_col is None:
            return []

        total_untagged = untagged_col.sum()
        total_dbus = dbus_col.sum()
        if total_dbus <= 0:
            return []

        ratio = float(total_untagged) / float(total_dbus)
        if ratio <= 0.3:
            return []

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=">30% of DBUs untagged",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-B04",
                threshold="sum(untagged_dbus) / sum(dbus) > 30%",
                actual_value=f"{100 * ratio:.1f}%",
                affected_entities=(),
            )
        ]


@dataclass(frozen=True)
class BIL004UnattributedIdentity:
    """BIL-004: Unattributed Identity — >20% of DBUs attributed to Unattributed user_type."""

    @property
    def rule_id(self) -> str:
        return "BIL-004"

    @property
    def domain(self) -> str:
        return "billing"

    @property
    def name(self) -> str:
        return "Unattributed Identity"

    @property
    def description(self) -> str:
        return ">20% of DBUs attributed to Unattributed user_type"

    @property
    def severity(self) -> Severity:
        return "MEDIUM"

    @property
    def dimension(self) -> Dimension:
        return "governance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-B01")
        if df is None:
            return []

        if "user_type" not in df.columns or "dbus_consumed" not in df.columns:
            return []

        total = df.get_column("dbus_consumed").sum()
        if total <= 0:
            return []

        unattributed_df = df.filter(pl.col("user_type") == "Unattributed")
        unattributed_dbus = unattributed_df.get_column("dbus_consumed").sum()
        ratio = float(unattributed_dbus) / float(total)
        if ratio <= 0.2:
            return []

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=">20% of DBUs unattributed",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-B01",
                threshold="sum(Unattributed DBUs) / total DBUs > 20%",
                actual_value=f"{100 * ratio:.1f}%",
                affected_entities=(),
            )
        ]


@dataclass(frozen=True)
class BIL005ServerlessAdoptionGap:
    """BIL-005: Serverless Adoption Gap — <10% of eligible workloads using serverless."""

    @property
    def rule_id(self) -> str:
        return "BIL-005"

    @property
    def domain(self) -> str:
        return "billing"

    @property
    def name(self) -> str:
        return "Serverless Adoption Gap"

    @property
    def description(self) -> str:
        return "<10% of eligible workloads using serverless"

    @property
    def severity(self) -> Severity:
        return "LOW"

    @property
    def dimension(self) -> Dimension:
        return "configuration"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        df = get_df(results, "C-B01")
        if df is None:
            return []

        if "is_serverless" not in df.columns or "dbus_consumed" not in df.columns:
            return []

        total = df.get_column("dbus_consumed").sum()
        if total <= 0:
            return []

        serverless_df = df.filter(pl.col("is_serverless") == True)  # noqa: E712
        serverless_dbus = serverless_df.get_column("dbus_consumed").sum()
        ratio = float(serverless_dbus) / float(total)
        if ratio >= 0.1:
            return []

        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title="<10% of DBUs from serverless",
                severity=self.severity,
                dimension=self.dimension,
                description=self.description,
                evidence_query_id="C-B01",
                threshold="serverless DBUs / total DBUs >= 10%",
                actual_value=f"{100 * ratio:.1f}%",
                affected_entities=(),
            )
        ]


BILLING_RULES: tuple[
    BIL001DBUConcentration,
    BIL002WeekOverWeekDBUGrowth,
    BIL003UntaggedConsumption,
    BIL004UnattributedIdentity,
    BIL005ServerlessAdoptionGap,
] = (
    BIL001DBUConcentration(),
    BIL002WeekOverWeekDBUGrowth(),
    BIL003UntaggedConsumption(),
    BIL004UnattributedIdentity(),
    BIL005ServerlessAdoptionGap(),
)
