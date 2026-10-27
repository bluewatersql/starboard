# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-3 verify templates: ``vt-job-run-states`` and the shared failure set (D3-18, §F)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starboard_core.engagement.jobruns import CANCELLED_STATE, FAILED_STATES
from starboard_skills.helpers import verify as v

_REPO = Path(__file__).resolve().parents[4]
_PUBLIC = v.default_templates_path()
_MIRROR = (
    _REPO
    / "packages/starboard-internal/skills/starboard-internal-overlay/mirror-verify.md"
)
_PATHS = pytest.mark.parametrize("path", [_PUBLIC, _MIRROR], ids=["public", "mirror"])

_RUN_COLUMNS = (
    "workspace_id",
    "job_id",
    "run_id",
    "result_state",
    "first_period_start",
    "last_period_end",
)
_FAILED_IN = re.compile(
    r"result_state IN \(([^)]*)\) THEN 1 ELSE 0 END\)\s*AS failed_runs"
)


def _templates(path: Path) -> dict[str, v.VerifyTemplate]:
    _, templates = v.load_templates(path)
    return templates


def _literals(group: str) -> tuple[str, ...]:
    return tuple(re.findall(r"'([^']*)'", group))


@pytest.mark.unit
class TestJobRunStates:
    @_PATHS
    def test_present_in_both_files(self, path: Path) -> None:
        assert "vt-job-run-states" in _templates(path)

    @_PATHS
    def test_requires_job_ids_and_is_workspace_scoped(self, path: Path) -> None:
        tpl = _templates(path)["vt-job-run-states"]
        assert set(tpl.placeholders) == {"ws", "start", "end", "job_ids"}
        assert "job_id IN ({job_ids})" in tpl.sql
        assert "workspace_id = '{ws}'" in tpl.sql

    @_PATHS
    def test_has_no_sql_limit(self, path: Path) -> None:
        sql = _templates(path)["vt-job-run-states"].sql
        assert not re.search(r"\bLIMIT\b", sql, re.IGNORECASE)

    @_PATHS
    def test_returns_per_run_columns(self, path: Path) -> None:
        sql = _templates(path)["vt-job-run-states"].sql
        for col in _RUN_COLUMNS:
            assert re.search(rf"\b{col}\b", sql), col
        assert "MAX_BY(result_state, period_end_time) AS result_state" in sql
        assert "MIN(period_start_time)" in sql and "AS first_period_start" in sql
        assert "MAX(period_end_time)" in sql and "AS last_period_end" in sql
        # One row per run, selected by when it ended (same runs CTE as vt-job-runs).
        assert "GROUP BY workspace_id, job_id, run_id" in sql
        assert (
            "HAVING MAX(period_end_time) >= DATE'{start}' "
            "AND MAX(period_end_time) < DATE_ADD(DATE'{end}', 1)"
        ) in sql

    @_PATHS
    def test_doc_says_pass_limit_20000(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        section = text.split("### vt-job-run-states:", 1)[1].split("\n### ", 1)[0]
        assert "--limit 20000" in section
        assert "limit_reached" in section

    def test_fills_with_the_multi_id_flag(self) -> None:
        tpl = _templates(_PUBLIC)["vt-job-run-states"]
        params = v.derive_params(
            ws="123", start="2026-09-01", end="2026-09-30", job_ids="42,43"
        )
        sql = tpl.sql
        for name in tpl.placeholders:
            sql = sql.replace("{" + name + "}", params[name])
        assert "job_id IN ('42', '43')" in sql
        assert "{" not in sql


@pytest.mark.unit
class TestFailureLiterals:
    @_PATHS
    def test_vt_job_runs_failure_set_equals_kernel(self, path: Path) -> None:
        sql = _templates(path)["vt-job-runs"].sql
        (group,) = _FAILED_IN.findall(sql)
        assert _literals(group) == FAILED_STATES
        assert f"result_state = '{CANCELLED_STATE}'" in sql

    @_PATHS
    def test_vt_job_run_states_failure_set_equals_kernel(self, path: Path) -> None:
        # Per-run rows carry the raw final state; the template documents the
        # failed set it is counted against, which must be the kernel set.
        text = path.read_text(encoding="utf-8")
        section = text.split("### vt-job-run-states:", 1)[1].split("\n### ", 1)[0]
        (group,) = re.findall(r"failed = `([^`]*)`", section)
        assert tuple(s.strip() for s in group.split(",")) == FAILED_STATES
