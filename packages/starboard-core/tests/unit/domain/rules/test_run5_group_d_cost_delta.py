# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-5 group D7: ``compute_cost_delta`` applies the recur window-comparability rule.

Overlapping manifest windows are a recapture (``interval_overlap``), not a change; a
different lookback is ``window_mismatch``; abutting windows and lookbacks within the
±1-day tolerance stay comparable — the same rule ``run recur`` applies.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.rules.action_rate import (
    compute_cost_delta,
    manifest_interval,
    window_comparability,
)

from .test_cost_delta import _finding, _manifest

pytestmark = pytest.mark.unit


def _pair(prior_date: str, prior_lb: int = 30, cur_lb: int = 30):
    f = _finding(rule_id="W-IDLE", entity="wh-1", dbu=40.0)
    prev = _manifest(f, run_date=prior_date, lookback_days=prior_lb, products_dbu={"SQL": 100.0})
    curr = _manifest(f, run_date="2026-09-18", lookback_days=cur_lb, products_dbu={"SQL": 90.0})
    return prev, curr


def test_manifest_interval_defaults_to_the_lookback_days_before_the_run():
    prev, _ = _pair("2026-09-18")
    assert manifest_interval(prev) == ("2026-08-19", "2026-09-17")


def test_manifest_interval_prefers_the_discovery_window():
    m = {"run_date": "2026-09-18", "lookback_days": 30,
         "evidence_source": {"discovery_window": {"start": "2026-09-01T00:00:00Z",
                                                  "end": "2026-09-10T00:00:00Z"}}}
    assert manifest_interval(m) == ("2026-09-01", "2026-09-10")


def test_same_window_recapture_is_interval_overlap_not_a_change():
    prev, curr = _pair("2026-09-18")
    delta = compute_cost_delta(prev, curr)
    assert delta.comparable is False and delta.not_comparable_reason == "interval_overlap"
    assert delta.products_dbu_delta == {} and not delta.improved and not delta.regressed
    [both] = delta.persisting
    assert both.dbu_delta is None and "capture repeatability" in (both.note or "")


def test_discovery_window_overlap_is_not_comparable():
    prev = {"run_date": "2026-09-01", "lookback_days": 30,
            "evidence_source": {"discovery_window": {"start": "2026-08-20", "end": "2026-09-10"}}}
    curr = {"run_date": "2026-09-18", "lookback_days": 30,
            "evidence_source": {"discovery_window": {"start": "2026-09-01", "end": "2026-09-17"}}}
    assert window_comparability(prev, curr) == "interval_overlap"


def test_abutting_windows_stay_comparable():
    prev, curr = _pair("2026-08-19")
    delta = compute_cost_delta(prev, curr)
    assert delta.comparable is True and delta.not_comparable_reason is None
    assert delta.products_dbu_delta == {"SQL": -10.0}


def test_lookback_within_one_day_tolerance_stays_comparable():
    prev, curr = _pair("2026-08-18", prior_lb=31, cur_lb=30)
    assert window_comparability(prev, curr) is None


def test_different_lookback_is_window_mismatch_before_overlap():
    prev, curr = _pair("2026-09-18", prior_lb=7, cur_lb=30)
    assert compute_cost_delta(prev, curr).not_comparable_reason == "window_mismatch"
