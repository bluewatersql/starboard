# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the seed rule YAML + loader + kernel ``RuleRegistry`` (Phase-1 D3 / Phase-3 D1a).

Proves the shared rule schema loads and validates the seed YAML files
(data only, no engine); that the seed content carries no internal namespaces
or ``go/`` links (governance); that the kernel ``RuleRegistry`` loads them,
ranks them deterministically via the D3 scorer, and validates every rule's
``evidence_query`` against a real query-pack ``query_id`` (closing Phase-1
review finding #3); and that the registry imports with no
``databricks-sdk`` / ``openai`` / ``fastapi`` / ``mcp`` present.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from starboard_core.domain.models.finding import (
    Confidence,
    Effort,
    Finding,
    Severity,
)
from starboard_core.domain.rules import (
    DanglingEvidenceQueryError,
    Rule,
    RuleLoadError,
    RuleRegistry,
    RuleSet,
    load_ruleset_from_string,
    load_rulesets_from_directory,
    rank_findings,
    seed_rules_dir,
)

# starboard-core package dir (…/packages/starboard-core), used as the cwd for
# the isolated-import purity subprocess.
_CORE_DIR = Path(__file__).parents[4]

# The distinct, real query-pack ``query_id`` values the seed rules must resolve
# to after Phase-3 D1a repointed the Phase-1 dangling strings (finding #3) and
# Phase-3 D1c added the jobs seed ruleset:
#   C-Q02  query_perf "Multi-Signal Optimization Candidates"
#   W-W01  warehouse  "Warehouse Utilization Bands"
#   W-W02  warehouse  "Auto-Stop Efficiency / Waste"
#   PO-01  predictive_optimization "PO operations by type" (OPTIMIZE/VACUUM history)
#   C-J03  jobs "Runtime Variance + DBU per Minute"
#   C-J04  jobs "Compound Reliability Scorecard"
# v1 (jobs/sql/warehouse/uc) evidence ids.
_V1_EVIDENCE_QUERY_IDS = {
    "C-Q02", "W-W01", "W-W02", "PO-01", "C-J03", "C-J04",
}
# Phase-2 D-a added the opt-in DLT / ML / vector-search review domains, whose
# seed rules cite these real query-pack query_ids for evidence.
_V2_EVIDENCE_QUERY_IDS = {
    "P-DLT03", "P-DLT01", "P-DLT05", "C-ML01", "P-MLF04", "P-VS03", "P-VS01",
}
_EXPECTED_EVIDENCE_QUERY_IDS = _V1_EVIDENCE_QUERY_IDS | _V2_EVIDENCE_QUERY_IDS

# Internal namespaces / link forms that must never appear in shipped seed data.
_FORBIDDEN_SUBSTRINGS = [
    "go/",
    "centralized_system_tables",
    "fin_live_gold",
    "eng_dp_debug_tools",
    "eng_time_series_metrics",
    "eng_lumberjack",
    "logfood",
    "clickhouse",
]


@pytest.mark.unit
class TestSeedRulesLoad:
    """Every seed rule YAML loads and validates fail-fast against the schema."""

    def test_seed_dir_exists_and_has_yaml(self) -> None:
        d = seed_rules_dir()
        assert d.is_dir(), d
        yaml_files = list(d.glob("*.yaml")) + list(d.glob("*.yml"))
        assert yaml_files, f"no seed rule YAML in {d}"

    def test_all_seed_rulesets_validate(self) -> None:
        rulesets = load_rulesets_from_directory(seed_rules_dir())
        assert rulesets, "expected at least one seed ruleset"
        total_rules = sum(len(rs.rules) for rs in rulesets)
        assert total_rules >= 3, f"expected >= 3 seed rules, got {total_rules}"
        for rs in rulesets:
            assert isinstance(rs, RuleSet)
            for rule in rs.rules:
                assert isinstance(rule.severity, Severity)
                assert isinstance(rule.default_effort, Effort)
                assert 1 <= rule.default_impact <= 5
                assert rule.id
                assert rule.suggested_fix

    def test_rule_ids_unique_across_seed(self) -> None:
        rulesets = load_rulesets_from_directory(seed_rules_dir())
        ids = [rule.id for rs in rulesets for rule in rs.rules]
        assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


@pytest.mark.unit
class TestLoaderFailFast:
    """The loader rejects malformed / invalid rule YAML fail-fast."""

    def test_invalid_severity_fails_fast(self) -> None:
        bad = """
version: "1.0.0"
domain: query
rules:
  - id: bad_rule
    name: Bad Rule
    category: query
    short_description: nope
    rationale: because
    severity: urgent
    default_effort: S
    default_impact: 3
    suggested_fix: fix it
"""
        with pytest.raises(RuleLoadError):
            load_ruleset_from_string(bad)

    def test_duplicate_ids_within_ruleset_fail_fast(self) -> None:
        dup = """
version: "1.0.0"
domain: query
rules:
  - id: same
    name: A
    category: query
    short_description: a
    rationale: a
    severity: low
    default_effort: S
    default_impact: 2
    suggested_fix: a
  - id: same
    name: B
    category: query
    short_description: b
    rationale: b
    severity: low
    default_effort: S
    default_impact: 2
    suggested_fix: b
"""
        with pytest.raises(RuleLoadError):
            load_ruleset_from_string(dup)

    def test_empty_ruleset_fails_fast(self) -> None:
        with pytest.raises(RuleLoadError):
            load_ruleset_from_string("version: '1.0.0'\ndomain: query\nrules: []\n")


@pytest.mark.unit
class TestGovernance:
    """Seed rule content must be free of internal namespaces / go/ links."""

    def test_no_internal_namespaces_in_seed_files(self) -> None:
        offenders: list[str] = []
        for path in sorted(seed_rules_dir().glob("*.y*ml")):
            text = path.read_text(encoding="utf-8").lower()
            for needle in _FORBIDDEN_SUBSTRINGS:
                if needle in text:
                    offenders.append(f"{path.name}: {needle}")
        assert not offenders, f"internal content in seed rules: {offenders}"

    def test_seed_rules_source_has_no_go_links(self) -> None:
        rulesets = load_rulesets_from_directory(seed_rules_dir())
        for rs in rulesets:
            for rule in rs.rules:
                if rule.source is not None:
                    assert not re.search(r"\bgo/", rule.source), rule.source


@pytest.mark.unit
class TestRuleRegistryLoading:
    """The kernel ``RuleRegistry`` loads the seed rules and exposes them."""

    def test_from_seed_loads_all_seed_rules(self) -> None:
        registry = RuleRegistry.from_seed()
        # Same rule count as the raw rulesets — nothing dropped on load.
        rulesets = load_rulesets_from_directory(seed_rules_dir())
        expected = sum(len(rs.rules) for rs in rulesets)
        assert len(registry.rules) == expected
        assert expected >= 3
        assert all(isinstance(r, Rule) for r in registry.rules)

    def test_domains_cover_seed_domains(self) -> None:
        registry = RuleRegistry.from_seed()
        # v1 domains plus the Phase-2 D-a opt-in DLT / ML / vector-search domains.
        assert set(registry.domains) == {
            "query", "warehouse", "uc", "jobs",
            "dlt", "ml", "vector_search",
        }

    def test_jobs_rules_present_and_bind_to_real_query_ids(self) -> None:
        registry = RuleRegistry.from_seed()
        jobs_rules = registry.rules_for("jobs")
        assert {r.id for r in jobs_rules} == {
            "job_high_failure_rate",
            "job_wasted_dbu_on_failures_retries",
            "job_high_runtime_variance",
        }
        # Every jobs rule points at a real jobs query-pack query_id.
        assert {r.evidence_query for r in jobs_rules} == {"C-J03", "C-J04"}

    def test_rules_for_returns_only_that_domain(self) -> None:
        registry = RuleRegistry.from_seed()
        query_rules = registry.rules_for("query")
        assert query_rules, "expected query-domain rules"
        assert {r.id for r in query_rules} == {
            "select_star_projection",
            "non_sargable_partition_filter",
        }

    def test_rules_for_unknown_domain_is_empty(self) -> None:
        registry = RuleRegistry.from_seed()
        assert registry.rules_for("does_not_exist") == []

    def test_rules_for_enabled_only_filters_disabled(self) -> None:
        ruleset = load_ruleset_from_string(
            """
version: "1.0.0"
domain: query
rules:
  - id: on_rule
    name: "On"
    category: query
    short_description: a
    rationale: a
    severity: low
    default_effort: S
    default_impact: 2
    suggested_fix: a
    enabled: true
  - id: off_rule
    name: "Off"
    category: query
    short_description: b
    rationale: b
    severity: low
    default_effort: S
    default_impact: 2
    suggested_fix: b
    enabled: false
"""
        )
        registry = RuleRegistry([ruleset])
        assert {r.id for r in registry.rules_for("query")} == {"on_rule"}
        assert {
            r.id for r in registry.rules_for("query", enabled_only=False)
        } == {"on_rule", "off_rule"}

    def test_duplicate_rule_ids_across_rulesets_raise(self) -> None:
        rs_a = load_ruleset_from_string(
            "version: '1.0.0'\ndomain: query\nrules:\n"
            "  - {id: dup, name: A, category: query, short_description: a, "
            "rationale: a, severity: low, default_effort: S, default_impact: 2, "
            "suggested_fix: a}\n"
        )
        rs_b = load_ruleset_from_string(
            "version: '1.0.0'\ndomain: warehouse\nrules:\n"
            "  - {id: dup, name: B, category: warehouse, short_description: b, "
            "rationale: b, severity: low, default_effort: S, default_impact: 2, "
            "suggested_fix: b}\n"
        )
        with pytest.raises(ValueError, match="Duplicate rule ids"):
            RuleRegistry([rs_a, rs_b])


@pytest.mark.unit
class TestScorerOrdering:
    """The registry wires the D3 scorer into a stable, deterministic order."""

    def test_ranked_rules_expected_total_order(self) -> None:
        # Scores (severity_weight × default_impact / effort_points), tie-break
        # score desc → severity desc → id asc. Phase-2 D-a merged the DLT / ML /
        # vector-search rules into this global order; the v1 rules keep their
        # relative order (asserted separately below).
        #   warehouse_auto_stop_disabled              high(3)*4/XS(1)   = 12.0
        #   dlt_high_pipeline_failure_rate            high(3)*4/S(2)    =  6.0
        #   job_high_failure_rate                     high(3)*4/S(2)    =  6.0
        #   non_sargable_partition_filter             high(3)*4/S(2)    =  6.0
        #   ml_test_demo_endpoint_cleanup             medium(2)*3/XS(1) =  6.0
        #   select_star_projection                    medium(2)*3/XS(1) =  6.0
        #   job_wasted_dbu_on_failures_retries        high(3)*3/S(2)    =  4.5
        #   vector_search_idle_endpoint               medium(2)*4/S(2)  =  4.0
        #   table_missing_maintenance                 medium(2)*3/S(2)  =  3.0
        #   warehouse_persistently_underutilized      medium(2)*3/S(2)  =  3.0
        #   dlt_classic_compute_serverless_candidate  medium(2)*3/M(3)  =  2.0
        #   job_high_runtime_variance                 medium(2)*3/M(3)  =  2.0
        #   dlt_stale_pipeline                        low(1)*2/XS(1)    =  2.0
        #   ml_noisy_experiment                       low(1)*2/S(2)     =  1.0
        #   vector_search_high_cost_endpoint          low(1)*2/S(2)     =  1.0
        registry = RuleRegistry.from_seed()
        ordered = [r.id for r in registry.ranked_rules()]
        assert ordered == [
            "warehouse_auto_stop_disabled",
            "dlt_high_pipeline_failure_rate",
            "job_high_failure_rate",
            "non_sargable_partition_filter",
            "ml_test_demo_endpoint_cleanup",
            "select_star_projection",
            "job_wasted_dbu_on_failures_retries",
            "vector_search_idle_endpoint",
            "table_missing_maintenance",
            "warehouse_persistently_underutilized",
            "dlt_classic_compute_serverless_candidate",
            "job_high_runtime_variance",
            "dlt_stale_pipeline",
            "ml_noisy_experiment",
            "vector_search_high_cost_endpoint",
        ]

    def test_v1_rules_keep_relative_order(self) -> None:
        # The v1 flagship rules retain their exact relative order within the
        # merged ranking (the v2 additions never reorder them).
        registry = RuleRegistry.from_seed()
        v1_ids = {
            "warehouse_auto_stop_disabled",
            "job_high_failure_rate",
            "non_sargable_partition_filter",
            "select_star_projection",
            "job_wasted_dbu_on_failures_retries",
            "table_missing_maintenance",
            "warehouse_persistently_underutilized",
            "job_high_runtime_variance",
        }
        ordered_v1 = [r.id for r in registry.ranked_rules() if r.id in v1_ids]
        assert ordered_v1 == [
            "warehouse_auto_stop_disabled",
            "job_high_failure_rate",
            "non_sargable_partition_filter",
            "select_star_projection",
            "job_wasted_dbu_on_failures_retries",
            "table_missing_maintenance",
            "warehouse_persistently_underutilized",
            "job_high_runtime_variance",
        ]

    def test_ranked_rules_scores_are_non_increasing(self) -> None:
        registry = RuleRegistry.from_seed()
        scores = [registry.rule_score(r) for r in registry.ranked_rules()]
        assert scores == sorted(scores, reverse=True)

    def test_ranked_rules_is_deterministic_across_calls(self) -> None:
        registry = RuleRegistry.from_seed()
        first = [r.id for r in registry.ranked_rules()]
        second = [r.id for r in registry.ranked_rules()]
        assert first == second

    def test_rules_for_is_ranked_within_domain(self) -> None:
        registry = RuleRegistry.from_seed()
        ordered = [r.id for r in registry.rules_for("query")]
        # non_sargable (high, score 6.0) outranks select_star (medium, score 6.0).
        assert ordered == [
            "non_sargable_partition_filter",
            "select_star_projection",
        ]

    def test_rank_findings_is_stable_and_score_ordered(self) -> None:
        def _finding(fid: str, severity: Severity, impact: int, effort: Effort) -> Finding:
            return Finding(
                id=fid,
                severity=severity,
                category="query",
                summary=fid,
                rationale="r",
                current_state="bad",
                suggested_fix="good",
                impact=impact,
                effort=effort,
                confidence=Confidence.MEDIUM,
            )

        findings = [
            _finding("a", Severity.LOW, 1, Effort.XL),      # 1*1/5 = 0.2
            _finding("b", Severity.CRITICAL, 5, Effort.XS),  # 4*5/1 = 20.0
            _finding("c", Severity.MEDIUM, 3, Effort.S),     # 2*3/2 = 3.0
            _finding("d", Severity.HIGH, 3, Effort.S),       # 3*3/2 = 4.5
        ]
        ranked = rank_findings(findings)
        assert [f.id for f in ranked] == ["b", "d", "c", "a"]
        # Deterministic: re-ranking the already-ranked list is a no-op.
        assert [f.id for f in rank_findings(ranked)] == ["b", "d", "c", "a"]

    def test_rank_findings_tie_breaks_by_severity_then_id(self) -> None:
        def _finding(fid: str, severity: Severity, impact: int, effort: Effort) -> Finding:
            return Finding(
                id=fid,
                severity=severity,
                category="query",
                summary=fid,
                rationale="r",
                current_state="bad",
                suggested_fix="good",
                impact=impact,
                effort=effort,
            )

        # All score 6.0; tie-break severity desc then id asc.
        findings = [
            _finding("z_med", Severity.MEDIUM, 3, Effort.XS),  # 2*3/1 = 6.0
            _finding("a_med", Severity.MEDIUM, 3, Effort.XS),  # 6.0
            _finding("m_high", Severity.HIGH, 4, Effort.S),    # 3*4/2 = 6.0
        ]
        ranked = rank_findings(findings)
        assert [f.id for f in ranked] == ["m_high", "a_med", "z_med"]


@pytest.mark.unit
class TestEvidenceQueryValidation:
    """Every seed rule's ``evidence_query`` resolves to a real ``query_id``."""

    def test_seed_evidence_query_ids_are_the_expected_real_ids(self) -> None:
        registry = RuleRegistry.from_seed()
        assert registry.evidence_query_ids() == _EXPECTED_EVIDENCE_QUERY_IDS

    def test_every_seed_rule_has_an_evidence_query(self) -> None:
        # Finding #3 was about dangling references; the seed rules all carry one.
        registry = RuleRegistry.from_seed()
        missing = [r.id for r in registry.rules if r.evidence_query is None]
        assert not missing, f"seed rules without evidence_query: {missing}"

    def test_validate_passes_against_known_ids(self) -> None:
        registry = RuleRegistry.from_seed()
        # Superset of the real ids resolves cleanly.
        registry.validate_evidence_queries(
            _EXPECTED_EVIDENCE_QUERY_IDS | {"C-Q01", "W-W03"}
        )

    def test_validate_raises_on_dangling_reference(self) -> None:
        registry = RuleRegistry.from_seed()
        with pytest.raises(DanglingEvidenceQueryError) as exc_info:
            # Known set holds only C-Q02 + W-W01; every other evidence id
            # (v1 warehouse/uc/jobs + the v2 DLT/ML/vector-search ids) is dangling.
            registry.validate_evidence_queries({"C-Q02", "W-W01"})
        unresolved = exc_info.value.unresolved
        assert set(unresolved.values()) == (
            _EXPECTED_EVIDENCE_QUERY_IDS - {"C-Q02", "W-W01"}
        )

    def test_validate_skips_rules_without_evidence_query(self) -> None:
        ruleset = load_ruleset_from_string(
            "version: '1.0.0'\ndomain: query\nrules:\n"
            "  - {id: no_ev, name: N, category: query, short_description: a, "
            "rationale: a, severity: low, default_effort: S, default_impact: 2, "
            "suggested_fix: a}\n"
        )
        registry = RuleRegistry([ruleset])
        # No evidence_query set → nothing to resolve, empty known set is fine.
        registry.validate_evidence_queries(set())

    def test_seed_evidence_queries_resolve_against_real_query_packs(self) -> None:
        """Closes finding #3 against the real packs (runs in the merged tree).

        The query packs live in the Tier-2 ``starboard`` server package, which
        the kernel must not import; this test reaches across at the *test* tier
        to prove the seed ``evidence_query`` values bind to real ``query_id``
        values. In an isolated worktree ``starboard`` may be unimportable — the
        parent verifies pytest after merging into the main tree.
        """
        from starboard.discovery.query_packs import create_default_registry

        real_query_ids = {
            query.query_id
            for pack in create_default_registry().all_packs
            for query in pack.queries
        }
        # Every id the seed rules point at must be a real pack query_id.
        assert real_query_ids >= _EXPECTED_EVIDENCE_QUERY_IDS
        # And the registry validates cleanly against the real universe.
        RuleRegistry.from_seed().validate_evidence_queries(real_query_ids)


@pytest.mark.unit
class TestRuleRegistryPurity:
    """The registry imports with no databricks-sdk / openai / fastapi / mcp."""

    def test_registry_imports_without_heavy_deps(self) -> None:
        prelude = """
import sys
import importlib.abc


class _Blocker(importlib.abc.MetaPathFinder):
    def __init__(self, prefixes):
        self._prefixes = prefixes

    def find_spec(self, name, path, target=None):
        for prefix in self._prefixes:
            if name == prefix or name.startswith(prefix + "."):
                raise ImportError(f"simulated-absent: {name}")
        return None


sys.meta_path.insert(0, _Blocker(["databricks", "openai", "fastapi", "mcp"]))
"""
        body = """
import sys

from starboard_core.domain.rules import RuleRegistry, rank_findings  # noqa: F401

# Loading + ranking must not pull any forbidden dependency.
registry = RuleRegistry.from_seed()
_ = registry.ranked_rules()
_ = registry.evidence_query_ids()

forbidden = ("databricks", "openai", "fastapi", "mcp")
leaked = sorted(
    m for m in sys.modules
    if any(m == f or m.startswith(f + ".") for f in forbidden)
)
assert not leaked, f"forbidden modules imported: {leaked}"
print("OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", prelude + body],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout
