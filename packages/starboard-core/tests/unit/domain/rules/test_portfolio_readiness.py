# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Portfolio Readiness review domain (Phase-2 X4).

Phase-2 X4 adds a public-safe **workload-maturity** review domain
(``portfolio_readiness``) over the already-present ``billing`` / ``jobs`` query
packs, reusing the kernel rule engine (seed YAML -> :class:`RuleRegistry` ->
detectors -> :func:`build_review`). This proves, at the pure kernel tier:

* the new seed ruleset loads and exposes its rules under the new rule-domain;
* every new rule's ``evidence_query`` binds to a **real** query-pack ``query_id``;
* the domain classifies fixture workloads into maturity gaps and detects
  untracked production consumption with ranked, evidence-cited findings;
* the caller-facing ``portfolio-readiness`` hyphen token routes through
  :data:`DOMAIN_TO_RULE_DOMAIN`;
* the v1 scope (jobs/sql/warehouse) and defaults are unchanged; and
* the seed YAML + reference file carry no internal identifiers / CRM fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starboard_core.domain.rules import (
    DEFAULT_DOMAINS,
    DOMAIN_TO_RULE_DOMAIN,
    RuleRegistry,
)
from starboard_core.domain.rules.evaluator import build_review

_RULE_DOMAIN = "portfolio_readiness"
_RULE_IDS = {
    "portfolio_untracked_production_consumption",
    "portfolio_unattended_production_job",
    "portfolio_unreliable_production_workload",
}
# The real query-pack query_ids the new rules cite for evidence.
_EVIDENCE_IDS = {"C-B01", "C-J01", "C-J04"}


@pytest.fixture
def registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


@pytest.mark.unit
class TestPortfolioSeedRulesLoad:
    def test_new_rule_domain_present(self, registry: RuleRegistry) -> None:
        assert _RULE_DOMAIN in registry.domains

    def test_domain_exposes_expected_rules(self, registry: RuleRegistry) -> None:
        got = {r.id for r in registry.rules_for(_RULE_DOMAIN)}
        assert got == _RULE_IDS

    def test_rules_category_matches_domain(self, registry: RuleRegistry) -> None:
        for rule in registry.rules_for(_RULE_DOMAIN):
            assert rule.category == _RULE_DOMAIN

    def test_v1_scope_unchanged(self, registry: RuleRegistry) -> None:
        assert {"query", "warehouse", "uc", "jobs"} <= set(registry.domains)
        assert DEFAULT_DOMAINS == ("jobs", "sql", "warehouse")


@pytest.mark.unit
class TestPortfolioEvidenceQueriesResolve:
    def test_rules_cite_expected_real_query_ids(
        self, registry: RuleRegistry
    ) -> None:
        got = {
            r.evidence_query
            for r in registry.rules_for(_RULE_DOMAIN)
            if r.evidence_query is not None
        }
        assert got == _EVIDENCE_IDS

    def test_evidence_resolves_against_real_query_packs(self) -> None:
        """The evidence ``query_id`` values are real pack query_ids.

        Reaches across to the Tier-2 ``starboard`` packs at the *test* tier (the
        kernel must not import them). In an isolated worktree ``starboard`` may be
        unimportable; the parent verifies pytest in the merged tree.
        """
        from starboard.discovery.query_packs import create_default_registry

        real_ids = {
            q.query_id
            for pack in create_default_registry().all_packs
            for q in pack.queries
        }
        assert real_ids >= _EVIDENCE_IDS
        # The whole registry (v1 + v2 + X4) validates against the real universe.
        RuleRegistry.from_seed().validate_evidence_queries(real_ids)


@pytest.mark.unit
class TestPortfolioDomainRouting:
    def test_tokens_map_to_rule_domain(self) -> None:
        assert DOMAIN_TO_RULE_DOMAIN["portfolio_readiness"] == _RULE_DOMAIN
        # CLI-friendly hyphen alias routes to the same rule-domain.
        assert DOMAIN_TO_RULE_DOMAIN["portfolio-readiness"] == _RULE_DOMAIN

    def test_v1_and_da_mappings_unchanged(self) -> None:
        assert DOMAIN_TO_RULE_DOMAIN["jobs"] == "jobs"
        assert DOMAIN_TO_RULE_DOMAIN["sql"] == "query"
        assert DOMAIN_TO_RULE_DOMAIN["warehouse"] == "warehouse"
        assert DOMAIN_TO_RULE_DOMAIN["vector-search"] == "vector_search"


# --- Golden evidence rows shaped like the real query-pack outputs ---------- #
# C-B01: DBU by workspace x product x identity (billing.py).
_C_B01_ROWS = [
    {
        "workspace_id": "1234567890",
        "billing_origin_product": "JOBS",
        "user_type": "Unattributed",  # no run-as identity
        "dbus_consumed": 800.0,  # >= untracked floor -> untracked production
    },
    {
        "workspace_id": "1234567890",
        "billing_origin_product": "SQL",
        "user_type": "Unattributed",
        "dbus_consumed": 10.0,  # below untracked floor -> no finding
    },
    {
        "workspace_id": "1234567890",
        "billing_origin_product": "ALL_PURPOSE",
        "user_type": "Human User",  # attributed -> no finding
        "dbus_consumed": 5000.0,
    },
]
# C-J01: job DBU leaderboard (jobs.py).
_C_J01_ROWS = [
    {
        "name": "nightly_elt",
        "job_id": "j-unowned",
        "run_as": None,  # missing owner
        "total_dbus": 420.0,  # production-scale -> unattended production job
        "avg_dbus_per_run": 14.0,
    },
    {
        "name": "owned_prod",
        "job_id": "j-owned",
        "run_as": "svc-etl@example.com",  # owned -> no finding
        "total_dbus": 900.0,
        "avg_dbus_per_run": 30.0,
    },
    {
        "name": "tiny_unowned",
        "job_id": "j-tiny",
        "run_as": "system",  # unattributed sentinel, but below production scale
        "total_dbus": 3.0,
        "avg_dbus_per_run": 1.0,
    },
]
# C-J04: compound reliability scorecard (jobs.py).
_C_J04_ROWS = [
    {
        "job_name": "fragile_prod",
        "job_id": "j-fragile",
        "total_runs": 100,
        "failure_rate_pct": 30.0,  # >= ceiling
        "total_dbus": 300.0,  # production-scale -> unreliable production workload
        "wasted_dbu_pct": 25.0,
    },
    {
        "job_name": "reliable_prod",
        "job_id": "j-reliable",
        "total_runs": 100,
        "failure_rate_pct": 1.0,  # below ceiling -> no finding
        "total_dbus": 500.0,
        "wasted_dbu_pct": 1.0,
    },
    {
        "job_name": "flaky_pilot",
        "job_id": "j-flaky-pilot",
        "total_runs": 20,
        "failure_rate_pct": 90.0,  # high failure BUT below production scale
        "total_dbus": 4.0,
        "wasted_dbu_pct": 80.0,
    },
]
_ALL_ROWS = {"C-B01": _C_B01_ROWS, "C-J01": _C_J01_ROWS, "C-J04": _C_J04_ROWS}


@pytest.mark.unit
class TestPortfolioFindings:
    def test_domain_ranked_evidence_cited_findings(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["portfolio-readiness"],
            rows_by_query_id=_ALL_ROWS,
            workspace="acme",
        )
        rule_ids = {rf.finding.rule_id for rf in review.findings}
        assert rule_ids == _RULE_IDS
        # Untracked production consumption (high x 4 / S = 6.0) ranks first.
        assert (
            review.findings[0].finding.rule_id
            == "portfolio_untracked_production_consumption"
        )
        # Every finding cites a real evidence query + the triggering row.
        for rf in review.findings:
            assert rf.evidence
            assert rf.evidence[0].query_id in _EVIDENCE_IDS
            assert rf.evidence[0].row
        assert review.degraded is False
        assert {rf.finding.category for rf in review.findings} == {_RULE_DOMAIN}

    def test_untracked_production_detection_targets_right_row(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["portfolio-readiness"],
            rows_by_query_id={"C-B01": _C_B01_ROWS},
        )
        # Exactly the material, unattributed JOBS product row is flagged.
        assert {rf.finding.rule_id for rf in review.findings} == {
            "portfolio_untracked_production_consumption"
        }
        rf = review.findings[0]
        assert rf.evidence[0].row["billing_origin_product"] == "JOBS"
        assert rf.finding.location is not None
        assert rf.finding.location.entity == "1234567890:JOBS"

    def test_maturity_gaps_gate_on_production_scale(
        self, registry: RuleRegistry
    ) -> None:
        # Only production-scale workloads are flagged: the sub-threshold pilot
        # rows (tiny_unowned, flaky_pilot) must not produce findings.
        review = build_review(
            registry=registry,
            domains=["portfolio-readiness"],
            rows_by_query_id={"C-J01": _C_J01_ROWS, "C-J04": _C_J04_ROWS},
        )
        flagged = {rf.finding.location.entity for rf in review.findings}
        assert flagged == {"nightly_elt", "fragile_prod"}

    def test_domain_degrades_when_evidence_absent(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["portfolio-readiness"],
            rows_by_query_id={},
        )
        assert review.finding_count == 0
        assert review.degraded is True


# --- Governance: no internal identifiers / CRM fields --------------------- #
# Internal namespaces + Salesforce field markers that must never appear in the
# public seed YAML or reference file (CLAUDE.md governance red-lines + research/05).
_FORBIDDEN_MARKERS = (
    "centralized_system_tables",
    "fin_live_gold",
    "gtm_",
    "eng_",
    "logfood",
    "clickhouse",
    "hmr_stack_hash",
    "__c",  # Salesforce custom-field suffix
    "salesforce",
    "monthly_dbus",
    "implementation_status",
    "usecaseinplan",
    "go/",  # internal shortlinks
    "dnb",
    "pubsec",
)
_SEED_YAML = (
    Path(__file__).parents[4]
    / "starboard_core"
    / "domain"
    / "rules"
    / "seed"
    / "portfolio_readiness.yaml"
)
_REFERENCE_DOC = (
    Path(__file__).parents[6]
    / "docs"
    / "reference"
    / "portfolio_readiness.md"
)


@pytest.mark.unit
class TestPortfolioGovernance:
    @pytest.mark.parametrize("path", [_SEED_YAML, _REFERENCE_DOC])
    def test_no_internal_identifiers(self, path: Path) -> None:
        assert path.exists(), path
        text = path.read_text(encoding="utf-8").lower()
        hits = [marker for marker in _FORBIDDEN_MARKERS if marker in text]
        assert not hits, f"{path.name} contains forbidden markers: {hits}"

    def test_reference_documents_list_price_basis(self) -> None:
        # The reference file must label money as list-price DBU estimates.
        text = _REFERENCE_DOC.read_text(encoding="utf-8").lower()
        assert "list-price" in text
