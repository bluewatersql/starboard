"""E3 Scenario 3: ASQ alias (regression; ``drive_backed``; spec §H.3).

``ASQ-000000001`` normalizes to ``AR-000000001``; a run opened with the ASQ
token and a run opened with the AR key route into the SAME
``AR-000000001: <title>`` folder (reused by parent ID, never twinned); a missing
Salesforce record offers retry or skip, and a skip proceeds on the account
route. The phase-1 path through the phase-4 harness; no code change expected.
"""

from __future__ import annotations

from typing import Any

import pytest

from ._support import Ctx, new_run, shared_root, ticket_flags, ticket_ref

DRIVE = pytest.mark.parametrize("mode", ["drive_backed"])

AR_KEY = "AR-000000001"
FOLDER = f"{AR_KEY}: Job reliability"


def _ticket_folder(store: Any, rf: str) -> str:
    """The ``AR-…:<title>`` ancestor folder ID of a run folder."""
    seen: set[str] = set()
    todo = [rf]
    while todo:
        oid = todo.pop()
        if oid in seen:
            continue
        seen.add(oid)
        obj = store.get(oid)
        if obj.name == FOLDER:
            return str(obj.id)
        todo += list(obj.parent_ids)
    raise AssertionError(f"no {FOLDER!r} ancestor of {rf}")


def _ticket_folders(store: Any, root: str) -> list[str]:
    """Every folder named ``FOLDER`` anywhere under ``root``."""
    out: list[str] = []
    todo = [root]
    while todo:
        parent = todo.pop()
        for child in store.list_children(parent, folders_only=True):
            if child.name == FOLDER:
                out.append(str(child.id))
            todo.append(child.id)
    return out


def test_asq_token_normalizes_to_the_ar_key() -> None:
    from starboard_internal.ticket import normalize_token, parse_ticket_tokens

    assert normalize_token("ASQ-000000001") == AR_KEY
    parsed = parse_ticket_tokens("see ASQ-000000001 for the job 42 failures")
    assert parsed.state == "single"
    assert parsed.key == AR_KEY


@DRIVE
def test_asq_and_ar_runs_reuse_one_ticket_folder(ctx: Ctx) -> None:
    root = shared_root(ctx.store)
    asq = new_run(
        ctx,
        task="troubleshooting",
        task_name="job-42",
        route_flags=ticket_flags(
            ctx.store, ctx.tmp_path, ticket_ref(input_token="ASQ-000000001")
        ),
    )
    ar = new_run(
        ctx,
        task="troubleshooting",
        task_name="job-42",
        route_flags=ticket_flags(
            ctx.store, ctx.tmp_path, ticket_ref(input_token=AR_KEY)
        ),
    )
    assert asq.rf and ar.rf and asq.rf != ar.rf
    assert _ticket_folder(ctx.store, asq.rf) == _ticket_folder(ctx.store, ar.rf)
    assert len(_ticket_folders(ctx.store, root)) == 1


@DRIVE
def test_missing_record_offers_retry_or_skip(ctx: Ctx) -> None:
    from starboard_internal.ticket import skip_ticket, validate_ticket

    missing = validate_ticket(
        AR_KEY, "ASQ-000000001", [], expected_account_id=ticket_ref()["account_id"]
    )
    assert missing.resolution == "unresolved"
    assert "retry or explicitly skip" in missing.reason

    skipped = skip_ticket("ASQ-000000001", AR_KEY, "operator skipped ticket routing")
    assert skipped.resolution == "skipped"
    run = new_run(
        ctx,
        task="troubleshooting",
        task_name="job-42",
        route_flags=ticket_flags(ctx.store, ctx.tmp_path, skipped.to_dict()),
    )
    assert run.rf
    assert _ticket_folders(ctx.store, shared_root(ctx.store)) == []
