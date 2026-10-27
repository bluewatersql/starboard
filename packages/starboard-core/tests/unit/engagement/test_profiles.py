# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the workflow profiles and their ``run check`` item sets (spec §B1/§B2)."""

from __future__ import annotations

import pytest
from starboard_core.engagement.profiles import (
    CHECK_IDS,
    PROFILE_CHECKS,
    WORKFLOW_PROFILES,
    profile_for_task,
    required_checks,
)

_EXISTING = frozenset({*(str(n) for n in range(1, 17)), "health_read"})
_NEW = frozenset(
    {
        "health_present",
        "plays_present",
        "health_report",
        "case_linked",
        "focused_report",
        "review_json",
    }
)


def test_workflow_profile_names() -> None:
    assert set(WORKFLOW_PROFILES) == {
        "health_check",
        "troubleshooting",
        "discovery",
        "action_plan",
        "review",
    }
    assert len(WORKFLOW_PROFILES) == len(set(WORKFLOW_PROFILES))


@pytest.mark.parametrize("task", WORKFLOW_PROFILES)
def test_profile_for_task_is_identity(task: str) -> None:
    assert profile_for_task(task) == task


def test_profile_for_task_none_defaults_to_action_plan() -> None:
    assert profile_for_task(None) == "action_plan"


@pytest.mark.parametrize("task", ["", "health", "bogus", "Review"])
def test_profile_for_task_rejects_unknown(task: str) -> None:
    with pytest.raises(ValueError):
        profile_for_task(task)


def test_check_ids_are_the_existing_plus_new_in_report_order() -> None:
    assert len(CHECK_IDS) == len(set(CHECK_IDS)) == 23
    assert set(CHECK_IDS) == _EXISTING | _NEW
    assert CHECK_IDS[:16] == tuple(str(n) for n in range(1, 17))
    assert CHECK_IDS[16] == "health_read"


def test_action_plan_is_todays_checklist() -> None:
    assert required_checks("action_plan") == _EXISTING


def test_profile_check_sets_match_the_spec() -> None:
    assert required_checks("discovery") == {"1", "2", "3", "4", "12", "16"}
    assert required_checks("review") == {"1", "12", "13", "15", "16", "review_json"}
    assert required_checks("health_check") == {
        "1",
        "2",
        "12",
        "13",
        "15",
        "16",
        "health_read",
        "health_present",
        "plays_present",
        "health_report",
    }
    assert required_checks("troubleshooting") == {
        "1",
        "12",
        "16",
        "case_linked",
        "focused_report",
    }


def test_profile_checks_cover_every_profile_and_only_known_ids() -> None:
    assert set(PROFILE_CHECKS) == set(WORKFLOW_PROFILES)
    for profile, items in PROFILE_CHECKS.items():
        assert isinstance(items, frozenset)
        assert items <= set(CHECK_IDS), profile
        assert required_checks(profile) == items


def test_every_new_check_id_is_used_by_a_profile() -> None:
    used = frozenset().union(*PROFILE_CHECKS.values())
    assert used == set(CHECK_IDS)


@pytest.mark.parametrize("profile", ["", "health", "bogus", None])
def test_required_checks_rejects_unknown(profile: object) -> None:
    with pytest.raises(ValueError):
        required_checks(profile)  # type: ignore[arg-type]
