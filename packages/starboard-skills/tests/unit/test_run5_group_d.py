"""Run-5 group D: ``run recur`` delta / README / result contract fixes.

D1 capture repeatability from the two manifests; D2 no arrows on not-comparable totals;
D3 the delta title names the prior run; D4 empty backlog fields on a health check;
D5 a baseline is ``comparable: false`` / ``not_comparable_reason: "baseline"``;
D6 the product-DBU scope caveat follows the manifest's scope.
"""
from __future__ import annotations

import json

import pytest
from starboard_skills.helpers import contract
from starboard_skills.helpers.run import cmd_recur

from .conftest import drive_files, make_drive_run, put_files
from .test_run_recur import (
    _COST_DELTA,
    _args,
    _case,
    _finding,
    _local_descriptor,
    _make_run_dir,
    _public_run,
    _rid,
    _set_lookback,
    public,  # noqa: F401 - fixture
)
from .test_run_recur_drive import _REVIEW, PRIOR, _current, _recur, _registered_prior

_EMPTY_BACKLOG_DELTA = {
    "new": [], "resolved": [], "tier_changed": [], "confidence_changed": [], "unchanged": [],
}


def _mismatched_pair(tmp_path, **cur_kwargs):
    """A 30-day prior and a 7-day current run with the same three findings."""
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    _set_lookback(prior, 30)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", **cur_kwargs)
    _set_lookback(rd, 7)
    return case, prior, rd


def _repeat_section(md: str) -> str:
    return md.split("## Capture repeatability (not a change)\n", 1)[1].split("## Narrative", 1)[0]


# ---- D1: capture repeatability lists the findings present in both manifests ----------


def test_repeatability_lists_findings_in_both_captures_without_a_cost_delta(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01", findings=[
        _finding("W-IDLE", "wh-1", "high", 40.0),
        _finding("J-FAIL", "job-1", "critical", None),
        _finding("GONE", "x-1", "low", 1.0),
    ])
    _set_lookback(prior, 30)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", findings=[
        _finding("W-IDLE", "wh-1", "high", 30.0),
        _finding("J-FAIL", "job-1", "critical", None),
        _finding("Q-NEW", "q-9", "medium", 5.0),
    ])
    _set_lookback(rd, 7)

    cmd_recur(_args(rd, case))  # no analysis/review.json: no cost_delta at all

    section = _repeat_section((rd / "analysis" / "delta-vs-2026-09-01.md").read_text())
    assert "None." not in section
    assert "2 finding(s) are present in both captures, counted by rule" in section
    assert "| W-IDLE | 1 | 40.00 | 30.00 |" in section
    assert "| J-FAIL | 1 | — | — |" in section
    assert "GONE" not in section and "Q-NEW" not in section


def test_repeatability_comes_from_the_manifests_not_the_cost_delta_classes(tmp_path):
    """A finding present in both captures is listed even when a cost_delta classed it
    improved (a class a not-comparable run never reports)."""
    _, _, rd = _mismatched_pair(tmp_path, review={"data": {"cost_delta": _COST_DELTA}})
    cmd_recur(_args(rd, rd.parent))
    section = _repeat_section((rd / "analysis" / "delta-vs-2026-09-01.md").read_text())
    for rule in ("W-IDLE", "J-FAIL", "Q-SLOW"):
        assert f"| {rule} | 1 |" in section


def test_repeatability_says_none_only_when_no_finding_repeats(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01",
                          findings=[_finding("A", "a", "low", 1.0)])
    _set_lookback(prior, 30)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01",
                       findings=[_finding("B", "b", "low", 1.0)])
    _set_lookback(rd, 7)
    cmd_recur(_args(rd, case))
    section = _repeat_section((rd / "analysis" / "delta-vs-2026-09-01.md").read_text())
    assert "No finding (rule::entity) is present in both captures." in section


def test_drive_overlap_delta_lists_the_repeated_findings(covered_env, drive_run, capsys):
    _registered_prior(drive_run, capsys, window=("2026-08-20", "2026-09-18"))
    _current(drive_run)
    code, out = _recur(drive_run, capsys)
    assert code == 0, out
    files = drive_files(drive_run)
    rr = json.loads(files["analysis/recur-result.json"])
    assert rr["not_comparable_reason"] == "interval_overlap"
    section = _repeat_section(files[rr["delta_path"]].decode())
    assert "| W-IDLE | 1 | 40.00 | 30.00 |" in section
    assert "J-FAIL" not in section and "Q-SLOW" not in section


# ---- D2: not-comparable totals carry no arrow --------------------------------------


def test_not_comparable_totals_are_printed_without_an_arrow(tmp_path):
    _, _, rd = _mismatched_pair(tmp_path, products_dbu={"SQL": 30.0})
    cmd_recur(_args(rd, rd.parent))
    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    readme = (rd / "README.md").read_text().split("## Recur", 1)[1]
    assert (
        "Total DBU estimate (not compared): prior 150.00 · current 30.00 · "
        "findings (not compared): prior 3 · current 3"
    ) in md
    assert "Total DBU estimate (list-price, not compared): prior 150.00 · current 30.00" in readme
    for text in (md, readme):
        assert "150.00 → 30.00" not in text and "3 → 3" not in text


def test_comparable_totals_keep_the_arrow(tmp_path):
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", products_dbu={"SQL": 30.0})
    cmd_recur(_args(rd, case))
    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert "Total DBU estimate: 150.00 → 30.00 · findings: 3 → 3" in md
    assert "(not compared)" not in md


# ---- D3: the delta title names the prior run ---------------------------------------


def test_delta_title_names_the_prior_run(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-10-01", 1), "2026-10-01")
    rd = _make_run_dir(case, _rid("2026-10-01", 2), "2026-10-01")
    cmd_recur(_args(rd, case, prior))
    md = (rd / "analysis" / "delta-vs-2026-10-01.md").read_text()
    assert md.startswith("# Delta vs 2026-10-01 (prior run `20261001_00000001`)\n")


def test_drive_delta_title_names_the_prior_run(covered_env, drive_run, capsys):
    _registered_prior(drive_run, capsys, window=("2026-08-09", "2026-09-07"))
    _current(drive_run)
    code, out = _recur(drive_run, capsys)
    assert code == 0, out
    files = drive_files(drive_run)
    md = files["analysis/delta-vs-2026-09-08.md"].decode()
    assert md.startswith(f"# Delta vs 2026-09-08 (prior run `{PRIOR[:17]}`)\n")


# ---- D4: a health check emits the empty backlog fields ------------------------------


@pytest.mark.usefixtures("public")
def test_local_health_check_emits_empty_backlog_fields(tmp_path):
    rd = _public_run(tmp_path)
    _local_descriptor(rd, intent="health_check")
    prior = _make_run_dir(_case(tmp_path), _rid("2026-09-08"), "2026-09-08")
    out = cmd_recur(_args(rd, rd.parent, prior))
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    for doc in (out, rr):
        assert doc["backlog_delta"] == _EMPTY_BACKLOG_DELTA
        assert doc["backlog_sizing"] == []
    delta_md = (rd / "analysis" / "delta-vs-2026-09-08.md").read_text()
    assert "backlog" not in delta_md.lower()
    assert "backlog" not in (rd / "README.md").read_text().split("## Recur", 1)[1].lower()


@pytest.mark.usefixtures("public")
def test_local_health_check_baseline_emits_empty_backlog_fields(tmp_path):
    rd = _public_run(tmp_path)
    out = cmd_recur(_args(rd, rd.parent, baseline=True))
    assert out["backlog_delta"] == _EMPTY_BACKLOG_DELTA and out["backlog_sizing"] == []


def test_review_task_keeps_null_backlog_fields_without_a_backlog(tmp_path):
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    out = cmd_recur(_args(rd, case))
    assert out["backlog_delta"] is None and out["backlog_sizing"] is None


def test_drive_health_check_emits_empty_backlog_fields(
    covered_env, drive_run, capsys, monkeypatch
):
    _registered_prior(drive_run, capsys, task="health_check")
    health = make_drive_run(
        run_id="20261008_12345678-1234-4234-8234-0000000000aa",
        store=drive_run.store, intent="health_check",
    )
    monkeypatch.setattr(contract, "_load_storage", lambda: health.store)
    _current(health)
    put_files(health, {"analysis/review.json": json.dumps(_REVIEW)})
    code, out = _recur(health, capsys)
    assert code == 0, out
    rr = json.loads(drive_files(health)["analysis/recur-result.json"])
    assert rr["backlog_delta"] == _EMPTY_BACKLOG_DELTA and rr["backlog_sizing"] == []
    data = json.loads(out)["data"]
    assert data["backlog_delta"] == _EMPTY_BACKLOG_DELTA and data["backlog_sizing"] == []


# ---- D5: a baseline is not a comparison ---------------------------------------------


@pytest.mark.parametrize("forced", [True, False])
def test_local_baseline_is_not_comparable(tmp_path, forced):
    case = _case(tmp_path)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    out = cmd_recur(_args(rd, case, baseline=forced))
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    for doc in (out, rr):
        assert doc["baseline"] is True
        assert doc["comparable"] is False and doc["not_comparable_reason"] == "baseline"
        assert doc["window"]["comparable"] is False and doc["window"]["reason"] == "baseline"
        assert doc["window"]["prior_run_id"] is None
    readme = (rd / "README.md").read_text().split("## Recur", 1)[1]
    assert "baseline — no prior run" in readme and "not comparable" not in readme


def test_drive_baseline_is_not_comparable(covered_env, drive_run, capsys):
    _current(drive_run)
    code, out = _recur(drive_run, capsys, "--baseline")
    assert code == 0, out
    rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
    summary = json.loads(out)["data"]["summary"]
    for doc in (rr, summary):
        assert doc["baseline"] is True
        assert doc["comparable"] is False and doc["not_comparable_reason"] == "baseline"
    assert rr["window"]["comparable"] is False and rr["window"]["reason"] == "baseline"
    readme = drive_files(drive_run)["README.md"].decode().split("## Recur", 1)[1]
    assert "baseline — no prior run" in readme and "not comparable" not in readme


def test_a_recurrence_is_still_comparable(tmp_path):
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    out = cmd_recur(_args(rd, case))
    assert out["baseline"] is False
    assert out["comparable"] is True and out["not_comparable_reason"] is None


# ---- D6: the product-DBU caveat follows the manifest's scope -------------------------


def _set_scope(rd, *, workspace_ids=None, workspace_id=None):
    p = rd / "findings-manifest.json"
    m = json.loads(p.read_text())
    if workspace_ids is not None:
        m["evidence_source"] = {"kind": "discovery", "workspace_ids": workspace_ids}
    if workspace_id is not None:
        m["workspace_id"] = workspace_id
    p.write_text(json.dumps(m))


def test_workspace_scoped_discovery_totals_are_not_called_account_scoped(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01",
                       review={"data": {"cost_delta": _COST_DELTA}})
    for d in (prior, rd):
        _set_scope(d, workspace_ids=["1444828305810485"])
    cmd_recur(_args(rd, case))
    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert "account-scoped" not in md
    assert "Product-level DBU totals cover workspace 1444828305810485" in md
    assert "### Product DBU delta (workspace 1444828305810485)" in md


def test_manifest_workspace_id_scopes_the_totals(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    for d in (prior, rd):
        _set_scope(d, workspace_id="42")
    cmd_recur(_args(rd, case))
    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert "Product-level DBU totals cover workspace 42" in md and "account-scoped" not in md


def test_unscoped_totals_stay_account_scoped(tmp_path):
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01",
                       review={"data": {"cost_delta": _COST_DELTA}})
    cmd_recur(_args(rd, case))
    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert "Product-level DBU totals are account-scoped" in md
    assert "### Product DBU delta (account-scoped)" in md


# ---- D7: recur applies the same window rule as review --since ----------------------


def test_local_same_window_recapture_is_interval_overlap(tmp_path):
    """Two same-day 30-day runs overlap: the kernel rule ``review --since`` uses too."""
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-10-01", 1), "2026-10-01")
    _set_lookback(prior, 30)
    rd = _make_run_dir(case, _rid("2026-10-01", 2), "2026-10-01")
    _set_lookback(rd, 30)
    out = cmd_recur(_args(rd, case, prior))
    assert out["comparable"] is False and out["not_comparable_reason"] == "interval_overlap"
    md = (rd / "analysis" / "delta-vs-2026-10-01.md").read_text()
    assert "## Capture repeatability (not a change)" in md
    assert "3 finding(s) are present in both captures" in md


def test_local_abutting_windows_stay_comparable(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    _set_lookback(prior, 30)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    _set_lookback(rd, 30)
    out = cmd_recur(_args(rd, case))
    assert out["comparable"] is True and out["not_comparable_reason"] is None
