# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Per-domain LLM analysis prompt templates and prompt builder (Jinja2 v2).

Migrated from str.format() to Jinja2 templates in Wave 20260329.
Each domain gets a specialized prompt that guides the LLM to evaluate
query results and heuristic findings, producing a graded DomainAnalysis.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starboard_server.prompts.jinja_env import render_template
from starboard_server.tools.domain.analytics.dataframe_profiler import (
    profile_dataframe,
)

if TYPE_CHECKING:
    from starboard_core.domain.models.discovery.query import QueryResult

    from starboard_server.discovery.heuristics.base import HeuristicFinding

PROMPT_VERSION = "2.0.0"

# Map domain names to Jinja2 template paths
DOMAIN_TEMPLATE_MAP: dict[str, str] = {
    "billing": "discovery_analysis/billing.jinja2",
    "jobs": "discovery_analysis/jobs.jinja2",
    "compute": "discovery_analysis/compute.jinja2",
    "query_perf": "discovery_analysis/query_perf.jinja2",
    "query_performance": "discovery_analysis/query_perf.jinja2",
    "governance": "discovery_analysis/governance.jinja2",
}

_GENERIC_TEMPLATE = "discovery_analysis/generic.jinja2"


class PromptBuilder:
    """Builds domain-specific analysis prompts using Jinja2 templates.

    Converts raw query results and heuristic
    findings into structured text for LLM consumption.
    """

    def build_domain_prompt(
        self,
        domain: str,
        query_results: list[QueryResult],
        heuristic_findings: list[HeuristicFinding],
    ) -> str:
        """Build the full analysis prompt for a domain.

        Args:
            domain: Domain identifier (e.g., "billing", "jobs").
            query_results: Query execution results for this domain.
            heuristic_findings: Pre-screened heuristic findings.

        Returns:
            Fully rendered prompt string ready for LLM consumption.
        """
        template_path = DOMAIN_TEMPLATE_MAP.get(domain, _GENERIC_TEMPLATE)

        results_text = self._format_query_results(query_results)
        heuristics_text = self._format_heuristic_findings(heuristic_findings)

        return render_template(
            template_path,
            query_results=results_text,
            heuristic_findings=heuristics_text,
            domain_name=domain.replace("_", " ").title(),
        )

    def _format_query_results(self, results: list[QueryResult]) -> str:
        """Format query results into structured text for the prompt."""
        if not results:
            return "No query results available for this domain."

        sections: list[str] = []
        for result in results:
            header = f"### {result.query_id}: {result.domain}"
            if result.error:
                sections.append(f"{header}\n**Error:** {result.error}")
                continue

            if result.data is not None and len(result.data) > 0:
                profile = profile_dataframe(result.data)
                profile_json = json.dumps(profile, indent=2, default=str)
                sections.append(
                    f"{header}\n"
                    f"- Rows: {result.row_count}\n"
                    f"- Execution time: {result.execution_time_ms}ms\n"
                    f"- Data profile:\n```json\n{profile_json}\n```"
                )
            else:
                sections.append(f"{header}\n- No data returned (0 rows)")

        return "\n\n".join(sections)

    def _format_heuristic_findings(
        self, findings: list[HeuristicFinding]
    ) -> str:
        """Format heuristic findings into structured text for the prompt."""
        if not findings:
            return "No heuristic findings flagged for this domain."

        lines: list[str] = []
        for finding in findings:
            lines.append(
                f"- **[{finding.severity}] {finding.rule_id}: "
                f"{finding.title}**\n"
                f"  {finding.description}\n"
                f"  Evidence query: {finding.evidence_query_id} | "
                f"Threshold: {finding.threshold} | Actual: {finding.actual_value}"
            )

        return "\n".join(lines)
