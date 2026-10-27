"""Discovery heuristics list affected entities by id, never by a display name.

Same live-run-6b fix as the kernel detectors: job and pipeline names can carry a
person's name, so BIL-002 and JOB-007 prefer ``job_id`` / ``pipeline_id`` and fall
back to the name only when the id column is missing.
"""

from __future__ import annotations

import polars as pl
from starboard.discovery.heuristics.billing import BIL002WeekOverWeekDBUGrowth
from starboard.discovery.heuristics.jobs import JOB007DLTPipelineDegradation

NAME = "jane.doe@example.com nightly"


def test_bil002_lists_job_ids() -> None:
    df = pl.DataFrame({"job_id": ["111"], "job_name": [NAME], "wow_growth_pct": [40.0]})
    (finding,) = BIL002WeekOverWeekDBUGrowth().evaluate({"C-B03": df})
    assert finding.affected_entities == ("111",)


def test_job007_lists_pipeline_ids() -> None:
    df = pl.DataFrame(
        {"pipeline_id": ["p-1"], "pipeline_name": [NAME], "failure_rate_pct": [30.0]}
    )
    (finding,) = JOB007DLTPipelineDegradation().evaluate({"C-J07": df})
    assert finding.affected_entities == ("p-1",)


def test_bil002_falls_back_to_the_name_without_an_id() -> None:
    df = pl.DataFrame({"job_name": [NAME], "wow_growth_pct": [40.0]})
    (finding,) = BIL002WeekOverWeekDBUGrowth().evaluate({"C-B03": df})
    assert finding.affected_entities == (NAME,)
