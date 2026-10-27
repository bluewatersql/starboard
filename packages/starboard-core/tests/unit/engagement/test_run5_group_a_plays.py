# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 5 (group A): rule plays never print a review re-run as a next command."""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.health import RunTarget
from starboard_core.engagement.plays import PlayContext

from .test_concerns import manifest, present
from .test_plays import non_acquire, plays_for

pytestmark = pytest.mark.unit

_HEALTH = PlayContext(task="health_check")
_INTERNAL = PlayContext(task="troubleshooting", target=RunTarget(internal=True))
_WINDOW = "--start 2026-09-23 --end 2026-10-07 --limit 1000"


def _rule(rule_id: str, eid: str, severity: str = "high") -> dict[str, Any]:
    return {"rule_id": rule_id, "entity_id": eid, "severity": severity}


def _commands(rule_id: str, eid: str, context: PlayContext | None = None) -> tuple[str, ...]:
    kw: dict[str, Any] = {"context": context} if context is not None else {}
    plays, _ = plays_for(
        [present(f"{rule_id}::{eid}")], [], manifest=manifest(_rule(rule_id, eid)), **kw
    )
    (play,) = non_acquire(plays)
    return play.next_commands


@pytest.mark.parametrize("context", [None, _HEALTH])
@pytest.mark.parametrize(
    ("rule_id", "eid", "template"),
    [
        ("spend_step_change", "123", "vt-daily-totals"),
        ("portfolio_untracked_production_consumption", "123:VECTOR_SEARCH", "vt-product-totals"),
        ("warehouse_recent_resize", "wh-1", "vt-warehouse-config-history"),
    ],
)
def test_rule_maps_to_its_verify_template(
    rule_id: str, eid: str, template: str, context: PlayContext | None
) -> None:
    commands = _commands(rule_id, eid, context)
    assert commands[0].startswith(f"starboard-helper verify run {template} --ws 123 {_WINDOW}")
    assert not any(c.startswith("starboard review") for c in commands)


@pytest.mark.parametrize("context", [None, _HEALTH, _INTERNAL])
@pytest.mark.parametrize(
    ("rule_id", "eid"),
    [
        ("portfolio_unattended_production_job", "nightly_elt"),  # job name, no id
        ("dlt_stale_pipeline", "bronze_pipeline"),
        ("vector_search_idle_endpoint", "vs-ep"),
        ("job_wait_tasks", "77"),
        ("select_star_projection", "q-1"),
    ],
)
def test_no_rule_play_prints_a_review_rerun(
    rule_id: str, eid: str, context: PlayContext | None
) -> None:
    commands = _commands(rule_id, eid, context)
    assert commands
    assert not any(c.startswith("starboard review") for c in commands), commands


def test_job_rule_without_template_falls_back_to_the_job_run_timeline() -> None:
    assert _commands("job_wait_tasks", "77", _HEALTH) == (
        "starboard-helper verify run vt-job-runs --ws 123 --job-ids 77 "
        f"{_WINDOW} --warehouse-id <warehouse_id> --suffix 77 --out analysis/verify",
    )


def test_workspace_fallback_is_the_product_totals_verify() -> None:
    (command,) = _commands("portfolio_unattended_production_job", "nightly_elt", _HEALTH)
    assert command.startswith(f"starboard-helper verify run vt-product-totals --ws 123 {_WINDOW}")
    assert "--job-ids" not in command  # a job name is not a job id


def test_internal_fallback_uses_the_mirror_form() -> None:
    (command,) = _commands("job_wait_tasks", "77", _INTERNAL)
    assert command == (
        "starboard-helper verify run vt-job-runs --internal-workspace-id 123 --job-ids 77 "
        f"{_WINDOW} --suffix 77 --out analysis/verify"
    )
