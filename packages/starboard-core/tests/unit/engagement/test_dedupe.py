# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for explicit dedupe keys and observation merging (D3-19)."""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.dedupe import (
    DEDUPE_KEYS,
    dedupe_rows,
    job_aggregate_dedupe_key,
    merge,
    merge_observations,
    observation_dedupe_key,
)
from starboard_core.engagement.jobruns import METHOD_VERSION
from starboard_core.engagement.records import Observation, observation_id

RUN = "20261001_12345678-1234-4234-8234-123456789abc"
WS = "123"
START = "2026-09-01"
END = "2026-09-30"

_KEY_FIELDS = (
    "account_key",
    "workspace_id",
    "family",
    "entity_kind",
    "entity_id",
    "metric",
    "interval_start",
    "interval_end",
    "method_version",
)


def obs(**over: Any) -> Observation:
    base: dict[str, Any] = {
        "run_id": RUN,
        "account_key": "AR-000000001",
        "workspace_id": WS,
        "family": "reliability",
        "entity_kind": "job",
        "entity_id": "42",
        "metric": "failed_job_runs",
        "value": 5.0,
        "unit": "count",
        "grain": "interval",
        "method_version": METHOD_VERSION,
        "interval_start": START,
        "interval_end": END,
        "as_of": "2026-10-01T00:00:00+00:00",
        "coverage": "complete",
        "coverage_fraction": None,
        "state": "measured",
        "unknown_reason": None,
        "evidence_ids": ("ev_c",),
        "source_kind": "customer_workspace",
        "audience_class": "customer_shareable",
        "dedupe_key": "job_run_slice|123|42|2026-09-01|2026-09-30",
    }
    base.update(over)
    base["observation_id"] = observation_id(tuple(base[k] for k in _KEY_FIELDS))
    return Observation(**base)


def aggregate(**over: Any) -> Observation:
    entity = over.get("entity_id", "42")
    over.setdefault(
        "dedupe_key",
        job_aggregate_dedupe_key(WS, entity, START, END, METHOD_VERSION),
    )
    over.setdefault("coverage", "partial")
    over.setdefault("evidence_ids", ("ev_f12",))
    return obs(**over)


# ---- keys ----------------------------------------------------------------------


def test_every_kind_has_explicit_fields() -> None:
    assert set(DEDUPE_KEYS) == {
        "job_run",
        "job_aggregate_slice",
        "price_catalog",
        "node_type",
        "billing_usage",
        "observation",
    }
    for kind, fields in DEDUPE_KEYS.items():
        assert isinstance(fields, tuple) and fields, kind
        assert all(isinstance(f, str) and f for f in fields), kind
    assert DEDUPE_KEYS["job_run"] == ("workspace_id", "job_id", "run_id")
    assert DEDUPE_KEYS["job_aggregate_slice"] == (
        "workspace_id",
        "job_id",
        "window_start",
        "window_end",
        "method_version",
    )
    assert DEDUPE_KEYS["price_catalog"] == (
        "sku_name",
        "cloud",
        "usage_unit",
        "price_start_time",
    )
    assert DEDUPE_KEYS["node_type"] == ("node_type",)
    assert DEDUPE_KEYS["billing_usage"] == ("record_id",)
    assert DEDUPE_KEYS["observation"] == _KEY_FIELDS


def test_keys_are_read_only() -> None:
    with pytest.raises(TypeError):
        DEDUPE_KEYS["job_run"] = ("x",)  # type: ignore[index]


def test_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="kind"):
        dedupe_rows("nope", [])


def test_missing_key_field_raises() -> None:
    with pytest.raises(ValueError, match="run_id"):
        dedupe_rows("job_run", [{"workspace_id": WS, "job_id": "42"}])


# ---- dedupe_rows ---------------------------------------------------------------


def test_price_catalog_collapses_per_tenant_replicas() -> None:
    price = {
        "sku_name": "PREMIUM_JOBS_COMPUTE",
        "cloud": "AWS",
        "usage_unit": "DBU",
        "price_start_time": "2026-01-01T00:00:00",
        "pricing": {"default": "0.15"},
    }
    replicas = [
        {**price, "account_id": f"tenant-{i}", "workspace_id": str(i)}
        for i in range(50)
    ]
    other = {**price, "usage_unit": "HOUR", "account_id": "tenant-0"}
    result = dedupe_rows("price_catalog", [*replicas, other])
    assert len(result.unique) == 2
    assert result.duplicates == 49
    assert result.conflicts == ()


def test_node_type_collapses_fan_out() -> None:
    rows = [
        {
            "node_type": "i3.xlarge",
            "core_count": 4,
            "memory_mb": 31232,
            "workspace_id": str(i),
        }
        for i in range(10)
    ] + [{"node_type": "m5.large", "core_count": 2, "memory_mb": 8192}]
    result = dedupe_rows("node_type", rows)
    assert [r["node_type"] for r in result.unique] == ["i3.xlarge", "m5.large"]
    assert result.duplicates == 9


def test_conflicting_group_is_dropped() -> None:
    rows = [
        {"record_id": "a", "usage_quantity": 1.0},
        {"record_id": "a", "usage_quantity": 2.0},
        {"record_id": "b", "usage_quantity": 3.0},
    ]
    result = dedupe_rows("billing_usage", rows)
    assert [r["record_id"] for r in result.unique] == ["b"]
    assert result.conflicts == (("a",),)
    assert result.duplicates == 0


def test_job_run_mirror_copy_collapses() -> None:
    row = {"workspace_id": WS, "job_id": "42", "run_id": "r1", "result_state": "FAILED"}
    result = dedupe_rows("job_run", [row, dict(row)])
    assert len(result.unique) == 1
    assert result.duplicates == 1


# ---- observation keys --------------------------------------------------------------


def test_observation_key_prefers_dedupe_key() -> None:
    o = obs()
    assert observation_dedupe_key(o) == o.dedupe_key
    bare = obs(dedupe_key=None)
    assert observation_dedupe_key(bare) == "|".join(bare.key)


def test_aggregate_key_marks_kind() -> None:
    key = job_aggregate_dedupe_key(WS, "42", START, END, METHOD_VERSION)
    assert key == f"job_aggregate_slice|{WS}|42|{START}|{END}|{METHOD_VERSION}"


# ---- merge_observations --------------------------------------------------------------


def test_equal_values_merge_most_restrictive_source() -> None:
    customer = obs()
    mirror = obs(
        evidence_ids=("ev_m",),
        source_kind="internal_mirror",
        audience_class="internal_only",
        as_of="2026-10-02T00:00:00+00:00",
    )
    (merged,) = merge_observations([customer, mirror])
    assert merged.value == 5.0
    assert merged.state == "measured"
    assert merged.source_kind == "internal_mirror"
    assert merged.audience_class == "internal_only"
    assert merged.evidence_ids == ("ev_c", "ev_m")
    assert merged.as_of == "2026-10-02T00:00:00+00:00"
    assert merged.observation_id == customer.observation_id


def test_unequal_values_give_source_conflict() -> None:
    (merged,) = merge_observations([obs(), obs(value=6.0, evidence_ids=("ev_m",))])
    assert merged.state == "unknown"
    assert merged.value is None
    assert merged.unknown_reason == "source_conflict"
    assert merged.coverage == "unknown"
    assert merged.evidence_ids == ("ev_c", "ev_m")


def test_run_level_supersedes_aggregate_for_same_job() -> None:
    f12 = aggregate(value=7.0)
    run_level = obs(value=5.0)
    result = merge([f12, run_level])
    (kept,) = result.observations
    assert kept.value == 5.0
    assert kept.dedupe_key == run_level.dedupe_key
    assert result.superseded == ((kept.observation_id, f12),)
    assert merge_observations([run_level, f12]) == result.observations


def test_aggregate_for_other_job_is_kept() -> None:
    f12_other = aggregate(entity_id="43", value=7.0)
    run_level = obs(value=5.0)
    out = merge_observations([f12_other, run_level])
    assert {(o.entity_id, o.value) for o in out} == {("43", 7.0), ("42", 5.0)}


def test_conflicting_run_level_supersedes_aggregate() -> None:
    # Spec E3 / §I: a run-level source conflict stays unknown; it never falls
    # back to the capped F-12 value (which could read as serious).
    f12 = aggregate(value=7.0)
    unknown = obs(
        value=None,
        state="unknown",
        unknown_reason="source_conflict",
        coverage="unknown",
    )
    result = merge([f12, unknown])
    (kept,) = result.observations
    assert kept.state == "unknown" and kept.value is None
    assert kept.unknown_reason == "source_conflict"
    assert result.superseded == ((kept.observation_id, f12),)


def test_uncovered_run_level_does_not_supersede_aggregate() -> None:
    f12 = aggregate(value=7.0)
    unknown = obs(
        value=None,
        state="unknown",
        unknown_reason="missing_source:vt-job-run-states",
        coverage="unknown",
    )
    (kept,) = merge_observations([f12, unknown])
    assert kept.value == 7.0


def test_workspace_grain_value_is_never_superseded() -> None:
    f06 = obs(
        entity_kind="workspace",
        entity_id=WS,
        metric="job_failure_rate_pct",
        unit="pct",
        value=12.5,
        dedupe_key=job_aggregate_dedupe_key(WS, WS, START, END, METHOD_VERSION),
        evidence_ids=("ev_f06",),
    )
    run_level_same_key = obs(
        entity_kind="workspace",
        entity_id=WS,
        metric="job_failure_rate_pct",
        unit="pct",
        value=40.0,
    )
    per_job = obs(metric="job_failure_rate_pct", unit="pct", value=40.0)
    result = merge([f06, run_level_same_key, per_job])
    assert result.superseded == ()
    ws = [o for o in result.observations if o.entity_kind == "workspace"]
    (ws_obs,) = ws
    assert ws_obs.value != 40.0  # never replaced by a job-filtered value
    assert any(o.entity_kind == "job" and o.value == 40.0 for o in result.observations)
    alone = merge_observations([f06, per_job])
    assert [o for o in alone if o.entity_kind == "workspace"] == [f06]


def test_measured_copy_preferred_over_unknown_copy() -> None:
    unknown = obs(value=None, state="unknown", unknown_reason="missing_source:verify")
    (kept,) = merge_observations([unknown, obs()])
    assert kept.state == "measured"


def test_singletons_pass_through_in_order() -> None:
    a = obs(entity_id="1")
    b = obs(entity_id="2")
    assert merge_observations([b, a]) == (b, a)
