# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 11: the failure-rate rule keeps its worst-failing jobs at the cap.

``job_high_failure_rate`` scores by failure-DBU materiality, so at its 20-finding cap
a cheap job failing every run (opus P02: 672/672) was cut while costlier, less
failing jobs were kept. The rule's ``cap_rank_by`` orders the cap by evidence
columns (failure rate, then runs) instead of the score.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.rules import RuleRegistry
from starboard_core.domain.rules.evaluator import (
    EVALUATOR_PARAM_KEYS,
    _evaluate_rule_detailed,
)

pytestmark = pytest.mark.unit


def _rule(cap: int, **params: object):
    rule = next(
        r for r in RuleRegistry.from_seed().rules if r.id == "job_high_failure_rate"
    )
    return rule.model_copy(
        update={"params": {**rule.params, "max_findings": cap, **params}}
    )


def _row(job: str, rate: float, runs: int, failure_dbus: float) -> dict:
    return {
        "job_id": job,
        "failure_rate_pct": rate,
        "total_runs": runs,
        "failure_dbus": failure_dbus,
    }


_ROWS = [
    _row("costly-a", 25.0, 40, 900.0),  # high severity, impact 5 (major DBU)
    _row("costly-b", 30.0, 40, 800.0),
    _row("always-fails", 100.0, 672, 4.0),  # low severity: immaterial DBU
    _row("often-fails", 90.0, 100, 5.0),
]


def _kept(rule) -> list[str]:
    findings, _, _ = _evaluate_rule_detailed(rule, {"C-J04": _ROWS})
    return [rf.finding.location.entity for rf in findings]


def test_seed_rule_ranks_its_cap_by_failure_rate() -> None:
    rule = _rule(2)
    assert rule.params["cap_rank_by"] == "failure_rate_pct,total_runs"
    assert _kept(rule) == ["always-fails", "often-fails"]


def test_without_cap_rank_by_the_score_decides() -> None:
    rule = _rule(2, cap_rank_by=None)
    assert set(_kept(rule)) == {"costly-a", "costly-b"}


def test_cap_rank_by_is_an_evaluator_param_not_a_detector_one() -> None:
    assert "cap_rank_by" in EVALUATOR_PARAM_KEYS


def test_uncapped_rule_keeps_every_match() -> None:
    assert len(_kept(_rule(0))) == 4
