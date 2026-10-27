# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 9: a rule play's reason names what the rule asks for.

Run 9's plays carried only ``portfolio_unattended_production_job``; two runs read
"unattended" as "no one watching" and misdescribed the finding. The reason now
carries the rule's name ("Assign an owner to production-scale jobs").
"""

from __future__ import annotations

import pytest
from starboard_core.domain.rules import rule_name

from .test_concerns import manifest, present
from .test_plays import _rule, non_acquire, plays_for

pytestmark = pytest.mark.unit


def test_rule_name_comes_from_the_registry() -> None:
    assert (
        rule_name("portfolio_unattended_production_job")
        == "Assign an owner to production-scale jobs"
    )
    assert rule_name("not_a_rule") is None


def test_rule_play_reason_names_the_rule() -> None:
    rid = "portfolio_unattended_production_job"
    entry = _rule(rid, "77", "medium")
    plays, _ = plays_for([present(f"{rid}::77")], [], manifest=manifest(entry))
    (play,) = non_acquire(plays)
    assert play.reason.startswith(
        f"{rid} (Assign an owner to production-scale jobs) on "
    ), play.reason


def test_unknown_rule_reason_keeps_the_id_only() -> None:
    entry = _rule("job_wait_tasks", "77", "medium")
    plays, _ = plays_for([present("job_wait_tasks::77")], [], manifest=manifest(entry))
    (play,) = non_acquire(plays)
    name = rule_name("job_wait_tasks")
    prefix = f"job_wait_tasks ({name}) on " if name else "job_wait_tasks on "
    assert play.reason.startswith(prefix), play.reason
