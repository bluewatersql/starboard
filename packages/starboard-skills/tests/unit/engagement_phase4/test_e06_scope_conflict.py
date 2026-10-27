"""E6 Scenario 6: account / ticket / scope conflict (regression; ``drive_backed``; §H.6).

The workspace-account mismatch quarantines the run and stops the customer leg
(exit 5, every later stage refused). An explicit ticket skip proceeds on the
account route. An unauthenticated Salesforce lookup yields an ``unresolved``
ref that never guesses a ticket folder, and the operator can skip it.
"""

from __future__ import annotations

from typing import Any

import pytest

from ._support import (
    WS,
    Ctx,
    FakeWorkspace,
    eng,
    error_code,
    ok,
    preflight_argv,
    shared_root,
    ticket_flags,
    ticket_ref,
)

pytestmark = pytest.mark.parametrize("mode", ["drive_backed"])

AR_KEY = "AR-000000001"


def _preflight(ctx: Ctx) -> dict[str, Any]:
    return ok(
        ctx.capsys,
        *preflight_argv(
            ctx,
            task="troubleshooting",
            task_name="job-42",
            source_mode="customer_workspace",
        ),
    )


def _verified(ctx: Ctx) -> dict[str, Any]:
    pre = _preflight(ctx)
    ok(
        ctx.capsys,
        "verify-identity",
        "--run-id",
        pre["run_id"],
        "--profile",
        "acme",
        "--expected-workspace-id",
        WS,
    )
    return pre


def _ticket_folders(store: Any) -> list[str]:
    out: list[str] = []
    todo = [shared_root(store)]
    while todo:
        parent = todo.pop()
        for child in store.list_children(parent, folders_only=True):
            if str(child.name).startswith(f"{AR_KEY}: "):
                out.append(str(child.id))
            todo.append(child.id)
    return out


def test_account_mismatch_quarantines_and_stops_the_customer_leg(ctx: Ctx) -> None:
    from starboard_core.engagement.staging import QUARANTINE_PROPERTY

    pre = _preflight(ctx)
    ctx.seams.client = FakeWorkspace(workspace_id="999")
    code, env, raw = eng(
        ctx.capsys,
        "verify-identity",
        "--run-id",
        pre["run_id"],
        "--profile",
        "acme",
        "--expected-workspace-id",
        WS,
    )
    assert code == 5, raw
    assert error_code(env) == "IDENTITY_MISMATCH"
    staged = ctx.store.get(pre["staging_folder_id"])
    assert staged.properties.get(QUARANTINE_PROPERTY)
    status = ok(ctx.capsys, "status", "--run-id", pre["run_id"])
    assert status["run_status"] == "quarantined" and status["resume"] is None
    flags = ticket_flags(ctx.store, ctx.tmp_path)
    count = ctx.store.object_count
    code, env, raw = eng(ctx.capsys, "route", "--run-id", pre["run_id"], *flags)
    assert code == 5, raw
    assert error_code(env) == "RUN_QUARANTINED"
    assert ctx.store.object_count == count
    assert _ticket_folders(ctx.store) == []


def test_explicit_ticket_skip_proceeds_on_the_account_route(ctx: Ctx) -> None:
    from starboard_internal.ticket import skip_ticket

    pre = _verified(ctx)
    ref = skip_ticket("ASQ-000000001", AR_KEY, "operator chose the account route")
    data = ok(
        ctx.capsys,
        "route",
        "--run-id",
        pre["run_id"],
        *ticket_flags(ctx.store, ctx.tmp_path, ref.to_dict()),
    )
    assert data["route"] == "account"
    assert f"{AR_KEY}: " not in str(data["path"])
    assert _ticket_folders(ctx.store) == []


def test_unauthenticated_salesforce_lookup_can_be_skipped(ctx: Ctx) -> None:
    from starboard_internal.ticket import skip_ticket, unresolved_ticket

    unresolved = unresolved_ticket(
        "ASQ-000000001", AR_KEY, "salesforce lookup failed: 401 unauthenticated"
    )
    assert unresolved.resolution == "unresolved"
    pre = _verified(ctx)
    data = ok(
        ctx.capsys,
        "route",
        "--run-id",
        pre["run_id"],
        *ticket_flags(ctx.store, ctx.tmp_path, unresolved.to_dict()),
    )
    assert data["route"] == "account"
    assert data.get("ticket_warning")
    assert _ticket_folders(ctx.store) == []

    skipped = skip_ticket(
        unresolved.input_token or "ASQ-000000001", AR_KEY, "salesforce unavailable"
    )
    pre2 = _verified(ctx)
    data2 = ok(
        ctx.capsys,
        "route",
        "--run-id",
        pre2["run_id"],
        *ticket_flags(ctx.store, ctx.tmp_path, skipped.to_dict()),
    )
    assert data2["route"] == "account"
    assert _ticket_folders(ctx.store) == []


def test_ticket_account_mismatch_falls_back_to_the_account_route(ctx: Ctx) -> None:
    pre = _verified(ctx)
    ref = ticket_ref(
        account_id="001XYZ",
        resolution="mismatch",
        reason="ticket account differs from the workspace account",
    )
    data = ok(
        ctx.capsys,
        "route",
        "--run-id",
        pre["run_id"],
        *ticket_flags(ctx.store, ctx.tmp_path, ref),
    )
    assert data["route"] == "account"
    assert "mismatch" in str(data.get("ticket_warning"))
    assert _ticket_folders(ctx.store) == []
