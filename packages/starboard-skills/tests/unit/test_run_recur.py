"""Unit tests for ``starboard-helper run recur`` (the deterministic recur beat)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starboard_skills.helpers import charts_render
from starboard_skills.helpers import run as run_mod
from starboard_skills.helpers.contract import ArgError
from starboard_skills.helpers.run import _locate_prior, cmd_check, cmd_recur


def _finding(rule: str, entity: str, severity: str, dbu: float | None) -> dict:
    return {
        "id": f"{rule}::{entity}",
        "rule_id": rule,
        "category": "warehouse",
        "severity": severity,
        "score": 1.0,
        "entity_id": entity,
        "evidence_dbu_estimate": dbu,
        "composite_key": f"{rule}::{entity}",
    }


def _make_run_dir(
    reports: Path,
    name: str,
    run_date: str,
    *,
    findings: list[dict] | None = None,
    products_dbu: dict | None = None,
    review: dict | None = None,
) -> Path:
    rd = reports / name
    (rd / "analysis").mkdir(parents=True)
    manifest = {
        "snapshot_version": "2",
        "run_date": run_date,
        "workspace": name.rsplit("-", 3)[0],
        "products_dbu": products_dbu if products_dbu is not None else {"SQL": 100.0, "JOBS": 50.0},
        "findings": findings
        if findings is not None
        else [
            _finding("W-IDLE", "wh-1", "high", 40.0),
            _finding("J-FAIL", "job-1", "critical", None),
            _finding("Q-SLOW", "q-1", "medium", 5.0),
        ],
    }
    (rd / "findings-manifest.json").write_text(json.dumps(manifest))
    if review is not None:
        (rd / "analysis" / "review.json").write_text(json.dumps(review))
    return rd


_COST_DELTA = {
    "prior_run_date": "2026-09-01",
    "current_run_date": "2026-10-01",
    "improved": [
        {"composite_key": "W-IDLE::wh-1", "rule_id": "W-IDLE", "entity_id": "wh-1",
         "prior_dbu": 80.0, "current_dbu": 40.0, "dbu_delta": -40.0, "dbu_delta_pct": -0.5},
    ],
    "regressed": [],
    "newly_expensive": [
        {"composite_key": "Q-SLOW::q-1", "rule_id": "Q-SLOW", "entity_id": "q-1",
         "current_dbu": 500.0},
    ],
    "persisting": [
        {"composite_key": "J-FAIL::job-1", "rule_id": "J-FAIL", "entity_id": "job-1",
         "note": "DBU impact not measured (no attribution on one or both runs)"},
    ],
    "new_low_cost": [],
    "products_dbu_delta": {"SQL": -20.0},
}


@pytest.fixture(autouse=True)
def _fake_render(monkeypatch):
    """Render path on, with a fake PNG converter (no vl-convert needed)."""
    monkeypatch.setattr(run_mod, "_render_available", lambda: True)
    monkeypatch.setattr(charts_render, "_vegalite_to_png", lambda vl: b"\x89PNG-fake")


def _args(
    run_dir: Path, root: Path, prior: Path | None = None, *, baseline: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        run_dir=str(run_dir),
        workspace_root=str(root),
        prior=str(prior) if prior else None,
        baseline=baseline,
    )


def _backlog(rd: Path, items: list[tuple[str, str, int]], cut: list[dict] | None = None) -> None:
    doc = {
        "workspace_id": "1",
        "generated_at": "2026-10-01T00:00:00Z",
        "facts_window": {"start": "2026-09-01", "end": "2026-09-30"},
        "items": [{"id": i, "tier": t, "confidence": c} for i, t, c in items],
    }
    if cut is not None:
        doc["cut"] = cut
    (rd / "analysis" / "backlog.json").write_text(json.dumps(doc))


def test_baseline(tmp_path):
    reports = tmp_path / "starboard-reports"
    rd = _make_run_dir(reports, "ws-123-2026-10-01", "2026-10-01")
    root = reports / "ws-123"

    out = cmd_recur(_args(rd, root))

    assert out["baseline"] is True
    assert out["prior_run_dir"] is None
    history = json.loads((root / "trend" / "history.json").read_text())
    assert history == [
        {"run_date": "2026-10-01", "run": "ws-123-2026-10-01", "total_dbu_estimate": 150.0,
         "finding_count": 3, "critical": 1, "high": 1, "medium": 1,
         "act_now": None, "investigate": None, "not_now": None, "backlog_items": None,
         "degraded": None, "unavailable_queries": [], "unavailable_domains": [],
         "coverage_note": None}
    ]
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["ok"] is True and rr["baseline"] is True and rr["prior_run"] is None
    assert rr["history_entry"]["run_date"] == "2026-10-01"
    assert rr["backlog_delta"] is None and rr["errors"] == []
    spend = json.loads((rd / "charts" / "data" / "spend-over-time.json").read_text())
    assert spend == [{"run_date": "2026-10-01", "total_dbu_estimate": 150.0}]
    counts = json.loads((rd / "charts" / "data" / "finding-count-over-time.json").read_text())
    assert {r["severity"] for r in counts} == {"critical", "high", "medium"}
    assert (rd / "charts" / "trend" / "spend-over-time.png").read_bytes() == b"\x89PNG-fake"
    assert (rd / "charts" / "trend" / "finding-count-over-time.png").is_file()
    assert not list((rd / "analysis").glob("delta-vs-*.md"))
    readme = (rd / "README.md").read_text()
    assert "## Recur" in readme
    assert "baseline — no prior run" in readme


def test_with_prior_writes_delta_and_readme(tmp_path):
    reports = tmp_path / "starboard-reports"
    _make_run_dir(reports, "ws-123-2026-09-01", "2026-09-01", products_dbu={"SQL": 120.0})
    rd = _make_run_dir(
        reports, "ws-123-2026-10-01", "2026-10-01", review={"ok": True, "data": {"cost_delta": _COST_DELTA}}
    )
    (rd / "README.md").write_text("# Run\n\n## Recur\nold note\n\n## Delivery\n- doc → local\n")
    root = reports / "ws-123"

    out = cmd_recur(_args(rd, root))

    assert out["baseline"] is False
    assert out["prior_run_date"] == "2026-09-01"
    assert out["delta_counts"]["improved"] == 1
    assert out["delta_counts"]["newly_expensive"] == 1
    history = json.loads((root / "trend" / "history.json").read_text())
    assert [h["run_date"] for h in history] == ["2026-09-01", "2026-10-01"]  # prior backfilled
    delta = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    # cost_delta is the secondary section (review findings), under the sizing table.
    assert "## Review findings cost delta (secondary)" in delta
    assert "### Improved (1)" in delta
    assert "| wh-1 | W-IDLE | 80.00 | 40.00 | -50.0% |" in delta
    assert "### Newly expensive (1)" in delta
    assert "### Regressed (0)" in delta
    readme = (rd / "README.md").read_text()
    assert "old note" not in readme
    assert "Review findings (secondary): 1 improved, 0 regressed, 1 newly expensive" in readme
    assert "## Delivery\n- doc → local" in readme  # other sections preserved
    assert "analysis/delta-vs-2026-09-01.md" in readme


def test_history_is_idempotent_by_run_date(tmp_path):
    reports = tmp_path / "starboard-reports"
    rd = _make_run_dir(reports, "ws-123-2026-10-01", "2026-10-01")
    root = reports / "ws-123"
    cmd_recur(_args(rd, root))
    cmd_recur(_args(rd, root))
    history = json.loads((root / "trend" / "history.json").read_text())
    assert len(history) == 1
    readme = (rd / "README.md").read_text()
    assert readme.count("## Recur") == 1


def test_prior_auto_locate_excludes_current_and_newer(tmp_path):
    reports = tmp_path / "starboard-reports"
    old = _make_run_dir(reports, "ws-123-2026-08-01", "2026-08-01")
    newer_prior = _make_run_dir(reports, "ws-123-2026-09-01", "2026-09-01")
    current = _make_run_dir(reports, "ws-123-2026-10-01", "2026-10-01")
    _make_run_dir(reports, "ws-1234-2026-09-15", "2026-09-15")  # other workspace
    (reports / "ws-123-2026-09-20").mkdir()  # no manifest → skipped
    root = reports / "ws-123"

    found = _locate_prior(current.resolve(), root.resolve(), ("2026-10-01", current.name))
    assert found == newer_prior.resolve()
    # The current run is never its own prior, even when it is the only candidate.
    assert _locate_prior(old.resolve(), root.resolve(), ("2026-08-01", old.name)) is None


def test_explicit_prior_and_missing_cost_delta(tmp_path):
    reports = tmp_path / "starboard-reports"
    prior = _make_run_dir(reports, "custom-prior", "2026-09-01")
    rd = _make_run_dir(reports, "custom-current", "2026-10-01")
    out = cmd_recur(_args(rd, reports / "ws-9", prior=prior))
    assert out["prior_run_date"] == "2026-09-01"
    assert any("review.json not found" in w for w in out["warnings"])
    assert "cost_delta not found" in (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()


def test_delta_narrative_not_clobbered(tmp_path):
    reports = tmp_path / "starboard-reports"
    _make_run_dir(reports, "ws-1-2026-09-01", "2026-09-01")
    rd = _make_run_dir(
        reports, "ws-1-2026-10-01", "2026-10-01", review={"data": {"cost_delta": _COST_DELTA}}
    )
    delta = rd / "analysis" / "delta-vs-2026-09-01.md"
    delta.write_text("# Delta\nanalyst narrative\n")
    cmd_recur(_args(rd, reports / "ws-1"))
    assert delta.read_text() == "# Delta\nanalyst narrative\n"


def test_render_extra_missing_writes_data_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "_render_available", lambda: False)
    reports = tmp_path / "starboard-reports"
    rd = _make_run_dir(reports, "ws-1-2026-10-01", "2026-10-01")
    out = cmd_recur(_args(rd, reports / "ws-1"))
    assert out["charts_rendered"] == []
    assert any("render extra not installed" in w for w in out["warnings"])
    assert (rd / "charts" / "data" / "spend-over-time.json").is_file()
    assert not (rd / "charts" / "trend").exists()


def test_missing_manifest_is_arg_error(tmp_path):
    rd = tmp_path / "ws-1-2026-10-01"
    rd.mkdir()
    with pytest.raises(ArgError):
        cmd_recur(_args(rd, tmp_path / "ws-1"))


def test_recur_readme_satisfies_run_check_item1(tmp_path, capsys):
    reports = tmp_path / "starboard-reports"
    rd = _make_run_dir(reports, "ws-1-2026-10-01", "2026-10-01")
    (rd / "README.md").write_text("# Run\n\n## Delivery\n- doc: local: not uploaded\n")
    cmd_recur(_args(rd, reports / "ws-1"))
    with pytest.raises(SystemExit):
        cmd_check(SimpleNamespace(run_dir=str(rd), internal=False, format="json"))
    out = json.loads(capsys.readouterr().out)
    assert any(p.startswith("1:") for p in out["data"]["passed"])
    assert any(p.startswith("13:") for p in out["data"]["passed"])
    assert any(p.startswith("15:") for p in out["data"]["passed"])


def test_explicit_baseline_skips_prior_lookup(tmp_path):
    reports = tmp_path / "starboard-reports"
    _make_run_dir(reports, "ws-123-2026-09-01", "2026-09-01")
    rd = _make_run_dir(reports, "ws-123-2026-10-01", "2026-10-01")
    out = cmd_recur(_args(rd, reports / "ws-123", baseline=True))
    assert out["baseline"] is True and out["prior_run_dir"] is None
    assert not list((rd / "analysis").glob("delta-vs-*.md"))
    history = json.loads((reports / "ws-123" / "trend" / "history.json").read_text())
    assert [h["run_date"] for h in history] == ["2026-10-01"]  # no prior backfill
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["ok"] is True and rr["baseline"] is True


def test_baseline_and_prior_are_mutually_exclusive(tmp_path):
    reports = tmp_path / "starboard-reports"
    prior = _make_run_dir(reports, "a", "2026-09-01")
    rd = _make_run_dir(reports, "b", "2026-10-01")
    with pytest.raises(ArgError):
        cmd_recur(_args(rd, reports / "ws", prior=prior, baseline=True))


def test_workspace_root_equal_to_run_dir_rejected_and_recorded(tmp_path):
    rd = _make_run_dir(tmp_path, "run-1", "2026-10-01")
    with pytest.raises(ArgError):
        cmd_recur(_args(rd, rd, baseline=True))
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["ok"] is False and rr["history_entry"] is None
    assert "workspace-root" in rr["errors"][0]


@pytest.mark.parametrize("inside", ["ws-root", "deep/trend-root"])
def test_isolated_trend_root_inside_run_dir_allowed(tmp_path, inside):
    # The documented prompt-test form: run recur "$RUN_DIR" --workspace-root "$RUN_DIR/ws-root" --baseline
    rd = _make_run_dir(tmp_path, "run-1", "2026-10-01")
    cmd_recur(_args(rd, rd / inside, baseline=True))
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["ok"] is True and rr["baseline"] is True
    assert (rd / inside / "trend" / "history.json").is_file()


def test_failed_recur_writes_result_and_run_check_fails(tmp_path, capsys):
    rd = _make_run_dir(tmp_path, "run-1", "2026-10-01")
    with pytest.raises(ArgError):
        cmd_recur(_args(rd, tmp_path, prior=tmp_path / "missing"))
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["ok"] is False and "--baseline" in rr["errors"][0]
    with pytest.raises(SystemExit):
        cmd_check(SimpleNamespace(run_dir=str(rd), internal=False, format="json"))
    failed = {f["item"][:3]: f["reason"] for f in json.loads(capsys.readouterr().out)["data"]["failed"]}
    assert "recur did not succeed" in failed["15:"]


def test_nested_layout_locates_sibling_prior_under_root(tmp_path):
    root = tmp_path / "gpt-6"  # prompt-test layout: <root>/<run-uuid>
    old = _make_run_dir(root, "96e503f2", "2026-09-01")
    current = _make_run_dir(root, "ab26415d", "2026-10-01")
    _make_run_dir(tmp_path / "other-model", "zzz", "2026-09-15")  # outside the root → never seen
    out = cmd_recur(_args(current, root))
    assert out["prior_run_dir"] == str(old.resolve())
    assert (root / "trend" / "history.json").is_file()


def test_unrelated_layout_never_scans(tmp_path):
    reports = tmp_path / "starboard-reports"
    _make_run_dir(reports, "ws-9-2026-09-01", "2026-09-01")
    rd = _make_run_dir(reports / "elsewhere", "run-x", "2026-10-01")
    out = cmd_recur(_args(rd, reports / "ws-9"))
    assert out["baseline"] is True


def test_backlog_delta_by_catalog_id(tmp_path):
    reports = tmp_path / "starboard-reports"
    prior = _make_run_dir(reports, "ws-1-2026-09-01", "2026-09-01")
    _backlog(prior, [
        ("OPP-WH-QUEUE", "investigate", 9),
        ("OPP-JOB-OVERLAP", "investigate", 6),
        ("OPP-WH-IDLE", "not_now", 5),
        ("OPP-PO", "not_now", 4),
    ])
    rd = _make_run_dir(reports, "ws-1-2026-10-01", "2026-10-01")
    _backlog(
        rd,
        [
            ("OPP-WH-QUEUE", "act_now", 8),
            ("OPP-WH-QUEUE", "investigate", 7),  # duplicate id: highest tier wins
            ("OPP-JOB-OVERLAP", "investigate", 8),
            ("OPP-PO", "not_now", 4),
            ("OPP-LAKEBASE", "investigate", 7),
        ],
        cut=[{"id": "OPP-WH-IDLE", "reason": "serverless only"}],
    )
    out = cmd_recur(_args(rd, reports / "ws-1"))
    delta = out["backlog_delta"]
    assert delta["new"] == [{"id": "OPP-LAKEBASE", "tier": "investigate", "confidence": 7}]
    assert delta["resolved"] == [
        {"id": "OPP-WH-IDLE", "prior_tier": "not_now", "prior_confidence": 5, "cut_reason": "serverless only"}
    ]
    assert delta["tier_changed"] == [{
        "id": "OPP-WH-QUEUE", "prior_tier": "investigate", "current_tier": "act_now",
        "prior_confidence": 9, "current_confidence": 8,
    }]
    assert delta["confidence_changed"] == [
        {"id": "OPP-JOB-OVERLAP", "tier": "investigate", "prior_confidence": 6, "current_confidence": 8}
    ]
    assert delta["unchanged"] == ["OPP-PO"]
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["backlog_delta"] == delta
    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert "## Backlog delta (catalog ids)" in md
    assert "1 new, 1 resolved, 1 tier changed, 1 confidence changed, 1 unchanged" in md
    assert "| OPP-WH-QUEUE | investigate | act_now | 9 | 8 |" in md
    history = {h["run_date"]: h for h in json.loads((reports / "ws-1" / "trend" / "history.json").read_text())}
    assert (history["2026-10-01"]["act_now"], history["2026-10-01"]["investigate"],
            history["2026-10-01"]["not_now"]) == (1, 3, 1)
    assert (history["2026-09-01"]["investigate"], history["2026-09-01"]["not_now"]) == (2, 2)
    assert "Backlog vs 2026-09-01: 1 new, 1 resolved, 1 tier changed." in (rd / "README.md").read_text()


def test_backlog_delta_null_when_prior_has_no_backlog(tmp_path):
    reports = tmp_path / "starboard-reports"
    _make_run_dir(reports, "ws-1-2026-09-01", "2026-09-01")
    rd = _make_run_dir(reports, "ws-1-2026-10-01", "2026-10-01")
    _backlog(rd, [("OPP-PO", "not_now", 4)])
    out = cmd_recur(_args(rd, reports / "ws-1"))
    assert out["backlog_delta"] is None
    assert any("missing in the prior run" in w for w in out["warnings"])
    assert "missing in the prior run" in (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()


# A1 — degraded review coverage carried into the trend


def _degrade(rd: Path, *, queries: list[str], domains: list[str], flag: bool | None = True) -> None:
    p = rd / "findings-manifest.json"
    m = json.loads(p.read_text())
    if flag is not None:
        m["degraded"] = flag
    m["unavailable_queries"] = queries
    m["unavailable_domains"] = domains
    p.write_text(json.dumps(m))


def test_degraded_review_recorded_and_skipped_in_finding_trend(tmp_path):
    reports = tmp_path / "starboard-reports"
    _make_run_dir(reports, "ws-1-2026-09-01", "2026-09-01")
    cost_delta = json.loads(json.dumps(_COST_DELTA))
    cost_delta["improved"][0]["category"] = "warehouse"
    rd = _make_run_dir(reports, "ws-1-2026-10-01", "2026-10-01", review={"data": {"cost_delta": cost_delta}})
    _degrade(rd, queries=["W-W05", "C-Q01"], domains=["warehouse"])

    out = cmd_recur(_args(rd, reports / "ws-1"))

    history = {h["run_date"]: h for h in json.loads((reports / "ws-1" / "trend" / "history.json").read_text())}
    cur = history["2026-10-01"]
    assert cur["degraded"] is True
    assert cur["unavailable_queries"] == ["C-Q01", "W-W05"]
    assert cur["unavailable_domains"] == ["warehouse"]
    assert history["2026-09-01"]["degraded"] is None  # prior manifest predates the keys

    counts = json.loads((rd / "charts" / "data" / "finding-count-over-time.json").read_text())
    assert {r["run_date"] for r in counts} == {"2026-09-01"}
    spend = json.loads((rd / "charts" / "data" / "spend-over-time.json").read_text())
    assert {r["run_date"] for r in spend} == {"2026-09-01", "2026-10-01"}
    assert any("skips degraded review run(s): 2026-10-01" in w for w in out["warnings"])

    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert "(not comparable: a review was degraded)" in md
    assert "## Review coverage" in md
    assert "| warehouse | not comparable |" in md
    assert "| wh-1 | W-IDLE |" in md and "not comparable (domain degraded)" in md
    assert "Review degraded (unavailable domains: warehouse)" in (rd / "README.md").read_text()


def test_unavailable_lists_without_flag_count_as_degraded():
    cov = run_mod._review_coverage({"unavailable_queries": {"C-Q01": "timeout"}, "unavailable_domains": []})
    assert cov == {"degraded": True, "unavailable_queries": ["C-Q01"], "unavailable_domains": []}
    assert run_mod._review_coverage({}) == {"degraded": None, "unavailable_queries": [], "unavailable_domains": []}
    cov = run_mod._review_coverage({"degraded": False, "unavailable_domains": [{"domain": "jobs"}, 3]})
    assert cov["degraded"] is False and cov["unavailable_domains"] == ["jobs"]


def test_non_degraded_delta_has_no_coverage_section(tmp_path):
    reports = tmp_path / "starboard-reports"
    _make_run_dir(reports, "ws-1-2026-09-01", "2026-09-01")
    rd = _make_run_dir(reports, "ws-1-2026-10-01", "2026-10-01", review={"data": {"cost_delta": _COST_DELTA}})
    _degrade(rd, queries=[], domains=[], flag=False)
    cmd_recur(_args(rd, reports / "ws-1"))
    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert "## Review coverage" not in md and "not comparable" not in md


def _sized_backlog(rd: Path, items: list[dict]) -> None:
    doc = {
        "workspace_id": "1",
        "generated_at": "2026-10-01T00:00:00Z",
        "facts_window": {"start": "2026-09-01", "end": "2026-09-30"},
        "items": items,
    }
    (rd / "analysis" / "backlog.json").write_text(json.dumps(doc))


def _item(opp: str, target: str, tier: str, metric: str, value, unit: str) -> dict:
    return {
        "id": opp, "target": target, "tier": tier, "confidence": 7,
        "sizing": {"kind": "perf_metric", "metric": metric, "value": value, "unit": unit,
                   "formula": "x"},
    }


def test_backlog_sizing_is_the_primary_trend(tmp_path):
    reports = tmp_path / "starboard-reports"
    prior = _make_run_dir(reports, "ws-123-2026-09-01", "2026-09-01")
    rd = _make_run_dir(
        reports, "ws-123-2026-10-01", "2026-10-01", review={"data": {"cost_delta": _COST_DELTA}}
    )
    _sized_backlog(prior, [
        _item("OPP-JOB-OVERLAP", "job:1", "act_now", "pct_runs_started_while_running", 81.9, "%"),
        _item("OPP-WH-QUEUE", "warehouse:a", "investigate", "peak_daily_queued_pct", 50.6, "%"),
        _item("OPP-JOB-WAIT-TASK", "job:1", "investigate", "pilot", None, None),
    ])
    _sized_backlog(rd, [
        _item("OPP-JOB-OVERLAP", "job:1", "act_now", "pct_runs_started_while_running", 12.5, "%"),
        _item("OPP-JOB-OVERLAP", "job:2", "investigate", "pct_runs_started_while_running", 40.0, "%"),
        _item("OPP-JOB-WAIT-TASK", "job:1", "investigate", "pilot", None, None),
    ])

    out = cmd_recur(_args(rd, reports / "ws-123"))

    entry = out["entry"]
    assert entry["backlog_items"] == [
        {"id": "OPP-JOB-OVERLAP", "target": "job:1", "tier": "act_now",
         "sizing_metric": "pct_runs_started_while_running", "value": 12.5, "unit": "%"},
        {"id": "OPP-JOB-OVERLAP", "target": "job:2", "tier": "investigate",
         "sizing_metric": "pct_runs_started_while_running", "value": 40.0, "unit": "%"},
        {"id": "OPP-JOB-WAIT-TASK", "target": "job:1", "tier": "investigate",
         "sizing_metric": "pilot", "value": None, "unit": None},
    ]
    history = json.loads((reports / "ws-123" / "trend" / "history.json").read_text())
    assert history[0]["backlog_items"][0]["value"] == 81.9  # prior backfilled with sizing
    by_key = {(r["id"], r["target"]): r for r in out["backlog_sizing"]}
    assert by_key[("OPP-JOB-OVERLAP", "job:1")]["delta"] == -69.4
    assert by_key[("OPP-JOB-OVERLAP", "job:1")]["status"] == "changed"
    assert by_key[("OPP-JOB-OVERLAP", "job:2")]["status"] == "new"
    assert by_key[("OPP-WH-QUEUE", "warehouse:a")]["status"] == "resolved"
    assert by_key[("OPP-JOB-WAIT-TASK", "job:1")]["status"] == "unsized"
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["backlog_sizing"] == out["backlog_sizing"]

    delta = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert delta.index("## Backlog sizing (primary trend)") < delta.index(
        "## Review findings cost delta (secondary)"
    )
    assert (
        "| OPP-JOB-OVERLAP | job:1 | act_now → act_now | pct_runs_started_while_running | "
        "81.90 | 12.50 | % | -69.40 | changed |"
    ) in delta
    readme = (rd / "README.md").read_text()
    recur = readme.split("## Recur", 1)[1]
    first = recur.strip().splitlines()[0]
    assert first == (
        "delta vs 2026-09-01 (backlog sizing per id × target): 1 changed, 1 new, "
        "1 resolved, 1 unsized."
    )
    assert "Review findings (secondary): 1 improved" in recur


def test_metric_change_is_not_diffed(tmp_path):
    rows = run_mod._backlog_sizing_delta(
        [{"id": "OPP-X", "target": "w", "tier": "act_now", "sizing_metric": "a", "value": 2.0, "unit": "%"}],
        [{"id": "OPP-X", "target": "w", "tier": "act_now", "sizing_metric": "b", "value": 1.0, "unit": "%"}],
    )
    assert rows[0]["status"] == "metric changed" and rows[0]["delta"] is None


def test_coverage_note_is_copied_into_readme_recur(tmp_path):
    reports = tmp_path / "starboard-reports"
    rd = _make_run_dir(reports, "ws-1-2026-10-01", "2026-10-01")
    mpath = rd / "findings-manifest.json"
    m = json.loads(mpath.read_text())
    m["discovery_skipped"] = ["C-Q03", "N-L01"]
    m["coverage_note"] = (
        "2 discovery queries skipped; none used by review rules; all evidence used by "
        "review rules is present."
    )
    mpath.write_text(json.dumps(m))
    out = cmd_recur(_args(rd, reports / "ws-1"))
    assert out["entry"]["coverage_note"] == m["coverage_note"]
    readme = (rd / "README.md").read_text()
    assert f"Review coverage: {m['coverage_note']}" in readme.split("## Recur", 1)[1]
