# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for derived run status (P2-G8)."""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.access import AccessVerdict
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.records import (
    AccountRef,
    DriveContext,
    RunAuthorization,
    RunManifest,
    StorageRef,
)
from starboard_core.engagement.status import STATUSES, RunStatus, derive_status

RID = "20261007_12345678-1234-4234-8234-123456789abc"
OTHER = "20261007_22345678-1234-4234-8234-123456789abc"
OK = AccessVerdict(ok=True, reason="unchanged")


def drive() -> DriveContext:
    return DriveContext(
        provider="google_drive",
        principal="user-opaque-123",
        route="account",
        base_folder_id="base1",
        root_folder_id="root1",
        run_folder_id="run1",
        registry_folder_id="reg1",
        account_key="acme",
        acl_classification="internal_only",
        permission_fingerprints={"run1": "fp"},
        capabilities={"upload": True},
        created_at="2026-10-07T12:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
        links={},
    )


def auth(**over: Any) -> RunAuthorization:
    base: dict[str, Any] = {
        "engagement_id": "eng-acme",
        "run_id": RID,
        "intent": "health_check",
        "task": "workspace",
        "account": AccountRef(id="001", display_name="Acme", verifier="sfdc"),
        "requested_scope": {},
        "authorized_scope": {},
        "reporting_interval": "P30D",
        "timezone": "UTC",
        "source_mode": SourceMode.CUSTOMER_WORKSPACE,
        "storage_policy": StoragePolicy.DRIVE_REQUIRED,
        "audience": "internal",
        "methodology_version": "m1",
        "drive": drive(),
    }
    base.update(over)
    return RunAuthorization(**base)


def ref(path: str) -> StorageRef:
    return StorageRef(
        path=path,
        object_id="o-" + path,
        revision="r",
        md5="0" * 32,
        size=1,
        mime_type="application/json",
    )


def manifest(revision: int = 1, run_id: str = RID, **states: str) -> RunManifest:
    full = {
        "capture": "pending",
        "analysis": "pending",
        "check": "pending",
        "publication": "pending",
        **states,
    }
    return RunManifest(
        engagement_id="eng-acme",
        run_id=run_id,
        revision=revision,
        previous_object_id=None if revision == 1 else f"man-{revision - 1}",
        task="workspace",
        task_name="ws-1",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.DRIVE_REQUIRED,
        descriptor_ref=ref("run-authorization.json"),
        refs=(),
        states=full,
        committed_at="2026-10-08T09:00:00+00:00",
    )


DONE = {"capture": "complete", "analysis": "complete", "check": "complete"}


def test_statuses_constant() -> None:
    assert STATUSES == (
        "staged",
        "routed",
        "capture_pending",
        "analysis_pending",
        "check_pending",
        "publication_pending",
        "complete",
        "blocked_access",
        "quarantined",
    )


def test_staged_without_manifest() -> None:
    s = derive_status(auth(), [], OK, False)
    assert s == RunStatus(
        status="staged",
        states={},
        pending=("route",),
        resume={"run_id": RID, "run_folder_id": "run1", "stage": "route"},
        checkpoint_revision=None,
    )
    assert derive_status(None, [], None, False).status == "staged"
    assert derive_status(None, [], None, False).resume is None


def test_routed_on_rev1_with_nothing_started() -> None:
    s = derive_status(auth(), [manifest()], OK, False)
    assert s.status == "routed"
    assert s.pending == ("capture", "analysis", "check", "publication")
    assert s.resume == {"run_id": RID, "run_folder_id": "run1", "stage": "capture"}
    assert s.checkpoint_revision == 1


def test_capture_pending_shows_last_checkpoint() -> None:
    m1 = manifest()
    m2 = manifest(2, capture="in_progress")
    s = derive_status(auth(), [m2, m1], OK, False)
    assert s.status == "capture_pending"
    assert s.checkpoint_revision == 2
    assert s.resume is not None and s.resume["stage"] == "capture"
    failed = derive_status(auth(), [manifest(3, capture="failed")], OK, False)
    assert failed.status == "capture_pending"


@pytest.mark.parametrize(
    ("states", "expected", "stage"),
    [
        ({"capture": "complete"}, "analysis_pending", "analysis"),
        ({"capture": "complete", "analysis": "complete"}, "check_pending", "check"),
        (
            {"capture": "complete", "analysis": "complete", "check": "skipped"},
            "publication_pending",
            "publication",
        ),
    ],
)
def test_stage_pending(states: dict[str, str], expected: str, stage: str) -> None:
    s = derive_status(auth(), [manifest(2, **states)], OK, False)
    assert s.status == expected
    assert s.resume is not None and s.resume["stage"] == stage
    assert s.pending[0] == stage


def test_failed_delivery_is_publication_pending_with_analysis_complete() -> None:
    s = derive_status(auth(), [manifest(4, **DONE, publication="failed")], OK, False)
    assert s.status == "publication_pending"
    assert s.states["analysis"] == "complete"
    assert s.pending == ("publication",)


@pytest.mark.parametrize("publication", ["complete", "skipped"])
def test_complete(publication: str) -> None:
    s = derive_status(auth(), [manifest(5, **DONE, publication=publication)], OK, False)
    assert s.status == "complete"
    assert s.pending == ()
    assert s.resume is None


@pytest.mark.parametrize("reason", ["revoked", "changed", "unknown"])
def test_blocked_access(reason: str) -> None:
    s = derive_status(
        auth(),
        [manifest(2, capture="complete")],
        AccessVerdict(ok=False, reason=reason),
        False,
    )
    assert s.status == "blocked_access"
    assert s.resume is None
    assert s.states["capture"] == "complete"


def test_quarantined_wins() -> None:
    s = derive_status(
        auth(), [manifest()], AccessVerdict(ok=False, reason="revoked"), True
    )
    assert s.status == "quarantined"
    assert s.resume is None


def test_latest_revision_is_used_regardless_of_order() -> None:
    s = derive_status(
        auth(),
        [manifest(3, **DONE), manifest(2, capture="complete"), manifest()],
        OK,
        False,
    )
    assert s.status == "publication_pending"
    assert s.checkpoint_revision == 3


def test_mixed_run_ids_rejected() -> None:
    with pytest.raises(ValueError):
        derive_status(auth(), [manifest(), manifest(2, run_id=OTHER)], OK, False)
    with pytest.raises(ValueError):
        derive_status(auth(), [manifest(run_id=OTHER)], OK, False)


def test_resume_without_drive_context() -> None:
    s = derive_status(auth(drive=None), [manifest()], OK, False)
    assert s.resume == {"run_id": RID, "run_folder_id": None, "stage": "capture"}


def test_states_are_read_only() -> None:
    s = derive_status(auth(), [manifest()], OK, False)
    with pytest.raises(TypeError):
        s.states["capture"] = "complete"  # type: ignore[index]
