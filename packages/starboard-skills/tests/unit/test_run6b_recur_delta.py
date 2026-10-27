"""Run-6b: the not-comparable recur delta names no entity.

A rule may key its entity by a name (a job name that embeds a user name), so the
``## Capture repeatability (not a change)`` table counts the repeated findings per
rule id; the entity ids stay in the two ``findings-manifest.json`` files.
"""

from __future__ import annotations

from starboard_skills.helpers.run import cmd_recur

from .test_run5_group_d import _repeat_section
from .test_run_recur import _args, _case, _finding, _make_run_dir, _rid, _set_lookback

NAMED = "jane_doe_nightly_etl"


def _pair(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(
        case,
        _rid("2026-09-01"),
        "2026-09-01",
        findings=[
            _finding("W-IDLE", "wh-1", "high", 40.0),
            _finding("W-IDLE", "wh-2", "high", 2.0),
            _finding("portfolio_unreliable_production_workload", NAMED, "medium", None),
        ],
    )
    _set_lookback(prior, 30)
    rd = _make_run_dir(
        case,
        _rid("2026-10-01"),
        "2026-10-01",
        findings=[
            _finding("W-IDLE", "wh-1", "high", 30.0),
            _finding("W-IDLE", "wh-2", "high", 1.0),
            _finding("portfolio_unreliable_production_workload", NAMED, "medium", None),
        ],
    )
    _set_lookback(rd, 7)
    cmd_recur(_args(rd, case))
    return (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()


def test_repeatability_names_no_entity(tmp_path):
    md = _pair(tmp_path)
    assert NAMED not in md and "wh-1" not in md


def test_repeatability_counts_by_rule_id(tmp_path):
    section = _repeat_section(_pair(tmp_path))
    assert "3 finding(s) are present in both captures" in section
    assert "`findings-manifest.json`" in section
    assert "| Rule | Findings in both | Prior DBU | Current DBU |" in section
    assert "| W-IDLE | 2 | 42.00 | 31.00 |" in section
    assert "| portfolio_unreliable_production_workload | 1 | — | — |" in section


def test_not_comparable_delta_has_no_cost_delta_section(tmp_path):
    """The repeatability table replaces the cost delta: no "No review findings cost
    delta" line on a not-comparable delta (the skill text says the same)."""
    md = _pair(tmp_path)
    assert "## Review findings cost delta" not in md
    assert "carries none" not in md
