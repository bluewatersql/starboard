"""Live run 9: a run-rate finding never joins the history entry's DBU total.

Without ``products_dbu`` the entry's ``total_dbu`` falls back to the findings'
``evidence_dbu_estimate`` sum. ``spend_step_change`` carries a DBU/day lift there,
so adding it to window totals overstated the total.
"""

from __future__ import annotations

import pytest
from starboard_skills.helpers import run

pytestmark = pytest.mark.unit


def _manifest(*findings: dict) -> dict:
    return {"products_dbu": {}, "lookback_days": 30, "findings": list(findings)}


def test_fallback_total_skips_run_rate_findings() -> None:
    m = _manifest(
        {"rule_id": "spend_step_change", "evidence_dbu_estimate": 45116.57},
        {"rule_id": "job_failure_rate", "evidence_dbu_estimate": 120.0},
    )
    entry, source = run._entry_of("2026-10-16", "r1", m, None)
    assert source == "finding_evidence_dbu"
    assert entry["total_dbu_estimate"] == 120.0


def test_only_run_rate_findings_leave_no_total() -> None:
    m = _manifest({"rule_id": "spend_step_change", "evidence_dbu_estimate": 45116.57})
    entry, source = run._entry_of("2026-10-16", "r1", m, None)
    assert (entry["total_dbu_estimate"], source) == (None, "none")
