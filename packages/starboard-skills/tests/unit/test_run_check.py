"""Unit tests for ``starboard-helper run check``.

Each test uses tmp_path fixtures.  There is:
- one "fully passing" synthetic run (all 16 items pass), and
- one test per rule that exercises the specific failure path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from starboard_skills.helpers.contract import ArgError
from starboard_skills.helpers.run import (
    _check_clean_siblings,
    _validate_backlog,
    cmd_check,
)

# ---------------------------------------------------------------------------
# Helpers to build a synthetic run directory
# ---------------------------------------------------------------------------


def _make_run(base: Path, *, internal: bool = False) -> Path:
    """Build a fully-conformant synthetic run directory under base."""
    rd = base / "run"
    rd.mkdir()

    # 1. README.md with ## Delivery and ## Recur (valid artifact entry required)
    (rd / "README.md").write_text(
        "# Run\n\n## Delivery\ndeliverables/exec-summary.md: local: not uploaded\n\n## Recur\nBaseline run.\n"
    )

    # 2. discovery.json with data.facts
    (rd / "discovery.json").write_text(
        json.dumps(
            {
                "ok": True,
                "domain": "discovery",
                "command": "run",
                "data": {
                    "facts": {"window": {"start": "2026-09-01", "end": "2026-09-30"}},
                    "packs": [],
                },
                "error": None,
                "meta": {"format": "json", "contract_version": "1.0"},
            }
        )
    )

    # 3. discovery/domains/ >=3 files
    domains = rd / "discovery" / "domains"
    domains.mkdir(parents=True)
    for name in ("billing.md", "jobs.md", "warehouses.md", "platform.md"):
        (domains / name).write_text(f"# {name}\ncontent\n")

    # 4. discovery/analysis.md with Grade
    (rd / "discovery" / "analysis.md").write_text(
        "# Analysis\n\n## Domain report card\n| Domain | Grade | Headline |\n"
    )

    # 5. analysis/verify/ — 8+ .sql/.json pairs
    verify = rd / "analysis" / "verify"
    verify.mkdir(parents=True)
    for i in range(8):
        (verify / f"v{i}.sql").write_text(f"SELECT {i};")
        (verify / f"v{i}.json").write_text(json.dumps({"rows": []}))

    # 6. analysis/backlog.json — valid per §3
    bl_items = [
        _make_backlog_item("OPP-WH-IDLE", "act_now", "deliverables/notebooks/nb-0.py", target="warehouse:w0"),
        _make_backlog_item("OPP-WH-QUEUE", "investigate", "deliverables/notebooks/nb-1.py", target="warehouse:w1"),
        _make_backlog_item("OPP-PO", "not_now", None),
    ]
    # Act-now / investigate items reference verify files
    bl_items[0]["evidence"] = ["analysis/verify/v0.json"]
    bl_items[1]["evidence"] = ["analysis/verify/v1.json"]
    (rd / "analysis" / "backlog.json").write_text(
        json.dumps(
            {
                "workspace_id": "123456",
                "generated_at": "2026-10-01T00:00:00Z",
                "facts_window": {"start": "2026-09-01", "end": "2026-09-30"},
                "items": bl_items,
            }
        )
    )

    # 7. analysis/action-plan.md
    (rd / "analysis" / "action-plan.md").write_text("# Action plan\n")

    # 8. analysis/technical-review.md with ## Humanize
    (rd / "analysis" / "technical-review.md").write_text(
        "# Technical review\n\n## Findings\nNone.\n\n## Humanize\nVoice check.\n"
    )

    # 9. deliverables/ required files
    deliv = rd / "deliverables"
    deliv.mkdir(parents=True)
    for name in ("exec-summary.md", "evidence-pack.md", "action-plan.md", "slack-post.md"):
        (deliv / name).write_text(f"# {name}\n")

    # 10. notebooks per act_now/investigate item
    nb_dir = deliv / "notebooks"
    nb_dir.mkdir()
    for i in range(2):
        (nb_dir / f"nb-{i}.py").write_text(f"# notebook {i}\n")

    # 11. deliverables/charts/ >= 1 png
    charts = deliv / "charts"
    charts.mkdir()
    (charts / "dbu-trend.png").write_bytes(b"\x89PNG\r\n")

    # 13. findings-manifest.json (recurrence keystone, both paths)
    (rd / "findings-manifest.json").write_text(
        json.dumps({"snapshot_version": "2", "run_date": "2026-10-01", "findings": []})
    )

    # 15. analysis/recur-result.json (baseline) + its trend history entry
    hist = base / "trend" / "history.json"
    hist.parent.mkdir(parents=True)
    entry = {"run_date": "2026-10-01", "run": "run", "finding_count": 0}
    hist.write_text(json.dumps([entry]))
    (rd / "analysis" / "recur-result.json").write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": True,
                "prior_run": None,
                "history_path": str(hist),
                "history_entry": entry,
                "backlog_delta": None,
                "errors": [],
            }
        )
    )

    # 12. (--internal) .clean siblings
    if internal:
        for name in ("exec-summary.md", "evidence-pack.md", "action-plan.md", "slack-post.md"):
            stem = Path(name).stem
            (deliv / f"{stem}.clean.md").write_text(f"# {stem} clean\n")
        for i in range(2):
            (nb_dir / f"nb-{i}.clean.py").write_text(f"# notebook {i} clean\n")

    return rd


def _make_backlog_item(
    opp_id: str,
    tier: str,
    notebook: str | None,
    *,
    evidence: list[str] | None = None,
    target: str = "workspace",
) -> dict:
    return {
        "id": opp_id,
        "target": target,
        "title": f"Title for {opp_id}",
        "tier": tier,
        "confidence": 7,
        "sizing": {"kind": "pilot", "value": None, "unit": None, "formula": "measure X"},
        "evidence": evidence if evidence is not None else [],
        "lever": "some.setting = value",
        "notebook": notebook,
    }


# ---------------------------------------------------------------------------
# Full-pass test
# ---------------------------------------------------------------------------


def test_all_checks_pass(tmp_path, capsys):
    rd = _make_run(tmp_path)
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["data"]["summary"]["all_passed"] is True
    assert out["data"]["summary"]["fail_count"] == 0
    assert out["domain"] == "run"
    assert out["command"] == "check"


def test_all_checks_pass_internal(tmp_path, capsys):
    rd = _make_run(tmp_path, internal=True)
    args = SimpleNamespace(run_dir=str(rd), internal=True, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["data"]["summary"]["all_passed"] is True


# ---------------------------------------------------------------------------
# run-dir not found → ArgError
# ---------------------------------------------------------------------------


def test_missing_run_dir_raises_arg_error(tmp_path):
    args = SimpleNamespace(run_dir=str(tmp_path / "nope"), internal=False, format="json")
    with pytest.raises(ArgError):
        cmd_check(args)


# ---------------------------------------------------------------------------
# Item 1: README.md sections
# ---------------------------------------------------------------------------


def test_item1_fail_no_readme(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "README.md").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("1:" in i for i in item_ids)


def test_item1_fail_missing_delivery_section(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "README.md").write_text("# Run\n\n## Recur\nBaseline.\n")
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed_items = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item1 = next((v for k, v in failed_items.items() if k.startswith("1:")), None)
    assert item1 is not None
    assert "## Delivery" in item1


def test_item1_fail_missing_recur_section(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "README.md").write_text("# Run\n\n## Delivery\nSome artifact.\n")
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed_items = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item1 = next((v for k, v in failed_items.items() if k.startswith("1:")), None)
    assert item1 is not None
    assert "## Recur" in item1


# ---------------------------------------------------------------------------
# Item 2: discovery.json with data.facts
# ---------------------------------------------------------------------------


def test_item2_fail_no_discovery_json(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "discovery.json").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("2:" in i for i in item_ids)


def test_item2_fail_no_facts_key(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "discovery.json").write_text(json.dumps({"ok": True, "data": {"packs": []}}))
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed_reasons = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item2_reason = next((v for k, v in failed_reasons.items() if k.startswith("2:")), None)
    assert item2_reason is not None
    assert "facts" in item2_reason


# ---------------------------------------------------------------------------
# Item 3: discovery/domains/ >= 3 .md files
# ---------------------------------------------------------------------------


def test_item3_fail_too_few_domains(tmp_path, capsys):
    rd = _make_run(tmp_path)
    # Remove domain files until fewer than 3 remain
    for f in list((rd / "discovery" / "domains").glob("*.md"))[2:]:
        f.unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("3:" in i for i in item_ids)


# ---------------------------------------------------------------------------
# Item 4: discovery/analysis.md has Grade
# ---------------------------------------------------------------------------


def test_item4_fail_no_analysis_md(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "discovery" / "analysis.md").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("4:" in i for i in item_ids)


def test_item4_fail_no_grade_keyword(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "discovery" / "analysis.md").write_text("# Analysis\nNo report card here.\n")
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item4 = next((v for k, v in failed.items() if k.startswith("4:")), None)
    assert item4 is not None
    assert "Grade" in item4


# ---------------------------------------------------------------------------
# Item 5: .sql/.json pairs
# ---------------------------------------------------------------------------


def test_item5_fail_unpaired_sql(tmp_path, capsys):
    rd = _make_run(tmp_path)
    # Add an unpaired .sql
    (rd / "analysis" / "verify" / "orphan.sql").write_text("SELECT 1;")
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item5 = next((v for k, v in failed.items() if k.startswith("5:")), None)
    assert item5 is not None
    assert "orphan.sql" in item5


def test_item5_fail_too_few_pairs(tmp_path, capsys):
    rd = _make_run(tmp_path)
    # Remove backlog.json so min_pairs defaults to 8, then remove 4 of 8 pairs → 4 < 8
    (rd / "analysis" / "backlog.json").unlink()
    verify = rd / "analysis" / "verify"
    for i in range(4, 8):
        (verify / f"v{i}.sql").unlink()
        (verify / f"v{i}.json").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("5:" in i for i in item_ids)


def _check_data(rd: Path, capsys) -> dict:
    with pytest.raises(SystemExit):
        cmd_check(SimpleNamespace(run_dir=str(rd), internal=False, format="json"))
    return json.loads(capsys.readouterr().out)["data"]


def _failed_verify(path: Path) -> None:
    path.write_text(json.dumps({"ok": False, "data": None, "error": "statement timed out"}))


def test_item5_failed_verify_json_is_recorded_not_evidence(tmp_path, capsys):
    rd = _make_run(tmp_path)
    # v0 is the only verify file the act_now item cites; it failed (ok:false).
    _failed_verify(rd / "analysis" / "verify" / "v0.json")
    data = _check_data(rd, capsys)
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    item5 = next(v for k, v in failed.items() if k.startswith("5:"))
    assert "items[0] (OPP-WH-IDLE" in item5
    assert "cites only failed verify results (ok:false)" in item5
    assert "analysis/verify/v0.json" in item5
    assert any("recorded as failed" in w and "v0.json" in w for w in data["warnings"])


def test_item5_failed_verify_json_does_not_count_toward_min(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "analysis" / "backlog.json").unlink()  # min defaults to 8; exactly 8 pairs exist
    _failed_verify(rd / "analysis" / "verify" / "v7.json")
    data = _check_data(rd, capsys)
    item5 = next(f["reason"] for f in data["failed"] if f["item"].startswith("5:"))
    assert "only 7 successful .sql/.json pair(s); need >= 8" in item5
    assert "1 ok:false result(s) do not count" in item5


def test_item5_passes_when_a_failed_file_has_a_successful_sibling_citation(tmp_path, capsys):
    rd = _make_run(tmp_path)
    bl_path = rd / "analysis" / "backlog.json"
    bl = json.loads(bl_path.read_text())
    bl["items"][0]["evidence"] = ["analysis/verify/v0.json", "analysis/verify/v2.json"]
    bl_path.write_text(json.dumps(bl))
    _failed_verify(rd / "analysis" / "verify" / "v0.json")
    data = _check_data(rd, capsys)
    assert any(p.startswith("5:") for p in data["passed"])
    assert any("recorded as failed" in w for w in data["warnings"])


# ---------------------------------------------------------------------------
# Item 6: backlog.json schema
# ---------------------------------------------------------------------------


def test_item6_fail_no_backlog(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "analysis" / "backlog.json").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("6:" in i for i in item_ids)


def test_item6_fail_bad_id_pattern(tmp_path, capsys):
    rd = _make_run(tmp_path)
    bl = json.loads((rd / "analysis" / "backlog.json").read_text())
    bl["items"][0]["id"] = "bad-id"
    (rd / "analysis" / "backlog.json").write_text(json.dumps(bl))
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item6 = next((v for k, v in failed.items() if k.startswith("6:")), None)
    assert item6 is not None
    assert "bad-id" in item6


def test_item6_fail_bad_tier(tmp_path, capsys):
    rd = _make_run(tmp_path)
    bl = json.loads((rd / "analysis" / "backlog.json").read_text())
    bl["items"][0]["tier"] = "high"  # invalid
    (rd / "analysis" / "backlog.json").write_text(json.dumps(bl))
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item6 = next((v for k, v in failed.items() if k.startswith("6:")), None)
    assert item6 is not None


def test_item6_fail_confidence_out_of_range(tmp_path, capsys):
    rd = _make_run(tmp_path)
    bl = json.loads((rd / "analysis" / "backlog.json").read_text())
    bl["items"][0]["confidence"] = 11  # > 10
    (rd / "analysis" / "backlog.json").write_text(json.dumps(bl))
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item6 = next((v for k, v in failed.items() if k.startswith("6:")), None)
    assert item6 is not None
    assert "confidence" in item6


def test_item6_fail_bad_sizing_kind(tmp_path, capsys):
    rd = _make_run(tmp_path)
    bl = json.loads((rd / "analysis" / "backlog.json").read_text())
    bl["items"][0]["sizing"]["kind"] = "unknown_kind"
    (rd / "analysis" / "backlog.json").write_text(json.dumps(bl))
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1


def test_item6_fail_act_now_no_verify_evidence(tmp_path, capsys):
    rd = _make_run(tmp_path)
    bl = json.loads((rd / "analysis" / "backlog.json").read_text())
    bl["items"][0]["evidence"] = []  # act_now needs >=1 verify file ref
    (rd / "analysis" / "backlog.json").write_text(json.dumps(bl))
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item6 = next((v for k, v in failed.items() if k.startswith("6:")), None)
    assert item6 is not None
    assert "evidence" in item6.lower()


# ---------------------------------------------------------------------------
# Item 7: analysis/action-plan.md
# ---------------------------------------------------------------------------


def test_item7_fail_no_action_plan(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "analysis" / "action-plan.md").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("7:" in i for i in item_ids)


# ---------------------------------------------------------------------------
# Item 8: analysis/technical-review.md with ## Humanize
# ---------------------------------------------------------------------------


def test_item8_fail_no_technical_review(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "analysis" / "technical-review.md").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("8:" in i for i in item_ids)


def test_item8_fail_no_humanize_section(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "analysis" / "technical-review.md").write_text("# Technical review\n\n## Findings\nNone.\n")
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item8 = next((v for k, v in failed.items() if k.startswith("8:")), None)
    assert item8 is not None
    assert "Humanize" in item8


# ---------------------------------------------------------------------------
# Item 9: required deliverables
# ---------------------------------------------------------------------------


def test_item9_fail_missing_exec_summary(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "deliverables" / "exec-summary.md").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item9 = next((v for k, v in failed.items() if k.startswith("9:")), None)
    assert item9 is not None
    assert "exec-summary.md" in item9


# ---------------------------------------------------------------------------
# Item 10: notebooks per act_now/investigate item
# ---------------------------------------------------------------------------


def test_item10_fail_missing_notebook(tmp_path, capsys):
    rd = _make_run(tmp_path)
    # Remove notebook referenced by the act_now item
    (rd / "deliverables" / "notebooks" / "nb-0.py").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item10 = next((v for k, v in failed.items() if k.startswith("10:")), None)
    assert item10 is not None
    assert "nb-0.py" in item10


def test_item10_fail_null_notebook_for_act_now(tmp_path, capsys):
    rd = _make_run(tmp_path)
    bl = json.loads((rd / "analysis" / "backlog.json").read_text())
    bl["items"][0]["notebook"] = None  # act_now with null notebook
    (rd / "analysis" / "backlog.json").write_text(json.dumps(bl))
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item10 = next((v for k, v in failed.items() if k.startswith("10:")), None)
    assert item10 is not None


# ---------------------------------------------------------------------------
# Item 11: deliverables/charts/ >= 1 png
# ---------------------------------------------------------------------------


def test_item11_fail_no_charts(tmp_path, capsys):
    rd = _make_run(tmp_path)
    for f in (rd / "deliverables" / "charts").glob("*.png"):
        f.unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert any("11:" in i for i in item_ids)


def test_item1_fail_empty_recur_section(tmp_path, capsys):
    rd = _make_run(tmp_path)
    # ## Recur has no body; ## Delivery has valid content so the Delivery check passes first
    (rd / "README.md").write_text(
        "# Run\n\n## Recur\n\n## Delivery\ndeliverables/exec-summary.md: local: not uploaded\n"
    )
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed_items = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item1 = next((v for k, v in failed_items.items() if k.startswith("1:")), None)
    assert item1 is not None
    assert "empty" in item1


# ---------------------------------------------------------------------------
# Item 1: ## Delivery content enforcement (glm #1)
# ---------------------------------------------------------------------------


def test_item1_fail_delivery_placeholder_filled_at_delivery(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "README.md").write_text(
        "# Run\n\n## Delivery\n(Filled at delivery)\n\n## Recur\nBaseline run.\n"
    )
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed_items = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item1 = next((v for k, v in failed_items.items() if k.startswith("1:")), None)
    assert item1 is not None
    assert "placeholder" in item1.lower()


def test_item1_fail_delivery_tbd(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "README.md").write_text("# Run\n\n## Delivery\nTBD\n\n## Recur\nBaseline run.\n")
    code, data = _check(rd, capsys)
    assert code == 1
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    item1 = next((v for k, v in failed.items() if k.startswith("1:")), None)
    assert item1 is not None
    assert "placeholder" in item1.lower()


def test_item1_fail_delivery_pending(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "README.md").write_text(
        "# Run\n\n## Delivery\npending\n\n## Recur\nBaseline run.\n"
    )
    code, data = _check(rd, capsys)
    assert code == 1
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    item1 = next((v for k, v in failed.items() if k.startswith("1:")), None)
    assert item1 is not None
    assert "placeholder" in item1.lower()


def test_item1_fail_delivery_no_artifact_entry(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "README.md").write_text(
        "# Run\n\n## Delivery\nSome generic text with no artifact.\n\n## Recur\nBaseline.\n"
    )
    code, data = _check(rd, capsys)
    assert code == 1
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    item1 = next((v for k, v in failed.items() if k.startswith("1:")), None)
    assert item1 is not None
    assert "artifact" in item1.lower()


@pytest.mark.parametrize("delivery_line,desc", [
    ("deliverables/exec-summary.md: local: not uploaded", "deliverables/ path"),
    ("exec-summary → https://docs.google.com/document/example/edit", "https URL"),
    ("exec-summary: local: no Google Docs MCP", "local: outcome"),
    ("exec-summary: not delivered: host has no MCP tools", "not delivered: outcome"),
    (
        "- [Executive summary](deliverables/exec-summary.clean.md) - local: no MCP.",
        "markdown link with local:",
    ),
])
def test_item1_pass_delivery_with_artifact_entry(tmp_path, capsys, delivery_line, desc):
    rd = _make_run(tmp_path)
    (rd / "README.md").write_text(
        f"# Run\n\n## Delivery\n{delivery_line}\n\n## Recur\nBaseline run.\n"
    )
    code, data = _check(rd, capsys)
    assert code == 0, f"Expected pass for {desc}: {data['failed']}"


# ---------------------------------------------------------------------------
# Item 1: --out FILE appears in run check --help (opus #5)
# ---------------------------------------------------------------------------


def test_run_check_help_lists_out_flag(capsys):
    from starboard_skills.helpers.__main__ import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "check", "--help"])
    out = capsys.readouterr().out
    assert "--out FILE" in out


# ---------------------------------------------------------------------------
# Item 5 + 10: zero Act-now is legitimate
# ---------------------------------------------------------------------------


def test_zero_act_now_items_passes_items_5_and_10(tmp_path, capsys):
    """A backlog with 0 act_now/investigate items is legitimate — items 5 and 10 must not
    assume ≥1 act_now item."""
    rd = _make_run(tmp_path)
    bl = json.loads((rd / "analysis" / "backlog.json").read_text())
    # Downgrade every act_now/investigate to not_now; remove evidence/notebook requirements
    for item in bl["items"]:
        if item.get("tier") in ("act_now", "investigate"):
            item["tier"] = "not_now"
            item["notebook"] = None
            item["evidence"] = []
    (rd / "analysis" / "backlog.json").write_text(json.dumps(bl))
    code, data = _check(rd, capsys)
    assert code == 0, data["failed"]
    assert any(p.startswith("5:") for p in data["passed"])
    assert any(p.startswith("10:") for p in data["passed"])


@pytest.mark.parametrize("internal", [False, True])
def test_item13_fail_no_findings_manifest(tmp_path, capsys, internal):
    rd = _make_run(tmp_path, internal=internal)
    (rd / "findings-manifest.json").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=internal, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    item_ids = [f["item"] for f in out["data"]["failed"]]
    assert item_ids == ["13:findings-manifest.json"]


# ---------------------------------------------------------------------------
# Item 12: --internal clean siblings
# ---------------------------------------------------------------------------


def test_item12_pass_when_not_internal(tmp_path, capsys):
    """Item 12 is vacuously pass when --internal is not set."""
    rd = _make_run(tmp_path)  # no clean files
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    passed_items = out["data"]["passed"]
    assert any("12:" in i for i in passed_items)


def test_item12_fail_missing_clean_md(tmp_path, capsys):
    rd = _make_run(tmp_path, internal=True)
    # Remove one clean sibling
    (rd / "deliverables" / "evidence-pack.clean.md").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=True, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item12 = next((v for k, v in failed.items() if k.startswith("12:")), None)
    assert item12 is not None
    assert "evidence-pack.md" in item12


def test_item12_fail_missing_clean_notebook(tmp_path, capsys):
    rd = _make_run(tmp_path, internal=True)
    # Remove one notebook clean sibling
    (rd / "deliverables" / "notebooks" / "nb-0.clean.py").unlink()
    args = SimpleNamespace(run_dir=str(rd), internal=True, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    failed = {f["item"]: f["reason"] for f in out["data"]["failed"]}
    item12 = next((v for k, v in failed.items() if k.startswith("12:")), None)
    assert item12 is not None
    assert "nb-0.py" in item12


# ---------------------------------------------------------------------------
# _validate_backlog unit tests
# ---------------------------------------------------------------------------


def test_validate_backlog_ok(tmp_path):
    verify = tmp_path / "analysis" / "verify"
    verify.mkdir(parents=True)
    (verify / "v0.json").write_text("{}")

    bl = {
        "workspace_id": "12345",
        "generated_at": "2026-10-01T00:00:00Z",
        "facts_window": {"start": "2026-09-01", "end": "2026-09-30"},
        "items": [
            {
                "id": "OPP-WH-IDLE",
                "target": "warehouse:abc123",
                "title": "Idle warehouses",
                "tier": "act_now",
                "confidence": 8,
                "sizing": {"kind": "bounded_dbu", "value": 1000, "unit": "DBU", "formula": "X"},
                "evidence": ["analysis/verify/v0.json"],
                "lever": "auto_stop_mins = 10",
                "notebook": None,  # notebook check done separately in item 10
            }
        ],
    }
    # Need a notebook for act_now — add it
    nb_dir = tmp_path / "deliverables" / "notebooks"
    nb_dir.mkdir(parents=True)
    (nb_dir / "nb.py").write_text("")
    bl["items"][0]["notebook"] = "deliverables/notebooks/nb.py"

    errs = _validate_backlog(bl, tmp_path)
    assert errs == []


def test_validate_backlog_bad_confidence_float(tmp_path):
    bl = {
        "workspace_id": "x",
        "generated_at": "2026-01-01",
        "facts_window": {"start": "a", "end": "b"},
        "items": [
            {
                "id": "OPP-WH-IDLE",
                "title": "T",
                "tier": "not_now",
                "confidence": 7.5,  # float, not int
                "sizing": {"kind": "none", "value": None, "unit": None, "formula": "n/a"},
                "evidence": [],
                "lever": "x",
                "notebook": None,
            }
        ],
    }
    errs = _validate_backlog(bl, tmp_path)
    assert any("confidence" in e for e in errs)


# ---------------------------------------------------------------------------
# _check_clean_siblings unit tests
# ---------------------------------------------------------------------------


def test_check_clean_siblings_all_present(tmp_path):
    deliv = tmp_path / "deliverables"
    deliv.mkdir()
    for name in ("exec-summary.md", "evidence-pack.md"):
        (deliv / name).write_text("")
        (deliv / f"{Path(name).stem}.clean.md").write_text("")
    assert _check_clean_siblings(tmp_path) == []


def test_check_clean_siblings_doc_md_skipped(tmp_path):
    """action-plan.doc.md should NOT require a clean sibling."""
    deliv = tmp_path / "deliverables"
    deliv.mkdir()
    (deliv / "action-plan.doc.md").write_text("")
    # No clean file for .doc.md — should be fine
    errs = _check_clean_siblings(tmp_path)
    assert not any("action-plan.doc" in e for e in errs)


def test_check_clean_siblings_missing_notebook(tmp_path):
    deliv = tmp_path / "deliverables"
    nb_dir = deliv / "notebooks"
    nb_dir.mkdir(parents=True)
    (nb_dir / "foo.py").write_text("")
    # No clean py file
    errs = _check_clean_siblings(tmp_path)
    assert any("foo.py" in e for e in errs)


# ---------------------------------------------------------------------------
# Shared helpers for the round-3 items (2 path, 6 sizing/cut, 14, 15, 16)
# ---------------------------------------------------------------------------


def _check(rd: Path, capsys, *, internal: bool = False) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as exc:
        cmd_check(SimpleNamespace(run_dir=str(rd), internal=internal, format="json"))
    return exc.value.code, json.loads(capsys.readouterr().out)["data"]


def _failed(data: dict) -> dict[str, str]:
    return {f["item"].split(":", 1)[0]: f["reason"] for f in data["failed"]}


def _rewrite_backlog(rd: Path, **changes) -> None:
    p = rd / "analysis" / "backlog.json"
    bl = json.loads(p.read_text())
    bl.update(changes)
    p.write_text(json.dumps(bl))


def _write_discovery(rd: Path, facts: dict, results: list[dict]) -> None:
    (rd / "discovery.json").write_text(
        json.dumps({"ok": True, "data": {"facts": facts, "packs": [{"pack": "p", "results": results}]}})
    )


# D1 — discovery envelope under discovery/


def test_item2_accepts_discovery_out_dir_location(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "discovery" / "discovery.json").write_text((rd / "discovery.json").read_text())
    (rd / "discovery.json").unlink()
    code, data = _check(rd, capsys)
    assert code == 0, data["failed"]
    assert "2:discovery.json has data.facts" in data["passed"]


def test_item2_reports_both_locations_when_absent(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "discovery.json").unlink()
    _, data = _check(rd, capsys)
    assert "discovery/discovery.json" in _failed(data)["2"]


# A2 — sizing.value number|null


def test_item6_fail_string_sizing_value_names_id(tmp_path, capsys):
    rd = _make_run(tmp_path)
    bl = json.loads((rd / "analysis" / "backlog.json").read_text())
    bl["items"][2]["sizing"] = {"kind": "bounded_dbu", "value": "4,819.5 DBU", "unit": None, "formula": "x"}
    _rewrite_backlog(rd, items=bl["items"])
    code, data = _check(rd, capsys)
    assert code == 1
    reason = _failed(data)["6"]
    assert "OPP-PO" in reason and "sizing.value must be a number or null" in reason


def test_validate_backlog_numeric_value_and_unit_ok(tmp_path):
    item = {
        "id": "OPP-PO", "target": "workspace", "title": "t", "tier": "not_now", "confidence": 5,
        "sizing": {"kind": "bounded_dbu", "value": 12800.83, "unit": "DBU", "formula": "sum"},
        "evidence": [], "lever": "x", "notebook": None,
    }
    bl = {"workspace_id": "1", "generated_at": "t", "facts_window": {"start": "a", "end": "b"}, "items": [item]}
    assert _validate_backlog(bl, tmp_path) == []
    item["sizing"]["unit"] = 3
    assert any("sizing.unit" in e for e in _validate_backlog(bl, tmp_path))
    item["sizing"]["unit"] = "DBU"
    item["sizing"]["value"] = True
    assert any("sizing.value" in e for e in _validate_backlog(bl, tmp_path))


def test_validate_backlog_cut_entries(tmp_path):
    bl = {"workspace_id": "1", "generated_at": "t", "facts_window": {"start": "a", "end": "b"}, "items": []}
    assert _validate_backlog(bl, tmp_path) == []  # no cut key → empty list
    bl["cut"] = [{"id": "OPP-WH-IDLE", "rule": "disqualifier", "reason": "serverless only"}]
    assert _validate_backlog(bl, tmp_path) == []
    bl["cut"] = [{"id": "WH-IDLE", "reason": ""}, "x"]
    errs = _validate_backlog(bl, tmp_path)
    assert any("cut[0]: id" in e for e in errs)
    assert any("cut[0] (WH-IDLE): reason" in e for e in errs)
    assert any("cut[1]" in e for e in errs)
    bl["cut"] = {"id": "OPP-PO"}
    assert any("cut must be a list" in e for e in _validate_backlog(bl, tmp_path))


# A1 — catalog coverage (item 14)

_FIRING_FACTS = {
    "window": {"start": "2026-09-01", "end": "2026-09-30"},
    "step_change": {"date": "2026-09-14", "lift_daily_dbus": 10.0},
    "total": {"dbus": 1000.0},
    "warehouses": {"classic_dbus": 5.0},  # 0.5% < 1% → OPP-WH-CLASSIC-TO-SERVERLESS does not fire
}
_FIRING_RESULTS = [
    {"query_id": "W-W01", "rows": [
        {"queued_query_pct": "45.40", "avg_capacity_wait_secs": "67.6", "total_queries": "145844"},
    ]},
    {"query_id": "W-W02", "rows": [{"auto_stop_waste_pct": "40", "est_idle_dbus": None}]},  # serverless
    {"query_id": "C-J09", "rows": [{"task_key": "wait_for_vote_processing_readiness"}]},
]


def test_fired_triggers_reads_string_cells():
    from starboard_skills.helpers.run import _fired_triggers

    doc = {"data": {"facts": _FIRING_FACTS, "packs": [{"results": _FIRING_RESULTS}]}}
    ids = [i for i, _ in _fired_triggers(doc)]
    assert ids == ["OPP-WH-QUEUE", "OPP-JOB-WAIT-TASK", "OPP-STEP-CHANGE"]
    assert _fired_triggers({"data": {"facts": {}, "packs": []}}) == []
    assert _fired_triggers({}) == []


def test_item14_fails_naming_uncovered_fired_ids(tmp_path, capsys):
    rd = _make_run(tmp_path)  # backlog carries OPP-WH-IDLE, OPP-WH-QUEUE, OPP-PO
    _write_discovery(rd, _FIRING_FACTS, _FIRING_RESULTS)
    code, data = _check(rd, capsys)
    assert code == 1
    reason = _failed(data)["14"]
    assert "OPP-STEP-CHANGE" in reason and "OPP-JOB-WAIT-TASK" in reason
    assert "OPP-WH-QUEUE" not in reason  # carried in items


def test_item14_passes_when_fired_ids_are_cut(tmp_path, capsys):
    rd = _make_run(tmp_path)
    _write_discovery(rd, _FIRING_FACTS, _FIRING_RESULTS)
    _failed_verify(rd / "analysis" / "verify" / "vt-step-change.json")  # attempted, timed out
    _rewrite_backlog(rd, cut=[
        {"id": "OPP-STEP-CHANGE", "rule": "no_evidence", "reason": "vt-step-change timed out"},
        {"id": "OPP-JOB-WAIT-TASK", "rule": "disqualifier", "reason": "external dependency has no trigger"},
    ])
    code, data = _check(rd, capsys)
    assert code == 0, data["failed"]


def test_item14_fails_without_discovery(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "discovery.json").unlink()
    _, data = _check(rd, capsys)
    assert "cannot verify" in _failed(data)["14"]


# B2 — recur outcome (item 15)


def test_item15_fail_no_recur_result(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "analysis" / "recur-result.json").unlink()
    code, data = _check(rd, capsys)
    assert code == 1
    assert list(_failed(data)) == ["15"]
    assert "--baseline" in _failed(data)["15"]


def test_item15_fail_recur_not_ok(tmp_path, capsys):
    rd = _make_run(tmp_path)
    p = rd / "analysis" / "recur-result.json"
    rr = json.loads(p.read_text())
    rr.update(ok=False, baseline=False, errors=["--prior has no findings-manifest.json"])
    p.write_text(json.dumps(rr))
    _, data = _check(rd, capsys)
    assert "--prior has no findings-manifest.json" in _failed(data)["15"]


def test_item15_fail_history_lacks_this_run(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (tmp_path / "trend" / "history.json").write_text(json.dumps([{"run_date": "2026-09-01"}]))
    _, data = _check(rd, capsys)
    assert "no trend history entry" in _failed(data)["15"]


# D5 — sanitizer findings in .clean prose (item 16, --internal)


def test_item16_fallback_fails_prose_warns_code(tmp_path, capsys, monkeypatch):
    from starboard_skills.helpers import run as run_mod

    monkeypatch.setattr(run_mod, "_internal_sanitizer_available", lambda: False)
    rd = _make_run(tmp_path, internal=True)
    (rd / "deliverables" / "evidence-pack.clean.md").write_text("Source: scoped telemetry mirror\n")
    (rd / "deliverables" / "notebooks" / "nb-0.clean.py").write_text("# mirror verify\n")
    code, data = _check(rd, capsys, internal=True)
    assert code == 1
    reason = _failed(data)["16"]
    assert "deliverables/evidence-pack.clean.md: mirror" in reason
    assert "nb-0" not in reason
    assert any("nb-0.clean.py" in w and "warn-only" in w for w in data["warnings"])
    assert any("not installed" in w for w in data["warnings"])


def test_item16_vacuous_when_not_internal(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "deliverables" / "evidence-pack.clean.md").write_text("mirror\n")
    code, data = _check(rd, capsys)
    assert code == 0, data["failed"]


def test_item16_uses_internal_sanitizer_when_installed(tmp_path, capsys):
    pytest.importorskip("starboard_internal")
    rd = _make_run(tmp_path, internal=True)
    code, data = _check(rd, capsys, internal=True)
    assert code == 0, data["failed"]
    (rd / "deliverables" / "exec-summary.clean.md").write_text("Numbers from the telemetry mirror.\n")
    code, data = _check(rd, capsys, internal=True)
    assert code == 1
    assert "deliverables/exec-summary.clean.md: mirror" in _failed(data)["16"]


# ---------------------------------------------------------------------------
# Round 4 — C3 canonical perf metrics, C4 cut rule, C5 target, A1 degraded review
# ---------------------------------------------------------------------------

_CATALOG = (
    Path(__file__).parents[2]
    / "skills" / "starboard" / "starboard-action-plan" / "references" / "opportunity-catalog.md"
)


def _catalog_perf_metric_table() -> dict[str, tuple[str, str]]:
    text = _CATALOG.read_text()
    block = text.split("<!-- canonical-perf-metrics:start -->", 1)[1].split("<!-- canonical-perf-metrics:end -->", 1)[0]
    rows: dict[str, tuple[str, str]] = {}
    for line in block.strip().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or not cells[0].startswith("OPP-"):
            continue  # header / separator
        rows[cells[0]] = (cells[1], cells[2])
    return rows


def test_catalog_perf_metric_table_matches_run_constant():
    from starboard_skills.helpers.run import _PERF_METRICS

    table = _catalog_perf_metric_table()
    assert table, "catalog canonical-perf-metrics table not found"
    assert table == _PERF_METRICS


def _bl(items: list[dict], cut: list[dict] | None = None) -> dict:
    doc: dict = {"workspace_id": "1", "generated_at": "t", "facts_window": {"start": "a", "end": "b"}, "items": items}
    if cut is not None:
        doc["cut"] = cut
    return doc


def _perf_item(opp_id: str, metric, unit, target: str = "job:1") -> dict:
    return {
        "id": opp_id, "target": target, "title": "t", "tier": "not_now", "confidence": 5,
        "sizing": {"kind": "perf_metric", "metric": metric, "value": 80.0, "unit": unit, "formula": "f"},
        "evidence": [], "lever": "x", "notebook": None,
    }


def test_perf_metric_must_match_canonical(tmp_path):
    ok = _perf_item("OPP-JOB-OVERLAP", "pct_runs_started_while_running", "%")
    assert _validate_backlog(_bl([ok]), tmp_path) == []
    wrong_unit = _perf_item("OPP-JOB-OVERLAP", "pct_runs_started_while_running", "CRON runs started while running")
    errs = _validate_backlog(_bl([wrong_unit]), tmp_path)
    assert any("OPP-JOB-OVERLAP" in e and "pct_runs_started_while_running" in e for e in errs)
    no_metric = _perf_item("OPP-WH-QUEUE", None, "%", target="warehouse:w1")
    assert any("peak_daily_queued_pct" in e for e in _validate_backlog(_bl([no_metric]), tmp_path))


def test_perf_metric_on_id_without_canonical_fails_except_other(tmp_path):
    bad = _perf_item("OPP-JOB-FAILURE", "failure_rate_pct", "%", target="workspace")
    assert any("defines no perf_metric" in e for e in _validate_backlog(_bl([bad]), tmp_path))
    other = _perf_item("OPP-OTHER", "stale_table_count", "tables", target="workspace")
    assert _validate_backlog(_bl([other]), tmp_path) == []
    other["sizing"]["metric"] = ""
    assert any("OPP-OTHER" in e for e in _validate_backlog(_bl([other]), tmp_path))


def test_target_required_and_unique_per_id(tmp_path):
    a = _perf_item("OPP-JOB-OVERLAP", "pct_runs_started_while_running", "%", target="job:1")
    b = dict(a, target="job:2")
    assert _validate_backlog(_bl([a, b]), tmp_path) == []
    dup = dict(a)
    errs = _validate_backlog(_bl([a, dup]), tmp_path)
    assert any("duplicate (id, target)" in e for e in errs)
    missing = {k: v for k, v in a.items() if k != "target"}
    assert any("target is required" in e for e in _validate_backlog(_bl([missing]), tmp_path))
    prose = dict(a, target="Job 1 — Agentic Leaderboard Processing")
    assert any("target is required" in e for e in _validate_backlog(_bl([prose]), tmp_path))


def test_cut_rule_required(tmp_path):
    errs = _validate_backlog(_bl([], [{"id": "OPP-WH-IDLE", "reason": "serverless"}]), tmp_path)
    assert any("cut[0] (OPP-WH-IDLE): rule" in e for e in errs)
    errs = _validate_backlog(_bl([], [{"id": "OPP-WH-IDLE", "rule": "below_priority", "reason": "small"}]), tmp_path)
    assert any("rule must be one of" in e for e in errs)
    (tmp_path / "analysis" / "verify").mkdir(parents=True)
    (tmp_path / "analysis" / "verify" / "vt-product-totals.json").write_text("{}")  # no_evidence needs an attempt
    for rule in ("disqualifier", "no_evidence", "duplicate"):
        assert _validate_backlog(_bl([], [{"id": "OPP-PO", "rule": rule, "reason": "r"}]), tmp_path) == []
    bad_target = [{"id": "OPP-PO", "rule": "duplicate", "reason": "r", "target": "some prose"}]
    assert any("target, when given" in e for e in _validate_backlog(_bl([], bad_target), tmp_path))


def test_not_now_without_value_warns_only(tmp_path):
    item = {
        "id": "OPP-CLUSTER-RIGHTSIZE", "target": "cluster:c1", "title": "t", "tier": "not_now", "confidence": 4,
        "sizing": {"kind": "pilot", "value": None, "unit": None, "formula": "pilot"},
        "evidence": [], "lever": "x", "notebook": None,
    }
    warnings: list[str] = []
    assert _validate_backlog(_bl([item]), tmp_path, warnings) == []
    assert any("OPP-CLUSTER-RIGHTSIZE" in w and "cut" in w for w in warnings)


def test_degraded_review_warns_not_fails(tmp_path, capsys):
    rd = _make_run(tmp_path)
    (rd / "findings-manifest.json").write_text(json.dumps({
        "run_date": "2026-10-01", "findings": [], "degraded": True,
        "unavailable_queries": ["C-Q01", "W-W05"], "unavailable_domains": ["queries", "warehouses"],
    }))
    code, data = _check(rd, capsys)
    assert code == 0, data["failed"]
    assert any("review degraded" in w and "queries, warehouses" in w and "2 evidence" in w for w in data["warnings"])


def test_manifest_without_degraded_keys_no_warning(tmp_path, capsys):
    rd = _make_run(tmp_path)
    code, data = _check(rd, capsys)
    assert code == 0
    assert not any("review degraded" in w for w in data["warnings"])


def test_degraded_warning_falls_back_to_saved_review_domain_reports(tmp_path, capsys):
    rd = _make_run(tmp_path)  # manifest predates the degraded keys
    (rd / "analysis" / "review.json").write_text(json.dumps({"data": {"degraded": True, "domain_reports": [
        {"domain": "jobs", "degraded": True, "degraded_reason": "evidence queries unavailable: C-J04"},
        {"domain": "warehouse", "degraded": True, "degraded_reason": "evidence queries unavailable: W-W01, W-W02"},
        {"domain": "sql", "degraded": False},
    ]}}))
    code, data = _check(rd, capsys)
    assert code == 0
    assert any("domains jobs, warehouse; 3 evidence" in w for w in data["warnings"])


# ---------------------------------------------------------------------------
# Round 6 — no_evidence cut needs an attempted verify; target kind per id; --out
# ---------------------------------------------------------------------------


def _catalog_entry_rows(field: str) -> dict[str, str]:
    """``{catalog id: cell}`` for every ``| <field> | cell |`` row under a ``### OPP-…`` heading."""
    rows: dict[str, str] = {}
    current: str | None = None
    for line in _CATALOG.read_text().splitlines():
        if line.startswith("#"):
            m = re.match(r"^###\s+(OPP-[A-Z0-9-]+)", line)
            current = m.group(1) if m else None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if current and len(cells) >= 2 and cells[0] == field:
            rows[current] = cells[1]
    return rows


def _catalog_verify_templates() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for opp_id, cell in _catalog_entry_rows("Verify").items():
        cell = re.sub(r"\([^)]*\)", "", cell)  # drop parenthetical notes (they may hold commas)
        ids = tuple(dict.fromkeys(m for part in cell.split(",") for m in re.findall(r"vt-[a-z0-9-]+", part)))
        if ids:
            out[opp_id] = ids
    return out


def test_catalog_verify_rows_match_run_constant():
    from starboard_skills.helpers.run import _VERIFY_TEMPLATES

    table = _catalog_verify_templates()
    assert table, "catalog | Verify | rows not found"
    assert table == _VERIFY_TEMPLATES


def test_catalog_target_kind_rows_match_run_constant():
    from starboard_skills.helpers.run import _TARGET_KINDS

    rows = _catalog_entry_rows("Target kind")
    assert rows, "catalog | Target kind | rows not found"
    table = {
        k: frozenset(p.strip().strip("`") for p in v.split(",") if p.strip())
        for k, v in rows.items()
        if k != "OPP-OTHER"
    }
    assert table == _TARGET_KINDS


def test_no_evidence_cut_requires_an_attempted_verify(tmp_path):
    cut = [{"id": "OPP-JOB-TIMEOUT", "target": "job:1", "rule": "no_evidence", "reason": "vt-job-run-tail not run"}]
    errs = _validate_backlog(_bl([], cut), tmp_path)
    assert any("cut[0] (OPP-JOB-TIMEOUT job:1)" in e and "vt-job-run-tail" in e for e in errs)
    verify = tmp_path / "analysis" / "verify"
    verify.mkdir(parents=True)
    (verify / "vt-job-run-tail.stdout").write_text("")  # not a result file
    assert _validate_backlog(_bl([], cut), tmp_path) != []
    _failed_verify(verify / "vt-job-run-tail-1.json")  # attempted; ok:false still counts
    assert _validate_backlog(_bl([], cut), tmp_path) == []
    # disqualifier / duplicate cuts, and ids with no verify templates, need no attempt file.
    other = [
        {"id": "OPP-WH-SCAN", "rule": "disqualifier", "reason": "r"},
        {"id": "OPP-OTHER", "rule": "no_evidence", "reason": "r"},
    ]
    assert _validate_backlog(_bl([], other), tmp_path / "empty") == []


def test_target_kind_must_be_allowed_for_id(tmp_path):
    ok = _perf_item("OPP-WH-QUEUE", "peak_daily_queued_pct", "%", target="warehouse:w1")
    assert _validate_backlog(_bl([ok]), tmp_path) == []
    wrong = _perf_item("OPP-WH-QUEUE", "peak_daily_queued_pct", "%", target="job:1")
    errs = _validate_backlog(_bl([wrong]), tmp_path)
    assert any("target kind 'job'" in e and "warehouse" in e for e in errs)
    ws = _perf_item("OPP-JOB-OVERLAP", "pct_runs_started_while_running", "%", target="workspace")
    assert any("target kind 'workspace'" in e for e in _validate_backlog(_bl([ws]), tmp_path))
    other = _perf_item("OPP-OTHER", "m", "u", target="schema:main.x")
    assert _validate_backlog(_bl([other]), tmp_path) == []


def test_run_check_out_writes_envelope_and_stdout(tmp_path, capsys):
    from starboard_skills.helpers.__main__ import main

    rd = _make_run(tmp_path)
    out = rd / "analysis" / "run-check.json"
    with pytest.raises(SystemExit) as exc:
        main(["run", "check", str(rd), "--out", str(out)])
    assert exc.value.code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["data"]["summary"]["all_passed"] is True
    assert json.loads(out.read_text()) == printed


def test_item1_readme_needs_no_run_check_section(tmp_path, capsys):
    rd = _make_run(tmp_path)
    assert "## Run check" not in (rd / "README.md").read_text()
    code, data = _check(rd, capsys)
    assert code == 0, data["failed"]


# ---------------------------------------------------------------------------
# Round 8 — confidence_breakdown, vacuous-pass guards, copy-pasteable perf_metric fragment
# ---------------------------------------------------------------------------


def test_perf_metric_error_prints_copy_pasteable_fragment(tmp_path):
    no_metric = _perf_item("OPP-WH-QUEUE", None, None, target="warehouse:w1")
    errs = _validate_backlog(_bl([no_metric]), tmp_path)
    assert any('{"metric": "peak_daily_queued_pct", "unit": "%"}' in e for e in errs), errs


def _inv_item(tmp_path: Path, **extra) -> dict:
    (tmp_path / "analysis" / "verify").mkdir(parents=True, exist_ok=True)
    (tmp_path / "analysis" / "verify" / "v.json").write_text("{}")
    (tmp_path / "nb.py").write_text("")
    item = {
        "id": "OPP-STEP-CHANGE", "target": "workspace", "title": "t", "tier": "investigate",
        "confidence": 6, "sizing": {"kind": "none", "value": None, "unit": None, "formula": "f"},
        "evidence": ["analysis/verify/v.json"], "lever": "x", "notebook": "nb.py",
    }
    item.update(extra)
    return item


def test_confidence_breakdown_absent_warns_only(tmp_path):
    warnings: list[str] = []
    assert _validate_backlog(_bl([_inv_item(tmp_path)]), tmp_path, warnings) == []
    assert any("lack confidence_breakdown" in w for w in warnings)


@pytest.mark.parametrize(
    "bd", ["V3 R2 A0 L0 S1 C0", {"V": 3, "R": 2, "A": 0, "L": 0, "S": 1, "C": 0},
           {"verified": 3, "reconciled": 2, "stable": 1}],
)
def test_confidence_breakdown_valid_forms(tmp_path, bd):
    warnings: list[str] = []
    item = _inv_item(tmp_path, confidence_breakdown=bd)
    assert _validate_backlog(_bl([item]), tmp_path, warnings) == []
    assert not any("confidence_breakdown" in w for w in warnings)


def test_confidence_breakdown_sum_mismatch_and_cap_fail(tmp_path):
    errs = _validate_backlog(_bl([_inv_item(tmp_path, confidence_breakdown="V3 R2 A2 L0 S1 C0")]), tmp_path)
    assert any("confidence 6 != confidence_breakdown sum 8" in e for e in errs)
    errs = _validate_backlog(_bl([_inv_item(tmp_path, confidence_breakdown={"V": 4, "R": 2})]), tmp_path)
    assert any("V=4" in e and "0..3" in e for e in errs)
    errs = _validate_backlog(_bl([_inv_item(tmp_path, confidence_breakdown={"bogus": 1})]), tmp_path)
    assert any("unknown component" in e for e in errs)


def test_confidence_breakdown_zero_sum_floors_at_one(tmp_path):
    item = _inv_item(tmp_path, confidence=1, confidence_breakdown="V0 R0 A0 L0 S0 C0")
    assert _validate_backlog(_bl([item]), tmp_path) == []


def test_item12_and_16_fail_without_deliverables_internal(tmp_path, capsys):
    import shutil

    rd = _make_run(tmp_path, internal=True)
    shutil.rmtree(rd / "deliverables")
    code, data = _check(rd, capsys, internal=True)
    failed = _failed(data)
    assert code == 1
    assert "see item 9" in failed["12"]
    assert "deliverables/ missing — see item 9" in failed["16"]


def test_item16_fails_when_no_clean_files_internal(tmp_path, capsys):
    rd = _make_run(tmp_path, internal=True)
    for p in (rd / "deliverables").rglob("*.clean.*"):
        p.unlink()
    code, data = _check(rd, capsys, internal=True)
    assert code == 1
    assert "deliverables/ missing — see item 9" in _failed(data)["16"]
