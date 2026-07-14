# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for DomainAnalyzer.

Tests cover:
- analyze_domain: success, LLM failure fallback, empty heuristic findings
- analyze_all_domains
- _fallback_analysis: CRITICAL, HIGH, no findings
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest
from starboard_core.domain.models.discovery.query import PackResult, QueryResult
from starboard.adapters.llm.base import BaseLLMClient
from starboard.discovery.analyzer import DomainAnalyzer
from starboard.discovery.heuristics.base import (
    HeuristicFinding,
    HeuristicRegistry,
)


def _valid_domain_analysis_dict(domain: str = "billing") -> dict:
    """Valid DomainAnalysis dict matching the schema."""
    return {
        "domain": domain,
        "grade": "B",
        "score": 78,
        "summary": "Test summary",
        "observations": ["obs1"],
        "patterns": ["pattern1"],
        "findings": [],
        "recommended_actions": ["action1"],
        "data_coverage": {
            "queries_executed": 3,
            "queries_succeeded": 3,
            "time_range_start": None,
            "time_range_end": None,
            "gaps": [],
        },
    }


class StubRule:
    """Minimal HeuristicRule implementation for testing."""

    def __init__(
        self,
        rule_id: str,
        domain: str,
        findings: list[HeuristicFinding] | None = None,
    ) -> None:
        self._rule_id = rule_id
        self._domain = domain
        self._findings = findings or []

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
    def severity(self) -> str:
        return "MEDIUM"

    @property
    def dimension(self) -> str:
        return "performance"

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        return self._findings


@pytest.fixture
def sample_query_result() -> QueryResult:
    return QueryResult(
        query_id="C-B01",
        domain="billing",
        data=pl.DataFrame({"dbus": [100, 200]}),
        row_count=2,
        execution_time_ms=50.0,
    )


@pytest.fixture
def sample_pack_result(sample_query_result: QueryResult) -> PackResult:
    return PackResult(
        pack_id="billing-core", domain="billing", results=(sample_query_result,)
    )


@pytest.mark.asyncio
class TestAnalyzeDomain:
    async def test_analyze_domain_success(
        self,
        sample_pack_result: PackResult,
    ) -> None:
        mock_llm = MagicMock(spec=BaseLLMClient)
        mock_llm.json_response = AsyncMock(
            return_value=_valid_domain_analysis_dict(domain="billing")
        )
        hf = HeuristicFinding(
            rule_id="BIL-001",
            domain="billing",
            title="Test",
            severity="HIGH",
            dimension="consumption",
            description="Test desc",
            evidence_query_id="C-B01",
            threshold=">50%",
            actual_value="65%",
        )
        rule = StubRule("BIL-001", "billing", findings=[hf])
        registry = HeuristicRegistry(rules=(rule,))

        analyzer = DomainAnalyzer(llm_client=mock_llm, heuristic_registry=registry)
        result = await analyzer.analyze_domain("billing", [sample_pack_result])

        assert result.domain == "billing"
        assert result.grade == "B"
        assert result.score == 78
        assert result.summary == "Test summary"

    async def test_analyze_domain_llm_failure_fallback(
        self,
        sample_pack_result: PackResult,
    ) -> None:
        mock_llm = MagicMock(spec=BaseLLMClient)
        mock_llm.json_response = AsyncMock(side_effect=ValueError("LLM error"))
        hf = HeuristicFinding(
            rule_id="BIL-001",
            domain="billing",
            title="Critical issue",
            severity="HIGH",
            dimension="consumption",
            description="High severity finding",
            evidence_query_id="C-B01",
            threshold=">50%",
            actual_value="65%",
        )
        rule = StubRule("BIL-001", "billing", findings=[hf])
        registry = HeuristicRegistry(rules=(rule,))

        analyzer = DomainAnalyzer(llm_client=mock_llm, heuristic_registry=registry)
        result = await analyzer.analyze_domain("billing", [sample_pack_result])

        assert "LLM unavailable" in result.summary
        assert result.grade == "C"
        assert result.score == 55
        assert len(result.findings) == 1
        assert result.findings[0].title == "Critical issue"
        assert result.findings[0].priority == "HIGH"
        assert result.findings[0].domain == "billing"
        assert len(result.findings[0].evidence) == 1
        assert len(result.observations) >= 1
        assert len(result.recommended_actions) >= 1

    async def test_analyze_domain_no_heuristic_findings(
        self,
        sample_pack_result: PackResult,
    ) -> None:
        mock_llm = MagicMock(spec=BaseLLMClient)
        mock_llm.json_response = AsyncMock(
            return_value=_valid_domain_analysis_dict(domain="billing")
        )
        registry = HeuristicRegistry()

        analyzer = DomainAnalyzer(llm_client=mock_llm, heuristic_registry=registry)
        await analyzer.analyze_domain("billing", [sample_pack_result])

        call_args = mock_llm.json_response.call_args
        messages = call_args.kwargs["messages"]
        system_content = messages[0]["content"]
        assert "No heuristic violations detected" in system_content

    async def test_analyze_all_domains(self) -> None:
        mock_llm = MagicMock(spec=BaseLLMClient)
        mock_llm.json_response = AsyncMock(
            side_effect=[
                _valid_domain_analysis_dict(domain="billing"),
                _valid_domain_analysis_dict(domain="jobs"),
            ]
        )
        registry = HeuristicRegistry()

        qr_billing = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=pl.DataFrame({"dbus": [100]}),
            row_count=1,
            execution_time_ms=50.0,
        )
        qr_jobs = QueryResult(
            query_id="C-J01",
            domain="jobs",
            data=pl.DataFrame({"run_count": [10]}),
            row_count=1,
            execution_time_ms=50.0,
        )
        domain_results = {
            "billing": [PackResult("billing-core", "billing", (qr_billing,))],
            "jobs": [PackResult("jobs-core", "jobs", (qr_jobs,))],
        }

        analyzer = DomainAnalyzer(llm_client=mock_llm, heuristic_registry=registry)
        results = await analyzer.analyze_all_domains(domain_results)

        assert len(results) == 2
        assert results[0].domain == "billing"
        assert results[1].domain == "jobs"


@pytest.mark.asyncio
class TestFallbackAnalysis:
    async def test_fallback_analysis_critical_severity(self) -> None:
        mock_llm = MagicMock(spec=BaseLLMClient)
        hf = HeuristicFinding(
            rule_id="BIL-001",
            domain="billing",
            title="Critical",
            severity="CRITICAL",
            dimension="consumption",
            description="Critical finding",
            evidence_query_id="C-B01",
            threshold=">90%",
            actual_value="95%",
        )
        rule = StubRule("BIL-001", "billing", findings=[hf])
        registry = HeuristicRegistry(rules=(rule,))
        qr = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=pl.DataFrame({"dbus": [100]}),
            row_count=1,
            execution_time_ms=50.0,
        )
        pack = PackResult("billing-core", "billing", (qr,))

        analyzer = DomainAnalyzer(llm_client=mock_llm, heuristic_registry=registry)
        mock_llm.json_response = AsyncMock(side_effect=ValueError("LLM failed"))

        result = await analyzer.analyze_domain("billing", [pack])

        assert result.grade == "D"
        assert result.score == 35

    async def test_fallback_analysis_high_severity(self) -> None:
        mock_llm = MagicMock(spec=BaseLLMClient)
        hf = HeuristicFinding(
            rule_id="BIL-001",
            domain="billing",
            title="High",
            severity="HIGH",
            dimension="consumption",
            description="High finding",
            evidence_query_id="C-B01",
            threshold=">50%",
            actual_value="60%",
        )
        rule = StubRule("BIL-001", "billing", findings=[hf])
        registry = HeuristicRegistry(rules=(rule,))
        qr = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=pl.DataFrame({"dbus": [100]}),
            row_count=1,
            execution_time_ms=50.0,
        )
        pack = PackResult("billing-core", "billing", (qr,))

        analyzer = DomainAnalyzer(llm_client=mock_llm, heuristic_registry=registry)
        mock_llm.json_response = AsyncMock(side_effect=ValueError("LLM failed"))

        result = await analyzer.analyze_domain("billing", [pack])

        assert result.grade == "C"
        assert result.score == 55

    async def test_fallback_analysis_no_findings(self) -> None:
        mock_llm = MagicMock(spec=BaseLLMClient)
        mock_llm.json_response = AsyncMock(side_effect=ValueError("LLM failed"))
        registry = HeuristicRegistry()

        qr = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=pl.DataFrame({"dbus": [100]}),
            row_count=1,
            execution_time_ms=50.0,
        )
        pack = PackResult("billing-core", "billing", (qr,))

        analyzer = DomainAnalyzer(llm_client=mock_llm, heuristic_registry=registry)
        result = await analyzer.analyze_domain("billing", [pack])

        assert result.grade == "B"
        assert result.score == 80
