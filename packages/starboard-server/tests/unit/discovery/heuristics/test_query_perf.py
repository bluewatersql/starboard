# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for query performance heuristic rules."""

from __future__ import annotations

import polars as pl
from starboard_server.discovery.heuristics.query_perf import (
    QUERY_PERF_RULES,
    QPF001ExcessiveSpill,
    QPF002DataSkew,
    QPF003RepeatedQueryRate,
    QPF004LowCacheHitRate,
    QPF005P95LatencyOutliers,
    QPF006HighErrorRate,
    QPF007ConcurrencySaturation,
)


class TestQPF001ExcessiveSpill:
    def test_threshold_breach_returns_finding(self):
        rule = QPF001ExcessiveSpill()
        df = pl.DataFrame(
            {
                "statement_id": ["s1", "s2"],
                "spill_gb": [0.5, 2.0],
            }
        )
        findings = rule.evaluate({"C-Q02": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "QPF-001"
        assert "s2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = QPF001ExcessiveSpill()
        df = pl.DataFrame(
            {
                "statement_id": ["s1"],
                "spill_gb": [0.9],
            }
        )
        assert rule.evaluate({"C-Q02": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = QPF001ExcessiveSpill()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-Q02": pl.DataFrame()}) == []
        df = pl.DataFrame({"statement_id": ["s1"]})
        assert rule.evaluate({"C-Q02": df}) == []


class TestQPF002DataSkew:
    def test_threshold_breach_returns_finding(self):
        rule = QPF002DataSkew()
        df = pl.DataFrame(
            {
                "statement_id": ["s1", "s2"],
                "task_to_exec_ratio": [5, 15],
            }
        )
        findings = rule.evaluate({"C-Q02": df})
        assert len(findings) == 1
        assert "s2" in findings[0].affected_entities

    def test_below_threshold_returns_empty(self):
        rule = QPF002DataSkew()
        df = pl.DataFrame(
            {
                "statement_id": ["s1"],
                "task_to_exec_ratio": [8],
            }
        )
        assert rule.evaluate({"C-Q02": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = QPF002DataSkew()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-Q02": pl.DataFrame()}) == []
        df = pl.DataFrame({"statement_id": ["s1"]})
        assert rule.evaluate({"C-Q02": df}) == []


class TestQPF003RepeatedQueryRate:
    def test_threshold_breach_returns_finding(self):
        rule = QPF003RepeatedQueryRate()
        # total=110, dup_sum=60 (exec_count>=5), ratio=54.5% > 20%
        df = pl.DataFrame(
            {
                "execution_count": [2, 3, 10, 50],
            }
        )
        findings = rule.evaluate({"C-Q03": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "QPF-003"
        assert "%" in findings[0].actual_value

    def test_below_threshold_returns_empty(self):
        rule = QPF003RepeatedQueryRate()
        df = pl.DataFrame(
            {
                "execution_count": [1, 2, 3, 4],
            }
        )
        assert rule.evaluate({"C-Q03": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = QPF003RepeatedQueryRate()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-Q03": pl.DataFrame()}) == []
        df = pl.DataFrame({"other_col": [1]})
        assert rule.evaluate({"C-Q03": df}) == []


class TestQPF004LowCacheHitRate:
    def test_threshold_breach_returns_finding(self):
        rule = QPF004LowCacheHitRate()
        # Weighted avg: (10*10 + 5*20)/(10+20) = 200/30 ≈ 6.67 < 20
        df = pl.DataFrame(
            {
                "cache_hit_pct": [10, 5],
                "execution_count": [10, 20],
            }
        )
        findings = rule.evaluate({"C-Q03": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "QPF-004"

    def test_below_threshold_returns_empty(self):
        rule = QPF004LowCacheHitRate()
        df = pl.DataFrame(
            {
                "cache_hit_pct": [50],
            }
        )
        assert rule.evaluate({"C-Q03": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = QPF004LowCacheHitRate()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-Q03": pl.DataFrame()}) == []
        df = pl.DataFrame({"other_col": [1]})
        assert rule.evaluate({"C-Q03": df}) == []


class TestQPF005P95LatencyOutliers:
    def test_threshold_breach_returns_finding(self):
        rule = QPF005P95LatencyOutliers()
        df = pl.DataFrame(
            {
                "p95_total_secs": [10, 150],
                "p50_total_secs": [5, 10],
            }
        )
        findings = rule.evaluate({"C-Q01": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "QPF-005"

    def test_below_threshold_returns_empty(self):
        rule = QPF005P95LatencyOutliers()
        df = pl.DataFrame(
            {
                "p95_total_secs": [20],
                "p50_total_secs": [10],
            }
        )
        assert rule.evaluate({"C-Q01": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = QPF005P95LatencyOutliers()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-Q01": pl.DataFrame()}) == []
        df = pl.DataFrame({"p50_total_secs": [10]})
        assert rule.evaluate({"C-Q01": df}) == []


class TestQPF006HighErrorRate:
    def test_threshold_breach_returns_finding(self):
        rule = QPF006HighErrorRate()
        df_err = pl.DataFrame({"occurrences": [10]})
        df_vol = pl.DataFrame({"total_queries": [100]})
        findings = rule.evaluate({"C-Q04": df_err, "C-Q01": df_vol})
        assert len(findings) == 1
        assert findings[0].rule_id == "QPF-006"
        assert "10" in findings[0].actual_value and "errors" in findings[0].actual_value

    def test_below_threshold_returns_empty(self):
        rule = QPF006HighErrorRate()
        df_err = pl.DataFrame({"occurrences": [3]})
        df_vol = pl.DataFrame({"total_queries": [100]})
        assert rule.evaluate({"C-Q04": df_err, "C-Q01": df_vol}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = QPF006HighErrorRate()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-Q04": pl.DataFrame()}) == []
        assert (
            rule.evaluate(
                {"C-Q01": pl.DataFrame(), "C-Q04": pl.DataFrame({"occurrences": [1]})}
            )
            == []
        )


class TestQPF007ConcurrencySaturation:
    def test_threshold_breach_returns_finding(self):
        rule = QPF007ConcurrencySaturation()
        df = pl.DataFrame(
            {
                "queries_queued_30s_plus": [5, 15],
                "concurrent_queries": [100, 100],
            }
        )
        findings = rule.evaluate({"C-Q05": df})
        assert len(findings) == 1
        assert findings[0].rule_id == "QPF-007"
        assert "10%" in findings[0].description or "0.1" in findings[0].threshold

    def test_below_threshold_returns_empty(self):
        rule = QPF007ConcurrencySaturation()
        df = pl.DataFrame(
            {
                "queries_queued_30s_plus": [5],
                "concurrent_queries": [100],
            }
        )
        assert rule.evaluate({"C-Q05": df}) == []

    def test_empty_missing_dataframe_graceful(self):
        rule = QPF007ConcurrencySaturation()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-Q05": pl.DataFrame()}) == []
        df = pl.DataFrame({"concurrent_queries": [100]})
        assert rule.evaluate({"C-Q05": df}) == []


class TestQueryPerfRulesExport:
    def test_query_perf_rules_has_seven_rules(self):
        assert len(QUERY_PERF_RULES) == 7
        ids = [r.rule_id for r in QUERY_PERF_RULES]
        assert ids == [
            "QPF-001",
            "QPF-002",
            "QPF-003",
            "QPF-004",
            "QPF-005",
            "QPF-006",
            "QPF-007",
        ]
