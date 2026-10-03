# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Workload Review engine — rows + rules → ranked, evidence-cited findings (D1b).

This is the deterministic heart of the Workload Review flagship. Given a
:class:`~starboard_core.domain.rules.registry.RuleRegistry` and the rows returned
by the relevant query packs (keyed by ``query_id``), it:

1. resolves each requested domain to its seed-ruleset domain,
2. runs each rule's detector (:mod:`starboard_core.domain.rules.detectors`) over
   the rows of that rule's ``evidence_query``,
3. wraps every trigger into a scored :class:`~starboard_core.domain.models.finding.Finding`
   with an :class:`~starboard_core.domain.models.review.EvidenceRef` citation
   (the ``query_id`` + the triggering row), and
4. ranks all findings into one stable total order via the D3 scorer.

It is **pure and I/O-free** — no SQL, no ``databricks-sdk``, no model calls. The
SDK-touching pack execution lives in the ``starboard`` server tier and hands the
materialized rows to :func:`build_review`; the SDK-free ``starboard_x`` helper
calls the same function with rows read from a JSON file. Detection is fully
deterministic (D1b is bounded rule evaluation; the model validator council is
D1c, out of scope here).

Evaluator-level rule params (read here, never passed to a detector):
    * ``requires_column`` — an evidence column the rule's claim depends on
      (e.g. ``statement_text``). When the evidence query returned rows but none
      carries a non-null value for it, the rule is **suppressed** (no findings)
      and the reason is recorded in ``DomainReport.suppressed_rules``.
    * ``max_findings`` — per-rule cap (default
      :data:`DEFAULT_MAX_FINDINGS_PER_RULE`; ``0`` = uncapped). Findings are
      first de-duplicated by id (highest score wins), then the top-N by score
      are kept; the dropped count is recorded in ``DomainReport.capped_rules``
      so one rule cannot dominate the review.

Findings whose evidence query hit its row limit (``limit_reached_query_ids``)
carry ``metadata["evidence_capped"] = True``.

Row contract for ``rows_by_query_id``:
    * key present with a (possibly empty) list  → the query ran; an empty list
      means "ran cleanly, nothing to flag" (**not** degraded).
    * key absent, or listed in ``failed_query_ids`` → the query did not run or
      errored; the affected domain is marked **degraded** (partial findings).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from starboard_core.domain.models.finding import (
    SEVERITY_WEIGHTS,
    Confidence,
    Finding,
)
from starboard_core.domain.models.review import (
    COST_BASIS_LABEL,
    DomainReport,
    EvidenceRef,
    ReviewFinding,
    WorkloadReview,
)
from starboard_core.domain.rules.detectors import DETECTORS, RowMatch
from starboard_core.domain.rules.registry import RuleRegistry
from starboard_core.domain.rules.schema import Rule

# Maps a caller-facing review domain to the seed-ruleset domain it evaluates.
# The v1 flagship scope (PHASE_3 D-3.7) is jobs + queries + warehouses; ``uc``
# is included for callers that opt in. Phase-2 D-a adds the opt-in DLT / ML /
# vector-search surfaces, and Phase-2 X4 adds the opt-in ``portfolio_readiness``
# workload-maturity surface (all additive — the v1 mappings and DEFAULT_DOMAINS
# are unchanged). CLI-friendly aliases (``pipelines``, ``vector-search``,
# ``portfolio-readiness``) resolve to the same rule-domain as their canonical token.
DOMAIN_TO_RULE_DOMAIN: dict[str, str] = {
    "jobs": "jobs",
    "sql": "query",
    "warehouse": "warehouse",
    "uc": "uc",
    # Phase-2 D-a opt-in domains.
    "dlt": "dlt",
    "pipelines": "dlt",
    "ml": "ml",
    "vector_search": "vector_search",
    "vector-search": "vector_search",
    # Phase-2 X4 opt-in domain (public-safe workload-maturity review).
    "portfolio_readiness": "portfolio_readiness",
    "portfolio-readiness": "portfolio_readiness",
}

# The default review scope when the caller does not restrict domains (D-3.7).
DEFAULT_DOMAINS: tuple[str, ...] = ("jobs", "sql", "warehouse")

# Per-rule finding cap when a rule declares no ``max_findings`` param. Keeps one
# noisy rule (often fed by a row-capped evidence query) from dominating the
# review and its run-over-run trend.
DEFAULT_MAX_FINDINGS_PER_RULE = 20

# Rule params consumed by the evaluator itself (stripped before the detector).
EVALUATOR_PARAM_KEYS: frozenset[str] = frozenset({"requires_column", "max_findings"})


def _finding_from_match(
    rule: Rule, query_id: str, match: RowMatch, *, evidence_capped: bool = False
) -> ReviewFinding:
    """Build a scored, evidence-cited :class:`ReviewFinding` for one trigger."""
    finding = Finding(
        id=f"{rule.id}::{match.entity_key}",
        # A detector may grade an individual trigger (e.g. by materiality);
        # otherwise the rule's default severity / impact apply.
        severity=match.severity or rule.severity,
        category=rule.category,
        summary=rule.name,
        rationale=rule.rationale,
        current_state=match.current_state,
        suggested_fix=rule.suggested_fix,
        impact=match.impact if match.impact is not None else rule.default_impact,
        effort=rule.default_effort,
        confidence=Confidence.MEDIUM,
        location=match.location,
        rule_id=rule.id,
        source=rule.source,
    )
    citation = EvidenceRef(
        query_id=query_id, row_index=match.row_index, row=match.row
    )
    return ReviewFinding(
        finding=finding,
        evidence=(citation,),
        metadata={"evidence_capped": True} if evidence_capped else {},
    )


def _max_findings(rule: Rule) -> int:
    """The rule's finding cap (``0`` = uncapped); malformed values use the default."""
    raw = rule.params.get("max_findings")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return DEFAULT_MAX_FINDINGS_PER_RULE
    return max(int(raw), 0)


def _has_column_value(rows: Sequence[dict[str, Any]], column: str) -> bool:
    """True when any row carries a non-null, non-blank value for ``column``."""
    for row in rows:
        value = row.get(column)
        if value is not None and str(value).strip() != "":
            return True
    return False


def _dedupe_and_cap(
    findings: list[ReviewFinding], cap: int
) -> tuple[list[ReviewFinding], int]:
    """De-duplicate by finding id (highest score wins), then keep the top ``cap``.

    Stable: among equal scores the detector's (evidence row) order is kept.
    Returns ``(kept, dropped_count)``.
    """
    best: dict[str, ReviewFinding] = {}
    for rf in findings:
        prior = best.get(rf.finding.id)
        if prior is None or rf.finding.score > prior.finding.score:
            best[rf.finding.id] = rf
    unique = sorted(best.values(), key=lambda rf: -rf.finding.score)
    kept = unique[:cap] if cap > 0 else unique
    return kept, len(findings) - len(kept)


def _context_rows(
    rule: Rule,
    rows_by_query_id: Mapping[str, Sequence[dict[str, Any]]],
    failed_query_ids: Collection[str],
) -> dict[str, Sequence[dict[str, Any]]]:
    """Rows of the rule's ``context_queries`` that ran (absent/failed ids omitted)."""
    return {
        qid: rows_by_query_id[qid]
        for qid in rule.context_queries
        if qid in rows_by_query_id and qid not in failed_query_ids
    }


def _evaluate_rule_detailed(
    rule: Rule,
    rows_by_query_id: Mapping[str, Sequence[dict[str, Any]]],
    capped_query_ids: Collection[str] = (),
    failed_query_ids: Collection[str] = (),
) -> tuple[list[ReviewFinding], str | None, int]:
    """Evaluate one rule; returns ``(findings, suppressed_reason, dropped_count)``.

    A rule with ``context_queries`` gets a third detector argument: the context
    rows keyed by ``query_id`` (only the context queries that ran — a detector
    degrades on its own when one is missing).
    """
    detector = DETECTORS.get(rule.id)
    if detector is None or rule.evidence_query is None:
        return [], None, 0
    rows = rows_by_query_id.get(rule.evidence_query)
    if not rows:
        return [], None, 0

    required = rule.params.get("requires_column")
    if isinstance(required, str) and required and not _has_column_value(rows, required):
        return (
            [],
            (
                f"required evidence column '{required}' is unavailable in "
                f"{rule.evidence_query} (no row carries it); rule not evaluated"
            ),
            0,
        )

    detector_params = {
        k: v for k, v in rule.params.items() if k not in EVALUATOR_PARAM_KEYS
    }
    if rule.context_queries:
        context = _context_rows(rule, rows_by_query_id, failed_query_ids)
        matches = detector(rows, detector_params, context)
    elif detector_params:
        matches = detector(rows, detector_params)
    else:
        matches = detector(rows)
    capped = rule.evidence_query in capped_query_ids
    findings = [
        _finding_from_match(rule, rule.evidence_query, m, evidence_capped=capped)
        for m in matches
    ]
    kept, dropped = _dedupe_and_cap(findings, _max_findings(rule))
    return kept, None, dropped


def evaluate_rule(
    rule: Rule,
    rows_by_query_id: Mapping[str, Sequence[dict[str, Any]]],
    *,
    limit_reached_query_ids: Collection[str] = (),
) -> list[ReviewFinding]:
    """Evaluate a single rule against its evidence rows.

    Returns an empty list when the rule has no registered detector, no
    ``evidence_query``, its evidence query produced no rows, or the rule is
    suppressed (a ``requires_column`` is unavailable) — never raises. Findings
    are de-duplicated and capped per the rule's ``max_findings``.
    """
    findings, _reason, _dropped = _evaluate_rule_detailed(
        rule, rows_by_query_id, limit_reached_query_ids
    )
    return findings


def rank_review_findings(
    findings: Collection[ReviewFinding],
) -> list[ReviewFinding]:
    """Return review findings in the D3 stable priority order.

    Sorts by score (desc), then severity (desc), then finding id (asc) — the
    same total order as :func:`starboard_core.domain.rules.registry.rank_findings`,
    so two runs over the same inputs always produce the same order.
    """
    return sorted(
        findings,
        key=lambda rf: (
            -rf.finding.score,
            -SEVERITY_WEIGHTS[rf.finding.severity],
            rf.finding.id,
        ),
    )


def build_review(
    *,
    registry: RuleRegistry,
    domains: Sequence[str],
    rows_by_query_id: Mapping[str, Sequence[dict[str, Any]]],
    failed_query_ids: Collection[str] = (),
    workspace: str | None = None,
    limit_reached_query_ids: Collection[str] = (),
    cost_basis: str | None = None,
) -> WorkloadReview:
    """Assemble a ranked, evidence-cited :class:`WorkloadReview`.

    Args:
        registry: The loaded rule registry (typically ``RuleRegistry.from_seed()``).
        domains: Requested review domains (e.g. ``["jobs", "sql", "warehouse"]``).
            Unknown domains are skipped with a degraded report entry.
        rows_by_query_id: Rows per evidence ``query_id`` (see the module row
            contract). Values are plain dicts materialized by the caller.
        failed_query_ids: Evidence queries that errored during execution; the
            domains that depend on them are marked degraded.
        workspace: Reviewed workspace identifier for the result envelope.
        limit_reached_query_ids: Evidence queries whose result hit its row
            limit; findings from them carry ``metadata["evidence_capped"]``.
        cost_basis: The $ basis label for the review (default: the public
            :data:`~starboard_core.domain.models.review.COST_BASIS_LABEL`).

    Returns:
        A :class:`WorkloadReview` with globally-ranked findings and per-domain
        coverage/degradation reports. Never raises on empty or partial data.
    """
    failed = set(failed_query_ids)
    capped_ids = set(limit_reached_query_ids)
    all_findings: list[ReviewFinding] = []
    reports: list[DomainReport] = []

    for domain in domains:
        rule_domain = DOMAIN_TO_RULE_DOMAIN.get(domain)
        if rule_domain is None:
            reports.append(
                DomainReport(
                    domain=domain,
                    rule_domain="",
                    degraded=True,
                    degraded_reason=f"unknown review domain '{domain}'",
                )
            )
            continue

        rules = registry.rules_for(rule_domain)
        # Context queries are enrichment: a detector degrades on its own when one
        # is missing, so they never mark the domain degraded.
        evidence_ids = sorted(
            {r.evidence_query for r in rules if r.evidence_query is not None}
        )

        domain_findings: list[ReviewFinding] = []
        suppressed: dict[str, str] = {}
        dropped_by_rule: dict[str, int] = {}
        for rule in rules:
            findings, reason, dropped = _evaluate_rule_detailed(
                rule, rows_by_query_id, capped_ids, failed
            )
            domain_findings.extend(findings)
            if reason is not None:
                suppressed[rule.id] = reason
            if dropped:
                dropped_by_rule[rule.id] = dropped
        all_findings.extend(domain_findings)

        degraded_ids = [
            qid
            for qid in evidence_ids
            if qid in failed or qid not in rows_by_query_id
        ]
        reports.append(
            DomainReport(
                domain=domain,
                rule_domain=rule_domain,
                rules_evaluated=len(rules),
                evidence_query_ids=tuple(evidence_ids),
                degraded=bool(degraded_ids),
                degraded_reason=(
                    f"evidence queries unavailable: {', '.join(degraded_ids)}"
                    if degraded_ids
                    else None
                ),
                finding_count=len(domain_findings),
                unavailable_query_ids=tuple(degraded_ids),
                evidence_capped_query_ids=tuple(
                    qid
                    for qid in evidence_ids
                    if qid in capped_ids and qid not in degraded_ids
                ),
                suppressed_rules=suppressed,
                capped_rules=dropped_by_rule,
            )
        )

    return WorkloadReview(
        workspace=workspace,
        requested_domains=tuple(domains),
        findings=tuple(rank_review_findings(all_findings)),
        domain_reports=tuple(reports),
        cost_basis=cost_basis or COST_BASIS_LABEL,
    )


__all__ = [
    "DEFAULT_DOMAINS",
    "DEFAULT_MAX_FINDINGS_PER_RULE",
    "DOMAIN_TO_RULE_DOMAIN",
    "EVALUATOR_PARAM_KEYS",
    "build_review",
    "evaluate_rule",
    "rank_review_findings",
]
