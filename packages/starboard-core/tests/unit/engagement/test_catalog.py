# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the six-family metric catalog (spec §C, D3-15)."""

from __future__ import annotations

import dataclasses

import pytest
from starboard_core.engagement.catalog import FAMILY_METRICS, SIX_FAMILIES, MetricSpec
from starboard_core.engagement.records import ENTITY_KINDS, FAMILIES, UNITS


def test_six_families_in_families_order_without_other() -> None:
    assert tuple(f for f in FAMILIES if f != "other") == SIX_FAMILIES
    assert len(SIX_FAMILIES) == 6
    assert tuple(FAMILY_METRICS) == SIX_FAMILIES


def test_metric_spec_is_frozen() -> None:
    spec = FAMILY_METRICS["reliability"][0]
    assert isinstance(spec, MetricSpec)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.metric = "x"  # type: ignore[misc]


@pytest.mark.parametrize("family", [f for f in SIX_FAMILIES if f != "governance"])
def test_every_family_but_governance_has_a_required_facts_metric(family: str) -> None:
    required = [
        s
        for s in FAMILY_METRICS[family]
        if s.required and s.source != "findings_manifest"
    ]
    assert required, family


def test_governance_has_only_required_rule_metrics() -> None:
    specs = FAMILY_METRICS["governance"]
    assert {s.metric for s in specs} == {"rules_evaluated", "active_rule_findings"}
    assert all(s.required and s.source == "findings_manifest" for s in specs)


@pytest.mark.parametrize("family", SIX_FAMILIES)
def test_rule_metrics_in_every_family(family: str) -> None:
    rule = {
        s.metric: s for s in FAMILY_METRICS[family] if s.source == "findings_manifest"
    }
    assert set(rule) == {"rules_evaluated", "active_rule_findings"}
    for spec in rule.values():
        assert (spec.unit, spec.entity_kind) == ("count", "workspace")
        assert spec.required is (family == "governance")


def test_workspace_reliability_comes_only_from_f06() -> None:
    ws = [
        s
        for s in FAMILY_METRICS["reliability"]
        if s.entity_kind == "workspace" and s.source != "findings_manifest"
    ]
    assert {s.metric for s in ws} == {
        "job_runs",
        "failed_job_runs",
        "cancelled_job_runs",
        "job_failure_rate_pct",
    }
    assert all(s.source == "F-06" and s.required for s in ws)
    per_job = [s for s in FAMILY_METRICS["reliability"] if s.entity_kind == "job"]
    assert {s.metric for s in per_job} == {
        "job_runs",
        "failed_job_runs",
        "job_failure_rate_pct",
    }
    assert all(not s.required and "F-06" not in s.source for s in per_job)


def test_units_and_entity_kinds_are_in_vocabulary() -> None:
    for specs in FAMILY_METRICS.values():
        for s in specs:
            assert s.unit in UNITS, s
            assert s.entity_kind in ENTITY_KINDS, s
            assert s.source


def test_metric_keys_unique_per_family() -> None:
    for family, specs in FAMILY_METRICS.items():
        keys = [(s.metric, s.entity_kind) for s in specs]
        assert len(keys) == len(set(keys)), family


def test_concern_flags_are_not_catalog_metrics() -> None:
    metrics = {s.metric for specs in FAMILY_METRICS.values() for s in specs}
    assert "finding_present" not in metrics
    assert "job_failure_concern" not in metrics


def test_catalog_table_rows() -> None:
    def row(family: str, metric: str, entity: str = "workspace") -> MetricSpec:
        (spec,) = [
            s
            for s in FAMILY_METRICS[family]
            if s.metric == metric and s.entity_kind == entity
        ]
        return spec

    assert row("consumption_trajectory", "total_dbus") == MetricSpec(
        "total_dbus", "DBU", "workspace", "F-01", True
    )
    assert row("consumption_trajectory", "total_dsu").unit == "DSU"
    assert (
        row("consumption_trajectory", "step_change_lift_daily_dbus").unit == "DBU/day"
    )
    assert row("consumption_trajectory", "month_over_month_pct").required is False
    assert row("efficiency", "performance_optimized_pct").required is True
    assert row("efficiency", "warehouse_serverless_share_pct").source == "F-08|F-09"
    assert row("adoption_breadth", "products_in_use").required is True
    assert row("adoption_breadth", "product_in_use", "product").unit == "flag"
    assert row("concentration", "top_job_share_pct").source == "F-04"
    assert row("concentration", "top_warehouse_share_pct").source == "F-11"
    assert row("concentration", "top_product_share_pct").required is False
