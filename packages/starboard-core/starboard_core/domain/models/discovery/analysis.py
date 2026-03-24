"""Discovery analysis types.

Pydantic models for LLM structured output during domain analysis.
All cost metrics expressed in DBUs (never dollars).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Evidence(BaseModel):
    """A concrete data point supporting a finding.

    Args:
        source_query_id: Which query produced this evidence.
        excerpt: Verbatim data excerpt (short, high-signal).
        metric_name: Name of the metric (e.g., "dbus_consumed", "failure_rate").
        metric_value: Value of the metric (DBUs for cost, seconds for time,
            percentage for rates).
    """

    source_query_id: str
    excerpt: str
    metric_name: str | None = None
    metric_value: str | None = None


class LikelyCause(BaseModel):
    """A potential root cause for a finding.

    Args:
        description: What may be causing the issue.
        is_hypothesis: True if not directly proven by evidence.
        how_to_confirm: Steps to validate this hypothesis.
    """

    description: str
    is_hypothesis: bool = False
    how_to_confirm: str | None = None


class Remediation(BaseModel):
    """Structured remediation plan with time horizons.

    Args:
        immediate: Quick wins (less than 1 week, low risk).
        medium_term: Planned improvements (1-4 weeks).
        long_term: Structural changes (1+ months).
    """

    immediate: list[str] = Field(default_factory=list)
    medium_term: list[str] = Field(default_factory=list)
    long_term: list[str] = Field(default_factory=list)


FindingType = Literal[
    "PERFORMANCE",
    "COST_OPTIMIZATION",
    "RELIABILITY",
    "GOVERNANCE",
    "SECURITY",
    "DATA_QUALITY",
    "OBSERVABILITY",
    "CONFIGURATION",
]

Priority = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
ImpactLevel = Literal["HIGH", "MEDIUM", "LOW"]
Grade = Literal["A", "B", "C", "D", "F"]


class DiscoveryFinding(BaseModel):
    """A scored, evidence-based finding from workspace analysis.

    Impact is scored across three dimensions:

    - DBU consumption (never dollars)
    - Runtime / latency
    - Reliability / throughput

    Args:
        finding_id: Unique ID (e.g., "F-001").
        title: One-line summary.
        priority: Overall priority ranking.
        impact: How significant the effect is.
        effort: Estimated remediation effort.
        confidence: Confidence in the finding based on available evidence.
        finding_type: Category of the finding.
        domain: Which domain this finding belongs to.
        description: Detailed explanation.
        evidence: Supporting data points.
        likely_causes: Root cause analysis.
        remediation: Structured fix plan.
        expected_outcome: What improves if fixed.
    """

    finding_id: str
    title: str
    priority: Priority
    impact: ImpactLevel
    effort: ImpactLevel
    confidence: ImpactLevel
    finding_type: FindingType
    domain: str
    description: str
    evidence: list[Evidence] = Field(default_factory=list)
    likely_causes: list[LikelyCause] = Field(default_factory=list)
    remediation: Remediation = Field(default_factory=Remediation)
    expected_outcome: str = ""


class DataCoverage(BaseModel):
    """Describes data completeness for a domain analysis.

    Args:
        queries_executed: How many queries were attempted.
        queries_succeeded: How many returned data.
        time_range_start: Earliest date in the data.
        time_range_end: Latest date in the data.
        gaps: Known gaps or limitations.
    """

    queries_executed: int = 0
    queries_succeeded: int = 0
    time_range_start: date | None = None
    time_range_end: date | None = None
    gaps: list[str] = Field(default_factory=list)


_BULLET_PREFIX = re.compile(r"^\s*[-*•]\s+")


def _coerce_str_to_list(value: Any) -> list[str] | Any:
    """Coerce a markdown bullet-point string into a list of strings.

    LLMs sometimes return ``list[str]`` fields as a single string with
    embedded bullet points (e.g. ``"\\n- item one\\n- item two"``).
    This helper splits on newlines, strips bullet prefixes from each
    line, and filters blanks so Pydantic validation succeeds without
    losing data.

    Returns the value unchanged if it is not a string.
    """
    if not isinstance(value, str):
        return value
    lines = value.strip().splitlines()
    items = [_BULLET_PREFIX.sub("", line).strip() for line in lines]
    return [item for item in items if item]


class DomainAnalysis(BaseModel):
    """Complete health assessment for a single domain.

    Grade interpretation:

    - A (90-100): Excellent -- best practices followed, efficient, well-governed
    - B (75-89): Good -- minor issues, room for improvement
    - C (60-74): Fair -- significant gaps in one or more dimensions
    - D (40-59): Poor -- major issues requiring attention
    - F (0-39): Critical -- fundamental problems, immediate action needed

    Args:
        domain: Domain identifier.
        grade: Letter grade (A-F).
        score: Numeric score (0-100).
        summary: 2-3 sentence overview.
        observations: Factual observations with citations.
        patterns: Hotspots, concentrations, outliers.
        findings: Scored findings for this domain.
        recommended_actions: Concrete next steps (3-7 items).
        data_coverage: What data was available.
    """

    domain: str
    grade: Grade
    score: float = Field(ge=0, le=100)
    summary: str
    observations: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    findings: list[DiscoveryFinding] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    data_coverage: DataCoverage = Field(default_factory=DataCoverage)

    @field_validator("observations", "patterns", "recommended_actions", mode="before")
    @classmethod
    def _coerce_bullet_strings(cls, v: Any) -> list[str] | Any:
        return _coerce_str_to_list(v)
