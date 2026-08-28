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


def _finding_from_match(rule: Rule, query_id: str, match: RowMatch) -> ReviewFinding:
    """Build a scored, evidence-cited :class:`ReviewFinding` for one trigger."""
    finding = Finding(
        id=f"{rule.id}::{match.entity_key}",
        severity=rule.severity,
        category=rule.category,
        summary=rule.name,
        rationale=rule.rationale,
        current_state=match.current_state,
        suggested_fix=rule.suggested_fix,
        impact=rule.default_impact,
        effort=rule.default_effort,
        confidence=Confidence.MEDIUM,
        location=match.location,
        rule_id=rule.id,
        source=rule.source,
    )
    citation = EvidenceRef(
        query_id=query_id, row_index=match.row_index, row=match.row
    )
    return ReviewFinding(finding=finding, evidence=(citation,))


def evaluate_rule(
    rule: Rule, rows_by_query_id: Mapping[str, Sequence[dict[str, Any]]]
) -> list[ReviewFinding]:
    """Evaluate a single rule against its evidence rows.

    Returns an empty list when the rule has no registered detector, no
    ``evidence_query``, or its evidence query produced no rows — never raises.
    """
    detector = DETECTORS.get(rule.id)
    if detector is None or rule.evidence_query is None:
        return []
    rows = rows_by_query_id.get(rule.evidence_query)
    if not rows:
        return []
    return [
        _finding_from_match(rule, rule.evidence_query, match)
        for match in detector(rows)
    ]


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

    Returns:
        A :class:`WorkloadReview` with globally-ranked findings and per-domain
        coverage/degradation reports. Never raises on empty or partial data.
    """
    failed = set(failed_query_ids)
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
        evidence_ids = sorted(
            {r.evidence_query for r in rules if r.evidence_query is not None}
        )

        domain_findings: list[ReviewFinding] = []
        for rule in rules:
            domain_findings.extend(evaluate_rule(rule, rows_by_query_id))
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
            )
        )

    return WorkloadReview(
        workspace=workspace,
        requested_domains=tuple(domains),
        findings=tuple(rank_review_findings(all_findings)),
        domain_reports=tuple(reports),
    )


__all__ = [
    "DEFAULT_DOMAINS",
    "DOMAIN_TO_RULE_DOMAIN",
    "build_review",
    "evaluate_rule",
    "rank_review_findings",
]
