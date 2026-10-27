# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Workload Review v2 domains — DLT / ML / vector-search (D-a).

Phase-2 D-a adds three **opt-in** review domains over the already-present query
packs (``dlt_pipelines`` / ``ml`` / ``mlflow`` / ``vector_search``), reusing the
kernel rule engine (seed YAML → :class:`RuleRegistry` → detectors →
:func:`build_review`). This proves, at the pure kernel tier:

* the new seed rulesets load and expose their rules under the new rule-domains;
* every new rule's ``evidence_query`` binds to a **real** query-pack ``query_id``;
* each new domain produces ranked, evidence-cited findings against its pack via
  the registered detectors;
* the caller-facing ``--domain`` tokens (incl. the ``vector-search`` hyphen
  alias) route through :data:`DOMAIN_TO_RULE_DOMAIN`; and
* the v1 scope (jobs/sql/warehouse) and defaults are unchanged.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.rules import (
    DEFAULT_DOMAINS,
    DOMAIN_TO_RULE_DOMAIN,
    RuleRegistry,
)
from starboard_core.domain.rules.evaluator import build_review

# The new v2 rule-domains and the rules each ships.
_V2_RULE_DOMAINS = {"dlt", "ml", "vector_search"}
_V2_RULE_IDS = {
    "dlt": {
        "dlt_high_pipeline_failure_rate",
        "dlt_stale_pipeline",
        "dlt_classic_compute_serverless_candidate",
    },
    "ml": {
        "ml_test_demo_endpoint_cleanup",
        "ml_noisy_experiment",
    },
    "vector_search": {
        "vector_search_idle_endpoint",
        "vector_search_high_cost_endpoint",
    },
}
# The real query-pack query_ids the new rules cite for evidence.
_V2_EVIDENCE_IDS = {
    "dlt": {"P-DLT03", "P-DLT01", "P-DLT05"},
    "ml": {"C-ML01", "P-MLF04"},
    "vector_search": {"P-VS03", "P-VS01"},
}


@pytest.fixture
def registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


@pytest.mark.unit
class TestV2SeedRulesLoad:
    def test_new_rule_domains_present(self, registry: RuleRegistry) -> None:
        assert set(registry.domains) >= _V2_RULE_DOMAINS

    def test_new_domains_expose_expected_rules(
        self, registry: RuleRegistry
    ) -> None:
        for rule_domain, ids in _V2_RULE_IDS.items():
            got = {r.id for r in registry.rules_for(rule_domain)}
            assert got == ids, rule_domain

    def test_new_rules_category_matches_domain(
        self, registry: RuleRegistry
    ) -> None:
        for rule_domain in _V2_RULE_DOMAINS:
            for rule in registry.rules_for(rule_domain):
                assert rule.category == rule_domain

    def test_v1_scope_unchanged(self, registry: RuleRegistry) -> None:
        # The v1 flagship domains and defaults are untouched by the v2 add.
        assert {"query", "warehouse", "uc", "jobs"} <= set(registry.domains)
        assert DEFAULT_DOMAINS == ("jobs", "sql", "warehouse")


@pytest.mark.unit
class TestV2EvidenceQueriesResolve:
    def test_new_rules_cite_expected_real_query_ids(
        self, registry: RuleRegistry
    ) -> None:
        for rule_domain, evidence in _V2_EVIDENCE_IDS.items():
            got = {
                r.evidence_query
                for r in registry.rules_for(rule_domain)
                if r.evidence_query is not None
            }
            assert got == evidence, rule_domain

    def test_v2_evidence_resolves_against_real_query_packs(self) -> None:
        """The new evidence ``query_id`` values are real pack query_ids.

        Reaches across to the Tier-2 ``starboard`` packs at the *test* tier
        (the kernel must not import them). In an isolated worktree ``starboard``
        may be unimportable; the parent verifies pytest in the merged tree.
        """
        from starboard.discovery.query_packs import create_default_registry

        real_ids = {
            q.query_id
            for pack in create_default_registry().all_packs
            for q in pack.queries
        }
        wanted = set().union(*_V2_EVIDENCE_IDS.values())
        assert wanted <= real_ids
        # The whole registry (v1 + v2) validates cleanly against the real universe.
        RuleRegistry.from_seed().validate_evidence_queries(real_ids)


@pytest.mark.unit
class TestV2DomainRouting:
    def test_domain_tokens_map_to_rule_domains(self) -> None:
        assert DOMAIN_TO_RULE_DOMAIN["dlt"] == "dlt"
        assert DOMAIN_TO_RULE_DOMAIN["pipelines"] == "dlt"
        assert DOMAIN_TO_RULE_DOMAIN["ml"] == "ml"
        assert DOMAIN_TO_RULE_DOMAIN["vector_search"] == "vector_search"
        # CLI-friendly hyphen alias routes to the same rule-domain.
        assert DOMAIN_TO_RULE_DOMAIN["vector-search"] == "vector_search"

    def test_v1_mappings_unchanged(self) -> None:
        assert DOMAIN_TO_RULE_DOMAIN["jobs"] == "jobs"
        assert DOMAIN_TO_RULE_DOMAIN["sql"] == "query"
        assert DOMAIN_TO_RULE_DOMAIN["warehouse"] == "warehouse"
        assert DOMAIN_TO_RULE_DOMAIN["uc"] == "uc"


# --- Golden evidence rows shaped like the real query-pack outputs ---------- #
_DLT_ROWS = {
    "P-DLT03": [
        {
            "pipeline_name": "bronze_ingest",
            "pipeline_id": "pl-flaky",
            "total_updates": 40,
            "failure_rate_pct": 55.0,  # >= 20 → high failure rate
        },
        {
            "pipeline_name": "silver_agg",
            "pipeline_id": "pl-ok",
            "total_updates": 40,
            "failure_rate_pct": 2.0,  # below threshold → no finding
        },
        {
            "pipeline_name": "tiny",
            "pipeline_id": "pl-tiny",
            "total_updates": 1,  # too few updates → not meaningful
            "failure_rate_pct": 100.0,
        },
    ],
    "P-DLT01": [
        {
            "pipeline_name": "abandoned",
            "pipeline_id": "pl-stale",
            "days_since_last_update": 120,  # >= 60 → stale
        },
        {
            "pipeline_name": "recent",
            "pipeline_id": "pl-fresh",
            "days_since_last_update": 3,  # fresh → no finding
        },
    ],
    "P-DLT05": [
        {
            "pipeline_name": "classic_heavy",
            "pipeline_id": "pl-classic",
            "is_serverless_config": False,
            "dbus": 400.0,  # classic + spend → serverless candidate
        },
        {
            "pipeline_name": "classic_trivial",
            "pipeline_id": "pl-trivial",
            "is_serverless_config": False,
            "dbus": 1.0,  # spend below threshold → no finding
        },
    ],
}

_ML_ROWS = {
    "C-ML01": [
        {
            "endpoint_name": "demo-classifier",
            "endpoint_type": "Test/Demo (cleanup candidate)",
            "serving_tier": "Real-Time Inference",
            "total_dbus": 42.0,  # test/demo + billed → cleanup
        },
        {
            "endpoint_name": "prod-ranker",
            "endpoint_type": "Custom Model",
            "serving_tier": "Real-Time Inference",
            "total_dbus": 900.0,  # production model → no finding
        },
    ],
    "P-MLF04": [
        {
            "experiment_name": "hyperparam-sweep",
            "experiment_id": "exp-noisy",
            "success_ratio": 0.4,
            "run_count": 200,
            "is_noisy": True,  # → noisy experiment
        },
        {
            "experiment_name": "clean-exp",
            "experiment_id": "exp-clean",
            "success_ratio": 0.99,
            "run_count": 60,
            "is_noisy": False,  # → no finding
        },
    ],
}

_VS_ROWS = {
    "P-VS03": [
        {
            "endpoint_name": "vs-idle",
            "storage_quantity": 30.0,
            "serving_quantity": 0.0,  # billed storage, no serving → idle
        },
    ],
    "P-VS01": [
        {
            "endpoint_name": "vs-expensive",
            "first_billed_date": "2026-07-01",
            "last_billed_date": "2026-08-27",
            "num_usage_records": 500,
            "total_dbus": 5000.0,  # >= threshold → high-cost review candidate
        },
        {
            "endpoint_name": "vs-cheap",
            "first_billed_date": "2026-08-01",
            "last_billed_date": "2026-08-27",
            "num_usage_records": 5,
            "total_dbus": 3.0,  # below threshold → no finding
        },
    ],
}


@pytest.mark.unit
class TestV2FindingsPerDomain:
    def test_dlt_domain_ranked_evidence_cited_findings(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry,
            domains=["dlt"],
            rows_by_query_id=_DLT_ROWS,
            workspace="acme",
        )
        rule_ids = {rf.finding.rule_id for rf in review.findings}
        assert rule_ids == {
            "dlt_high_pipeline_failure_rate",
            "dlt_stale_pipeline",
            "dlt_classic_compute_serverless_candidate",
        }
        # Ranked: highest score first (failure-rate high×4/S = 6.0 leads).
        assert review.findings[0].finding.rule_id == "dlt_high_pipeline_failure_rate"
        # Every finding cites a real evidence query + the triggering row.
        for rf in review.findings:
            assert rf.evidence
            assert rf.evidence[0].query_id in _V2_EVIDENCE_IDS["dlt"]
            assert rf.evidence[0].row
        assert review.degraded is False
        assert {rf.finding.category for rf in review.findings} == {"dlt"}

    def test_ml_domain_findings_from_both_packs(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry, domains=["ml"], rows_by_query_id=_ML_ROWS
        )
        by_rule = {rf.finding.rule_id: rf for rf in review.findings}
        assert set(by_rule) == {
            "ml_test_demo_endpoint_cleanup",
            "ml_noisy_experiment",
        }
        # ml domain draws evidence from ml.py (C-ML01) AND mlflow.py (P-MLF04).
        assert by_rule["ml_test_demo_endpoint_cleanup"].evidence[0].query_id == "C-ML01"
        assert by_rule["ml_noisy_experiment"].evidence[0].query_id == "P-MLF04"
        assert review.degraded is False

    def test_vector_search_domain_and_hyphen_alias_route(
        self, registry: RuleRegistry
    ) -> None:
        for token in ("vector_search", "vector-search"):
            review = build_review(
                registry=registry, domains=[token], rows_by_query_id=_VS_ROWS
            )
            rule_ids = {rf.finding.rule_id for rf in review.findings}
            assert rule_ids == {
                "vector_search_idle_endpoint",
                "vector_search_high_cost_endpoint",
            }, token
            assert review.domain_reports[0].rule_domain == "vector_search"
            assert review.degraded is False

    def test_v2_domain_degrades_when_evidence_absent(
        self, registry: RuleRegistry
    ) -> None:
        review = build_review(
            registry=registry, domains=["dlt"], rows_by_query_id={}
        )
        assert review.finding_count == 0
        assert review.degraded is True

    def test_v1_and_v2_domains_compose_without_interference(
        self, registry: RuleRegistry
    ) -> None:
        rows = {**_DLT_ROWS, **_VS_ROWS}
        review = build_review(
            registry=registry,
            domains=["dlt", "vector-search"],
            rows_by_query_id=rows,
        )
        cats = {rf.finding.category for rf in review.findings}
        assert cats == {"dlt", "vector_search"}
