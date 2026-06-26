# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for billing heuristic rules."""

from __future__ import annotations

import polars as pl
from starboard_server.discovery.heuristics.billing import (
    BILLING_RULES,
    BIL001DBUConcentration,
    BIL002WeekOverWeekDBUGrowth,
    BIL003UntaggedConsumption,
    BIL004UnattributedIdentity,
    BIL005ServerlessAdoptionGap,
)


class TestBIL001DBUConcentration:
    def test_empty_results_returns_empty(self):
        rule = BIL001DBUConcentration()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-B01": pl.DataFrame()}) == []

    def test_missing_column_returns_empty(self):
        rule = BIL001DBUConcentration()
        df = pl.DataFrame({"job_id": ["j1"], "other": [100]})
        assert rule.evaluate({"C-B01": df}) == []

    def test_below_threshold_returns_empty(self):
        rule = BIL001DBUConcentration()
        df = pl.DataFrame(
            {
                "job_id": ["j1", "j2", "j3"],
                "dbus_consumed": [30, 35, 35],
            }
        )
        assert rule.evaluate({"C-B01": df}) == []

    def test_above_threshold_returns_finding(self):
        rule = BIL001DBUConcentration()
        df = pl.DataFrame(
            {
                "job_id": ["j1", "j2"],
                "dbus_consumed": [60, 40],
            }
        )
        findings = rule.evaluate({"C-B01": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "BIL-001"
        assert "j1" in findings[0].affected_entities

    def test_uses_run_as_when_present(self):
        rule = BIL001DBUConcentration()
        df = pl.DataFrame(
            {
                "run_as": ["user-a", "user-b"],
                "dbus_consumed": [80, 20],
            }
        )
        findings = rule.evaluate({"C-B01": df})
        assert len(findings) == 1
        assert "user-a" in findings[0].affected_entities


class TestBIL002WeekOverWeekDBUGrowth:
    def test_missing_query_returns_empty(self):
        rule = BIL002WeekOverWeekDBUGrowth()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-B04": pl.DataFrame()}) == []

    def test_no_breachers_returns_empty(self):
        rule = BIL002WeekOverWeekDBUGrowth()
        df = pl.DataFrame(
            {
                "job_id": ["j1", "j2"],
                "wow_growth_pct": [10, 15],
            }
        )
        assert rule.evaluate({"C-B03": df}) == []

    def test_breachers_returns_finding(self):
        rule = BIL002WeekOverWeekDBUGrowth()
        df = pl.DataFrame(
            {
                "job_id": ["j1", "j2"],
                "wow_growth_pct": [10, 30],
            }
        )
        findings = rule.evaluate({"C-B03": df})
        assert len(findings) == 1
        assert "j2" in findings[0].affected_entities


class TestBIL003UntaggedConsumption:
    def test_missing_columns_returns_empty(self):
        rule = BIL003UntaggedConsumption()
        df = pl.DataFrame({"x": [1]})
        assert rule.evaluate({"C-B04": df}) == []

    def test_below_threshold_returns_empty(self):
        rule = BIL003UntaggedConsumption()
        df = pl.DataFrame(
            {
                "untagged_dbus": [20],
                "dbus": [100],
            }
        )
        assert rule.evaluate({"C-B04": df}) == []

    def test_above_threshold_returns_finding(self):
        rule = BIL003UntaggedConsumption()
        df = pl.DataFrame(
            {
                "untagged_dbus": [40],
                "dbus": [100],
            }
        )
        findings = rule.evaluate({"C-B04": df})
        assert len(findings) == 1
        assert "40.0" in findings[0].actual_value or "40" in findings[0].actual_value


class TestBIL004UnattributedIdentity:
    def test_missing_columns_returns_empty(self):
        rule = BIL004UnattributedIdentity()
        df = pl.DataFrame({"dbus_consumed": [100]})
        assert rule.evaluate({"C-B01": df}) == []

    def test_above_threshold_returns_finding(self):
        rule = BIL004UnattributedIdentity()
        df = pl.DataFrame(
            {
                "user_type": ["Attributed", "Unattributed"],
                "dbus_consumed": [70, 30],
            }
        )
        findings = rule.evaluate({"C-B01": df})
        assert len(findings) == 1


class TestBIL005ServerlessAdoptionGap:
    def test_missing_columns_returns_empty(self):
        rule = BIL005ServerlessAdoptionGap()
        df = pl.DataFrame({"dbus_consumed": [100]})
        assert rule.evaluate({"C-B01": df}) == []

    def test_above_threshold_returns_empty(self):
        rule = BIL005ServerlessAdoptionGap()
        df = pl.DataFrame(
            {
                "is_serverless": [True, False],
                "dbus_consumed": [15, 85],
            }
        )
        assert rule.evaluate({"C-B01": df}) == []

    def test_below_threshold_returns_finding(self):
        rule = BIL005ServerlessAdoptionGap()
        df = pl.DataFrame(
            {
                "is_serverless": [True, False],
                "dbus_consumed": [5, 95],
            }
        )
        findings = rule.evaluate({"C-B01": df})
        assert len(findings) == 1


class TestBillingRulesExport:
    def test_billing_rules_tuple(self):
        assert len(BILLING_RULES) == 5
        ids = [r.rule_id for r in BILLING_RULES]
        assert ids == ["BIL-001", "BIL-002", "BIL-003", "BIL-004", "BIL-005"]
