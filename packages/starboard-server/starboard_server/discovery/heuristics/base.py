"""Heuristic framework base types.

Provides the ``HeuristicRule`` protocol, ``HeuristicFinding`` result type,
and ``HeuristicRegistry`` for collecting and executing rules by domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    import polars as pl

logger = get_logger(__name__)

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
Dimension = Literal[
    "performance",
    "reliability",
    "consumption",
    "governance",
    "configuration",
]


@dataclass(frozen=True)
class HeuristicFinding:
    """Result of a deterministic heuristic evaluation.

    Args:
        rule_id: Which heuristic rule produced this finding.
        domain: Domain the rule belongs to.
        title: One-line finding summary.
        severity: How severe the issue is.
        dimension: Which health dimension is affected.
        description: What was found.
        evidence_query_id: Which query's data triggered this.
        threshold: The threshold that was breached (human-readable).
        actual_value: The actual observed value (human-readable).
        affected_entities: IDs of affected resources (job_ids, cluster_ids, etc.).
    """

    rule_id: str
    domain: str
    title: str
    severity: Severity
    dimension: Dimension
    description: str
    evidence_query_id: str
    threshold: str
    actual_value: str
    affected_entities: tuple[str, ...] = ()


def get_df(results: dict[str, pl.DataFrame], query_id: str) -> pl.DataFrame | None:
    """Return DataFrame for query_id or None if missing/empty.

    Args:
        results: Map of query_id to DataFrame.
        query_id: The query identifier to look up.

    Returns:
        The DataFrame if present and non-empty, otherwise None.
    """
    df = results.get(query_id)
    if df is None or df.is_empty():
        return None
    return df


def get_col(df: pl.DataFrame, col: str) -> pl.Series | None:
    """Return column series if present, else None.

    Args:
        df: The Polars DataFrame to inspect.
        col: Column name to look up.

    Returns:
        The column Series if present, otherwise None.
    """
    if col in df.columns:
        return df.get_column(col)
    return None


@runtime_checkable
class HeuristicRule(Protocol):
    """Protocol for deterministic best-practice evaluation rules.

    Each rule inspects query results for a specific domain and returns
    findings when thresholds are breached. Rules must be stateless and
    deterministic.
    """

    @property
    def rule_id(self) -> str: ...

    @property
    def domain(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def severity(self) -> Severity: ...

    @property
    def dimension(self) -> Dimension: ...

    def evaluate(self, results: dict[str, pl.DataFrame]) -> list[HeuristicFinding]:
        """Evaluate query results against this rule.

        Args:
            results: Map of query_id to DataFrame for the rule's domain.

        Returns:
            List of findings (empty if rule passes).
        """
        ...


DOMAIN_ALIASES: dict[str, str] = {
    "query_performance": "query_perf",
}


class HeuristicRegistry:
    """Collects and executes heuristic rules by domain.

    Args:
        rules: All heuristic rules to register.
    """

    def __init__(self, rules: tuple[HeuristicRule, ...] = ()) -> None:
        self._rules_by_domain: dict[str, list[HeuristicRule]] = {}
        for rule in rules:
            self._rules_by_domain.setdefault(rule.domain, []).append(rule)

    def register(self, rule: HeuristicRule) -> None:
        """Register a single rule.

        Args:
            rule: The heuristic rule to add.
        """
        self._rules_by_domain.setdefault(rule.domain, []).append(rule)

    def evaluate(
        self,
        domain: str,
        results: dict[str, pl.DataFrame],
    ) -> list[HeuristicFinding]:
        """Run all rules for a domain against query results.

        Supports domain aliases (e.g. ``query_performance`` resolves to
        ``query_perf``) so that query-pack domain strings match heuristic
        rule domains.

        Args:
            domain: The domain to evaluate.
            results: Map of query_id to DataFrame.

        Returns:
            All findings from all rules for this domain.
        """
        resolved = DOMAIN_ALIASES.get(domain, domain)
        findings: list[HeuristicFinding] = []
        for rule in self._rules_by_domain.get(resolved, []):
            try:
                findings.extend(rule.evaluate(results))
            except Exception:
                logger.warning(
                    "heuristic_rule_failed",
                    rule_id=rule.rule_id,
                    domain=domain,
                    exc_info=True,
                )
        return findings

    def get_rules_for_domain(self, domain: str) -> list[HeuristicRule]:
        """Get all registered rules for a domain.

        Supports domain aliases (e.g. ``query_performance`` resolves to
        ``query_perf``).

        Args:
            domain: The domain to look up.

        Returns:
            List of rules (empty if none registered).
        """
        resolved = DOMAIN_ALIASES.get(domain, domain)
        return list(self._rules_by_domain.get(resolved, []))

    @property
    def all_domains(self) -> list[str]:
        """All domains that have registered rules."""
        return list(self._rules_by_domain.keys())

    @property
    def rule_count(self) -> int:
        """Total number of registered rules across all domains."""
        return sum(len(rules) for rules in self._rules_by_domain.values())
