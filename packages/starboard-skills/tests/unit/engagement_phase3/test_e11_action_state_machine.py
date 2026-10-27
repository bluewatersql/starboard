"""E11: the action state machine; attribution only after an accepted, executed action (D3-13)."""

from __future__ import annotations

from . import _j42
from ._support import (
    Ctx,
    baseline_run,
    commit,
    current_run,
    eng,
    engagement_ok,
    error_code,
    read_json,
    records,
    recovery_run,
)

ACTIONS = "analysis/actions.json"


def _proposed(ctx: Ctx):
    baseline_run(ctx)
    run = current_run(ctx, commit_it=False)
    fid = _j42.finding_id_j42()
    action = next(a for a in records(ctx, run).actions if a["finding_id"] == fid)
    assert action["acceptance_state"] == "pending"
    return run, action["action_id"]


def _action(ctx: Ctx, run, action_id: str) -> dict:
    return next(a for a in read_json(ctx, run, ACTIONS) if a["action_id"] == action_id)


def test_execute_before_accept_is_refused(
    mode, capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    run, action_id = _proposed(ctx)
    code, env, raw = eng(
        capsys,
        "action",
        "execute",
        *run.flags(),
        "--action-id",
        action_id,
        "--executed-at",
        "2026-10-07",
    )
    assert code == 2, raw
    assert error_code(env) == "INVALID_TRANSITION"
    action = _action(ctx, run, action_id)
    assert action["execution_state"] == "not_started"
    assert action["acceptance_state"] == "pending"


def test_accepted_executed_improved_is_consistent(
    mode, capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    run, action_id = _proposed(ctx)
    engagement_ok(
        ctx,
        run,
        "action",
        "accept",
        *run.flags(),
        "--action-id",
        action_id,
        "--note",
        "owner agreed in session",
    )
    engagement_ok(
        ctx,
        run,
        "action",
        "execute",
        *run.flags(),
        "--action-id",
        action_id,
        "--executed-at",
        "2026-10-07",
    )
    action = _action(ctx, run, action_id)
    assert action["acceptance_state"] == "accepted"
    assert action["execution_state"] == "executed"
    assert action["executed_at"] == "2026-10-07"
    assert [e["kind"] for e in action["events"]] == ["proposed", "accepted", "executed"]
    assert [e["recorded_by"] for e in action["events"]][0] == "rule"
    commit(ctx, run)

    nxt = recovery_run(ctx)
    action = _action(ctx, nxt, action_id)
    assert action["verification_window_start"] > action["executed_at"]
    assert action["outcome_state"] == "improved"
    assert action["attribution"] == "consistent_with_action"
    assert action["acceptance_state"] == "accepted"
    assert "caused" not in {str(v) for v in action.values()}


def test_rejected_is_not_established(
    mode, capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    run, action_id = _proposed(ctx)
    engagement_ok(ctx, run, "action", "reject", *run.flags(), "--action-id", action_id)
    code, env, raw = eng(
        capsys, "action", "accept", *run.flags(), "--action-id", action_id
    )
    assert code == 2, raw
    assert error_code(env) == "INVALID_TRANSITION"
    commit(ctx, run)

    action = _action(ctx, recovery_run(ctx), action_id)
    assert action["acceptance_state"] == "rejected"
    assert action["outcome_state"] == "improved"
    assert action["attribution"] == "not_established"
