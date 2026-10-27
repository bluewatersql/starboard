# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared fakes for the phase-2 starboard CLI writer tests (discover, review, goal agent).

* an in-memory Drive run (descriptor plus a verified identity check),
* helpers that fake the overlay and sandbox HOME, cwd and TMPDIR,
* readers for what a run folder holds.

Same fixtures as ``starboard-core``'s ``tests/unit/starboard_x/_writer_support.py``,
copied here because each package's tests run on their own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.commit import write_descriptor
from starboard_core.engagement.folders import IDENTITY_PROPERTY
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.records import (
    AccountRef,
    DriveContext,
    EvidenceRef,
    IdentityCheck,
    RunAuthorization,
)
from starboard_core.engagement.sink import DriveRunSink
from starboard_core.engagement.write_guard import sandbox_diff, sandbox_snapshot
from starboard_core.ports.engagement_storage import Grant

RID = "20261008_12345678-1234-4234-8234-123456789abc"
WS = "123"
STDOUT_BUDGET = 24_000
IDENTITY_RELPATH = "analysis/identity-check.json"


def identity_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": 1,
        "run_id": RID,
        "provisional_account_key": "acme",
        "provisional_account_name": "Acme Corp",
        "provisional_source": "operator",
        "expected_workspace_id": WS,
        "expected_host": None,
        "observed_workspace_id": WS,
        "observed_host": "https://acme.cloud.databricks.com",
        "principal_id": "7781234",
        "principal_kind": "user",
        "checked_at": "2026-10-08T09:00:00+00:00",
        "status": "verified",
        "reasons": [],
    }
    record.update(overrides)
    return record


def drive_run(
    *,
    workspace_ids: tuple[str, ...] = (WS,),
    identity: bool = True,
    source_mode: SourceMode = SourceMode.CUSTOMER_WORKSPACE,
    basis: str | None = None,
    workspace_profile: str | None = None,
) -> tuple[InMemoryEngagementStorage, str]:
    """An authorized Drive run folder (descriptor + optional verified identity check).

    ``basis`` / ``workspace_profile``: ``authorized_scope.basis`` and the verified
    ``--profile`` the descriptor records (``None``: not recorded).
    """
    store = InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), "run", {})
    store.set_access(
        folder.id,
        can_add_children=True,
        grants=(Grant(kind="user", role="owner"),),
        complete=True,
    )
    staging = store.create_folder(store.root_folder_id(), "staging", {})
    fp = store.inspect_access(folder.id).fingerprint
    drive = DriveContext(
        provider="google_drive",
        principal="perm-1",
        route="account",
        base_folder_id="base",
        root_folder_id="root",
        run_folder_id=folder.id,
        registry_folder_id="reg",
        account_key="acme",
        acl_classification="restricted",
        permission_fingerprints={folder.id: fp},
        capabilities={"upload": True},
        created_at="2026-10-08T09:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
        preflight_folder_id=staging.id,
    )
    write_descriptor(
        store,
        folder.id,
        RunAuthorization(
            engagement_id="acme/workspace/ws-123",
            run_id=RID,
            intent="discovery",
            task="workspace",
            account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
            requested_scope={"workspace_ids": list(workspace_ids)},
            authorized_scope={
                "account_key": "acme",
                "workspace_ids": list(workspace_ids),
                **({"basis": basis} if basis else {}),
            },
            reporting_interval="P30D",
            timezone="UTC",
            source_mode=source_mode,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            audience="internal",
            methodology_version="m1",
            drive=drive,
            workspace_profile=workspace_profile,
        ),
    )
    if identity:
        record = identity_record()
        IdentityCheck.from_dict(record)
        parent = store.create_folder(
            folder.id, "analysis", {IDENTITY_PROPERTY: "artifact-dir:analysis"}
        ).id
        store.put_stream(
            parent,
            "identity-check.json",
            "application/json",
            [json.dumps(record).encode()],
            properties={"starboard_artifact": IDENTITY_RELPATH, "starboard_run": RID},
        )
    return store, folder.id


def covered_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    store: InMemoryEngagementStorage,
    *modules: Any,
) -> dict[str, Path]:
    """Fake the overlay, route storage to ``store``, sandbox the env.

    Every module in ``modules`` gets ``detect_overlay`` -> enabled and
    ``load_engagement_storage`` -> ``store`` (the CLI's lookup seams).
    """
    import tempfile

    sandbox = {name: tmp_path / name for name in ("home", "cwd", "tmp")}
    for path in sandbox.values():
        path.mkdir()
    monkeypatch.setenv("STARBOARD_OVERLAY", "1")
    monkeypatch.setenv("HOME", str(sandbox["home"]))
    monkeypatch.setenv("TMPDIR", str(sandbox["tmp"]))
    monkeypatch.setattr(tempfile, "tempdir", str(sandbox["tmp"]))
    monkeypatch.chdir(sandbox["cwd"])
    for module in modules:
        overlay_on(monkeypatch, module)
        monkeypatch.setattr(module, "load_engagement_storage", lambda: store)
    return sandbox


def overlay_on(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    monkeypatch.setattr(
        module, "detect_overlay", lambda **_kw: OverlaySignal(True, ("test",))
    )


def snapshot(sandbox: dict[str, Path]) -> dict[str, tuple[int, int]]:
    return sandbox_snapshot(list(sandbox.values()))


def diff(sandbox: dict[str, Path], before: dict[str, tuple[int, int]]) -> list[str]:
    return sandbox_diff(before, snapshot(sandbox))


def sink_for(store: InMemoryEngagementStorage, folder_id: str) -> DriveRunSink:
    return DriveRunSink(
        store,
        folder_id,
        run_id=RID,
        access_fingerprint=store.inspect_access(folder_id).fingerprint,
    )


def written(sink: DriveRunSink, prefix: str = "") -> set[str]:
    """Relpaths in a run besides the fixture's own identity check."""
    return set(sink.list(prefix)) - {IDENTITY_RELPATH}


def evidence(sink: DriveRunSink) -> list[EvidenceRef]:
    return [
        EvidenceRef.from_dict(d)
        for d in json.loads(sink.get_bytes("evidence/index.json"))
    ]


def local_run_dir(root: Path) -> Path:
    """A local run directory holding an internal-only local descriptor (D-11)."""
    run_dir = root / "local-run"
    (run_dir / "analysis").mkdir(parents=True)
    auth = RunAuthorization(
        engagement_id="internal/workspace/ws-123",
        run_id=RID,
        intent="discovery",
        task="workspace",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={},
        authorized_scope={"account_key": "acme"},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.INTERNAL_ONLY,
        storage_policy=StoragePolicy.INTERNAL_ONLY_LOCAL,
        audience="internal",
        methodology_version="m1",
    )
    (run_dir / "analysis" / "run-authorization.json").write_text(
        json.dumps(auth.to_dict())
    )
    return run_dir
