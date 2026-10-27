"""Detectors key entities by their id, never by a display name.

Live run 6b: a comparable recur cost delta printed a review ``entity_id`` that was a
job name carrying a person's name. The portfolio detectors keyed jobs by name before
``job_id``; the DLT and MLflow detectors did the same with pipeline and experiment
names (experiment names are often ``/Users/<email>/…`` paths). Each now uses the id,
and the name stays out of the finding's text.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pytest
from starboard_core.domain.rules import detectors as d

NAME = "/Users/jane.doe@example.com/nightly"

CASES: list[
    tuple[Callable[[Sequence[dict[str, Any]]], list[Any]], dict[str, Any], str]
] = [
    (
        d.detect_portfolio_unattended_production_job,
        {"job_id": "111", "name": NAME, "total_dbus": 500.0, "run_as": None},
        "111",
    ),
    (
        d.detect_portfolio_unreliable_production_workload,
        {
            "job_id": "222",
            "job_name": NAME,
            "total_dbus": 500.0,
            "failure_rate_pct": 40.0,
        },
        "222",
    ),
    (
        d.detect_dlt_high_pipeline_failure_rate,
        {
            "pipeline_id": "p-1",
            "pipeline_name": NAME,
            "failure_rate_pct": 50.0,
            "total_updates": 10,
        },
        "p-1",
    ),
    (
        d.detect_dlt_stale_pipeline,
        {"pipeline_id": "p-2", "pipeline_name": NAME, "days_since_last_update": 90},
        "p-2",
    ),
    (
        d.detect_dlt_classic_compute_serverless_candidate,
        {
            "pipeline_id": "p-3",
            "pipeline_name": NAME,
            "is_serverless_config": False,
            "dbus": 80.0,
        },
        "p-3",
    ),
    (
        d.detect_ml_noisy_experiment,
        {"experiment_id": "e-1", "experiment_name": NAME, "is_noisy": True},
        "e-1",
    ),
]


@pytest.mark.parametrize(
    ("detector", "row", "entity_id"), CASES, ids=[c[0].__name__ for c in CASES]
)
def test_entity_key_is_the_id_not_the_name(detector, row, entity_id) -> None:
    (match,) = detector([row])
    assert match.entity_key == entity_id
    assert match.location.entity == entity_id
    assert NAME not in match.current_state


@pytest.mark.parametrize(
    ("detector", "row", "entity_id"), CASES, ids=[c[0].__name__ for c in CASES]
)
def test_name_only_rows_still_match(detector, row, entity_id) -> None:
    """A row without its id falls back to the name rather than being dropped."""
    id_key = next(k for k in row if k.endswith("_id"))
    (match,) = detector([{k: v for k, v in row.items() if k != id_key}])
    assert match.entity_key == NAME
