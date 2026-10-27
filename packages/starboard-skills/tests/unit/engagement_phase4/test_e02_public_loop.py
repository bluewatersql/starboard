"""E2 Scenario 2: the public customer-only loop (``public_local``; spec §H.2, D4-5, D4-13).

A public (overlay-off) ``health_check`` run with a LOCAL run authorization gets
the kernel records from ``run recur <run-dir> --workspace-root <case-root>``.
``health_report`` never passes vacuously: no body, or a body that omits an
unknown family, fails it. A troubleshooting run in a sibling task root opens a
case on the health finding; the second health run carries the same finding,
episode and action. No Drive call, no Salesforce call and no file outside the
case roots.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from . import _fixtures
from ._support import (
    HEALTH_READ,
    QUESTION,
    Ctx,
    Run,
    engagement_ok,
    failed_ids,
    finding,
    has,
    health_body,
    local_files,
    new_run,
    readme,
    records,
    run_check,
    run_recur,
    verify_slice,
    write,
    write_inputs,
)

pytestmark = pytest.mark.parametrize("mode", ["public_local"])


def _recurred(
    ctx: Ctx,
    *,
    facts: dict[str, Any],
    slices: tuple[tuple[tuple[str, str], list[dict[str, Any]], str], ...],
    baseline: bool,
) -> Run:
    """A public health_check run: route -> capture -> README -> ``run recur``."""
    run = new_run(ctx, task="health_check")
    assert run.source_mode == "customer_workspace"
    assert run.run_dir and run.run_dir.parts[-4:-1] == (
        "acme-corp",
        "health_check",
        "ws-123",
    )
    write_inputs(ctx, run, facts=facts, review=_fixtures.review_manifest())
    for window, rows, suffix in slices:
        verify_slice(ctx, run, window, rows, suffix=suffix)
    readme(ctx, run)
    code, data, raw = run_recur(ctx, run, baseline=baseline)
    assert code == 0, raw
    return run


def _first(ctx: Ctx) -> Run:
    return _recurred(
        ctx,
        facts=_fixtures.current_facts(),
        slices=(
            (_fixtures.S1, _fixtures.s1_rows(), "s1"),
            (_fixtures.S2, _fixtures.s2_rows(), "s2"),
        ),
        baseline=True,
    )


def _second(ctx: Ctx) -> Run:
    return _recurred(
        ctx,
        facts=_fixtures.recovery_facts(),
        slices=((_fixtures.RECOVERY, _fixtures.recovery_rows(), "next"),),
        baseline=False,
    )


def test_public_recur_writes_kernel_records_under_the_run_dir(ctx: Ctx) -> None:
    run = _first(ctx)
    for rel in (
        "analysis/health.json",
        "analysis/plays.json",
        "analysis/findings.json",
        "analysis/observations.json",
        "analysis/actions.json",
        "analysis/baseline-selection.json",
    ):
        assert has(ctx, run, rel), rel
    recs = records(ctx, run)
    assert recs.plays
    assert {f["finding_id"] for f in recs.findings} >= {_fixtures.finding_id_j42()}


def test_health_report_never_passes_vacuously(ctx: Ctx) -> None:
    run = _first(ctx)
    assert has(ctx, run, "analysis/health.json"), "public recur wrote no health.json"
    assert has(ctx, run, "analysis/plays.json")
    health = records(ctx, run).health
    unknown = [f["family"] for f in health["families"] if f["assessment"] == "unknown"]
    assert unknown, "the J-42 fixture leaves at least one family unknown"

    code, data, raw = run_check(ctx, run)
    assert code == 1, raw[:2000]
    assert "health_report" in failed_ids(data)

    write(ctx, run, {HEALTH_READ: health_body(health, omit=unknown[0])})
    code, data, raw = run_check(ctx, run)
    assert code == 1, raw[:2000]
    assert "health_report" in failed_ids(data)

    write(ctx, run, {HEALTH_READ: health_body(health)})
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == "health_check"
    assert data.get("profile_source") == "descriptor"
    assert failed_ids(data) == set(), raw[:2000]
    assert code == 0


def test_troubleshooting_run_in_a_sibling_task_root_opens_and_revises_the_case(
    ctx: Ctx,
) -> None:
    health_run = _first(ctx)
    fid = _fixtures.finding_id_j42()
    detected = finding(records(ctx, health_run), fid)

    trouble = new_run(ctx, task="troubleshooting", task_name="job-42")
    assert trouble.case_root and health_run.case_root
    assert trouble.case_root.parent.parent == health_run.case_root.parent.parent
    assert trouble.case_root != health_run.case_root
    opened = engagement_ok(
        ctx,
        trouble,
        "case",
        "open",
        *trouble.flags(),
        "--finding-id",
        fid,
        "--question",
        QUESTION,
    )
    assert opened["finding_id"] == fid
    assert opened["episode_id"] == detected["episode_id"]
    rel = verify_slice(ctx, trouble, _fixtures.S2, _fixtures.s2_rows(), suffix="s2")
    revised = engagement_ok(
        ctx,
        trouble,
        "case",
        "revise",
        *trouble.flags(),
        "--case-id",
        opened["case_id"],
        "--verify",
        rel,
    )
    assert revised["finding_id"] == fid
    assert revised["finding_revision"] == detected["revision"] + 1


def test_public_loop_carries_finding_episode_and_action_without_drive(
    ctx: Ctx, drive_calls: list[str]
) -> None:
    first = _first(ctx)
    recs1 = records(ctx, first)
    fid = _fixtures.finding_id_j42()
    detected = finding(recs1, fid)
    action = next(a for a in recs1.actions if a["finding_id"] == fid)
    write(ctx, first, {HEALTH_READ: health_body(recs1.health)})

    second = _second(ctx)
    recs2 = records(ctx, second)
    carried = finding(recs2, fid)
    assert carried["finding_id"] == detected["finding_id"]
    assert carried["episode_id"] == detected["episode_id"]
    assert action["action_id"] in [
        a["action_id"] for a in recs2.actions if a["finding_id"] == fid
    ]

    # The host-visible report's ``$`` lines carry the list-price label.
    assert first.run_dir
    body = (first.run_dir / HEALTH_READ).read_text()
    dollar_lines = [ln for ln in body.splitlines() if "$" in ln]
    assert dollar_lines
    assert all("list-price DBU estimate" in ln for ln in dollar_lines)

    # No Drive storage entry point and no ticket resolver call.
    assert drive_calls == []
    # Every file the loop wrote is under a case root (or the test's own inputs).
    roots = [r for r in (first.case_root, second.case_root) if r]
    sandbox_roots = [ctx.tmp_path / n for n in ("home", "cwd", "tmp")]
    stray = [
        p
        for p in local_files(ctx.tmp_path)
        if not any(_under(p, r) for r in (*roots, *sandbox_roots))
    ]
    assert stray == []
    for root in sandbox_roots:
        assert local_files(root) == [], root


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
