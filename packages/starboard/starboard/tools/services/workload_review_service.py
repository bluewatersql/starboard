# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Workload Review service — packs → rules → ranked findings (Phase-3 D1b).

The server-tier orchestrator for the Workload Review flagship. For a target
workspace and a set of domains (default **jobs + sql + warehouse**, per PHASE_3
D-3.7) it:

1. resolves the rules for those domains from the kernel
   :class:`~starboard_core.domain.rules.registry.RuleRegistry`,
2. collects the distinct evidence ``query_id`` values those rules reference,
3. runs exactly the query-pack queries that supply that evidence (via the
   existing :class:`~starboard.discovery.executor.QueryPackExecutor`),
4. materializes the returned Polars rows into plain dicts, and
5. hands them to the pure kernel engine
   (:func:`starboard_core.domain.rules.evaluator.build_review`) which produces a
   ranked, evidence-cited :class:`~starboard_core.domain.models.review.WorkloadReview`.

The SDK-touching pack execution lives here (Tier-2 ``starboard``); the scoring
and rule logic stay pure in the kernel. Uses **public ``system.*`` data only**;
findings are DBU / utilization based and never emit a finance-grade dollar
figure (D-3.8).

Domain routing is fully **data-driven**: a review domain resolves to its
seed-ruleset domain through the kernel
:data:`~starboard_core.domain.rules.evaluator.DOMAIN_TO_RULE_DOMAIN` map, and the
required evidence queries are derived from whatever rules that rule-domain
carries. New surfaces are therefore added by shipping a seed ruleset + its
``DOMAIN_TO_RULE_DOMAIN`` entry — no per-domain code here. Phase-2 D-a adds the
opt-in **DLT / ML / vector-search** domains (see :data:`OPT_IN_DOMAINS`) over the
already-present ``dlt_pipelines`` / ``ml`` / ``mlflow`` / ``vector_search`` packs,
and Phase-2 X4 adds the opt-in **portfolio-readiness** workload-maturity surface
over the ``billing`` / ``jobs`` packs; the default scope
(:data:`DEFAULT_DOMAINS`) stays jobs/sql/warehouse.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict
from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryPack,
    SystemQuery,
)
from starboard_core.domain.models.review import (
    COST_BASIS_LABEL,
    TELEMETRY_COST_BASIS_LABEL,
    WorkloadReview,
)
from starboard_core.domain.rules.evaluator import (
    DEFAULT_DOMAINS,
    DOMAIN_TO_RULE_DOMAIN,
    build_review,
)
from starboard_core.domain.rules.gate import (
    GateOutcome,
    SeverityGate,
    apply_severity_gate,
)
from starboard_core.domain.rules.registry import RuleRegistry

from starboard.discovery.executor import QueryPackExecutor, SQLExecutor
from starboard.discovery.query_packs.registry import (
    QueryPackRegistry,
    create_default_registry,
)
from starboard.discovery.sources import SystemTablesSource
from starboard.infra.observability.logging import get_logger
from starboard.tools.services.discovery_evidence import result_status

if TYPE_CHECKING:
    from starboard.discovery.sources import QuerySource
    from starboard.tools.services.discovery_evidence import DiscoveryEvidence

logger = get_logger(__name__)


class ValidatedReview(BaseModel):
    """A review plus the severity-gate decision that shaped its findings.

    ``review.findings`` holds only the findings that survived the severity gate.
    ``gate`` carries the suppression detail so callers can report what was
    filtered. ``gate`` is ``None`` when it was not run (reproducing the default,
    un-gated review verbatim).
    """

    model_config = ConfigDict(frozen=True)

    review: WorkloadReview
    gate: GateOutcome | None = None

# Synthetic pack id/domain used to run only the evidence queries a review needs.
_REVIEW_PACK_ID = "workload_review"

# Headline-facts query whose window totals (by product x usage_unit) feed the
# findings-manifest ``products_dbu`` (DBU only; DSU is never summed into it).
# Not rule evidence: its failure never degrades the review.
_PRODUCTS_QUERY_ID = "F-01"

# Opt-in review surfaces beyond the DEFAULT_DOMAINS v1 scope (Phase-2 D-a), in
# their canonical CLI-facing token form. Advertised by ``starboard review`` /
# ``python -m starboard_x.review`` help; each token resolves through the kernel
# ``DOMAIN_TO_RULE_DOMAIN`` map. Kept here (server tier) as the single source of
# truth for the CLI so the flag help never drifts from what actually routes.
OPT_IN_DOMAINS: tuple[str, ...] = (
    "uc",
    "dlt",
    "ml",
    "vector-search",
    "portfolio-readiness",
)


def available_domains() -> tuple[str, ...]:
    """Return the review domains a caller may request (defaults + opt-in).

    The default v1 scope first (jobs/sql/warehouse), then the opt-in surfaces in
    advertised order. Derived so the CLI advertises exactly what routes.
    """
    return (*DEFAULT_DOMAINS, *OPT_IN_DOMAINS)


class WorkloadReviewService:
    """Run a Workload Review over public ``system.*`` data for a workspace.

    Args:
        sql_executor: Async SQL backend (e.g. ``AsyncSQLExecutor``) used to run
            the evidence queries. Any object satisfying the discovery
            :class:`~starboard.discovery.executor.SQLExecutor` protocol works,
            so tests can inject a fake.
        rule_registry: Loaded rule registry; defaults to the bundled seed rules.
        pack_registry: Query-pack registry; defaults to the standard packs.
        lookback_days: Time window for the evidence queries.
        max_parallelism: Max concurrent evidence queries.
        enable_cache: Reuse the discovery scan cache across identical queries.
        workspace: Workspace identifier recorded on the resulting review.
        source: Discovery ``QuerySource`` the evidence queries run through
            (same seam as the discovery engine). ``None`` = the public
            ``SystemTablesSource`` over ``sql_executor``; the gated internal
            ``MirrorSource`` is passed here for a no-connect internal review.
        evidence: Saved discovery output (``review --from-discovery``). When
            given, NO query runs: rows come from the discovery results by
            ``query_id``; a skipped/failed/missing needed result is treated as a
            failed evidence query (domain degraded). ``sql_executor`` is unused.

    After :meth:`run`, :attr:`products_dbu` holds the trailing-30-full-day DBU
    totals per ``billing_origin_product`` (DBU only; empty when unavailable),
    and :attr:`evidence_report` holds, for the needed evidence queries,
    ``unavailable`` (query_id -> reason), ``limit_reached_query_ids``,
    ``query_lookback_days`` and ``query_attempts`` (query_id -> attempts, only
    for results whose attempt count shows a retry, i.e. ``attempts > 1``).

    The review's ``cost_basis`` follows the evidence source: the public label
    for the workspace's own system tables, the workspace-telemetry label for a
    non-public source (a gated ``source`` or an ``internal`` discovery run).
    """

    def __init__(
        self,
        sql_executor: SQLExecutor,
        *,
        rule_registry: RuleRegistry | None = None,
        pack_registry: QueryPackRegistry | None = None,
        lookback_days: int = 30,
        max_parallelism: int = 4,
        enable_cache: bool = True,
        workspace: str | None = None,
        source: QuerySource | None = None,
        evidence: DiscoveryEvidence | None = None,
    ) -> None:
        self._sql_executor = sql_executor
        self._source = source
        self._evidence = evidence
        self.products_dbu: dict[str, float] = {}
        self.evidence_report: dict[str, Any] = {}
        self._rule_registry = rule_registry or RuleRegistry.from_seed()
        self._pack_registry = pack_registry or create_default_registry()
        self._lookback_days = lookback_days
        self._max_parallelism = max_parallelism
        self._enable_cache = enable_cache
        self._workspace = workspace

    def _resolve_domains(self, domains: Sequence[str] | None) -> list[str]:
        """Return the requested domains, defaulting to the D-3.7 v1 scope."""
        return list(domains) if domains else list(DEFAULT_DOMAINS)

    def _needed_evidence_query_ids(self, domains: Sequence[str]) -> set[str]:
        """Distinct evidence ``query_id`` values the domains' rules reference."""
        needed: set[str] = set()
        for domain in domains:
            rule_domain = DOMAIN_TO_RULE_DOMAIN.get(domain)
            if rule_domain is None:
                continue
            for rule in self._rule_registry.rules_for(rule_domain):
                if rule.evidence_query is not None:
                    needed.add(rule.evidence_query)
                needed.update(rule.context_queries)
        return needed

    def _build_evidence_pack(self, needed_query_ids: set[str]) -> QueryPack:
        """Wrap exactly the needed evidence queries into one synthetic pack.

        Running a single pack of only the required queries keeps the review from
        executing unrelated pack queries. Queries are de-duplicated by
        ``query_id`` (which is globally unique across packs).
        """
        collected: dict[str, SystemQuery] = {}
        for pack in self._pack_registry.all_packs:
            for query in pack.queries:
                if query.query_id in needed_query_ids:
                    collected.setdefault(query.query_id, query)
        return QueryPack(
            pack_id=_REVIEW_PACK_ID,
            domain=_REVIEW_PACK_ID,
            name="Workload Review evidence",
            description="Evidence queries selected for a Workload Review run.",
            queries=tuple(collected[qid] for qid in sorted(collected)),
        )

    async def run(
        self,
        domains: Sequence[str] | None = None,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> WorkloadReview:
        """Execute the review and return a ranked, evidence-cited result.

        Degrades gracefully: an evidence query that errors marks its domain
        degraded (partial findings) rather than failing the whole review.

        ``progress``, when given, is called with a short human-readable status
        string at each phase boundary so a long scan is not silent.
        """
        resolved = self._resolve_domains(domains)
        needed = self._needed_evidence_query_ids(resolved)

        rows_by_query_id: dict[str, list[dict]] = {}
        failed_query_ids: set[str] = set()
        self.products_dbu = {}
        self.evidence_report = _empty_evidence_report()

        if self._evidence is not None:
            if progress is not None:
                progress(
                    f"reading {len(needed)} evidence queries from discovery "
                    f"output across {len(resolved)} domains ({', '.join(resolved)})"
                )
            self._load_evidence(
                self._evidence, needed, rows_by_query_id, failed_query_ids
            )
        elif needed:
            if progress is not None:
                progress(
                    f"scanning {len(needed)} evidence queries "
                    f"across {len(resolved)} domains ({', '.join(resolved)})"
                )
            evidence_pack = self._build_evidence_pack(needed | {_PRODUCTS_QUERY_ID})
            executor = QueryPackExecutor(
                self._sql_executor,
                max_parallelism=self._max_parallelism,
                default_lookback_days=self._lookback_days,
                # DEEP_DIVE so an evidence query runs regardless of the depth it
                # was tagged with in its source pack; the synthetic pack already
                # holds only the queries this review needs.
                discovery_mode=DiscoveryMode.DEEP_DIVE,
                enable_cache=self._enable_cache,
                workspace_id=self._workspace,
                source=self._source,
            )
            pack_result = await executor.execute_pack(evidence_pack)
            report = self.evidence_report
            for result in pack_result.results:
                if (
                    result.query_id == _PRODUCTS_QUERY_ID
                    and result.succeeded
                    and result.data is not None
                ):
                    self.products_dbu = _products_dbu(result.data.to_dicts())
                if result.query_id not in needed:
                    continue
                qid = result.query_id
                attempts = getattr(result, "attempts", None)
                if _is_retry_count(attempts):
                    report["query_attempts"][qid] = attempts
                if isinstance(result.lookback_days, int):
                    report["query_lookback_days"][qid] = result.lookback_days
                if result.succeeded and result.data is not None:
                    rows_by_query_id[qid] = result.data.to_dicts()
                    if (
                        result.result_limit is not None
                        and result.row_count >= result.result_limit
                    ):
                        report["limit_reached_query_ids"].append(qid)
                else:
                    rows_by_query_id[qid] = []
                    failed_query_ids.add(qid)
                    report["unavailable"][qid] = result.status + (
                        f": {result.error}" if result.error else ""
                    )
            report["limit_reached_query_ids"].sort()

        review = build_review(
            registry=self._rule_registry,
            domains=resolved,
            rows_by_query_id=rows_by_query_id,
            failed_query_ids=failed_query_ids,
            workspace=self._workspace,
            limit_reached_query_ids=self.evidence_report["limit_reached_query_ids"],
            cost_basis=self._cost_basis(),
        )

        if progress is not None:
            progress(f"scan complete: {review.finding_count} candidate findings")

        logger.info(
            "workload_review_complete",
            domains=resolved,
            evidence_queries=sorted(needed),
            failed_queries=sorted(failed_query_ids),
            finding_count=review.finding_count,
            degraded=review.degraded,
        )
        return review

    def _cost_basis(self) -> str:
        """$ basis label for the evidence source (public vs. workspace telemetry)."""
        if self._evidence is not None:
            internal = self._evidence.source == "internal"
        else:
            internal = self._source is not None and not isinstance(
                self._source, SystemTablesSource
            )
        return TELEMETRY_COST_BASIS_LABEL if internal else COST_BASIS_LABEL

    def _load_evidence(
        self,
        evidence: DiscoveryEvidence,
        needed: set[str],
        rows_by_query_id: dict[str, list[dict]],
        failed_query_ids: set[str],
    ) -> None:
        """Fill rows / failed ids from saved discovery results (no execution)."""
        results = evidence.results
        products = results.get(_PRODUCTS_QUERY_ID)
        if products is not None and result_status(products) == "succeeded":
            self.products_dbu = _products_dbu(products.get("rows") or [])

        report = self.evidence_report
        for qid in sorted(needed):
            result = results.get(qid)
            if result is None:
                rows_by_query_id[qid] = []
                failed_query_ids.add(qid)
                report["unavailable"][qid] = "not in discovery output"
                continue
            if isinstance(result.get("lookback_days"), int):
                report["query_lookback_days"][qid] = result["lookback_days"]
            attempts = result.get("attempts")
            if _is_retry_count(attempts):
                report["query_attempts"][qid] = attempts
            status = result_status(result)
            if status != "succeeded":
                rows_by_query_id[qid] = []
                failed_query_ids.add(qid)
                error = result.get("error")
                report["unavailable"][qid] = f"{status} in discovery" + (
                    f": {error}" if error else ""
                )
                continue
            rows_by_query_id[qid] = list(result.get("rows") or [])
            # ``truncated`` = the serializer dropped rows past its own safety
            # cap; either way the cited population is a capped sample.
            if result.get("limit_reached") or result.get("truncated"):
                report["limit_reached_query_ids"].append(qid)

    async def run_validated(
        self,
        domains: Sequence[str] | None = None,
        *,
        gate: SeverityGate | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> ValidatedReview:
        """Run a review, then optionally gate its findings by severity.

        Opt-in pipeline: the default ``run`` behavior is unchanged — this method
        only adds a pure severity-gate filter when a ``gate`` is supplied.

        Args:
            domains: Requested review domains (default D-3.7 scope).
            gate: A pure severity gate; ``None`` skips gating.

        Returns:
            A :class:`ValidatedReview` whose ``review.findings`` are the
            survivors, with the gate decision attached.
        """
        review = await self.run(domains, progress=progress)

        candidates = list(review.findings)
        gate_outcome: GateOutcome | None = None
        if gate is not None:
            gate_outcome = apply_severity_gate(candidates, gate)
            candidates = list(gate_outcome.kept)
            if progress is not None:
                progress(
                    f"severity gate: {len(candidates)} of "
                    f"{review.finding_count} findings kept"
                )

        final_review = review.model_copy(update={"findings": tuple(candidates)})

        logger.info(
            "workload_review_validated",
            base_findings=review.finding_count,
            gate_suppressed=(gate_outcome.suppressed_count if gate_outcome else 0),
            final_findings=final_review.finding_count,
        )
        return ValidatedReview(review=final_review, gate=gate_outcome)


def _is_retry_count(value: Any) -> bool:
    """True for an int attempt count above 1 (the statement was retried)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 1


def _empty_evidence_report() -> dict[str, Any]:
    """Fresh per-run evidence report (see :class:`WorkloadReviewService`)."""
    return {
        "unavailable": {},
        "limit_reached_query_ids": [],
        "query_lookback_days": {},
        "query_attempts": {},
    }


def _products_dbu(rows: Sequence[dict]) -> dict[str, float]:
    """Sum DBU per ``billing_origin_product`` from F-01 rows (DSU rows dropped)."""
    totals: dict[str, float] = {}
    for row in rows:
        if str(row.get("usage_unit") or "").upper() != "DBU":
            continue
        try:
            qty = float(row.get("usage_quantity") or 0.0)
        except (TypeError, ValueError):
            continue
        product = str(row.get("billing_origin_product") or "UNKNOWN")
        totals[product] = totals.get(product, 0.0) + qty
    return {p: round(v, 4) for p, v in sorted(totals.items()) if v}


__all__ = [
    "OPT_IN_DOMAINS",
    "ValidatedReview",
    "WorkloadReviewService",
    "available_domains",
]
