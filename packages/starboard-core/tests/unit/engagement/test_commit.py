# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the run descriptor and the append-only manifest commit record."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest
from starboard_core.engagement.commit import (
    DESCRIPTOR_NAME,
    DESCRIPTOR_PROPERTY,
    MANIFEST_PROPERTY,
    MANIFEST_SEGMENT,
    CommitError,
    DescriptorConflictError,
    ManifestConflictError,
    append_manifest,
    latest_manifest,
    read_descriptor,
    write_descriptor,
)
from starboard_core.engagement.folders import IDENTITY_PROPERTY
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.records import (
    AccountRef,
    DriveContext,
    RunAuthorization,
    RunManifest,
    StorageRef,
)
from starboard_core.ports.engagement_storage import StorageIntegrityError, StorageObject

RID = "20261008_12345678-1234-4234-8234-123456789abc"
STATES = {
    "capture": "pending",
    "analysis": "pending",
    "check": "pending",
    "publication": "pending",
}


def make_auth(run_folder_id: str, **over: Any) -> RunAuthorization:
    drive = DriveContext(
        provider="google_drive",
        principal="perm-1",
        route="account",
        base_folder_id="base",
        root_folder_id="root",
        run_folder_id=run_folder_id,
        registry_folder_id="reg",
        account_key="acme",
        acl_classification="restricted",
        permission_fingerprints={run_folder_id: "fp"},
        capabilities={"upload": True},
        created_at="2026-10-08T09:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
    )
    base: dict[str, Any] = {
        "engagement_id": "eng-acme",
        "run_id": RID,
        "intent": "discovery",
        "task": "workspace",
        "account": AccountRef(id="acme", display_name="Acme", verifier="operator"),
        "requested_scope": {"workspace_ids": ["123"]},
        "authorized_scope": {"account_key": "acme", "workspace_ids": ["123"]},
        "reporting_interval": "P30D",
        "timezone": "UTC",
        "source_mode": SourceMode.CUSTOMER_WORKSPACE,
        "storage_policy": StoragePolicy.DRIVE_REQUIRED,
        "audience": "internal",
        "methodology_version": "m1",
        "drive": drive,
    }
    base.update(over)
    return RunAuthorization(**base)


def setup_run() -> tuple[InMemoryEngagementStorage, str, RunAuthorization]:
    store = InMemoryEngagementStorage()
    run = store.create_folder(
        store.root_folder_id(), RID, {IDENTITY_PROPERTY: f"run:{RID}"}
    )
    return store, run.id, make_auth(run.id)


def ref_of(obj: StorageObject, path: str) -> StorageRef:
    return StorageRef(
        path=path,
        object_id=obj.id,
        revision=obj.revision,
        md5=obj.md5,
        size=obj.size,
        mime_type=obj.mime_type,
    )


def builder(
    descriptor: StorageObject, refs: tuple[StorageRef, ...] = (), **over: Any
) -> Callable[[int, str | None], RunManifest]:
    def build(n: int, previous: str | None) -> RunManifest:
        base: dict[str, Any] = {
            "engagement_id": "eng-acme",
            "run_id": RID,
            "revision": n,
            "previous_object_id": previous,
            "task": "workspace",
            "task_name": "ws-123",
            "source_mode": SourceMode.CUSTOMER_WORKSPACE,
            "storage_policy": StoragePolicy.DRIVE_REQUIRED,
            "descriptor_ref": ref_of(descriptor, DESCRIPTOR_NAME),
            "refs": refs,
            "states": STATES,
            "committed_at": "2026-10-08T10:00:00+00:00",
        }
        base.update(over)
        return RunManifest(**base)

    return build


# ---- descriptor -----------------------------------------------------------------


def test_write_descriptor_writes_and_reads_back() -> None:
    store, run_id, auth = setup_run()
    obj = write_descriptor(store, run_id, auth)
    assert obj.name == DESCRIPTOR_NAME
    assert obj.parent_ids == (run_id,)
    assert obj.properties[DESCRIPTOR_PROPERTY] == f"run:{RID}"
    payload = json.loads(b"".join(store.get_stream(obj.id)))
    assert payload == auth.to_dict()
    assert "token" not in json.dumps(payload).lower()

    got, got_obj = read_descriptor(store, run_id)
    assert got == auth
    assert got_obj.id == obj.id


def test_write_descriptor_equal_rewrite_is_idempotent() -> None:
    store, run_id, auth = setup_run()
    first = write_descriptor(store, run_id, auth)
    count = store.object_count
    again = write_descriptor(store, run_id, make_auth(run_id))
    assert again.id == first.id
    assert again.revision == first.revision
    assert store.object_count == count


def test_write_descriptor_conflict_on_different_content() -> None:
    store, run_id, auth = setup_run()
    write_descriptor(store, run_id, auth)
    with pytest.raises(DescriptorConflictError):
        write_descriptor(store, run_id, make_auth(run_id, audience="customer"))
    # The original stays untouched (descriptors are never updated).
    assert read_descriptor(store, run_id)[0] == auth


def test_write_descriptor_conflict_on_foreign_same_name_object() -> None:
    store, run_id, auth = setup_run()
    store.put_stream(
        run_id, DESCRIPTOR_NAME, "application/json", [b"{}"], properties={}
    )
    with pytest.raises(DescriptorConflictError):
        write_descriptor(store, run_id, auth)


def test_write_descriptor_conflict_on_concurrent_duplicate() -> None:
    store, run_id, auth = setup_run()
    store.duplicate_on_put = {DESCRIPTOR_NAME}
    with pytest.raises(DescriptorConflictError):
        write_descriptor(store, run_id, auth)


def test_write_descriptor_must_name_this_run_folder() -> None:
    store, run_id, _ = setup_run()
    with pytest.raises(CommitError):
        write_descriptor(store, run_id, make_auth("some-other-folder"))


def test_write_descriptor_read_back_mismatch() -> None:
    store, run_id, auth = setup_run()
    store.corrupt_get_stream = lambda data: data.replace(b"acme", b"evil")
    with pytest.raises(StorageIntegrityError):
        write_descriptor(store, run_id, auth)


def test_read_descriptor_errors() -> None:
    store, run_id, auth = setup_run()
    with pytest.raises(CommitError):
        read_descriptor(store, run_id)  # none
    props = {DESCRIPTOR_PROPERTY: f"run:{RID}"}
    store.put_stream(
        run_id, DESCRIPTOR_NAME, "application/json", [b"not json"], properties=props
    )
    with pytest.raises(CommitError):
        read_descriptor(store, run_id)  # unparseable
    store.put_stream(
        run_id, DESCRIPTOR_NAME, "application/json", [b"{}"], properties=props
    )
    with pytest.raises(CommitError):
        read_descriptor(store, run_id)  # two


def test_read_descriptor_property_must_match_run() -> None:
    store, run_id, auth = setup_run()
    raw = (json.dumps(auth.to_dict(), sort_keys=True, indent=2) + "\n").encode()
    store.put_stream(
        run_id,
        DESCRIPTOR_NAME,
        "application/json",
        [raw],
        properties={
            DESCRIPTOR_PROPERTY: "run:20261008_00000000-0000-4000-8000-000000000000"
        },
    )
    with pytest.raises(CommitError):
        read_descriptor(store, run_id)


# ---- manifest -------------------------------------------------------------------


def test_append_manifest_rev1_then_chains_previous_object_id() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    seen: list[tuple[int, str | None]] = []

    def recording(n: int, prev: str | None) -> RunManifest:
        seen.append((n, prev))
        return builder(desc)(n, prev)

    m1, o1 = append_manifest(store, run_id, recording)
    m2, o2 = append_manifest(store, run_id, recording)
    m3, o3 = append_manifest(store, run_id, recording)

    assert seen == [(1, None), (2, o1.id), (3, o2.id)]
    assert (m1.revision, m2.revision, m3.revision) == (1, 2, 3)
    assert m3.previous_object_id == o2.id
    assert o1.name == "rev-000001.json"
    assert o3.name == "rev-000003.json"
    assert o3.properties[MANIFEST_PROPERTY] == f"{RID}:3"
    (folder,) = store.list_children(run_id, name=MANIFEST_SEGMENT, folders_only=True)
    assert folder.properties[IDENTITY_PROPERTY] == f"manifest:{RID}"
    assert o1.parent_ids == (folder.id,)
    assert RunManifest.from_dict(json.loads(b"".join(store.get_stream(o3.id)))) == m3


def test_manifest_revisions_are_never_updated() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    _, o1 = append_manifest(store, run_id, builder(desc))
    append_manifest(store, run_id, builder(desc))
    assert store.get(o1.id).revision == o1.revision
    assert b"".join(store.get_stream(o1.id))  # still readable at its first revision


def test_append_manifest_carries_typed_refs() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    report = store.put_stream(
        run_id, "r.json", "application/json", [b"{}"], properties={}
    )
    m, _ = append_manifest(
        store, run_id, builder(desc, refs=(ref_of(report, "analysis/r.json"),))
    )
    assert m.refs[0].object_id == report.id
    assert m.refs[0].md5 == report.md5


def test_identical_duplicate_revision_is_one_revision() -> None:
    # Run 13: a retried final upload request left two byte-identical copies of
    # revision 3; every later commit and status stopped "concurrent writer".
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    append_manifest(store, run_id, builder(desc))
    store.duplicate_on_put = {"rev-000002.json"}
    _, second = append_manifest(store, run_id, builder(desc))
    (folder,) = store.list_children(run_id, name=MANIFEST_SEGMENT, folders_only=True)
    twins = store.list_children(folder.id, name="rev-000002.json")
    assert len(twins) == 2 and second.id in {o.id for o in twins}
    latest, _ = latest_manifest(store, run_id)
    assert latest.revision == 2
    third, _ = append_manifest(store, run_id, builder(desc))
    assert third.revision == 3 and third.previous_object_id in {o.id for o in twins}
    assert latest_manifest(store, run_id)[0].revision == 3


def test_next_revision_may_chain_to_either_identical_copy() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    append_manifest(store, run_id, builder(desc))
    store.duplicate_on_put = {"rev-000002.json"}
    append_manifest(store, run_id, builder(desc))
    (folder,) = store.list_children(run_id, name=MANIFEST_SEGMENT, folders_only=True)
    twins = sorted(
        store.list_children(folder.id, name="rev-000002.json"), key=lambda o: o.id
    )
    for twin in twins:  # whichever copy the next writer listed, the chain holds
        m = builder(desc)(3, twin.id)
        store.put_stream(
            folder.id,
            "rev-000003.json",
            "application/json",
            [json.dumps(m.to_dict(), sort_keys=True, separators=(",", ":")).encode()],
            properties={MANIFEST_PROPERTY: f"{RID}:3"},
        )
        assert latest_manifest(store, run_id)[0].previous_object_id == twin.id
        for o in store.list_children(folder.id, name="rev-000003.json"):
            store.trash(o.id)


def test_append_manifest_concurrent_writer_wins_the_race() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)

    def racing(n: int, prev: str | None) -> RunManifest:
        # Another writer commits revision n between our list and our create.
        (folder,) = store.list_children(
            run_id, name=MANIFEST_SEGMENT, folders_only=True
        )
        store.put_stream(
            folder.id,
            f"rev-{n:06d}.json",
            "application/json",
            [b"{}"],
            properties={MANIFEST_PROPERTY: f"{RID}:{n}"},
        )
        return builder(desc)(n, prev)

    with pytest.raises(ManifestConflictError):
        append_manifest(store, run_id, racing)


def test_append_manifest_validates_build_result() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    other = store.put_stream(run_id, "x", "text/plain", [b"x"], properties={})
    for bad in (
        builder(desc, run_id="20261008_00000000-0000-4000-8000-000000000000"),
        builder(desc, engagement_id="eng-other"),
        builder(other),  # descriptor_ref names the wrong object
    ):
        with pytest.raises(CommitError):
            append_manifest(store, run_id, bad)

    def wrong_number(n: int, prev: str | None) -> RunManifest:
        return dataclasses.replace(
            builder(desc)(n, prev), revision=n + 1, previous_object_id="x"
        )

    with pytest.raises(CommitError):
        append_manifest(store, run_id, wrong_number)
    assert latest_manifest(store, run_id) is None


def test_append_manifest_requires_descriptor() -> None:
    store, run_id, auth = setup_run()
    with pytest.raises(CommitError):
        append_manifest(store, run_id, builder(store.get(run_id)))


def test_append_manifest_read_back_mismatch() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    # Only manifest content carries "committed_at"; the descriptor reads back clean.
    store.corrupt_get_stream = lambda data: data.replace(
        b"committed_at", b"committed_by"
    )
    with pytest.raises(StorageIntegrityError):
        append_manifest(store, run_id, builder(desc))


def test_latest_manifest() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    assert latest_manifest(store, run_id) is None
    append_manifest(store, run_id, builder(desc))
    m2, o2 = append_manifest(
        store, run_id, builder(desc, states={**STATES, "publication": "complete"})
    )
    got = latest_manifest(store, run_id)
    assert got is not None
    assert got[0] == m2
    assert got[1].id == o2.id
    assert got[0].states["publication"] == "complete"


def test_latest_manifest_with_a_known_run_id_skips_the_descriptor() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    m1, _ = append_manifest(store, run_id, builder(desc))
    store.corrupt_object(desc.id)  # unread: the caller already checked it
    got = latest_manifest(store, run_id, run_id=RID)
    assert got is not None and got[0] == m1
    with pytest.raises(CommitError):
        latest_manifest(store, run_id)  # without it, the descriptor is read
    assert latest_manifest(store, run_id, run_id="other-run") is None


def test_latest_manifest_detects_broken_chain() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    append_manifest(store, run_id, builder(desc))
    (folder,) = store.list_children(run_id, name=MANIFEST_SEGMENT, folders_only=True)
    forged = builder(desc)(2, "not-the-predecessor")
    raw = (json.dumps(forged.to_dict(), sort_keys=True, indent=2) + "\n").encode()
    store.put_stream(
        folder.id,
        "rev-000002.json",
        "application/json",
        [raw],
        properties={MANIFEST_PROPERTY: f"{RID}:2"},
    )
    with pytest.raises(CommitError):
        latest_manifest(store, run_id)
    with pytest.raises(CommitError):
        append_manifest(store, run_id, builder(desc))


def test_latest_manifest_detects_missing_revision() -> None:
    store, run_id, auth = setup_run()
    desc = write_descriptor(store, run_id, auth)
    _, o1 = append_manifest(store, run_id, builder(desc))
    (folder,) = store.list_children(run_id, name=MANIFEST_SEGMENT, folders_only=True)
    forged = builder(desc)(3, o1.id)
    raw = (json.dumps(forged.to_dict(), sort_keys=True, indent=2) + "\n").encode()
    store.put_stream(
        folder.id,
        "rev-000003.json",
        "application/json",
        [raw],
        properties={MANIFEST_PROPERTY: f"{RID}:3"},
    )
    with pytest.raises(CommitError):
        latest_manifest(store, run_id)
