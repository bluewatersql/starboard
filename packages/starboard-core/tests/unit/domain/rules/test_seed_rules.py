# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the seed rule YAML + loader (Phase-1 D3).

Proves the shared rule schema loads and validates the seed YAML files
(data only, no engine) and that the seed content carries no internal
namespaces or ``go/`` links (governance).
"""

from __future__ import annotations

import re

import pytest
from starboard_core.domain.models.finding import Effort, Severity
from starboard_core.domain.rules import (
    RuleLoadError,
    RuleSet,
    load_ruleset_from_string,
    load_rulesets_from_directory,
    seed_rules_dir,
)

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
