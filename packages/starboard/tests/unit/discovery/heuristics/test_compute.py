# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for compute heuristic rules."""

from __future__ import annotations

import polars as pl
from starboard.discovery.heuristics.compute import (
    COMPUTE_RULES,
    CMP001ExcessiveAutoTermination,
    CMP002HighIdlePercentage,
    CMP003NoAutoScalingOnInteractive,
    CMP004OverProvisionedClusters,
    CMP005MissingAutoTermination,
    CMP006SqlWarehouseQueuePressure,
)


class TestCMP001ExcessiveAutoTermination:
    def test_threshold_breach_returns_finding(self):
        rule = CMP001ExcessiveAutoTermination()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1", "c2"],
                "auto_termination_minutes": [60, 180],
            }
        )
        findings = rule.evaluate({"C-C02": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "CMP-001"
        assert "c2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = CMP001ExcessiveAutoTermination()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1"],
                "auto_termination_minutes": [120],
            }
        )
        assert rule.evaluate({"C-C02": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = CMP001ExcessiveAutoTermination()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-C02": pl.DataFrame()}) == []
        df = pl.DataFrame({"cluster_id": ["c1"]})
        assert rule.evaluate({"C-C02": df}) == []


class TestCMP002HighIdlePercentage:
    def test_threshold_breach_returns_finding(self):
        rule = CMP002HighIdlePercentage()
        threshold = 0.4 * 30 * 24 * 60
        df = pl.DataFrame(
            {
                "cluster_id": ["c1", "c2"],
                "idle_minutes": [1000, int(threshold) + 1000],
            }
        )
        findings = rule.evaluate({"C-C02": df})
        assert len(findings) == 1
        assert "c2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = CMP002HighIdlePercentage()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1"],
                "idle_minutes": [1000],
            }
        )
        assert rule.evaluate({"C-C02": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = CMP002HighIdlePercentage()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-C02": pl.DataFrame()}) == []
        df = pl.DataFrame({"cluster_id": ["c1"]})
        assert rule.evaluate({"C-C02": df}) == []


class TestCMP003NoAutoScalingOnInteractive:
    def test_threshold_breach_returns_finding(self):
        rule = CMP003NoAutoScalingOnInteractive()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1", "c2"],
                "cluster_type": ["Autoscaling", "Fixed Size"],
                "cluster_source": ["API", "UI"],
            }
        )
        findings = rule.evaluate({"C-C01": df})
        assert len(findings) == 1
        assert "c2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = CMP003NoAutoScalingOnInteractive()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1"],
                "cluster_type": ["Autoscaling"],
                "cluster_source": ["API"],
            }
        )
        assert rule.evaluate({"C-C01": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = CMP003NoAutoScalingOnInteractive()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-C01": pl.DataFrame()}) == []
        df = pl.DataFrame({"cluster_id": ["c1"]})
        assert rule.evaluate({"C-C01": df}) == []


class TestCMP004OverProvisionedClusters:
    def test_threshold_breach_returns_finding(self):
        rule = CMP004OverProvisionedClusters()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1", "c2"],
                "avg_cpu_pct": [50, 15],
                "avg_mem_pct": [60, 70],
            }
        )
        findings = rule.evaluate({"C-C01": df})
        assert len(findings) == 1
        assert "c2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = CMP004OverProvisionedClusters()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1"],
                "avg_cpu_pct": [50],
                "avg_mem_pct": [60],
            }
        )
        assert rule.evaluate({"C-C01": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = CMP004OverProvisionedClusters()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-C01": pl.DataFrame()}) == []
        df = pl.DataFrame({"cluster_id": ["c1"]})
        assert rule.evaluate({"C-C01": df}) == []


class TestCMP005MissingAutoTermination:
    def test_threshold_breach_null_returns_finding(self):
        rule = CMP005MissingAutoTermination()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1", "c2"],
                "auto_termination_minutes": [60, None],
                "termination_risk": ["OK", "OK"],
            }
        )
        findings = rule.evaluate({"C-C02": df})
        assert len(findings) == 1
        assert "c2" in findings[0].affected_entities

    def test_threshold_breach_no_auto_terminate_returns_finding(self):
        rule = CMP005MissingAutoTermination()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1"],
                "termination_risk": ["NO AUTO-TERMINATE"],
            }
        )
        findings = rule.evaluate({"C-C02": df})
        assert len(findings) == 1

    def test_below_threshold_returns_empty(self):
        rule = CMP005MissingAutoTermination()
        df = pl.DataFrame(
            {
                "cluster_id": ["c1"],
                "auto_termination_minutes": [60],
                "termination_risk": ["OK"],
            }
        )
        assert rule.evaluate({"C-C02": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = CMP005MissingAutoTermination()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-C02": pl.DataFrame()}) == []


class TestCMP006SqlWarehouseQueuePressure:
    def test_threshold_breach_returns_finding(self):
        rule = CMP006SqlWarehouseQueuePressure()
        df = pl.DataFrame(
            {
                "warehouse_id": ["wh1", "wh2"],
                "avg_queue_secs": [10, 45],
            }
        )
        findings = rule.evaluate({"C-C03": df})
        assert len(findings) == 1
        assert "wh2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = CMP006SqlWarehouseQueuePressure()
        df = pl.DataFrame(
            {
                "warehouse_id": ["wh1"],
                "avg_queue_secs": [25],
            }
        )
        assert rule.evaluate({"C-C03": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = CMP006SqlWarehouseQueuePressure()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-C03": pl.DataFrame()}) == []
        df = pl.DataFrame({"warehouse_id": ["wh1"]})
        assert rule.evaluate({"C-C03": df}) == []


class TestComputeRulesExport:
    def test_compute_rules_has_six_rules(self):
        assert len(COMPUTE_RULES) == 6
        ids = [r.rule_id for r in COMPUTE_RULES]
        assert ids == [
            "CMP-001",
            "CMP-002",
            "CMP-003",
            "CMP-004",
            "CMP-005",
            "CMP-006",
        ]
