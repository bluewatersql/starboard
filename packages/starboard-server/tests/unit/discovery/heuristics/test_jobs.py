"""Tests for job workload heuristic rules."""

from __future__ import annotations

import polars as pl
from starboard_server.discovery.heuristics.jobs import (
    JOB_RULES,
    JOB001HighFailureRate,
    JOB002ExcessiveRetryRatio,
    JOB003RuntimeVariance,
    JOB004DBUPerMinuteOutliers,
    JOB005DailyFailureRateSpike,
    JOB006TaskLevelFailureConcentration,
    JOB007DLTPipelineDegradation,
)


class TestJOB001HighFailureRate:
    def test_empty_results_returns_empty(self):
        rule = JOB001HighFailureRate()
        assert rule.evaluate({}) == []
        assert rule.evaluate({"C-J04": pl.DataFrame()}) == []

    def test_missing_column_returns_empty(self):
        rule = JOB001HighFailureRate()
        df = pl.DataFrame({"job_id": ["j1"]})
        assert rule.evaluate({"C-J04": df}) == []

    def test_above_threshold_returns_finding(self):
        rule = JOB001HighFailureRate()
        df = pl.DataFrame(
            {
                "job_id": ["j1", "j2"],
                "failure_rate_pct": [5, 15],
            }
        )
        findings = rule.evaluate({"C-J04": df})
        assert len(findings) == 1
        assert "j2" in findings[0].affected_entities


class TestJOB002ExcessiveRetryRatio:
    def test_missing_columns_returns_empty(self):
        rule = JOB002ExcessiveRetryRatio()
        df = pl.DataFrame({"job_id": ["j1"]})
        assert rule.evaluate({"C-J04": df}) == []

    def test_above_threshold_returns_finding(self):
        rule = JOB002ExcessiveRetryRatio()
        df = pl.DataFrame(
            {
                "job_id": ["j1", "j2"],
                "retried_runs": [5, 30],
                "total_runs": [100, 100],
            }
        )
        findings = rule.evaluate({"C-J04": df})
        assert len(findings) == 1
        assert "j2" in findings[0].affected_entities

    def test_handles_zero_total_runs(self):
        rule = JOB002ExcessiveRetryRatio()
        df = pl.DataFrame(
            {
                "job_id": ["j1"],
                "retried_runs": [10],
                "total_runs": [0],
            }
        )
        findings = rule.evaluate({"C-J04": df})
        assert findings == []


class TestJOB003RuntimeVariance:
    def test_above_threshold_returns_finding(self):
        rule = JOB003RuntimeVariance()
        df = pl.DataFrame(
            {
                "job_id": ["j1", "j2"],
                "stddev_runtime_mins": [60, 30],
                "avg_runtime_mins": [100, 50],
            }
        )
        findings = rule.evaluate({"C-J03": df})
        assert len(findings) == 1
        assert "j1" in findings[0].affected_entities


class TestJOB004DBUPerMinuteOutliers:
    def test_above_threshold_returns_finding(self):
        rule = JOB004DBUPerMinuteOutliers()
        df = pl.DataFrame(
            {
                "job_id": ["j1", "j2", "j3"],
                "avg_dbus_per_minute": [1.0, 2.0, 10.0],
            }
        )
        findings = rule.evaluate({"C-J03": df})
        assert len(findings) == 1
        assert "j3" in findings[0].affected_entities


class TestJOB005DailyFailureRateSpike:
    def test_above_threshold_returns_finding(self):
        rule = JOB005DailyFailureRateSpike()
        df = pl.DataFrame(
            {
                "job_id": ["j1"],
                "run_date": ["2025-01-15"],
                "failure_rate_pct": [30],
            }
        )
        findings = rule.evaluate({"C-J05": df})
        assert len(findings) == 1


class TestJOB006TaskLevelFailureConcentration:
    def test_above_threshold_returns_finding(self):
        rule = JOB006TaskLevelFailureConcentration()
        df = pl.DataFrame(
            {
                "task_type": ["Python", "Spark", "SQL"],
                "failures": [30, 10, 10],
            }
        )
        findings = rule.evaluate({"C-J06": df})
        assert len(findings) == 1
        assert "Python" in findings[0].affected_entities


class TestJOB007DLTPipelineDegradation:
    def test_above_threshold_returns_finding(self):
        rule = JOB007DLTPipelineDegradation()
        df = pl.DataFrame(
            {
                "pipeline_name": ["p1", "p2"],
                "failure_rate_pct": [5, 20],
            }
        )
        findings = rule.evaluate({"C-J07": df})
        assert len(findings) == 1
        assert "p2" in findings[0].affected_entities


class TestJobRulesExport:
    def test_job_rules_tuple(self):
        assert len(JOB_RULES) == 7
        ids = [r.rule_id for r in JOB_RULES]
        assert ids == [
            "JOB-001",
            "JOB-002",
            "JOB-003",
            "JOB-004",
            "JOB-005",
            "JOB-006",
            "JOB-007",
        ]
