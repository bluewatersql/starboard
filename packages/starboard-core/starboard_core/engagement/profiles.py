# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Workflow profiles and the ``run check`` item set each one requires (phase-4 spec §B1/§B2).

A profile names the kind of run (health check, troubleshooting, discovery, action plan,
review). The profile name is the task name (one vocabulary), recorded once at route.
``run check`` gates only the items a profile requires and lists the rest as skipped.
Pure: stdlib only.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

__all__ = [
    "CHECK_IDS",
    "PROFILE_CHECKS",
    "WORKFLOW_PROFILES",
    "profile_for_task",
    "required_checks",
]

WORKFLOW_PROFILES: tuple[str, ...] = (
    "health_check",
    "troubleshooting",
    "discovery",
    "action_plan",
    "review",
)

_DEFAULT_PROFILE = "action_plan"

# Every check id, in report order: the 16 numbered items and ``health_read`` exist today;
# the other six are phase-4 additions.
CHECK_IDS: tuple[str, ...] = (
    *(str(n) for n in range(1, 17)),
    "health_read",
    "health_present",
    "plays_present",
    "health_report",
    "case_linked",
    "focused_report",
    "review_json",
)

_ACTION_PLAN = frozenset({*(str(n) for n in range(1, 17)), "health_read"})

PROFILE_CHECKS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "action_plan": _ACTION_PLAN,
        "discovery": frozenset({"1", "2", "3", "4", "12", "16"}),
        "review": frozenset({"1", "12", "13", "15", "16", "review_json"}),
        "health_check": frozenset(
            {
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
        ),
        "troubleshooting": frozenset(
            {"1", "12", "16", "case_linked", "focused_report"}
        ),
    }
)


def profile_for_task(task: str | None) -> str:
    """The workflow profile for ``task`` (identity); ``None`` -> ``action_plan``.

    Raises:
        ValueError: ``task`` is not a workflow profile name.
    """
    if task is None:
        return _DEFAULT_PROFILE
    if task not in WORKFLOW_PROFILES:
        raise ValueError(f"unknown task {task!r}; expected one of {WORKFLOW_PROFILES}")
    return task


def required_checks(profile: str) -> frozenset[str]:
    """The check ids ``profile`` requires.

    Raises:
        ValueError: ``profile`` is not a workflow profile.
    """
    try:
        return PROFILE_CHECKS[profile]
    except (KeyError, TypeError):
        raise ValueError(
            f"unknown workflow profile {profile!r}; expected one of {WORKFLOW_PROFILES}"
        ) from None
