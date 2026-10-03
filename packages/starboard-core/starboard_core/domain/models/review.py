# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Workload-review output models — evidence-cited findings (Phase-3 D1b).

The Workload Review flow (D1b) runs the relevant query packs for a workspace,
feeds the returned rows to the kernel :class:`~starboard_core.domain.rules.registry.RuleRegistry`,
and emits a ranked set of :class:`~starboard_core.domain.models.finding.Finding`
objects **with evidence citations**. Each citation references the pack
``query_id`` that produced the evidence and the row(s) that triggered the rule.

This module adds only the D1b *output contract* on top of the Phase-1 D3
``Finding`` schema — it does **not** modify ``Finding``. Kernel-clean: pure
pydantic, no ``databricks-sdk`` / ``openai`` / ``fastapi`` / ``mcp``. The
SDK-touching pack execution lives in the ``starboard`` server tier; this module
only describes the result it produces.

**$ semantics (PHASE_3 D-3.8):** the public review path never emits a
finance-grade dollar figure. D1b findings are DBU / utilization based; any cost
framing is a **list-price DBU estimate**, surfaced via :pyattr:`WorkloadReview.cost_basis`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from starboard_core.domain.models.finding import Finding

# The public cost basis label (D-3.8): the public review path is DBU-only and
# never emits a finance-grade dollar figure.
COST_BASIS_LABEL = "DBU list-price estimate (public data; not a finance-grade figure)"

# The cost basis label when the evidence came from workspace telemetry rather
# than the workspace's own public system tables (e.g. a no-connect review). Same
# list-price DBU semantics; only the data-provenance wording differs.
TELEMETRY_COST_BASIS_LABEL = (
    "DBU list-price estimate (workspace telemetry; not a finance-grade figure)"
)


class EvidenceRef(BaseModel):
    """A citation tying a finding to the query-pack row that triggered it.

    Args:
        query_id: The pack ``query_id`` whose result supplied the evidence
            (e.g. ``"W-W02"``). Matches a rule's ``evidence_query``.
        row_index: Position of the triggering row within the query result
            (0-based), for reproducibility.
        row: The triggering row as a plain dict (the evidence itself). Kept
            verbatim so a reader can audit exactly what fired the rule.
    """

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(..., description="Pack query_id that supplied the evidence")
    row_index: int | None = Field(
        default=None, description="0-based index of the triggering row"
    )
    row: dict[str, Any] = Field(
        default_factory=dict, description="The triggering row (verbatim evidence)"
    )


class ReviewFinding(BaseModel):
    """A single review finding paired with its evidence citations.

    Wraps the Phase-1 D3 :class:`Finding` (which carries the severity / impact /
    effort the scorer consumes) with one or more :class:`EvidenceRef` citations.
    """

    model_config = ConfigDict(frozen=True)

    finding: Finding = Field(..., description="The scored review finding")
    evidence: tuple[EvidenceRef, ...] = Field(
        default=(), description="Query-pack citations that triggered the finding"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Evidence-quality annotations. ``evidence_capped: true`` = the "
            "evidence query hit its row limit, so the flagged population may "
            "be larger than the cited rows."
        ),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score(self) -> float:
        """Priority score of the wrapped finding (convenience accessor)."""
        return self.finding.score


class DomainReport(BaseModel):
    """Per-domain summary of what the review evaluated and whether it degraded.

    Args:
        domain: The requested review domain (``"jobs"`` / ``"sql"`` /
            ``"warehouse"``).
        rule_domain: The seed-ruleset domain the review evaluated for this
            domain (``"query"`` / ``"warehouse"`` / ``"uc"`` / ``"jobs"``).
        rules_evaluated: Number of enabled rules considered for this domain.
        evidence_query_ids: Distinct evidence ``query_id`` values the rules
            referenced.
        degraded: True when one or more evidence queries failed or returned no
            data, so findings for this domain may be partial.
        degraded_reason: Human-readable note describing the degradation.
        finding_count: Number of findings produced for this domain.
        unavailable_query_ids: Evidence queries that failed, were skipped, or
            were not run — the reason the domain is degraded.
        evidence_capped_query_ids: Evidence queries whose result hit its row
            limit (findings from them carry ``evidence_capped``).
        suppressed_rules: Rules deliberately not evaluated, keyed by rule id,
            with the reason (e.g. a required evidence column is unavailable).
        capped_rules: Findings dropped by the per-rule dedupe/cap, keyed by
            rule id (so one rule cannot dominate the review).
    """

    model_config = ConfigDict(frozen=True)

    domain: str
    rule_domain: str
    rules_evaluated: int = 0
    evidence_query_ids: tuple[str, ...] = ()
    degraded: bool = False
    degraded_reason: str | None = None
    finding_count: int = 0
    unavailable_query_ids: tuple[str, ...] = ()
    evidence_capped_query_ids: tuple[str, ...] = ()
    suppressed_rules: dict[str, str] = Field(default_factory=dict)
    capped_rules: dict[str, int] = Field(default_factory=dict)


class WorkloadReview(BaseModel):
    """The ranked, evidence-cited output of a Workload Review run (D1b).

    Args:
        workspace: The reviewed workspace identifier (profile / host / id), or
            ``None`` when not provided (e.g. the pure helper path).
        requested_domains: The domains the caller asked to review.
        findings: Findings in stable priority order (score desc, severity desc,
            id asc) — see :func:`~starboard_core.domain.rules.evaluator.rank_review_findings`.
        domain_reports: Per-domain evaluation summaries (coverage + degradation).
        cost_basis: The $ basis label (D-3.8); DBU list-price estimate. Derived
            from the evidence source (public system tables vs. workspace
            telemetry).
    """

    model_config = ConfigDict(frozen=True)

    workspace: str | None = Field(default=None)
    requested_domains: tuple[str, ...] = ()
    findings: tuple[ReviewFinding, ...] = ()
    domain_reports: tuple[DomainReport, ...] = ()
    cost_basis: str = Field(default=COST_BASIS_LABEL)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def finding_count(self) -> int:
        """Total number of findings across all domains."""
        return len(self.findings)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def degraded(self) -> bool:
        """True when any reviewed domain degraded (partial evidence)."""
        return any(report.degraded for report in self.domain_reports)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unavailable_queries(self) -> tuple[str, ...]:
        """Sorted evidence ``query_id`` values that were unavailable (any domain)."""
        return tuple(
            sorted(
                {qid for r in self.domain_reports for qid in r.unavailable_query_ids}
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unavailable_domains(self) -> tuple[str, ...]:
        """Requested domains that degraded (partial or no evidence), in order."""
        return tuple(r.domain for r in self.domain_reports if r.degraded)


__all__ = [
    "COST_BASIS_LABEL",
    "TELEMETRY_COST_BASIS_LABEL",
    "DomainReport",
    "EvidenceRef",
    "ReviewFinding",
    "WorkloadReview",
]
