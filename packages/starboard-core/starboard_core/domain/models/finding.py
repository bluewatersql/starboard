# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared review ``Finding`` model + priority scorer (Phase-1 D3).

This is the kernel-tier output contract shared by the seed rules (this phase)
and the Phase-3 Workload Review flow (D1). It is **pure pydantic** and stays
kernel-clean — no ``databricks-sdk`` / ``openai`` / ``fastapi`` / ``mcp``.

Design harvested from two public/internal review methodologies (paraphrased,
no internal namespaces — see ``changes/2026_26_25_agents/internal_harvest``):

- **Finding shape** — rationale + current-state/"bad" + suggested-fix/"good" +
  severity (the review comment schema).
- **Priority scorer** — ``score = (severity_weight x impact) / effort_points``
  bucketed into *Fix Immediately / This Sprint / Backlog / Nice-to-Have*, with
  ``severity {Critical=4, High=3, Medium=2, Low=1}`` and
  ``effort {XS=1, S=2, M=3, L=4, XL=5}``.

Note:
    ``starboard_core.domain.models`` already exports an unrelated ``Finding``
    (the LLM optimizer-report finding, ``llm_schemas.Finding``). This review
    ``Finding`` intentionally lives in its own module and is **not** re-exported
    from ``models/__init__`` to avoid shadowing that name. Import it explicitly:
    ``from starboard_core.domain.models.finding import Finding``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
)


class Severity(StrEnum):
    """Finding severity — drives the priority weight in the scorer."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Effort(StrEnum):
    """Remediation effort (t-shirt sizing) — the scorer divisor."""

    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class Confidence(StrEnum):
    """Confidence that the finding is real and actionable."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Bucket(StrEnum):
    """Priority bucket derived from the score."""

    FIX_IMMEDIATELY = "Fix Immediately"
    THIS_SPRINT = "This Sprint"
    BACKLOG = "Backlog"
    NICE_TO_HAVE = "Nice-to-Have"


# --- Scorer weights (elt-review synthesizer formula) -------------------------
SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
}

EFFORT_POINTS: dict[Effort, int] = {
    Effort.XS: 1,
    Effort.S: 2,
    Effort.M: 3,
    Effort.L: 4,
    Effort.XL: 5,
}

# Score thresholds (inclusive lower bound) for each bucket, high to low.
FIX_IMMEDIATELY_THRESHOLD = 20.0
THIS_SPRINT_THRESHOLD = 10.0
BACKLOG_THRESHOLD = 4.0


def score(severity: Severity, impact: int, effort: Effort) -> float:
    """Compute ``(severity_weight x impact) / effort_points``.

    Args:
        severity: Finding severity (maps to a weight 1-4).
        impact: Impact multiplier on a 1-5 scale.
        effort: Remediation effort (maps to divisor points 1-5).

    Returns:
        The raw priority score (higher = more urgent per unit of effort).
    """
    return (SEVERITY_WEIGHTS[severity] * impact) / EFFORT_POINTS[effort]


def bucket_for_score(value: float) -> Bucket:
    """Map a raw score to a priority bucket (thresholds inclusive)."""
    if value >= FIX_IMMEDIATELY_THRESHOLD:
        return Bucket.FIX_IMMEDIATELY
    if value >= THIS_SPRINT_THRESHOLD:
        return Bucket.THIS_SPRINT
    if value >= BACKLOG_THRESHOLD:
        return Bucket.BACKLOG
    return Bucket.NICE_TO_HAVE


def score_and_bucket(
    severity: Severity, impact: int, effort: Effort
) -> tuple[float, Bucket]:
    """Return the raw ``(score, bucket)`` for a severity/impact/effort triple."""
    value = score(severity, impact, effort)
    return value, bucket_for_score(value)


class Location(BaseModel):
    """Where a finding applies — a file, table, or generic entity reference."""

    model_config = ConfigDict(frozen=True)

    file: str | None = Field(default=None, description="Source file path")
    line: int | None = Field(default=None, description="Line number (1-based)")
    table: str | None = Field(default=None, description="Fully-qualified table name")
    entity: str | None = Field(
        default=None, description="Generic entity id (job/query/warehouse id)"
    )
    entity_type: str | None = Field(
        default=None, description="Entity kind: job, query, warehouse, cluster, ..."
    )

    def key(self) -> tuple[str | None, int | None, str | None, str | None]:
        """Stable identity used to merge duplicate findings."""
        return (self.file, self.line, self.table, self.entity)


class Finding(BaseModel):
    """A single review finding (kernel-tier output contract).

    Fields harvested from the Isaac ``/review`` comment schema and the
    ``databricks-elt-review`` synthesizer (paraphrased):
    rationale + current-state/"bad" + suggested-fix/"good" + severity, plus the
    ``impact`` / ``effort`` / ``confidence`` inputs the scorer consumes.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Stable finding identifier", min_length=1)
    severity: Severity = Field(..., description="Severity level")
    category: str = Field(
        ..., description="Domain category (query, cluster, uc, warehouse, ...)"
    )
    summary: str = Field(..., description="One-line summary of the finding")
    rationale: str = Field(
        ..., description="Why this matters — used to judge edge cases"
    )
    current_state: str = Field(
        ...,
        validation_alias=AliasChoices("current_state", "bad"),
        serialization_alias="current_state",
        description="Observed state / the 'bad' pattern",
    )
    suggested_fix: str = Field(
        ...,
        validation_alias=AliasChoices("suggested_fix", "good"),
        serialization_alias="suggested_fix",
        description="Recommended remediation / the 'good' pattern",
    )
    impact: int = Field(
        ..., ge=1, le=5, description="Impact multiplier on a 1-5 scale"
    )
    effort: Effort = Field(..., description="Remediation effort (XS-XL)")
    confidence: Confidence = Field(
        default=Confidence.MEDIUM, description="Confidence the finding is real"
    )
    location: Location | None = Field(
        default=None, description="Where the finding applies"
    )
    rule_id: str | None = Field(
        default=None, description="Originating rule id, if produced by a rule"
    )
    source: str | None = Field(
        default=None,
        description="Public reference for the finding (nullable; no internal links)",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score(self) -> float:
        """Priority score ``(severity_weight x impact) / effort_points``."""
        return score(self.severity, self.impact, self.effort)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bucket(self) -> Bucket:
        """Priority bucket derived from :pyattr:`score`."""
        return bucket_for_score(self.score)


# Severity ordering for dedup tie-breaks (higher index = more severe).
_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """Merge findings that share a concrete location, keeping the most severe.

    Mirrors the ``databricks-elt-review`` synthesizer's dedup step (merge same
    location, keep the highest severity). Findings without a location, or whose
    location has no identifying fields, are always preserved (never merged).

    Order is stable: the first occurrence position of each surviving finding is
    preserved.
    """
    merged: dict[tuple[str | None, int | None, str | None, str | None], int] = {}
    result: list[Finding] = []
    for finding in findings:
        loc_key = finding.location.key() if finding.location else None
        # Preserve findings with no identifying location.
        if loc_key is None or all(part is None for part in loc_key):
            result.append(finding)
            continue
        if loc_key not in merged:
            merged[loc_key] = len(result)
            result.append(finding)
            continue
        existing_idx = merged[loc_key]
        existing = result[existing_idx]
        if _SEVERITY_ORDER[finding.severity] > _SEVERITY_ORDER[existing.severity]:
            result[existing_idx] = finding
    return result
