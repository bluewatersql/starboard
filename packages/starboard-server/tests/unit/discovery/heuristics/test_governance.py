"""Tests for governance heuristic rules."""

from __future__ import annotations

import polars as pl
from starboard_server.discovery.heuristics.governance import (
    GOVERNANCE_RULES,
    GOV001PermissionSprawl,
    GOV002MissingLineage,
    GOV003StaleTables,
    GOV004BroadWriteAccess,
    GOV005DeltaTableHealth,
)


class TestGOV001PermissionSprawl:
    def test_threshold_breach_returns_finding(self):
        rule = GOV001PermissionSprawl()
        df = pl.DataFrame(
            {
                "catalog": ["main", "main"],
                "schema": ["foo", "bar"],
                "table": ["t1", "t2"],
                "grantee_count": [50, 150],
            }
        )
        findings = rule.evaluate({"N-L03": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "GOV-001"
        assert "main.bar.t2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = GOV001PermissionSprawl()
        df = pl.DataFrame(
            {
                "table_name": ["t1"],
                "grantee_count": [80],
            }
        )
        assert rule.evaluate({"N-L03": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = GOV001PermissionSprawl()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"N-L03": pl.DataFrame()}) == []
        df = pl.DataFrame({"table_name": ["t1"]})
        assert rule.evaluate({"N-L03": df}) == []


class TestGOV002MissingLineage:
    def test_threshold_breach_returns_finding(self):
        rule = GOV002MissingLineage()
        df = pl.DataFrame({"col": list(range(5))})
        findings = rule.evaluate({"N-L01": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "GOV-002"
        assert "5" in findings[0].actual_value

    def test_below_threshold_returns_empty(self):
        rule = GOV002MissingLineage()
        df = pl.DataFrame({"col": list(range(15))})
        assert rule.evaluate({"N-L01": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = GOV002MissingLineage()
        assert rule.evaluate({}) == []
        df = pl.DataFrame()
        findings = rule.evaluate({"N-L01": df})
        assert len(findings) == 1
        assert "0" in findings[0].actual_value


class TestGOV003StaleTables:
    def test_threshold_breach_returns_finding(self):
        rule = GOV003StaleTables()
        df = pl.DataFrame(
            {
                "table_name": ["t1", "t2"],
                "days_since_modified": [30, 120],
            }
        )
        findings = rule.evaluate({"N-DT01": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "GOV-003"
        assert "t2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = GOV003StaleTables()
        df = pl.DataFrame(
            {
                "table_name": ["t1"],
                "days_since_modified": [60],
            }
        )
        assert rule.evaluate({"N-DT01": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = GOV003StaleTables()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"N-DT01": pl.DataFrame()}) == []
        df = pl.DataFrame({"table_name": ["t1"]})
        assert rule.evaluate({"N-DT01": df}) == []


class TestGOV004BroadWriteAccess:
    def test_threshold_breach_returns_finding(self):
        rule = GOV004BroadWriteAccess()
        df = pl.DataFrame(
            {
                "table_name": ["t1", "t2"],
                "privilege_type": ["SELECT", "MODIFY"],
                "grantee_count": [3, 10],
            }
        )
        findings = rule.evaluate({"N-L03": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "GOV-004"
        assert "t2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = GOV004BroadWriteAccess()
        df = pl.DataFrame(
            {
                "table_name": ["t1"],
                "privilege_type": ["MODIFY"],
                "grantee_count": [3],
            }
        )
        assert rule.evaluate({"N-L03": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = GOV004BroadWriteAccess()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"N-L03": pl.DataFrame()}) == []
        df = pl.DataFrame({"table_name": ["t1"]})
        assert rule.evaluate({"N-L03": df}) == []


class TestGOV005DeltaTableHealth:
    def test_threshold_breach_returns_finding(self):
        rule = GOV005DeltaTableHealth()
        df = pl.DataFrame(
            {
                "table_name": ["t1", "t2"],
                "freshness_status": ["Fresh", "Stale (>30d)"],
                "table_format": ["delta", "delta"],
            }
        )
        findings = rule.evaluate({"N-DT01": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "GOV-005"
        assert "t2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = GOV005DeltaTableHealth()
        df = pl.DataFrame(
            {
                "table_name": ["t1"],
                "freshness_status": ["Fresh"],
            }
        )
        assert rule.evaluate({"N-DT01": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = GOV005DeltaTableHealth()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"N-DT01": pl.DataFrame()}) == []
        df = pl.DataFrame({"table_name": ["t1"]})
        assert rule.evaluate({"N-DT01": df}) == []


class TestGovernanceRulesExport:
    def test_governance_rules_has_five_rules(self):
        assert len(GOVERNANCE_RULES) == 5
        ids = [r.rule_id for r in GOVERNANCE_RULES]
        assert ids == [
            "GOV-001",
            "GOV-002",
            "GOV-003",
            "GOV-004",
            "GOV-005",
        ]
