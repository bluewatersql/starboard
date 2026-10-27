"""Unit tests for scripts/compare-runs.py (stdlib-only comparison harness).

Imports the script via importlib since the filename contains a hyphen.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Load the script as a module
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).parents[4] / "scripts" / "compare-runs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("compare_runs", str(_SCRIPT))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


cr = _load_module()


# ---------------------------------------------------------------------------
# compare_facts
# ---------------------------------------------------------------------------


def test_compare_facts_within_threshold():
    gold = {"total": {"dbus": 1000.0}}
    run = {"total": {"dbus": 1050.0}}  # 5% diff → under 10%
    records = cr.compare_facts(gold, run)
    assert any(r["field"] == "total.dbus" for r in records)
    flagged = [r for r in records if r["flagged"]]
    assert flagged == []


def test_compare_facts_flags_large_diff():
    gold = {"total": {"dbus": 1000.0}}
    run = {"total": {"dbus": 1200.0}}  # 20% diff → flagged
    records = cr.compare_facts(gold, run)
    flagged = [r for r in records if r["flagged"]]
    assert len(flagged) == 1
    assert flagged[0]["field"] == "total.dbus"
    assert abs(flagged[0]["diff_pct"] - 20.0) < 0.1


def test_compare_facts_both_none():
    assert cr.compare_facts(None, None) == []


def test_compare_facts_gold_none():
    run = {"total": {"dbus": 500.0}}
    records = cr.compare_facts(None, run)
    # run field present, gold absent → field appears in records, diff_pct is None (can't compare)
    assert any(r["field"] == "total.dbus" for r in records)
    rec = next(r for r in records if r["field"] == "total.dbus")
    assert rec["gold"] is None
    assert rec["run"] == 500.0
    assert rec["diff_pct"] is None
    # Not flagged: no diff threshold applies when one side is absent
    assert rec["flagged"] is False


def test_compare_facts_run_none():
    gold = {"total": {"dbus": 500.0}}
    records = cr.compare_facts(gold, None)
    assert any(r["field"] == "total.dbus" for r in records)


# ---------------------------------------------------------------------------
# compare_catalog
# ---------------------------------------------------------------------------


def test_compare_catalog_matching():
    gold = [
        {"id": "OPP-WH-IDLE", "tier": "act_now", "sizing": {"kind": "bounded_dbu"}},
    ]
    run = [
        {"id": "OPP-WH-IDLE", "tier": "act_now", "sizing": {"kind": "bounded_dbu"}},
    ]
    records = cr.compare_catalog(gold, run)
    assert len(records) == 1
    assert records[0]["flagged"] is False


def test_compare_catalog_tier_flip():
    gold = [{"id": "OPP-WH-IDLE", "tier": "act_now", "sizing": {"kind": "bounded_dbu"}}]
    run = [{"id": "OPP-WH-IDLE", "tier": "investigate", "sizing": {"kind": "bounded_dbu"}}]
    records = cr.compare_catalog(gold, run)
    assert records[0]["tier_flip"] is True
    assert records[0]["flagged"] is True


def test_compare_catalog_missing_from_run():
    gold = [{"id": "OPP-WH-IDLE", "tier": "act_now", "sizing": {"kind": "pilot"}}]
    run: list = []
    records = cr.compare_catalog(gold, run)
    assert records[0]["missing_from_run"] is True
    assert records[0]["flagged"] is True


def test_compare_catalog_kind_change():
    gold = [{"id": "OPP-WH-IDLE", "tier": "act_now", "sizing": {"kind": "bounded_dbu"}}]
    run = [{"id": "OPP-WH-IDLE", "tier": "act_now", "sizing": {"kind": "pilot"}}]
    records = cr.compare_catalog(gold, run)
    assert records[0]["kind_change"] is True
    assert records[0]["flagged"] is True


def test_compare_catalog_both_none():
    assert cr.compare_catalog(None, None) == []


# ---------------------------------------------------------------------------
# load_facts / load_backlog_items (filesystem)
# ---------------------------------------------------------------------------


def test_load_facts_present(tmp_path):
    djson = tmp_path / "discovery.json"
    djson.write_text(json.dumps({"data": {"facts": {"total": {"dbus": 100.0}}}}))
    result = cr.load_facts(tmp_path)
    assert result == {"total": {"dbus": 100.0}}


def test_load_facts_absent(tmp_path):
    djson = tmp_path / "discovery.json"
    djson.write_text(json.dumps({"data": {"packs": []}}))
    assert cr.load_facts(tmp_path) is None


def test_load_facts_no_file(tmp_path):
    assert cr.load_facts(tmp_path) is None


def test_load_backlog_items_present(tmp_path):
    bl = tmp_path / "analysis" / "backlog.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps({"items": [{"id": "OPP-WH-IDLE"}]}))
    items = cr.load_backlog_items(tmp_path)
    assert items == [{"id": "OPP-WH-IDLE"}]


def test_load_backlog_items_absent(tmp_path):
    assert cr.load_backlog_items(tmp_path) is None


# ---------------------------------------------------------------------------
# run_label
# ---------------------------------------------------------------------------


def test_run_label_standard_path(tmp_path):
    rd = tmp_path / "starboard-reports" / "claude-opus-5-5" / "abc12345xyz"
    rd.mkdir(parents=True)
    label = cr.run_label(rd)
    assert label == "claude-opus-5-5/abc12345"


def test_run_label_fallback(tmp_path):
    rd = tmp_path / "some" / "other" / "longrunid"
    rd.mkdir(parents=True)
    label = cr.run_label(rd)
    # Falls back to last two components
    assert "other" in label or "longrun" in label


# ---------------------------------------------------------------------------
# flatten_facts
# ---------------------------------------------------------------------------


def test_flatten_facts_nested():
    facts = {"total": {"dbus": 100.0, "dsu": 5.0}, "warehouses": {"count": 3}}
    flat = cr._flatten_facts(facts)
    assert flat["total.dbus"] == 100.0
    assert flat["total.dsu"] == 5.0
    assert flat["warehouses.count"] == 3.0


def test_flatten_facts_with_list():
    facts = {"top_jobs": [{"dbus": 50.0}, {"dbus": 30.0}]}
    flat = cr._flatten_facts(facts)
    assert flat["top_jobs[0].dbus"] == 50.0
    assert flat["top_jobs[1].dbus"] == 30.0


# ---------------------------------------------------------------------------
# Run-dir discovery (A6) and discovery/discovery.json facts (D1)
# ---------------------------------------------------------------------------


def test_find_runs_skips_non_run_dirs(tmp_path, capsys):
    (tmp_path / "gpt-6" / "run-a").mkdir(parents=True)
    (tmp_path / "gpt-6" / "run-a" / "README.md").write_text("# r\n")
    (tmp_path / "glm" / "run-b" / "discovery").mkdir(parents=True)
    (tmp_path / "glm" / "run-b" / "discovery" / "discovery.json").write_text("{}")
    (tmp_path / "ws-123" / "trend").mkdir(parents=True)  # trend root, not a run
    (tmp_path / "gpt-6" / "run-a" / "charts").mkdir()
    runs = cr.find_runs([str(tmp_path / "*" / "*"), str(tmp_path / "ws-123")])
    assert runs == [(tmp_path / "glm" / "run-b").resolve(), (tmp_path / "gpt-6" / "run-a").resolve()]
    assert "skipping non-run dir" in capsys.readouterr().err


def test_load_facts_from_discovery_out_dir(tmp_path):
    (tmp_path / "discovery").mkdir()
    (tmp_path / "discovery" / "discovery.json").write_text(
        json.dumps({"data": {"facts": {"total": {"dbus": 7.0}}}})
    )
    assert cr.load_facts(tmp_path) == {"total": {"dbus": 7.0}}


# ---------------------------------------------------------------------------
# Sizing values (A6): numbers diffed, legacy strings parsed with a warning
# ---------------------------------------------------------------------------


def test_parse_sizing_value():
    assert cr.parse_sizing_value(4819.5) == (4819.5, None)
    assert cr.parse_sizing_value(None) == (None, None)
    num, warn = cr.parse_sizing_value("4,819.5 DBU")
    assert num == 4819.5 and "4,819.5 DBU" in warn
    assert cr.parse_sizing_value("+11,963.52 DBU/day")[0] == 11963.52
    assert cr.parse_sizing_value("7.6–23.6% queued/day")[0] == 7.6
    num, warn = cr.parse_sizing_value("pilot — measure DBU per run")
    assert num is None and "no leading number" in warn


def _sized(opp_id: str, value) -> dict:
    return {"id": opp_id, "tier": "not_now", "sizing": {"kind": "bounded_dbu", "value": value}}


def test_compare_catalog_string_value_tolerated_and_diffed():
    gold = [_sized("OPP-JOB-FAILURE", "4,819.5 DBU"), _sized("OPP-PO", 12800.83)]
    run = [_sized("OPP-JOB-FAILURE", 4820), _sized("OPP-PO", 20000.0)]
    recs = {r["id"]: r for r in cr.compare_catalog(gold, run)}
    fail = recs["OPP-JOB-FAILURE"]
    assert fail["gold_sizing_value"] == 4819.5 and fail["run_sizing_value"] == 4820.0
    assert fail["value_diff"] is False and fail["flagged"] is False
    assert any("string sizing.value" in w for w in fail["warnings"])
    assert recs["OPP-PO"]["value_diff"] is True and recs["OPP-PO"]["flagged"] is True


def test_checklist_items_cover_sixteen():
    assert len(cr.CHECKLIST_ITEMS) == 16
    assert cr.ITEM_PREFIXES[-1] == "16:"


# ---------------------------------------------------------------------------
# Round 4 — C5 (id, target) keys, cut reasons, metric-aware sizing comparison
# ---------------------------------------------------------------------------


def _item(opp_id, target, tier="investigate", *, kind="perf_metric", metric=None, value=None, unit=None):
    it = {"id": opp_id, "tier": tier, "sizing": {"kind": kind, "metric": metric, "value": value, "unit": unit}}
    if target is not None:
        it["target"] = target
    return it


def test_compare_catalog_keys_on_id_and_target():
    gold = [_item("OPP-WH-QUEUE", "warehouse:a", "act_now"), _item("OPP-WH-QUEUE", "warehouse:b")]
    run = [_item("OPP-WH-QUEUE", "warehouse:b"), _item("OPP-WH-QUEUE", "warehouse:a", "act_now")]
    recs = cr.compare_catalog(gold, run)
    assert [(r["id"], r["target"]) for r in recs] == [("OPP-WH-QUEUE", "warehouse:a"), ("OPP-WH-QUEUE", "warehouse:b")]
    assert not any(r["flagged"] for r in recs)


def test_compare_catalog_legacy_items_key_on_occurrence():
    gold = [_item("OPP-WH-QUEUE", None, "act_now"), _item("OPP-WH-QUEUE", None)]
    run = [_item("OPP-WH-QUEUE", None, "act_now")]
    recs = {r["target"]: r for r in cr.compare_catalog(gold, run)}
    assert recs["#1"]["flagged"] is False
    assert recs["#2"]["missing_from_run"] is True


def test_compare_catalog_shows_cut_reason_instead_of_missing():
    gold = [_item("OPP-PO", "workspace", "not_now", kind="none", value=10.0, unit="DBU")]
    recs = cr.compare_catalog(gold, [], None, [{"id": "OPP-PO", "rule": "disqualifier", "reason": "unscoped"}])
    assert recs[0]["missing_from_run"] is False
    assert recs[0]["run_cut_reason"] == "[disqualifier] unscoped"
    assert recs[0]["flagged"] is True
    md = cr._md_catalog_section(gold, [], "x", None, [{"id": "OPP-PO", "rule": "disqualifier", "reason": "unscoped"}])
    assert "cut: [disqualifier] unscoped" in md and "missing" not in md


def test_compare_catalog_extra_run_item_flagged_with_gold_cut():
    run = [_item("OPP-WH-IDLE", "warehouse:a", "not_now", kind="bounded_dbu", value=5.0, unit="DBU")]
    recs = cr.compare_catalog([], run, [{"id": "OPP-WH-IDLE", "reason": "no idle"}], None)
    assert recs[0]["extra_in_run"] is True and recs[0]["gold_cut_reason"] == "no idle"
    assert recs[0]["flagged"] is True


def test_compare_catalog_sizing_compared_only_on_same_metric_and_unit():
    canon = {"metric": "pct_runs_started_while_running", "unit": "%"}
    gold = [_item("OPP-JOB-OVERLAP", "job:1", value=99.5, **canon)]
    same = [_item("OPP-JOB-OVERLAP", "job:1", value=80.0, **canon)]
    rec = cr.compare_catalog(gold, same)[0]
    assert rec["sizing_comparable"] is True and rec["value_diff"] is True
    other = [_item("OPP-JOB-OVERLAP", "job:1", value=99.0, metric="max_concurrent_observed", unit="runs")]
    rec = cr.compare_catalog(gold, other)[0]
    assert rec["sizing_comparable"] is False and rec["value_diff"] is False and rec["flagged"] is True
    md = cr._md_catalog_section(gold, other, "x")
    assert "sizing not comparable" in md


def test_compare_catalog_prose_target_falls_back_to_occurrence():
    gold = [_item("OPP-WH-QUEUE", None, "act_now")]
    run = [_item("OPP-WH-QUEUE", "Warehouse abc — Starter; capacity change", "act_now")]
    recs = cr.compare_catalog(gold, run)
    assert len(recs) == 1 and recs[0]["target"] == "#1" and recs[0]["flagged"] is False


# ---------------------------------------------------------------------------
# Round 6 — tolerate a missing metric, per-target cuts, aggregated items
# ---------------------------------------------------------------------------


def test_compare_catalog_missing_metric_on_one_side_is_comparable():
    gold = [_item("OPP-JOB-TIMEOUT", "job:1", "not_now", kind="bounded_dbu", value=265.6, unit="DBU")]
    run = [_item("OPP-JOB-TIMEOUT", "job:1", "not_now", kind="bounded_dbu", metric="failed_dbu", value=265.6, unit="DBU")]
    rec = cr.compare_catalog(gold, run)[0]
    assert rec["sizing_comparable"] is True and rec["flagged"] is False
    other_unit = [_item("OPP-JOB-TIMEOUT", "job:1", "not_now", kind="bounded_dbu", value=265.6, unit="min")]
    rec = cr.compare_catalog(gold, other_unit)[0]
    assert rec["sizing_comparable"] is False and rec["flagged"] is True
    no_value = [_item("OPP-JOB-TIMEOUT", "job:1", "not_now", kind="bounded_dbu", value=None, unit=None)]
    rec = cr.compare_catalog(gold, no_value)[0]
    assert rec["value_missing"] is True and rec["flagged"] is True


def test_compare_catalog_cut_matches_target():
    gold = [_item("OPP-JOB-WAIT-TASK", "job:1"), _item("OPP-JOB-WAIT-TASK", "job:2")]
    run_cut = [{"id": "OPP-JOB-WAIT-TASK", "target": "job:2", "rule": "no_evidence", "reason": "timed out"}]
    recs = {r["target"]: r for r in cr.compare_catalog(gold, [], None, run_cut)}
    assert recs["job:2"]["run_cut_reason"] == "[no_evidence] timed out"
    assert recs["job:1"]["run_cut_reason"] is None and recs["job:1"]["missing_from_run"] is True


def test_compare_catalog_aggregated_not_missing():
    gold = [_item("OPP-CLUSTER-RIGHTSIZE", "cluster:5902-abc", "not_now", kind="bounded_dbu", value=5.0, unit="DBU")]
    agg = _item("OPP-CLUSTER-RIGHTSIZE", "workspace", "not_now", kind="bounded_dbu", value=5.0, unit="DBU")
    agg["sizing"]["formula"] = "one driver rated SEVERELY_OVERPROVISIONED (cluster 5902-abc)"
    recs = {r["target"]: r for r in cr.compare_catalog(gold, [agg])}
    assert recs["cluster:5902-abc"]["missing_from_run"] is False
    assert recs["cluster:5902-abc"]["run_aggregated_into"] == "workspace"
    assert recs["workspace"]["extra_in_run"] is True
    md = cr._md_catalog_section(gold, [agg], "x")
    assert "aggregated (run carries it in workspace)" in md and "| missing" not in md
