# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Per-domain LLM analysis prompt templates and prompt builder.

Each domain gets a specialized prompt that guides the LLM to evaluate
query results and heuristic findings, producing a graded DomainAnalysis.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starboard_server.tools.domain.analytics.dataframe_profiler import (
    profile_dataframe,
)

if TYPE_CHECKING:
    from starboard_core.domain.models.discovery.query import QueryResult

    from starboard_server.discovery.heuristics.base import HeuristicFinding

DOMAIN_ANALYSIS_PREAMBLE = """\
## Non-negotiable Rules
- **Evidence-only**: Do not invent data. Every claim must be supported by the query results below.
- **Facts vs hypotheses**: If you propose a cause not directly proven by evidence, label it \
**Hypothesis** and include **How to confirm**.
- **DBUs only**: Express all resource consumption in DBUs. Never use dollar amounts.
- **Cite everything material**: Reference the source query ID for any claim about DBUs, \
runtime, failures, configuration, or behavior.
- **No filler**: Prefer specific findings over generic best practices.
- **Be thorough**: Extract every actionable signal from the data. Do not summarize away \
important details — each distinct issue should be its own finding.

## Evaluation Dimensions
Evaluate across ALL of these dimensions (weight varies by domain):
- **Performance**: Runtime, latency, throughput, efficiency
- **Reliability**: Failure rates, retries, error patterns, stability
- **Resource Consumption**: DBU usage, waste, growth trends
- **Governance**: Attribution, tagging, access controls, lineage
- **Configuration**: Best-practice alignment, optimization opportunities

## Workload Breakdown
For each domain, identify and characterize the distinct workloads:
- **Name or identifier** of each significant workload (job name, warehouse, cluster, table, etc.)
- **Volume**: DBU consumption, run count, query count, or other relevant metric
- **Health signal**: Is this workload healthy, degrading, or problematic?
- Surface the **top 10-15 individual workloads** by impact in your observations/patterns.

## Scoring
- Grade: A (90-100), B (75-89), C (60-74), D (40-59), F (0-39)
- Weight findings by severity and breadth of impact
- A grade of "A" means excellence across all dimensions, not just absence of problems
"""

BILLING_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing resource consumption and attribution data.

## Focus Areas
- **Attribution quality**: How well are DBUs attributed to teams, projects, identities?
- **Consumption efficiency**: Are there concentration risks, waste patterns, or growth anomalies?
- **Trend stability**: Is consumption predictable or volatile?
- **Governance maturity**: Tagging coverage, chargeback readiness, identity attribution

## Grading Rubric
- **A (90-100)**: DBUs well-attributed (>90% tagged), stable trends, no concentration risk, \
good identity coverage
- **B (75-89)**: Minor attribution gaps, slight growth anomalies, mostly tagged
- **C (60-74)**: Significant untagged DBUs (>30%), noticeable concentration, or consumption spikes
- **D (40-59)**: Major governance gaps, uncontrolled growth, poor attribution
- **F (0-39)**: Critical attribution failures, no tagging, extreme concentration

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

JOBS_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing job workload health and reliability.

## Focus Areas
- **Reliability**: Failure rates, retry patterns, error concentration
- **Performance consistency**: Runtime variance, SLA risk, duration trends
- **Resource efficiency**: DBU consumption per unit of work, over-provisioned jobs
- **Operational maturity**: Monitoring coverage, alerting, pipeline structure
- **DLT health**: Pipeline update performance, failure patterns (if data available)

## Grading Rubric
- **A (90-100)**: <5% failure rate, low runtime variance (CV <0.3), efficient DBU/min, \
good retry discipline
- **B (75-89)**: 5-10% failure rate, moderate variance, minor inefficiencies
- **C (60-74)**: 10-15% failure rate, high variance, some retry storms
- **D (40-59)**: >15% failure rate, unpredictable runtimes, significant waste
- **F (0-39)**: Systemic failures, no reliability patterns, major DBU waste

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

COMPUTE_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing compute infrastructure health.

## Focus Areas
- **Right-sizing**: Are clusters appropriately sized for their workloads?
- **Idle waste**: Auto-termination settings, idle time percentage
- **Configuration hygiene**: Auto-scaling, Photon adoption, runtime versions
- **Warehouse health**: Queue times, scaling behavior, error patterns
- **Modernization**: Serverless readiness, Photon migration candidates

## Grading Rubric
- **A (90-100)**: Clusters right-sized, <10% idle, auto-termination ≤60 min, \
auto-scaling enabled, low queue times
- **B (75-89)**: Minor sizing issues, 10-20% idle, reasonable auto-termination
- **C (60-74)**: Several oversized clusters, 20-40% idle, some missing auto-termination
- **D (40-59)**: Widespread over-provisioning, >40% idle, poor configuration
- **F (0-39)**: Clusters running unbounded, extreme waste, no governance

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

QUERY_PERF_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing SQL query performance and efficiency.

## Focus Areas
- **Query efficiency**: Spill, skew, scan volume, compile time
- **Caching effectiveness**: Hit rates, repeated query patterns
- **Concurrency management**: Queue times, peak utilization, scaling behavior
- **Error patterns**: Failure types, error concentration, retry impact
- **Optimization opportunities**: Repeated queries, missing optimizations, inefficient patterns

## Grading Rubric
- **A (90-100)**: No significant spill/skew, good cache rates (>60%), low error rate (<1%), \
well-managed concurrency
- **B (75-89)**: Minor spill/skew issues, moderate cache rates, low errors
- **C (60-74)**: Noticeable spill (>1GB) or skew (>5x), repeated query waste, some errors
- **D (40-59)**: Widespread performance issues, poor caching, high error rate
- **F (0-39)**: Critical performance problems, frequent failures, no optimization

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

GOVERNANCE_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing data governance and Unity Catalog health.

## Focus Areas
- **Access control**: Permission patterns, least-privilege adherence, sprawl
- **Data lineage**: Coverage, downstream impact tracking, dependency mapping
- **Data lifecycle**: Table freshness, stale data detection, storage hygiene
- **Delta table health**: File compaction, OPTIMIZE cadence, small file problems
- **Audit coverage**: What is tracked, what gaps exist

## Grading Rubric
- **A (90-100)**: >90% lineage coverage, least-privilege permissions, tables well-maintained, \
comprehensive audit logs
- **B (75-89)**: Good lineage, minor permission issues, most tables healthy
- **C (60-74)**: Significant lineage gaps (>30% missing), some permission sprawl, \
stale tables accumulating
- **D (40-59)**: Poor lineage, widespread permission issues, many unhealthy tables
- **F (0-39)**: No lineage, uncontrolled permissions, severe data quality risks

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

GENERIC_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing {domain_name} usage and health.

## Focus Areas
- **Adoption**: How actively is this product being used?
- **Resource efficiency**: DBU consumption relative to usage volume
- **Idle/zombie detection**: Resources provisioned but not actively used
- **Configuration**: Are best practices followed?
- **Operational maturity**: Monitoring, alerting, lifecycle management

## Grading Rubric
- **A (90-100)**: Active usage, efficient consumption, no zombie resources, well-configured
- **B (75-89)**: Active with minor inefficiencies
- **C (60-74)**: Underutilized or some waste detected
- **D (40-59)**: Significant waste or misconfiguration
- **F (0-39)**: Provisioned but barely used, or critical issues

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

DLT_PIPELINES_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing Delta Live Tables (DLT) pipeline health.

## Focus Areas
- **Pipeline reliability**: Update failure rates, frequent failures, error patterns
- **Performance**: Long-running updates, p95 duration outliers, slow target tables
- **Resource efficiency**: DBU consumption per pipeline, serverless migration candidates
- **Lifecycle management**: Stale/abandoned pipelines, continuous vs triggered balance
- **Configuration**: Edition selection, Photon adoption, serverless usage

## Grading Rubric
- **A (90-100)**: <5% failure rate, efficient update durations, no stale pipelines, \
serverless where applicable, good Photon adoption
- **B (75-89)**: 5-10% failure rate, minor duration outliers, few stale pipelines
- **C (60-74)**: 10-20% failure rate, several long-running updates, stale pipelines present
- **D (40-59)**: >20% failure rate, widespread duration issues, many abandoned pipelines
- **F (0-39)**: Systemic pipeline failures, extreme waste, no lifecycle management

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

AI_GATEWAY_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing AI Gateway and model serving health.

## Focus Areas
- **Endpoint reliability**: Error rates, server errors, success ratios
- **Latency profile**: Average and p95 latency, latency outliers
- **Token efficiency**: Token consumption patterns, cost attribution by requester
- **Capacity**: Request volumes, peak patterns, scaling behavior
- **Cost governance**: Per-requester chargeback readiness, token budget adherence

## Grading Rubric
- **A (90-100)**: <1% error rate, p95 latency <5s, tokens well-attributed, \
balanced load across endpoints
- **B (75-89)**: 1-3% error rate, occasional latency spikes, mostly attributed
- **C (60-74)**: 3-5% error rate, frequent latency issues, attribution gaps
- **D (40-59)**: >5% error rate, poor latency, uncontrolled token spending
- **F (0-39)**: Systemic endpoint failures, extreme latency, no cost governance

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

MLFLOW_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing MLflow experiment and model lifecycle health.

## Focus Areas
- **Experiment health**: Success ratios, noisy experiments, reliability patterns
- **Usage patterns**: Run volume trends, active vs deleted experiments, user activity
- **Resource efficiency**: Long-running runs, experiment lifecycle management
- **Governance**: Soft-deleted experiment cleanup, user attribution, experiment naming
- **Adoption maturity**: Run frequency, user diversity, experiment organization

## Grading Rubric
- **A (90-100)**: >90% success ratio, well-organized experiments, no stale artifacts, \
active user base, clean lifecycle
- **B (75-89)**: 80-90% success, minor cleanup needed, good user adoption
- **C (60-74)**: 70-80% success, noisy experiments present, some stale artifacts
- **D (40-59)**: <70% success, many noisy experiments, poor experiment hygiene
- **F (0-39)**: Systemic run failures, abandoned experiments, no governance

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

LAKEFLOW_CONNECT_ANALYSIS_PROMPT = (
    DOMAIN_ANALYSIS_PREAMBLE
    + """\
## Role
You are a Databricks platform expert analyzing Lakeflow Connect ingestion health.

## Focus Areas
- **Ingestion volume**: DBU consumption trends, workspace distribution
- **Pipeline efficiency**: Per-pipeline cost, connector type breakdown
- **Growth patterns**: Day-over-day consumption trends, spikes
- **Configuration**: Connector type mix (ingestion pipeline, gateway, table sync)
- **Cost governance**: Attribution to specific pipelines and creators

## Grading Rubric
- **A (90-100)**: Stable ingestion patterns, well-attributed costs, diverse connector usage, \
no unexpected spikes
- **B (75-89)**: Minor cost fluctuations, mostly attributed, reasonable growth
- **C (60-74)**: Noticeable cost spikes, some unattributed usage, concentrated on few pipelines
- **D (40-59)**: Volatile costs, poor attribution, growth concerns
- **F (0-39)**: Uncontrolled consumption, no visibility into pipeline costs

## Heuristic Findings (pre-screened)
{heuristic_findings}

## Query Results
{query_results}

Produce a DomainAnalysis JSON object with grade, score, summary, observations (include workload \
breakdown details), patterns, findings (10-15, one per distinct issue), \
recommended_actions (5-10), and data_coverage.
"""
)

DOMAIN_PROMPT_TEMPLATES: dict[str, str] = {
    "billing": BILLING_ANALYSIS_PROMPT,
    "jobs": JOBS_ANALYSIS_PROMPT,
    "compute": COMPUTE_ANALYSIS_PROMPT,
    "query_perf": QUERY_PERF_ANALYSIS_PROMPT,
    "query_performance": QUERY_PERF_ANALYSIS_PROMPT,
    "governance": GOVERNANCE_ANALYSIS_PROMPT,
    # Phase 4 additions
    "dlt_pipelines": DLT_PIPELINES_ANALYSIS_PROMPT,
    "ai_gateway": AI_GATEWAY_ANALYSIS_PROMPT,
    "mlflow": MLFLOW_ANALYSIS_PROMPT,
    "lakeflow_connect": LAKEFLOW_CONNECT_ANALYSIS_PROMPT,
}


class PromptBuilder:
    """Builds prompts for domain analysis and report synthesis.

    Responsible for selecting the appropriate prompt template, formatting
    query results via the dataframe profiler, and serializing heuristic
    findings into structured text for LLM consumption.
    """

    def build_domain_prompt(
        self,
        domain: str,
        query_results: list[QueryResult],
        heuristic_findings: list[HeuristicFinding],
    ) -> str:
        """Build the analysis prompt for a specific domain.

        Args:
            domain: The domain being analyzed (e.g. "billing", "jobs").
            query_results: Query results for this domain.
            heuristic_findings: Pre-screened heuristic findings.

        Returns:
            Fully interpolated prompt string ready for LLM consumption.
        """
        template = DOMAIN_PROMPT_TEMPLATES.get(domain, GENERIC_ANALYSIS_PROMPT)

        results_text = self._format_query_results(query_results)
        heuristics_text = self._format_heuristic_findings(heuristic_findings)

        return template.format(
            query_results=results_text,
            heuristic_findings=heuristics_text,
            domain_name=domain.replace("_", " ").title(),
        )

    def _format_query_results(self, results: list[QueryResult]) -> str:
        """Profile and format query results for LLM consumption.

        Args:
            results: List of query results with DataFrames.

        Returns:
            Formatted string with profiled DataFrame summaries.
        """
        sections: list[str] = []
        for r in results:
            if r.data is None or r.data.is_empty():
                sections.append(
                    f"### {r.query_id}: {r.domain}\n"
                    f"No data (query failed or returned empty)"
                )
                continue

            profile = profile_dataframe(r.data)
            profile_str = json.dumps(profile, indent=2, default=str)
            sections.append(
                f"### {r.query_id}\n"
                f"Rows: {r.row_count}\n"
                f"Execution time: {r.execution_time_ms:.0f}ms\n\n"
                f"{profile_str}"
            )
        return "\n\n".join(sections) if sections else "No query results available."

    def _format_heuristic_findings(self, findings: list[HeuristicFinding]) -> str:
        """Format heuristic findings as structured text.

        Args:
            findings: List of heuristic findings.

        Returns:
            Formatted markdown-style list of findings, or a note if empty.
        """
        if not findings:
            return "No heuristic violations detected."

        lines: list[str] = []
        for f in findings:
            lines.append(
                f"- **[{f.severity}] {f.rule_id}: {f.title}**\n"
                f"  Threshold: {f.threshold} | Actual: {f.actual_value}\n"
                f"  Source: {f.evidence_query_id}\n"
                f"  {f.description}"
            )
        return "\n".join(lines)
