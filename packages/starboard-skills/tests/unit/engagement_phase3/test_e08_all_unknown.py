"""E8: no evidence at all is ``insufficient_evidence`` with six acquisition requests (D3-7)."""

from __future__ import annotations

from typing import Any

from . import _j42
from ._support import (
    Ctx,
    Run,
    analyze,
    commit,
    engagement_ok,
    helper,
    new_run,
    records,
    sink_put,
    write_inputs,
)

REPORT = "deliverables/health-read.md"


def _all_unknown_run(ctx: Ctx) -> Run:
    run = new_run(ctx)
    write_inputs(ctx, run, facts=_j42.empty_facts(), review=_j42.degraded_manifest())
    analyze(ctx, run, _j42.CURRENT)
    return run


def test_all_unknown_is_insufficient_evidence(
    mode, capsys, store, sandbox, seams, tmp_path
) -> None:
    from starboard_core.engagement.catalog import SIX_FAMILIES

    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    recs = records(ctx, _all_unknown_run(ctx))
    health = recs.health
    assert health["verdict"] == "insufficient_evidence"
    assert health["assessed_count"] == 0
    assert health["top_concern_finding_ids"] == []

    families = {f["family"]: f for f in health["families"]}
    assert set(families) == set(SIX_FAMILIES)
    requests = [f["acquisition_request"] for f in families.values()]
    assert all(f["assessment"] == "unknown" for f in families.values())
    assert len([r for r in requests if r and r["command"]]) == 6

    assert [p for p in recs.plays if p["play_code"] != "acquire_family_evidence"] == []
    acquire = [p for p in recs.plays if p["play_code"] == "acquire_family_evidence"]
    assert len(acquire) == 6
    assert recs.actions == [] or all(
        a["play_id"] in {p["play_id"] for p in acquire} for a in recs.actions
    )


def _report(families: list[str], *, insufficient: bool) -> str:
    lines = ["# Workspace health read", ""]
    if insufficient:
        lines += ["Insufficient evidence", ""]
    lines += ["## Unknowns", "", *[f"- {name}: unknown" for name in families], ""]
    return "\n".join(lines)


def _health_item(ctx: Ctx, run: Run) -> tuple[int, dict[str, Any]]:
    assert run.rf
    code, env, raw = helper(ctx.capsys, "run", "check", "--run-folder", run.rf)
    data = env.get("data") or {}
    failed = {f["item"] for f in data.get("failed", [])}
    return code, {"failed": failed, "passed": set(data.get("passed", [])), "raw": raw}


def test_run_check_requires_the_insufficient_evidence_line(
    capsys, store, sandbox, seams, tmp_path
) -> None:
    from starboard_core.engagement.catalog import SIX_FAMILIES

    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, "drive_backed")
    run = _all_unknown_run(ctx)
    assert run.rf
    families = list(SIX_FAMILIES)

    for insufficient in (False, True):
        sink_put(store, run.rf, {REPORT: _report(families, insufficient=insufficient)})
        commit(ctx, run, "analysis")
        commit(ctx, run, "check")
        engagement_ok(
            ctx,
            run,
            "report",
            "--run-folder",
            run.rf,
            "--report-id",
            "health-read",
            "--audience",
            "internal",
            "--path",
            REPORT,
        )
        code, item = _health_item(ctx, run)
        if insufficient:
            assert "health_read" in item["passed"], item["raw"]
            assert "health_read" not in item["failed"]
        else:
            assert code == 1, item["raw"]
            assert "health_read" in item["failed"]

    # A report whose Unknowns section misses a family fails the item too.
    sink_put(store, run.rf, {REPORT: _report(families[1:], insufficient=True)})
    commit(ctx, run, "check")
    engagement_ok(
        ctx,
        run,
        "report",
        "--run-folder",
        run.rf,
        "--report-id",
        "health-read",
        "--audience",
        "internal",
        "--path",
        REPORT,
    )
    code, item = _health_item(ctx, run)
    assert code == 1 and "health_read" in item["failed"]
