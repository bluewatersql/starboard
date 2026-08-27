# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Kernel ``RuleRegistry`` — loads seed rules, validates evidence, ranks (Phase-3 D1a).

The registry is the first consumer of the Phase-1 D3 seed rules
(``domain/rules/seed/*.yaml``). It:

- loads one or more :class:`~starboard_core.domain.rules.schema.RuleSet` (the seed
  set by default, via :meth:`RuleRegistry.from_seed`),
- exposes ``rules_for(domain)`` and the full loaded rule set,
- validates that every rule's ``evidence_query`` resolves to a **real**
  query-pack ``query_id`` (:meth:`validate_evidence_queries`), closing Phase-1
  review finding #3, and
- wires the D3 ``severity × impact / effort`` scorer
  (:mod:`starboard_core.domain.models.finding`) into a **stable total order** of
  rules (and of findings, via :func:`rank_findings`).

**Kernel-clean by construction.** This module imports only from the kernel
(``starboard_core.domain.*``) and the stdlib — no ``databricks-sdk`` / ``openai``
/ ``fastapi`` / ``mcp``. The query packs that own the real ``query_id`` values
live in the Tier-2 ``starboard`` server package, which the kernel must not
import; validation is therefore **dependency-inverted**: the caller passes the
set of known ``query_id`` values (e.g. gathered from the query-pack registry at
the server tier) into :meth:`validate_evidence_queries`. Merely importing this
module never loads ``yaml`` (the seed loader imports it lazily on use).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from pathlib import Path

from starboard_core.domain.models.finding import (
    SEVERITY_WEIGHTS,
    Finding,
    score,
)
from starboard_core.domain.rules.loader import (
    load_rulesets_from_directory,
    seed_rules_dir,
)
from starboard_core.domain.rules.schema import Rule, RuleSet


class DanglingEvidenceQueryError(Exception):
    """Raised when a rule's ``evidence_query`` names an unknown ``query_id``.

    Carries the ``unresolved`` mapping (``rule_id -> evidence_query``) so callers
    can report every offending rule at once rather than one at a time.
    """

    def __init__(self, unresolved: dict[str, str]) -> None:
        self.unresolved: dict[str, str] = dict(unresolved)
        detail = ", ".join(
            f"{rule_id} -> {query!r}"
            for rule_id, query in sorted(unresolved.items())
        )
        super().__init__(f"Unresolved evidence_query references: {detail}")


def _rule_score(rule: Rule) -> float:
    """Priority score for a rule from its default severity/impact/effort."""
    return score(rule.severity, rule.default_impact, rule.default_effort)


def _rule_rank_key(rule: Rule) -> tuple[float, int, str]:
    """Total-order key for a rule: score desc, severity desc, id asc.

    The first two components are negated so a plain ascending sort surfaces the
    highest-priority rule first. ``rule.id`` (unique within a registry) breaks
    remaining ties, making the order fully deterministic.
    """
    return (-_rule_score(rule), -SEVERITY_WEIGHTS[rule.severity], rule.id)


def _finding_rank_key(finding: Finding) -> tuple[float, int, str]:
    """Total-order key for a finding: score desc, severity desc, id asc."""
    return (-finding.score, -SEVERITY_WEIGHTS[finding.severity], finding.id)


def rank_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Return findings in a stable, deterministic priority order.

    Sorts by the D3 scorer (``score`` descending), breaking ties by severity
    (descending) and then by ``id`` (ascending). Two calls over the same inputs
    always produce the same order.
    """
    return sorted(findings, key=_finding_rank_key)


class RuleRegistry:
    """In-memory registry of workload-review rules loaded from rulesets.

    Args:
        rulesets: The rulesets to register. Rule ids must be unique across the
            whole registry (each ruleset already enforces uniqueness within
            itself); a cross-ruleset collision raises ``ValueError``.
    """

    def __init__(self, rulesets: Iterable[RuleSet]) -> None:
        self._rulesets: tuple[RuleSet, ...] = tuple(rulesets)

        rules: list[Rule] = []
        by_domain: dict[str, list[Rule]] = {}
        for ruleset in self._rulesets:
            for rule in ruleset.rules:
                rules.append(rule)
                by_domain.setdefault(ruleset.domain, []).append(rule)

        ids = [rule.id for rule in rules]
        duplicates = sorted({rid for rid in ids if ids.count(rid) > 1})
        if duplicates:
            raise ValueError(
                f"Duplicate rule ids across rulesets: {duplicates}"
            )

        self._rules: tuple[Rule, ...] = tuple(rules)
        self._by_domain: dict[str, tuple[Rule, ...]] = {
            domain: tuple(domain_rules)
            for domain, domain_rules in by_domain.items()
        }

    @classmethod
    def from_seed(cls, directory: Path | None = None) -> RuleRegistry:
        """Load the bundled seed rulesets (or those under ``directory``).

        Raises:
            RuleLoadError: If the directory is missing or any YAML is invalid.
        """
        source = directory if directory is not None else seed_rules_dir()
        return cls(load_rulesets_from_directory(source))

    @property
    def rules(self) -> tuple[Rule, ...]:
        """All registered rules, in load order."""
        return self._rules

    @property
    def rulesets(self) -> tuple[RuleSet, ...]:
        """The registered rulesets, in load order."""
        return self._rulesets

    @property
    def domains(self) -> tuple[str, ...]:
        """Sorted list of domains covered by the registered rulesets."""
        return tuple(sorted(self._by_domain))

    def rules_for(
        self,
        domain: str,
        *,
        enabled_only: bool = True,
        ranked: bool = True,
    ) -> list[Rule]:
        """Return the rules for ``domain``.

        Args:
            domain: The ruleset domain (e.g. ``"query"``, ``"warehouse"``,
                ``"uc"``). Unknown domains return an empty list.
            enabled_only: If True (default), drop rules with ``enabled=False``.
            ranked: If True (default), return the rules in the stable priority
                order (see :meth:`ranked_rules`); otherwise preserve load order.
        """
        rules = list(self._by_domain.get(domain, ()))
        if enabled_only:
            rules = [rule for rule in rules if rule.enabled]
        if ranked:
            rules.sort(key=_rule_rank_key)
        return rules

    def ranked_rules(self, *, enabled_only: bool = True) -> list[Rule]:
        """Return all rules in a stable, deterministic priority order.

        Sorts by the D3 scorer (``(severity_weight × default_impact) /
        effort_points`` descending), breaking ties by severity (descending) and
        then by ``id`` (ascending).
        """
        rules = [
            rule
            for rule in self._rules
            if not enabled_only or rule.enabled
        ]
        rules.sort(key=_rule_rank_key)
        return rules

    def rule_score(self, rule: Rule) -> float:
        """Priority score for ``rule`` from its default severity/impact/effort."""
        return _rule_score(rule)

    def evidence_query_ids(self) -> set[str]:
        """The distinct, non-null ``evidence_query`` ids referenced by rules."""
        return {
            rule.evidence_query
            for rule in self._rules
            if rule.evidence_query is not None
        }

    def validate_evidence_queries(
        self, known_query_ids: Collection[str]
    ) -> None:
        """Assert every rule's ``evidence_query`` resolves to a real ``query_id``.

        Rules whose ``evidence_query`` is ``None`` are skipped (the field is
        optional). Validation is dependency-inverted so the kernel stays pure:
        the caller supplies ``known_query_ids`` (e.g. the ids exposed by the
        server-tier query-pack registry).

        Args:
            known_query_ids: The set of real query-pack ``query_id`` values.

        Raises:
            DanglingEvidenceQueryError: If any rule references an unknown id.
        """
        known = set(known_query_ids)
        unresolved = {
            rule.id: rule.evidence_query
            for rule in self._rules
            if rule.evidence_query is not None
            and rule.evidence_query not in known
        }
        if unresolved:
            raise DanglingEvidenceQueryError(unresolved)


__all__ = [
    "DanglingEvidenceQueryError",
    "RuleRegistry",
    "rank_findings",
]
