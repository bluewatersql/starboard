# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Rule family / entity_kind tags (phase-3 D3-17).

Every seed rule carries a ``family`` (one of the six) and an ``entity_kind``;
the tags are optional so user rule directories without them keep loading, and
``rule_family`` falls back to ``"unclassified"``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from starboard_core.domain.rules import (
    Rule,
    RuleRegistry,
    load_ruleset_from_string,
)
from starboard_core.domain.rules.registry import rule_entity_kind, rule_family

SIX = {
    "reliability",
    "efficiency",
    "consumption_trajectory",
    "governance",
    "adoption_breadth",
    "concentration",
}

EXPECTED: dict[str, tuple[str, str]] = {
    "job_high_failure_rate": ("reliability", "job"),
    "job_wasted_dbu_on_failures_retries": ("reliability", "job"),
    "dlt_high_pipeline_failure_rate": ("reliability", "pipeline"),
    "portfolio_unreliable_production_workload": ("reliability", "job"),
    "job_high_runtime_variance": ("efficiency", "job"),
    "job_cron_overlap": ("efficiency", "job"),
    "job_wait_tasks": ("efficiency", "job"),
    "warehouse_auto_stop_disabled": ("efficiency", "warehouse"),
    "warehouse_persistently_underutilized": ("efficiency", "warehouse"),
    "warehouse_queueing": ("efficiency", "warehouse"),
    "warehouse_recent_resize": ("efficiency", "warehouse"),
    "select_star_projection": ("efficiency", "query"),
    "non_sargable_partition_filter": ("efficiency", "query"),
    "dlt_classic_compute_serverless_candidate": ("efficiency", "pipeline"),
    "dlt_stale_pipeline": ("efficiency", "pipeline"),
    "ml_test_demo_endpoint_cleanup": ("efficiency", "endpoint"),
    "ml_noisy_experiment": ("efficiency", "endpoint"),
    "vector_search_idle_endpoint": ("efficiency", "endpoint"),
    "vector_search_high_cost_endpoint": ("efficiency", "endpoint"),
    "spend_step_change": ("consumption_trajectory", "workspace"),
    "table_missing_maintenance": ("governance", "table"),
    "portfolio_untracked_production_consumption": ("governance", "workspace"),
    "portfolio_unattended_production_job": ("governance", "job"),
}

_RULE = """
version: "1.0.0"
domain: custom
rules:
  - id: my_rule
    name: My rule
    category: custom
    short_description: d
    rationale: r
    severity: low
    default_effort: S
    default_impact: 1
    suggested_fix: f
{extra}
"""


@pytest.fixture(scope="module")
def registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


def test_expected_table_covers_all_23_seed_rules(registry: RuleRegistry) -> None:
    assert {r.id for r in registry.rules} == set(EXPECTED)
    assert len(EXPECTED) == 23


@pytest.mark.parametrize("rule_id", sorted(EXPECTED))
def test_seed_rule_family_and_entity_kind(registry: RuleRegistry, rule_id: str) -> None:
    family, kind = EXPECTED[rule_id]
    rule = next(r for r in registry.rules if r.id == rule_id)
    assert rule.family == family
    assert rule.family in SIX
    assert rule.entity_kind == kind
    assert rule_family(rule_id, registry) == family
    assert rule_entity_kind(rule_id, registry) == kind


def test_rule_family_default_registry() -> None:
    assert rule_family("job_high_failure_rate") == "reliability"
    assert rule_entity_kind("job_high_failure_rate") == "job"


def test_unknown_rule_is_unclassified() -> None:
    assert rule_family("no_such_rule") == "unclassified"
    assert rule_entity_kind("no_such_rule") is None


def test_custom_directory_without_family_loads(tmp_path: Path) -> None:
    (tmp_path / "custom.yaml").write_text(_RULE.format(extra=""))
    reg = RuleRegistry.from_seed(tmp_path)
    assert [r.id for r in reg.rules] == ["my_rule"]
    assert reg.rules[0].family is None
    assert rule_family("my_rule", reg) == "unclassified"
    assert rule_entity_kind("my_rule", reg) is None


def test_custom_directory_with_family_is_read(tmp_path: Path) -> None:
    (tmp_path / "custom.yaml").write_text(
        _RULE.format(extra="    family: governance\n    entity_kind: table\n")
    )
    reg = RuleRegistry.from_seed(tmp_path)
    assert rule_family("my_rule", reg) == "governance"
    assert rule_entity_kind("my_rule", reg) == "table"


@pytest.mark.parametrize("bad", ["other", "unclassified", "nonsense", ""])
def test_invalid_family_fails_validation(bad: str) -> None:
    with pytest.raises(Exception) as exc:
        load_ruleset_from_string(_RULE.format(extra=f"    family: '{bad}'\n"))
    assert "family" in str(exc.value)


def test_rule_model_rejects_other_family() -> None:
    with pytest.raises(ValidationError):
        Rule(
            id="x",
            name="x",
            category="c",
            short_description="d",
            rationale="r",
            severity="low",  # type: ignore[arg-type]
            default_effort="S",  # type: ignore[arg-type]
            default_impact=1,
            suggested_fix="f",
            family="other",
        )
