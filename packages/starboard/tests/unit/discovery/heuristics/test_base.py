# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for heuristic framework base types.

Tests cover:
- HeuristicFinding construction and immutability
- HeuristicRule protocol conformance
- HeuristicRegistry: register, evaluate, domain lookup, rule counting
- Error handling when a rule raises during evaluation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest
from starboard.discovery.heuristics.base import (
    HeuristicFinding,
    HeuristicRegistry,
)

if TYPE_CHECKING:
    from starboard.discovery.heuristics.base import Dimension, Severity


class StubRule:
    """Minimal HeuristicRule implementation for testing."""

    def __init__(
        self,
        rule_id: str,
        domain: str,
        findings: list[HeuristicFinding] | None = None,
        *,
        should_raise: bool = False,
    ) -> None:
        self._rule_id = rule_id
        self._domain = domain
        self._findings = findings or []
        self._should_raise = should_raise

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def name(self) -> str:
        return f"Rule {self._rule_id}"

    @property
    def description(self) -> str:
        return "Stub rule"

    @property
    def severity(self) -> Severity:
        return "MEDIUM"

    @property
    def dimension(self) -> Dimension:
        return "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        if self._should_raise:
            raise RuntimeError("Rule evaluation failed")
        return self._findings


class TestHeuristicFinding:
    def test_construction(self):
        f = HeuristicFinding(
            rule_id="H-B01",
            domain="billing",
            title="Excessive DBU consumption",
            severity="HIGH",
            dimension="consumption",
            description="Top job consumes 40% of total DBUs.",
            evidence_query_id="C-B01",
            threshold=">25%",
            actual_value="40%",
        )
        assert f.rule_id == "H-B01"
        assert f.affected_entities == ()

    def test_with_affected_entities(self):
        f = HeuristicFinding(
            rule_id="H-J01",
            domain="jobs",
            title="Failing jobs",
            severity="CRITICAL",
            dimension="reliability",
            description="3 jobs exceed 30% failure rate.",
            evidence_query_id="C-J01",
            threshold=">30%",
            actual_value="45%",
            affected_entities=("job-123", "job-456", "job-789"),
        )
        assert len(f.affected_entities) == 3

    def test_frozen(self):
        f = HeuristicFinding(
            rule_id="X",
            domain="test",
            title="X",
            severity="LOW",
            dimension="governance",
            description="X",
            evidence_query_id="X",
            threshold="X",
            actual_value="X",
        )
        with pytest.raises(AttributeError):
            f.rule_id = "Y"  # type: ignore[misc]


class TestHeuristicRegistry:
    @pytest.fixture()
    def sample_finding(self) -> HeuristicFinding:
        return HeuristicFinding(
            rule_id="H-B01",
            domain="billing",
            title="Test finding",
            severity="MEDIUM",
            dimension="consumption",
            description="Test",
            evidence_query_id="C-B01",
            threshold=">50%",
            actual_value="60%",
        )

    def test_register_and_lookup(self, sample_finding: HeuristicFinding):
        rule = StubRule("H-B01", "billing", [sample_finding])
        registry = HeuristicRegistry()
        registry.register(rule)

        assert registry.rule_count == 1
        assert "billing" in registry.all_domains
        assert len(registry.get_rules_for_domain("billing")) == 1

    def test_constructor_registration(self, sample_finding: HeuristicFinding):
        rule = StubRule("H-B01", "billing", [sample_finding])
        registry = HeuristicRegistry(rules=(rule,))
        assert registry.rule_count == 1

    def test_evaluate_returns_findings(self, sample_finding: HeuristicFinding):
        rule = StubRule("H-B01", "billing", [sample_finding])
        registry = HeuristicRegistry(rules=(rule,))

        findings = registry.evaluate("billing", {"C-B01": pl.DataFrame()})
        assert len(findings) == 1
        assert findings[0].rule_id == "H-B01"

    def test_evaluate_unknown_domain(self):
        registry = HeuristicRegistry()
        findings = registry.evaluate("nonexistent", {})
        assert findings == []

    def test_evaluate_catches_rule_errors(self):
        bad_rule = StubRule("H-BAD", "jobs", should_raise=True)
        registry = HeuristicRegistry(rules=(bad_rule,))
        findings = registry.evaluate("jobs", {})
        assert findings == []

    def test_multiple_rules_same_domain(self, sample_finding: HeuristicFinding):
        r1 = StubRule("H-B01", "billing", [sample_finding])
        r2 = StubRule("H-B02", "billing")
        registry = HeuristicRegistry(rules=(r1, r2))

        assert registry.rule_count == 2
        assert len(registry.get_rules_for_domain("billing")) == 2

    def test_multiple_domains(self, sample_finding: HeuristicFinding):
        r1 = StubRule("H-B01", "billing", [sample_finding])
        r2 = StubRule("H-J01", "jobs")
        registry = HeuristicRegistry(rules=(r1, r2))

        assert set(registry.all_domains) == {"billing", "jobs"}
        assert registry.rule_count == 2

    def test_get_rules_empty_domain(self):
        registry = HeuristicRegistry()
        assert registry.get_rules_for_domain("billing") == []


@pytest.mark.unit
class TestStringTypedFrames:
    """Round-6: internal-source frames arrive with numeric columns as strings."""

    def test_coerce_numeric_strings_casts_numbers_and_bools_keeps_ids(self) -> None:
        from starboard.discovery.heuristics.base import coerce_numeric_strings

        df = pl.DataFrame(
            {
                "warehouse_id": ["123", "456"],
                "peak_hour_avg_queue_secs": ["60.0", "27.7"],
                "runs": ["3", None],
                "is_serverless": ["true", "FALSE"],
                "sku_name": ["PREMIUM_SQL", "2026-09-01"],
            }
        )
        out = coerce_numeric_strings(df)
        assert out.schema["warehouse_id"] == pl.Utf8  # identifier untouched
        assert out.schema["peak_hour_avg_queue_secs"] == pl.Float64
        assert out.schema["runs"] == pl.Int64
        assert out["is_serverless"].to_list() == [True, False]
        assert out.schema["sku_name"] == pl.Utf8  # not all numeric

    def test_registry_evaluates_string_typed_frames_without_compute_error(self) -> None:
        from starboard.discovery.heuristics import create_default_heuristic_registry

        registry = create_default_heuristic_registry()
        c_c03 = pl.DataFrame(
            {"warehouse_id": ["w1", "w2"], "peak_hour_avg_queue_secs": ["60.0", "27.7"]}
        )
        findings = registry.evaluate("compute", {"C-C03": c_c03})
        cmp006 = [f for f in findings if f.rule_id == "CMP-006"]
        assert cmp006 and cmp006[0].affected_entities == ("w1",)

        p_q = pl.DataFrame({"statement_id": ["s1"], "task_to_exec_ratio": ["12.5"]})
        qpf = registry.evaluate("query_perf", {"C-Q02": p_q})
        assert [f.rule_id for f in qpf] == ["QPF-002"]

    def test_rule_failure_logs_one_line_without_traceback(self) -> None:
        from unittest.mock import patch

        registry = HeuristicRegistry(rules=(StubRule("BAD-1", "billing", should_raise=True),))
        with patch("starboard.discovery.heuristics.base.logger") as log:
            assert registry.evaluate("billing", {}) == []
        log.warning.assert_called_once()
        args, kwargs = log.warning.call_args
        assert args[0].startswith("heuristic BAD-1 skipped: ")
        assert "\n" not in args[0]
        assert "exc_info" not in kwargs
