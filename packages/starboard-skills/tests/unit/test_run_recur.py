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


def _case(tmp_path: Path) -> Path:
    """An engagement case root: ``starboard-reports/<account>/<task>/<task-name>``."""
    return tmp_path / "starboard-reports" / "acme" / "review" / "ws-1"


def _rid(run_date: str, n: int = 0) -> str:
    """A ``YYYYMMDD_<uuid4>`` run ID for ``run_date``."""
    return f"{run_date.replace('-', '')}_{n:08x}-0000-4000-8000-{int(run_date.replace('-', '')):012x}"


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
        "workspace": "ws-1",
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
    case = _case(tmp_path)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    root = case

    out = cmd_recur(_args(rd, root))

    assert out["baseline"] is True
    assert out["prior_run_dir"] is None
    history = json.loads((root / "trend" / "history.json").read_text())
    assert history == [
        {"run_date": "2026-10-01", "run": rd.name, "total_dbu_estimate": 150.0,
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
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01", products_dbu={"SQL": 120.0})
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", review={"ok": True, "data": {"cost_delta": _COST_DELTA}}
    )
    (rd / "README.md").write_text("# Run\n\n## Recur\nold note\n\n## Delivery\n- doc → local\n")
    root = case

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
    case = _case(tmp_path)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    root = case
    cmd_recur(_args(rd, root))
    cmd_recur(_args(rd, root))
    history = json.loads((root / "trend" / "history.json").read_text())
    assert len(history) == 1
    readme = (rd / "README.md").read_text()
    assert readme.count("## Recur") == 1


def test_two_same_day_recurs_keep_two_history_entries(tmp_path, capsys):
    """Live run 3: a second same-day recur replaced the first run's entry, so
    run check item 15 then failed on the first run."""
    case = _case(tmp_path)
    first = _make_run_dir(case, _rid("2026-10-01", 1), "2026-10-01")
    second = _make_run_dir(case, _rid("2026-10-01", 2), "2026-10-01")
    cmd_recur(_args(first, case, baseline=True))
    cmd_recur(_args(second, case, prior=first))
    cmd_recur(_args(second, case, prior=first))  # still idempotent per run
    history = json.loads((case / "trend" / "history.json").read_text())
    assert [(h["run_date"], h["run"]) for h in history] == [
        ("2026-10-01", first.name),
        ("2026-10-01", second.name),
    ]
    for rd in (first, second):
        (rd / "README.md").write_text("# Run\n")
        with pytest.raises(SystemExit):
            cmd_check(SimpleNamespace(run_dir=str(rd), internal=False, format="json"))
        out = json.loads(capsys.readouterr().out)
        assert any(p.startswith("15:") for p in out["data"]["passed"]), rd.name


def test_prior_auto_locate_excludes_current_and_newer(tmp_path):
    case = _case(tmp_path)
    old = _make_run_dir(case, _rid("2026-08-01"), "2026-08-01")
    newer_prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    current = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    _make_run_dir(case.parent / "ws-12", _rid("2026-09-15"), "2026-09-15")  # other case
    (case / _rid("2026-09-20")).mkdir()  # no manifest → skipped
    root = case.resolve()

    found = _locate_prior(current.resolve(), root, run_mod._run_key(current, {"run_date": "2026-10-01"}))
    assert found == newer_prior.resolve()
    # The current run is never its own prior, even when it is the only candidate.
    assert _locate_prior(old.resolve(), root, run_mod._run_key(old, {"run_date": "2026-08-01"})) is None


def test_explicit_prior_and_missing_cost_delta(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(tmp_path / "pinned", _rid("2026-09-01"), "2026-09-01")  # outside the case
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    out = cmd_recur(_args(rd, case, prior=prior))
    assert out["prior_run_date"] == "2026-09-01"
    assert any("review.json not found" in w for w in out["warnings"])
    assert "cost_delta not found" in (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()


def test_delta_narrative_not_clobbered(tmp_path):
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", review={"data": {"cost_delta": _COST_DELTA}}
    )
    delta = rd / "analysis" / "delta-vs-2026-09-01.md"
    delta.write_text("# Delta\nanalyst narrative\n")
    cmd_recur(_args(rd, case))
    assert delta.read_text() == "# Delta\nanalyst narrative\n"


def test_render_extra_missing_writes_data_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "_render_available", lambda: False)
    case = _case(tmp_path)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    out = cmd_recur(_args(rd, case))
    assert out["charts_rendered"] == []
    assert any("render extra not installed" in w for w in out["warnings"])
    assert (rd / "charts" / "data" / "spend-over-time.json").is_file()
    assert not (rd / "charts" / "trend").exists()


def test_missing_manifest_is_arg_error(tmp_path):
    rd = _case(tmp_path) / _rid("2026-10-01")
    rd.mkdir(parents=True)
    with pytest.raises(ArgError):
        cmd_recur(_args(rd, rd.parent))


def test_recur_readme_satisfies_run_check_item1(tmp_path, capsys):
    case = _case(tmp_path)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    (rd / "README.md").write_text("# Run\n\n## Delivery\n- doc: local: not uploaded\n")
    cmd_recur(_args(rd, case))
    with pytest.raises(SystemExit):
        cmd_check(SimpleNamespace(run_dir=str(rd), internal=False, format="json"))
    out = json.loads(capsys.readouterr().out)
    assert any(p.startswith("1:") for p in out["data"]["passed"])
    assert any(p.startswith("13:") for p in out["data"]["passed"])
    assert any(p.startswith("15:") for p in out["data"]["passed"])


def test_explicit_baseline_skips_prior_lookup(tmp_path):
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    out = cmd_recur(_args(rd, case, baseline=True))
    assert out["baseline"] is True and out["prior_run_dir"] is None
    assert not list((rd / "analysis").glob("delta-vs-*.md"))
    history = json.loads((case / "trend" / "history.json").read_text())
    assert [h["run_date"] for h in history] == ["2026-10-01"]  # no prior backfill
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["ok"] is True and rr["baseline"] is True


def test_baseline_and_prior_are_mutually_exclusive(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    with pytest.raises(ArgError):
        cmd_recur(_args(rd, case, prior=prior, baseline=True))


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


@pytest.mark.parametrize("how", ["missing_prior", "prior_is_run_dir", "with_baseline"])
def test_a_refused_prior_writes_nothing(tmp_path, how):
    """A refused --prior / --baseline exits 4 before any write — not even an ok:false
    recur-result.json."""
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    before = sorted(p for p in tmp_path.rglob("*"))
    kwargs = {
        "missing_prior": {"prior": tmp_path / "missing"},
        "prior_is_run_dir": {"prior": rd},
        "with_baseline": {"prior": prior, "baseline": True},
    }[how]
    with pytest.raises(ArgError) as exc:
        cmd_recur(_args(rd, case, **kwargs))
    assert exc.value.exit_code == 4
    assert sorted(p for p in tmp_path.rglob("*")) == before


def test_failed_recur_writes_result_and_run_check_fails(tmp_path, capsys):
    rd = _make_run_dir(tmp_path, "run-1", "2026-10-01")
    (rd / "findings-manifest.json").unlink()  # a bad input (not a refused --prior) is recorded
    with pytest.raises(ArgError):
        cmd_recur(_args(rd, tmp_path, baseline=True))
    rr = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert rr["ok"] is False and "findings-manifest.json" in rr["errors"][0]
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


def test_run_dir_outside_the_case_root_never_scans(tmp_path):
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    beside = _make_run_dir(case.parent, "run-x", "2026-10-01")  # next to the case root
    deeper = _make_run_dir(case / "sub", _rid("2026-10-01"), "2026-10-01")  # below a run's level
    assert cmd_recur(_args(beside, case))["baseline"] is True
    assert cmd_recur(_args(deeper, case))["baseline"] is True


def test_backlog_delta_by_catalog_id(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    _backlog(prior, [
        ("OPP-WH-QUEUE", "investigate", 9),
        ("OPP-JOB-OVERLAP", "investigate", 6),
        ("OPP-WH-IDLE", "not_now", 5),
        ("OPP-PO", "not_now", 4),
    ])
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
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
    out = cmd_recur(_args(rd, case))
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
    history = {h["run_date"]: h for h in json.loads((case / "trend" / "history.json").read_text())}
    assert (history["2026-10-01"]["act_now"], history["2026-10-01"]["investigate"],
            history["2026-10-01"]["not_now"]) == (1, 3, 1)
    assert (history["2026-09-01"]["investigate"], history["2026-09-01"]["not_now"]) == (2, 2)
    assert "Backlog vs 2026-09-01: 1 new, 1 resolved, 1 tier changed." in (rd / "README.md").read_text()


def test_backlog_delta_null_when_prior_has_no_backlog(tmp_path):
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    _backlog(rd, [("OPP-PO", "not_now", 4)])
    out = cmd_recur(_args(rd, case))
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
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    cost_delta = json.loads(json.dumps(_COST_DELTA))
    cost_delta["improved"][0]["category"] = "warehouse"
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", review={"data": {"cost_delta": cost_delta}})
    _degrade(rd, queries=["W-W05", "C-Q01"], domains=["warehouse"])

    out = cmd_recur(_args(rd, case))

    history = {h["run_date"]: h for h in json.loads((case / "trend" / "history.json").read_text())}
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
    case = _case(tmp_path)
    _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", review={"data": {"cost_delta": _COST_DELTA}})
    _degrade(rd, queries=[], domains=[], flag=False)
    cmd_recur(_args(rd, case))
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
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", review={"data": {"cost_delta": _COST_DELTA}}
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

    out = cmd_recur(_args(rd, case))

    entry = out["entry"]
    assert entry["backlog_items"] == [
        {"id": "OPP-JOB-OVERLAP", "target": "job:1", "tier": "act_now",
         "sizing_metric": "pct_runs_started_while_running", "value": 12.5, "unit": "%"},
        {"id": "OPP-JOB-OVERLAP", "target": "job:2", "tier": "investigate",
         "sizing_metric": "pct_runs_started_while_running", "value": 40.0, "unit": "%"},
        {"id": "OPP-JOB-WAIT-TASK", "target": "job:1", "tier": "investigate",
         "sizing_metric": "pilot", "value": None, "unit": None},
    ]
    history = json.loads((case / "trend" / "history.json").read_text())
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
    case = _case(tmp_path)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    mpath = rd / "findings-manifest.json"
    m = json.loads(mpath.read_text())
    m["discovery_skipped"] = ["C-Q03", "N-L01"]
    m["coverage_note"] = (
        "2 discovery queries skipped; none used by review rules; all evidence used by "
        "review rules is present."
    )
    mpath.write_text(json.dumps(m))
    out = cmd_recur(_args(rd, case))
    assert out["entry"]["coverage_note"] == m["coverage_note"]
    readme = (rd / "README.md").read_text()
    assert f"Review coverage: {m['coverage_note']}" in readme.split("## Recur", 1)[1]


def _preflight_record(rd: Path, created_at: str) -> None:
    (rd / "analysis" / "storage-preflight.json").write_text(
        json.dumps({"run_id": rd.name, "created_at": created_at})
    )


def test_engagement_case_root_locates_prior_run_id_dir(tmp_path):
    case = tmp_path / "starboard-reports" / "lm-arena" / "health_check" / "ws-1"
    old = _make_run_dir(case, "20260901_" + "a" * 8 + "-1111-4111-8111-" + "1" * 12, "2026-09-01")
    current = _make_run_dir(case, "20261001_" + "b" * 8 + "-2222-4222-8222-" + "2" * 12, "2026-10-01")
    other_task = tmp_path / "starboard-reports" / "lm-arena" / "troubleshooting" / "job-7"
    _make_run_dir(other_task, "20260915_" + "c" * 8 + "-3333-4333-8333-" + "3" * 12, "2026-09-15")
    out = cmd_recur(_args(current, case))
    assert out["prior_run_dir"] == str(old.resolve())
    assert (case / "trend" / "history.json").is_file()


def test_same_day_runs_order_by_preflight_created_at(tmp_path):
    case = tmp_path / "case"
    # Run IDs are random after the date: the later run can sort first by name.
    earlier = _make_run_dir(case, "20261007_" + "f" * 8 + "-1111-4111-8111-" + "1" * 12, "2026-10-07")
    later = _make_run_dir(case, "20261007_" + "0" * 8 + "-2222-4222-8222-" + "2" * 12, "2026-10-07")
    _preflight_record(earlier, "2026-10-07T09:00:00+00:00")
    _preflight_record(later, "2026-10-07T15:00:00+00:00")
    assert _locate_prior(later.resolve(), case, run_mod._run_key(later, {"run_date": "2026-10-07"})) == earlier.resolve()
    assert _locate_prior(earlier.resolve(), case, run_mod._run_key(earlier, {"run_date": "2026-10-07"})) is None


def test_run_date_falls_back_to_run_id_prefix(tmp_path):
    rd = tmp_path / ("20261007_" + "a" * 8 + "-1111-4111-8111-" + "1" * 12)
    assert run_mod._run_date_of(rd, {}) == "2026-10-07"


# --------------------------------------------------------------------------- #
# Public local runs with a LOCAL run authorization keep kernel records (§B7)
# --------------------------------------------------------------------------- #
_PUBLIC_RID = "20261008_12345678-1234-4234-8234-123456789abc"
_NO_AUTH = "no run authorization: kernel records skipped"
_NOT_RUN_ID = "run dir name is not its run id; later runs will not find these records"


@pytest.fixture
def public(monkeypatch):
    """Overlay off: a run dir with a LOCAL descriptor is a public local run."""
    from starboard_core.engagement.overlay import OverlaySignal
    from starboard_skills.helpers import contract

    monkeypatch.setattr(
        contract, "_detect_overlay", lambda: OverlaySignal(enabled=False), raising=False
    )
    monkeypatch.delenv("STARBOARD_OVERLAY", raising=False)


def _local_descriptor(rd: Path, *, intent: str = "health_check") -> None:
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import AccountRef, RunAuthorization

    auth = RunAuthorization(
        engagement_id=f"acme/{intent}/ws-1",
        run_id=_PUBLIC_RID,
        intent=intent,
        task="ws-1",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={"workspace_ids": ["123"]},
        authorized_scope={"account_key": "acme", "workspace_ids": ["123"]},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.LOCAL,
        audience="operator",
        methodology_version="m1",
        drive=None,
    )
    (rd / "analysis" / "run-authorization.json").write_text(json.dumps(auth.to_dict()))


def _public_run(tmp_path: Path, name: str = _PUBLIC_RID) -> Path:
    from .test_run_recur_drive import _finding as _drive_finding
    from .test_run_recur_drive import _manifest

    rd = _make_run_dir(_case(tmp_path), name, "2026-10-08")
    (rd / "findings-manifest.json").write_text(
        _manifest(
            "2026-09-08", "2026-10-07", [_drive_finding("W-IDLE", "wh-1", 30.0)], "2026-10-08"
        )
    )
    _local_descriptor(rd)
    return rd


def _recur_result(rd: Path) -> dict:
    return json.loads((rd / "analysis" / "recur-result.json").read_text())


@pytest.mark.unit
class TestPublicLocalRecur:
    def test_a_local_descriptor_writes_the_kernel_records(self, public, tmp_path):
        rd = _public_run(tmp_path)
        out = cmd_recur(_args(rd, rd.parent, baseline=True))
        for rel in ("findings.json", "health.json", "plays.json", "baseline-selection.json"):
            assert (rd / "analysis" / rel).is_file(), rel
        assert out["analysis"]["counts"]["findings"] >= 1
        assert _NO_AUTH not in out["warnings"]
        assert (rd.parent / "trend" / "history.json").is_file()
        assert _recur_result(rd)["analysis"]["counts"] == out["analysis"]["counts"]

    def test_no_descriptor_is_trend_only_and_warns(self, public, tmp_path):
        rd = _make_run_dir(_case(tmp_path), _PUBLIC_RID, "2026-10-08")
        out = cmd_recur(_args(rd, rd.parent, baseline=True))
        assert "analysis" not in out
        assert _NO_AUTH in out["warnings"]
        assert _NO_AUTH in _recur_result(rd)["warnings"]
        assert not (rd / "analysis" / "health.json").exists()

    @pytest.mark.parametrize("how", ["bad_json", "unknown_intent"])
    def test_a_bad_descriptor_is_exit_4_before_any_write(self, public, tmp_path, how):
        rd = _public_run(tmp_path)
        path = rd / "analysis" / "run-authorization.json"
        if how == "bad_json":
            path.write_text("{not json")
            reason = "run authorization unreadable:"
        else:
            path.write_text(json.dumps({**json.loads(path.read_text()), "intent": "bogus"}))
            reason = "run authorization intent bogus is not a workflow profile"
        with pytest.raises(ArgError) as exc:
            cmd_recur(_args(rd, rd.parent, baseline=True))
        assert reason in str(exc.value) and exc.value.exit_code == 4
        assert not (rd / "analysis" / "recur-result.json").exists()
        assert not (rd.parent / "trend").exists()

    def test_a_trend_root_elsewhere_reads_the_prior_from_the_case_root(
        self, public, tmp_path
    ):
        rd = _public_run(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        out = cmd_recur(_args(rd, elsewhere, baseline=True))
        warning = (
            f"analysis prior read from the case root {rd.parent}; "
            f"trend written under {elsewhere}"
        )
        assert warning in out["analysis"]["warnings"]
        assert (elsewhere / "trend" / "history.json").is_file()
        assert not (rd.parent / "trend").exists()
        assert (rd / "analysis" / "health.json").is_file()

    def test_a_run_dir_not_named_by_its_run_id_warns(self, public, tmp_path):
        rd = _public_run(tmp_path, name="my-review")
        out = cmd_recur(_args(rd, rd.parent, baseline=True))
        assert _NOT_RUN_ID in out["analysis"]["warnings"]
        assert (rd / "analysis" / "health.json").is_file()


@pytest.mark.unit
@pytest.mark.parametrize("intent", ["health_check", "review"])
def test_a_health_check_recur_says_nothing_about_a_backlog(public, tmp_path, intent):
    """A health check builds no backlog: its recur has no backlog warning, no backlog
    sections in the delta file and no backlog line in the README — a review still does."""
    rd = _public_run(tmp_path)
    _local_descriptor(rd, intent=intent)
    (rd / "analysis" / "review.json").write_text(json.dumps({"data": {"cost_delta": _COST_DELTA}}))
    prior = _make_run_dir(_case(tmp_path), _rid("2026-09-08"), "2026-09-08")
    out = cmd_recur(_args(rd, rd.parent, prior))
    delta_md = (rd / "analysis" / "delta-vs-2026-09-08.md").read_text()
    recur_md = (rd / "README.md").read_text().split("## Recur", 1)[1]
    said = [w for w in out["warnings"] if "backlog" in w.lower()]
    if intent == "health_check":
        assert said == []
        assert "backlog" not in delta_md.lower()
        assert "## Review findings cost delta\n" in delta_md
        assert "backlog" not in recur_md.lower()
        assert "delta vs 2026-09-08 (review findings): 1 improved" in recur_md
        # run-5 D4: a health check emits empty backlog fields, not null
        assert out["backlog_delta"] == {
            "new": [], "resolved": [], "tier_changed": [], "confidence_changed": [], "unchanged": [],
        }
        assert out["backlog_sizing"] == []
    else:
        assert said
        assert "## Backlog sizing (primary trend)" in delta_md
        assert "backlog sizing unavailable" in recur_md
        assert "Review findings (secondary): 1 improved" in recur_md


# The total DBU estimate is a lookback-window total (products_dbu = F-01): runs over
# different windows are not compared as a change.


def _set_lookback(rd: Path, days: int) -> None:
    p = rd / "findings-manifest.json"
    m = json.loads(p.read_text())
    m["lookback_days"] = days
    p.write_text(json.dumps(m))


def test_total_dbu_not_comparable_across_different_lookback_windows(tmp_path):
    case = _case(tmp_path)
    _set_lookback(_make_run_dir(case, _rid("2026-09-01"), "2026-09-01"), 30)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", products_dbu={"SQL": 30.0})
    _set_lookback(rd, 7)

    out = cmd_recur(_args(rd, case))

    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    # run-5 D2: not-comparable totals are printed side by side, never as an arrow
    assert (
        "Total DBU estimate (not compared): prior 150.00 · current 30.00 · "
        "findings (not compared): prior 3 · current 3"
    ) in md
    assert "Total DBU estimate (list-price, not compared): prior 150.00 · current 30.00." in (
        rd / "README.md"
    ).read_text()
    assert "the prior run covers 30 days, this run 7" in md  # the window reason leads
    assert any("30-day vs 7-day lookback windows" in w for w in out["warnings"])


@pytest.mark.parametrize("prior_lb, cur_lb", [(7, 7), (None, 7), (30, None)])
def test_total_dbu_comparable_on_same_or_unknown_window(tmp_path, prior_lb, cur_lb):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    for d, lb in ((prior, prior_lb), (rd, cur_lb)):
        if lb is not None:
            _set_lookback(d, lb)
    out = cmd_recur(_args(rd, case))
    assert "lookback windows" not in (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert not any("lookback windows" in w for w in out["warnings"])


# ---- window_mismatch: 7 / 30 / 90-day runs are never differenced ----------------------


def test_auto_prior_prefers_the_same_lookback_window(tmp_path):
    case = _case(tmp_path)
    seven = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    _set_lookback(seven, 7)
    thirty = _make_run_dir(case, _rid("2026-09-20"), "2026-09-20")  # newer, other window
    _set_lookback(thirty, 30)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    _set_lookback(rd, 7)

    out = cmd_recur(_args(rd, case))

    assert out["prior_run_dir"] == str(seven.resolve())
    assert out["comparable"] is True and out["not_comparable_reason"] is None
    assert _locate_prior(rd, case, run_mod._run_key(rd, {"run_date": "2026-10-01"}), 30) == thirty.resolve()
    assert _locate_prior(rd, case, run_mod._run_key(rd, {"run_date": "2026-10-01"}), None) == thirty.resolve()


def test_recur_across_windows_reports_window_mismatch(tmp_path):
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")  # 150 DBU over 30 days
    _set_lookback(prior, 30)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01", products_dbu={"SQL": 70.0})  # 7 days
    _set_lookback(rd, 7)
    _sized_backlog(prior, [_item("OPP-JOB-OVERLAP", "job:1", "act_now", "pct", 80.0, "%")])
    _sized_backlog(rd, [_item("OPP-JOB-OVERLAP", "job:1", "act_now", "pct", 10.0, "%")])

    out = cmd_recur(_args(rd, case))

    assert out["comparable"] is False
    assert out["not_comparable_reason"] == "window_mismatch"
    assert out["window"] == {
        "comparable": False,
        "reason": "window_mismatch",
        "prior_run_id": prior.name,
        "prior_lookback_days": 30,
        "current_lookback_days": 7,
    }
    (row,) = out["backlog_sizing"]
    assert row["status"] == "not_comparable" and row["delta"] is None
    assert out["entry"]["dbu_per_day"] == 10.0
    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    assert md.split("\n\n", 2)[1].startswith("> **not comparable (window_mismatch)** — windows differ")
    assert "5.00 → 10.00 DBU/day" in md  # 150 / 30 -> 70 / 7, normalised per day
    assert "## Capture repeatability (not a change)" in md
    assert "### Persisting" not in md and "### Improved" not in md
    readme = (rd / "README.md").read_text()
    assert readme.split("## Recur\n", 1)[1].lstrip("\n").startswith("not comparable (window_mismatch)")
    assert out["delta_skipped_reason"] is None
    result = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert result["comparable"] is False and result["not_comparable_reason"] == "window_mismatch"
    assert any(w.startswith("window_mismatch:") for w in out["warnings"])
    # No --since re-run advice: a review over a not comparable window has no delta either.
    assert [w for w in out["warnings"] if "--since" in w or "review.json" in w] == []
    assert "--since" not in md


def test_local_prior_runs_carry_the_prior_interval(tmp_path):
    """A7: a local recur's prior_runs[].interval is the prior's window, not null."""
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    manifest = json.loads((prior / "findings-manifest.json").read_text())
    manifest["facts_window"] = {"start": "2026-08-02", "end": "2026-08-31"}
    (prior / "findings-manifest.json").write_text(json.dumps(manifest))
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")

    out = cmd_recur(_args(rd, case))

    assert out["prior_runs"] == [{
        "run_id": prior.name, "interval": {"start": "2026-08-02", "end": "2026-08-31"},
        "task": None, "skipped_reason": None,
    }]
    result = json.loads((rd / "analysis" / "recur-result.json").read_text())
    assert result["prior_runs"] == out["prior_runs"]
    assert result["delta_skipped_reason"] is None and out["delta_skipped_reason"] is None


def test_not_comparable_delta_lists_persisting_findings_as_repeatability(tmp_path):
    """A5: a not comparable delta titles the persisting table as capture repeatability."""
    case = _case(tmp_path)
    prior = _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
    _set_lookback(prior, 30)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01",
                       review={"data": {"cost_delta": _COST_DELTA}})
    _set_lookback(rd, 7)

    cmd_recur(_args(rd, case))

    md = (rd / "analysis" / "delta-vs-2026-09-01.md").read_text()
    section = md.split("## Capture repeatability (not a change)\n", 1)[1]
    # run-5 D1: every finding present in both manifests is listed (from the manifests, not
    # the cost_delta classes) — the improved W-IDLE included, with no improved/regressed label
    assert "| J-FAIL | 1 |" in section.split("## Narrative", 1)[0]
    assert "| W-IDLE | 1 |" in section.split("## Narrative", 1)[0]
    assert "### Improved" not in md and "### Newly expensive" not in md


def test_spend_trend_only_charts_the_same_window(tmp_path):
    case = _case(tmp_path)
    (case / "trend").mkdir(parents=True)
    (case / "trend" / "history.json").write_text(json.dumps([
        {"run_date": "2026-08-01", "run": "old", "total_dbu_estimate": 900.0, "lookback_days": 30,
         "finding_count": 1, "critical": 0, "high": 1, "medium": 0},
    ]))
    _set_lookback(_make_run_dir(case, _rid("2026-09-01"), "2026-09-01"), 7)
    rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
    _set_lookback(rd, 7)

    out = cmd_recur(_args(rd, case))

    spend = json.loads((rd / "charts" / "data" / "spend-over-time.json").read_text())
    assert [r["run_date"] for r in spend] == ["2026-09-01", "2026-10-01"]
    assert any("2026-08-01" in w and "window_mismatch" in w for w in out["warnings"])
    history = json.loads((case / "trend" / "history.json").read_text())
    assert [h.get("lookback_days") for h in history] == [30, 7, 7]  # kept, just not charted together
