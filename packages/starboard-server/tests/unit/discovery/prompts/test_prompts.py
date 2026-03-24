"""Tests for discovery prompt module and PromptBuilder.

Tests cover:
- PROMPT_VERSION and PROMPT_METADATA
- DOMAIN_PROMPT_TEMPLATES structure
- Preamble and placeholder presence in templates
- PromptBuilder: domain prompts, generic fallback, empty results, heuristic formatting
"""

from __future__ import annotations

import polars as pl
from starboard_core.domain.models.discovery.query import QueryResult
from starboard_server.discovery.heuristics.base import HeuristicFinding
from starboard_server.discovery.prompts.domain_analysis import (
    DOMAIN_PROMPT_TEMPLATES,
    GENERIC_ANALYSIS_PROMPT,
    PromptBuilder,
)
from starboard_server.discovery.prompts.v1 import PROMPT_METADATA, PROMPT_VERSION


class TestPromptVersion:
    def test_prompt_version_exists(self) -> None:
        assert PROMPT_VERSION == "1.0.0"

    def test_prompt_metadata_has_all_domains(self) -> None:
        expected = {
            "billing",
            "jobs",
            "compute",
            "query_perf",
            "governance",
            "ml",
            "migration",
            "apps",
            "lakebase",
            "vector_search",
            "delta_sharing",
            "monitoring",
            "serverless_sql",
            "workflow",
            "aibi",
        }
        assert set(PROMPT_METADATA["domains"]) == expected


class TestDomainPromptTemplates:
    def test_domain_prompt_templates_keys(self) -> None:
        assert set(DOMAIN_PROMPT_TEMPLATES.keys()) == {
            "billing",
            "jobs",
            "compute",
            "query_perf",
            "query_performance",
            "governance",
        }

    def test_all_prompts_contain_preamble(self) -> None:
        preamble_sections = [
            "Non-negotiable Rules",
            "Evaluation Dimensions",
            "Scoring",
        ]
        for template in DOMAIN_PROMPT_TEMPLATES.values():
            for section in preamble_sections:
                assert section in template, f"Missing '{section}' in domain template"

    def test_all_prompts_contain_placeholders(self) -> None:
        for template in DOMAIN_PROMPT_TEMPLATES.values():
            assert "{heuristic_findings}" in template
            assert "{query_results}" in template

    def test_generic_prompt_has_domain_name_placeholder(self) -> None:
        assert "{domain_name}" in GENERIC_ANALYSIS_PROMPT


class TestPromptBuilder:
    def test_prompt_builder_domain_prompt(self) -> None:
        builder = PromptBuilder()
        qr = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=pl.DataFrame({"col": [1, 2, 3]}),
            row_count=3,
            execution_time_ms=100.0,
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
        prompt = builder.build_domain_prompt(
            domain="billing",
            query_results=[qr],
            heuristic_findings=[hf],
        )
        assert "Test desc" in prompt
        assert "BIL-001" in prompt
        assert "C-B01" in prompt
        assert "65%" in prompt
        assert "100ms" in prompt or "100" in prompt
        assert "Rows: 3" in prompt

    def test_prompt_builder_generic_domain(self) -> None:
        builder = PromptBuilder()
        prompt = builder.build_domain_prompt(
            domain="apps",
            query_results=[],
            heuristic_findings=[],
        )
        assert "usage and health" in prompt

    def test_prompt_builder_empty_results(self) -> None:
        builder = PromptBuilder()
        prompt = builder.build_domain_prompt(
            domain="billing",
            query_results=[],
            heuristic_findings=[],
        )
        assert "No heuristic violations detected" in prompt
        assert "No query results" in prompt

    def test_prompt_builder_format_heuristic_findings(self) -> None:
        builder = PromptBuilder()
        findings = [
            HeuristicFinding(
                rule_id="BIL-001",
                domain="billing",
                title="Finding 1",
                severity="HIGH",
                dimension="consumption",
                description="Desc 1",
                evidence_query_id="C-B01",
                threshold=">50%",
                actual_value="60%",
            ),
            HeuristicFinding(
                rule_id="BIL-002",
                domain="billing",
                title="Finding 2",
                severity="MEDIUM",
                dimension="governance",
                description="Desc 2",
                evidence_query_id="C-B02",
                threshold="<90%",
                actual_value="70%",
            ),
        ]
        result = builder._format_heuristic_findings(findings)
        assert "[HIGH] BIL-001: Finding 1" in result
        assert "[MEDIUM] BIL-002: Finding 2" in result
        assert "Desc 1" in result
        assert "Desc 2" in result
        assert "60%" in result
        assert "70%" in result
        assert "C-B01" in result
        assert "C-B02" in result
