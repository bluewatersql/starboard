# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 5 (group A): rule evidence DBU, identity suppression, deleted
warehouses, and explicit cap naming in the findings manifest."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from starboard_core.domain.rules.action_rate import FindingsManifest
from starboard_core.domain.rules.detectors import (
    detect_spend_step_change,
    detect_warehouse_auto_stop_disabled,
)
from starboard_core.domain.rules.evaluator import (
    DEFAULT_MAX_FINDINGS_PER_RULE,
    build_review,
)
from starboard_core.domain.rules.registry import RuleRegistry

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


# ---- A1: the step-change evidence DBU is the DBU/day lift ----------------------


def _f03_rows() -> list[dict[str, Any]]:
    start = date(2026, 9, 1)
    rows = []
    for i in range(28):  # 7 baseline days, then 7 flat window days, then a step
        dbus = 100.0 if i < 14 else 1000.0
        rows.append(
            {
                "workspace_id": "123",
                "usage_date": (start + timedelta(days=i)).isoformat(),
                "dbus": dbus,
                "in_window": i >= 7,
            }
        )
    return rows


def test_step_change_cites_the_lift_not_the_step_day_total() -> None:
    (match,) = detect_spend_step_change(_f03_rows())
    assert match.row["dbus"] == 1000.0  # the step-date row is still cited
    assert match.row["evidence_dbu_estimate"] == 900.0
    assert match.row["lift_daily_dbus"] == 900.0
    assert match.row["before_daily_dbus"] == 100.0
    assert match.row["after_daily_dbus"] == 1000.0
    assert match.row["step_date"] == "2026-09-15"


def test_step_change_manifest_dbu_is_the_lift(registry: RuleRegistry) -> None:
    review = build_review(
        registry=registry, domains=["jobs"], rows_by_query_id={"F-03": _f03_rows()}
    )
    manifest = FindingsManifest.from_review(review)
    (record,) = [r for r in manifest.findings if r.rule_id == "spend_step_change"]
    assert record.evidence_dbu_estimate == 900.0


# ---- A4: identity rules are suppressed when the source carries no identity ------


_C_B01_NO_IDENTITY = [
    {
        "workspace_id": "123",
        "billing_origin_product": "VECTOR_SEARCH",
        "run_as": None,
        "user_type": "Unattributed",
        "dbus_consumed": 5000.0,
    }
]
_C_J01_NO_IDENTITY = [
    {"name": "nightly", "job_id": "1", "run_as": None, "total_dbus": 900.0}
]


def test_identity_rules_suppressed_without_identity(registry: RuleRegistry) -> None:
    review = build_review(
        registry=registry,
        domains=["portfolio-readiness"],
        rows_by_query_id={"C-B01": _C_B01_NO_IDENTITY, "C-J01": _C_J01_NO_IDENTITY},
    )
    assert review.finding_count == 0
    suppressed = review.domain_reports[0].suppressed_rules
    assert set(suppressed) == {
        "portfolio_untracked_production_consumption",
        "portfolio_unattended_production_job",
    }
    assert "run_as" in suppressed["portfolio_unattended_production_job"]
    manifest = FindingsManifest.from_review(review)
    assert set(manifest.suppressed_rules) == set(suppressed)
    assert manifest.model_dump()["suppressed_rules"] == suppressed


def test_identity_rules_still_fire_when_identity_is_carried(
    registry: RuleRegistry,
) -> None:
    rows_b = [*_C_B01_NO_IDENTITY, {**_C_B01_NO_IDENTITY[0], "run_as": "a@x.com",
                                    "user_type": "Human User"}]
    rows_j = [*_C_J01_NO_IDENTITY, {"name": "owned", "job_id": "2",
                                    "run_as": "svc", "total_dbus": 900.0}]
    review = build_review(
        registry=registry,
        domains=["portfolio-readiness"],
        rows_by_query_id={"C-B01": rows_b, "C-J01": rows_j},
    )
    assert {rf.finding.rule_id for rf in review.findings} == {
        "portfolio_untracked_production_consumption",
        "portfolio_unattended_production_job",
    }
    assert FindingsManifest.from_review(review).suppressed_rules == {}


# ---- A5: auto-stop rule title and deleted warehouses -----------------------------


def test_auto_stop_rule_is_titled_for_idle_time(registry: RuleRegistry) -> None:
    (rule,) = [r for r in registry.rules if r.id == "warehouse_auto_stop_disabled"]
    assert "idle" in rule.name.lower()
    assert not rule.name.lower().startswith("enable auto-stop")


def test_deleted_warehouse_is_not_flagged() -> None:
    rows = [
        {"warehouse_id": "gone", "auto_stop_waste_pct": 90.0, "auto_stop_minutes": 0,
         "delete_time": "2026-10-13T08:00:00Z"},
        {"warehouse_id": "live", "auto_stop_waste_pct": 90.0, "auto_stop_minutes": 0,
         "delete_time": None},
    ]
    assert [m.entity_key for m in detect_warehouse_auto_stop_disabled(rows)] == ["live"]


# ---- A6: the per-rule finding cap is named apart from the query row limit --------


def _variance_rows(n: int) -> list[dict[str, Any]]:
    return [
        {"job_id": f"{i}", "total_runs": 10, "max_min_ratio": 10.0 + i} for i in range(n)
    ]


def test_rule_finding_cap_is_explicit_on_records(registry: RuleRegistry) -> None:
    review = build_review(
        registry=registry,
        domains=["jobs"],
        rows_by_query_id={"C-J03": _variance_rows(50), "C-J04": []},
    )
    records = [
        r
        for r in FindingsManifest.from_review(review).findings
        if r.rule_id == "job_high_runtime_variance"
    ]
    assert len(records) == DEFAULT_MAX_FINDINGS_PER_RULE
    assert {r.rule_finding_cap for r in records} == {DEFAULT_MAX_FINDINGS_PER_RULE}
    assert {r.rule_findings_dropped for r in records} == {30}
    assert not any(r.evidence_capped for r in records)  # no query hit its row limit


def test_uncapped_rule_records_carry_no_cap(registry: RuleRegistry) -> None:
    rows = _variance_rows(3) + _variance_rows(3)  # duplicates are not a cap
    review = build_review(
        registry=registry,
        domains=["jobs"],
        rows_by_query_id={"C-J03": rows, "C-J04": []},
        limit_reached_query_ids=("C-J03",),
    )
    records = [
        r
        for r in FindingsManifest.from_review(review).findings
        if r.rule_id == "job_high_runtime_variance"
    ]
    assert len(records) == 3
    assert {(r.rule_finding_cap, r.rule_findings_dropped) for r in records} == {(None, None)}
    assert all(r.evidence_capped for r in records)  # the query row limit, separately
