# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 7: a run-rate play ranks on a window-comparable exposure.

A ``spend_step_change`` play carries a DBU/day lift, not a window total. It
used to sort as zero exposure, so a ~45,000 DBU/day step change came 75th,
behind every job play of the same severity (at most ~449 DBU over the window),
and never reached ``top_plays``. The computed order now weighs a run-rate as
DBU/day × the reporting interval's days. The exposure fields keep their units.
"""

from __future__ import annotations

import pytest

from .test_concerns import manifest, obs, present
from .test_plays import non_acquire, plays_for

pytestmark = pytest.mark.unit

#: test_concerns.INTERVAL is 2026-09-23..2026-10-07: 14 days.
_DAYS = 14


def _rule(rule_id: str, entity_id: str, dbus: float) -> tuple[dict, list]:
    eid = f"{rule_id}::{entity_id}"
    entry = {
        "composite_key": eid,
        "rule_id": rule_id,
        "entity_id": entity_id,
        "severity": "high",
    }
    cur = [
        present(eid, family="consumption_trajectory"),
        obs(
            family="consumption_trajectory",
            entity_kind="finding",
            entity_id=eid,
            metric="evidence_dbu_estimate",
            unit="DBU",
            value=dbus,
            method_version="findings_manifest_v2",
        ),
    ]
    return entry, cur


def _order(per_day: float, window_total: float) -> list[str]:
    step, step_obs = _rule("spend_step_change", "ws", per_day)
    job, job_obs = _rule("job_cron_overlap", "42", window_total)
    plays, _ = plays_for(step_obs + job_obs, [], manifest=manifest(step, job))
    return [p.reason.split(" ", 1)[0] for p in non_acquire(plays)]


def test_a_large_run_rate_outranks_a_smaller_window_total() -> None:
    assert _order(per_day=45_116.57, window_total=449.0) == [
        "spend_step_change",
        "job_cron_overlap",
    ]


def test_a_small_run_rate_still_ranks_below_a_larger_window_total() -> None:
    # 10 DBU/day over 14 days = 140 DBU < 449 DBU.
    assert _order(per_day=10.0, window_total=449.0) == [
        "job_cron_overlap",
        "spend_step_change",
    ]


def test_the_comparison_uses_the_interval_days() -> None:
    # 449 / 14 ≈ 32.07 DBU/day: just above outranks, just below doesn't.
    assert _order(per_day=449.0 / _DAYS + 0.1, window_total=449.0)[0] == (
        "spend_step_change"
    )
    assert _order(per_day=449.0 / _DAYS - 0.1, window_total=449.0)[0] == (
        "job_cron_overlap"
    )
