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

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryPack,
    SystemQuery,
)
from starboard_core.domain.models.review import WorkloadReview
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
from starboard.infra.observability.logging import get_logger
from starboard.tools.services.validator_council import (
    CouncilResult,
    ValidatorCouncil,
)

logger = get_logger(__name__)


class ValidatedReview(BaseModel):
    """A review plus the D1c gate/council decisions that shaped its findings.

    ``review.findings`` holds only the findings that survived the severity gate
    and (when configured) the validator council. ``gate`` / ``council`` carry the
    suppression detail so callers can report what was filtered and at what model
    spend. Either stage is ``None`` when it was not run (both ``None`` reproduces
    the default, un-gated review verbatim).
    """

    model_config = ConfigDict(frozen=True)

    review: WorkloadReview
    gate: GateOutcome | None = None
    council: CouncilResult | None = None

# Synthetic pack id/domain used to run only the evidence queries a review needs.
_REVIEW_PACK_ID = "workload_review"

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
    ) -> None:
        self._sql_executor = sql_executor
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

    async def run(self, domains: Sequence[str] | None = None) -> WorkloadReview:
        """Execute the review and return a ranked, evidence-cited result.

        Degrades gracefully: an evidence query that errors marks its domain
        degraded (partial findings) rather than failing the whole review.
        """
        resolved = self._resolve_domains(domains)
        needed = self._needed_evidence_query_ids(resolved)

        rows_by_query_id: dict[str, list[dict]] = {}
        failed_query_ids: set[str] = set()

        if needed:
            evidence_pack = self._build_evidence_pack(needed)
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
            )
            pack_result = await executor.execute_pack(evidence_pack)
            for result in pack_result.results:
                if result.query_id not in needed:
                    continue
                if result.succeeded and result.data is not None:
                    rows_by_query_id[result.query_id] = result.data.to_dicts()
                else:
                    rows_by_query_id[result.query_id] = []
                    failed_query_ids.add(result.query_id)

        review = build_review(
            registry=self._rule_registry,
            domains=resolved,
            rows_by_query_id=rows_by_query_id,
            failed_query_ids=failed_query_ids,
            workspace=self._workspace,
        )

        logger.info(
            "workload_review_complete",
            domains=resolved,
            evidence_queries=sorted(needed),
            failed_queries=sorted(failed_query_ids),
            finding_count=review.finding_count,
            degraded=review.degraded,
        )
        return review

    async def run_validated(
        self,
        domains: Sequence[str] | None = None,
        *,
        gate: SeverityGate | None = None,
        validator: ValidatorCouncil | None = None,
    ) -> ValidatedReview:
        """Run a review, then optionally gate + council-validate its findings.

        Opt-in D1c pipeline (PHASE_3 D-3.2): the default ``run`` behavior is
        unchanged — this method only adds filtering when a ``gate`` and/or a
        ``validator`` is supplied. The stages run in order (cheap, pure severity
        gate first, then the bounded model council over the survivors) so the
        council never spends model calls on findings the gate already dropped.

        Args:
            domains: Requested review domains (default D-3.7 scope).
            gate: A pure severity gate; ``None`` skips gating.
            validator: A bounded validator council; ``None`` skips it.

        Returns:
            A :class:`ValidatedReview` whose ``review.findings`` are the
            survivors, with the gate/council decisions attached.
        """
        review = await self.run(domains)

        candidates = list(review.findings)
        gate_outcome: GateOutcome | None = None
        if gate is not None:
            gate_outcome = apply_severity_gate(candidates, gate)
            candidates = list(gate_outcome.kept)

        council_result: CouncilResult | None = None
        if validator is not None:
            council_result = await validator.review(candidates)
            candidates = list(council_result.kept)

        final_review = review.model_copy(update={"findings": tuple(candidates)})

        logger.info(
            "workload_review_validated",
            base_findings=review.finding_count,
            gate_suppressed=(
                gate_outcome.suppressed_count if gate_outcome else 0
            ),
            council_suppressed=(
                council_result.suppressed_count if council_result else 0
            ),
            council_model_calls=(
                council_result.total_model_calls if council_result else 0
            ),
            final_findings=final_review.finding_count,
        )
        return ValidatedReview(
            review=final_review, gate=gate_outcome, council=council_result
        )


__all__ = [
    "OPT_IN_DOMAINS",
    "ValidatedReview",
    "WorkloadReviewService",
    "available_domains",
]
