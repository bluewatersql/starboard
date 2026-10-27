# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 9: a run-rate rule's DBU estimate is a DBU/day observation.

``spend_step_change`` carries its lift (DBU/day) in ``evidence_dbu_estimate``.
Run 9's observation said ``DBU``, so a reader of ``observations.json`` could add a
run-rate to window totals.
"""

from __future__ import annotations

import pytest
from starboard_core.engagement import plays
from starboard_core.engagement.records import RUN_RATE_RULES

from .test_observations import by_metric, finding, fm, manifest

pytestmark = pytest.mark.unit


def test_run_rate_estimate_is_dbu_per_day() -> None:
    step = finding(
        id="spend_step_change::123",
        rule_id="spend_step_change",
        composite_key="spend_step_change::123",
        evidence_dbu_estimate=45116.57,
    )
    obs = fm(manifest(step, finding()))
    assert (
        by_metric(obs, "spend_step_change::123")["evidence_dbu_estimate"].unit
        == "DBU/day"
    )
    assert by_metric(obs, "W-W01::wh-1")["evidence_dbu_estimate"].unit == "DBU"


def test_plays_share_the_one_run_rate_set() -> None:
    assert plays.RUN_RATE_RULES is RUN_RATE_RULES
