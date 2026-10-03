# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Governance and data management heuristic rules."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from starboard.discovery.heuristics.base import (
    Dimension,
    HeuristicFinding,
    Severity,
)


@dataclass(frozen=True)
class GOV001PermissionSprawl:
    """GOV-001: Permission Sprawl."""

    rule_id: str = "GOV-001"
    domain: str = "governance"
    name: str = "Permission Sprawl"
    description: str = "Tables with grantee_count > 100"
    severity: Severity = "HIGH"
    dimension: Dimension = "governance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "N-L03"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "grantee_count" not in df.columns:
            return []
        violators = df.filter(pl.col("grantee_count") > 100)
        if violators.is_empty():
            return []
        names: list[str] = []
        for row in violators.iter_rows(named=True):
            if "table" in row and "schema" in row and "catalog" in row:
                n = f"{row.get('catalog', '')}.{row.get('schema', '')}.{row.get('table', '')}"
            elif "table_name" in row:
                n = str(row["table_name"])
            else:
                n = str(row.get("table", row.get("name", "unknown")))
            names.append(n)
        if not names:
            names = [f"row_{i}" for i in range(len(violators))]
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} tables exceed 100 grantees.",
                evidence_query_id=query_id,
                threshold="grantee_count > 100",
                actual_value=f"max grantee_count={violators['grantee_count'].max()!r}",
                affected_entities=tuple(names),
            )
        ]


@dataclass(frozen=True)
class GOV002MissingLineage:
    """GOV-002: Missing Lineage."""

    rule_id: str = "GOV-002"
    domain: str = "governance"
    name: str = "Missing Lineage"
    description: str = "Few lineage entries relative to expected"
    severity: Severity = "MEDIUM"
    dimension: Dimension = "governance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "N-L01"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.height >= 10:
            return []
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"Only {df.height} lineage entries found; potential lineage gap.",
                evidence_query_id=query_id,
                threshold="< 10 lineage entries",
                actual_value=f"{df.height} entries",
                affected_entities=(),
            )
        ]


@dataclass(frozen=True)
class GOV003StaleTables:
    """GOV-003: Stale Tables."""

    rule_id: str = "GOV-003"
    domain: str = "governance"
    name: str = "Stale Tables"
    description: str = "Tables with days_since_modified > 90"
    severity: Severity = "LOW"
    dimension: Dimension = "governance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "N-DT01"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "days_since_modified" not in df.columns:
            return []
        violators = df.filter(pl.col("days_since_modified") > 90)
        if violators.is_empty():
            return []
        names: list[str] = []
        for row in violators.iter_rows(named=True):
            if "table_name" in row:
                names.append(str(row["table_name"]))
            elif "table" in row and "schema" in row and "catalog" in row:
                names.append(
                    f"{row.get('catalog', '')}.{row.get('schema', '')}.{row.get('table', '')}"
                )
            else:
                names.append(str(row.get("table", row.get("name", "unknown"))))
        if not names:
            names = [f"row_{i}" for i in range(len(violators))]
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} tables stale (>90 days).",
                evidence_query_id=query_id,
                threshold="days_since_modified > 90",
                actual_value=f"max days={violators['days_since_modified'].max()!r}",
                affected_entities=tuple(names),
            )
        ]


@dataclass(frozen=True)
class GOV004BroadWriteAccess:
    """GOV-004: Broad Write Access."""

    rule_id: str = "GOV-004"
    domain: str = "governance"
    name: str = "Broad Write Access"
    description: str = "Tables with MODIFY/ALL and grantee_count > 5"
    severity: Severity = "HIGH"
    dimension: Dimension = "governance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "N-L03"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        required = {"privilege_type", "grantee_count"}
        if not required.issubset(df.columns):
            return []
        violators = df.filter(
            (pl.col("privilege_type").is_in(["MODIFY", "ALL PRIVILEGES"]))
            & (pl.col("grantee_count") > 5)
        )
        if violators.is_empty():
            return []
        names: list[str] = []
        for row in violators.iter_rows(named=True):
            if "table_name" in row:
                names.append(str(row["table_name"]))
            elif "table" in row and "schema" in row and "catalog" in row:
                names.append(
                    f"{row.get('catalog', '')}.{row.get('schema', '')}.{row.get('table', '')}"
                )
            else:
                names.append(str(row.get("table", row.get("name", "unknown"))))
        if not names:
            names = [f"row_{i}" for i in range(len(violators))]
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} tables with broad MODIFY/ALL grants.",
                evidence_query_id=query_id,
                threshold="privilege_type IN ('MODIFY','ALL PRIVILEGES') AND grantee_count > 5",
                actual_value=f"{len(violators)} tables",
                affected_entities=tuple(names),
            )
        ]


@dataclass(frozen=True)
class GOV005DeltaTableHealth:
    """GOV-005: Delta Table Health."""

    rule_id: str = "GOV-005"
    domain: str = "governance"
    name: str = "Delta Table Health"
    description: str = "Stale Delta tables (freshness_status == 'Stale (>30d)')"
    severity: Severity = "MEDIUM"
    dimension: Dimension = "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        query_id = "N-DT01"
        if query_id not in results:
            return []
        df = results[query_id]
        if df.is_empty():
            return []
        if "freshness_status" not in df.columns:
            return []
        violators = df.filter(pl.col("freshness_status") == "Stale (>30d)")
        if "table_format" in df.columns or "format" in df.columns:
            fmt_col = "table_format" if "table_format" in df.columns else "format"
            violators = violators.filter(
                pl.col(fmt_col).str.to_lowercase().str.contains("delta")
            )
        if violators.is_empty():
            return []
        names: list[str] = []
        for row in violators.iter_rows(named=True):
            if "table_name" in row:
                names.append(str(row["table_name"]))
            elif "table" in row and "schema" in row and "catalog" in row:
                names.append(
                    f"{row.get('catalog', '')}.{row.get('schema', '')}.{row.get('table', '')}"
                )
            else:
                names.append(str(row.get("table", row.get("name", "unknown"))))
        if not names:
            names = [f"row_{i}" for i in range(len(violators))]
        return [
            HeuristicFinding(
                rule_id=self.rule_id,
                domain=self.domain,
                title=self.name,
                severity=self.severity,
                dimension=self.dimension,
                description=f"{len(violators)} Delta tables stale >30d.",
                evidence_query_id=query_id,
                threshold="freshness_status=='Stale (>30d)' AND Delta format",
                actual_value=f"{len(violators)} tables",
                affected_entities=tuple(names),
            )
        ]


GOVERNANCE_RULES: tuple[
    GOV001PermissionSprawl,
    GOV002MissingLineage,
    GOV003StaleTables,
    GOV004BroadWriteAccess,
    GOV005DeltaTableHealth,
] = (
    GOV001PermissionSprawl(),
    GOV002MissingLineage(),
    GOV003StaleTables(),
    GOV004BroadWriteAccess(),
    GOV005DeltaTableHealth(),
)
