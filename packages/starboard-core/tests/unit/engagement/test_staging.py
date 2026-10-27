# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for restricted Drive staging, verified JSON writes and quarantine."""

from __future__ import annotations

import json

import pytest
from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    FolderConflictError,
    FolderResolutionError,
)
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.staging import (
    PREFLIGHT_SEGMENT,
    QUARANTINE_PROPERTY,
    QUARANTINE_SEGMENT,
    Staging,
    StagingError,
    StagingNotRestrictedError,
    ensure_staging,
    put_json,
    quarantine_staging,
)
from starboard_core.ports.engagement_storage import (
    Grant,
    StorageIntegrityError,
    StorageObject,
)

RID = "20261008_12345678-1234-4234-8234-123456789abc"
RID2 = "20261008_87654321-4321-4321-8321-cba987654321"


def _child(store: InMemoryEngagementStorage, parent: str, name: str) -> StorageObject:
    (only,) = store.list_children(parent, name=name, folders_only=True)
    return only


# ---- ensure_staging -------------------------------------------------------------


def test_ensure_staging_builds_account_neutral_restricted_folder() -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)

    assert isinstance(staging, Staging)
    root = store.root_folder_id()
    starboard = _child(store, root, "starboard")
    preflight = _child(store, starboard.id, PREFLIGHT_SEGMENT)
    assert staging.preflight_folder_id == preflight.id
    assert staging.folder.name == RID
    assert staging.folder.parent_ids == (preflight.id,)
    assert staging.folder.properties[IDENTITY_PROPERTY] == f"staging:{RID}"
    assert preflight.properties[IDENTITY_PROPERTY] == "preflight"
    assert starboard.properties[IDENTITY_PROPERTY] == "segment:starboard"
    assert staging.access.object_id == staging.folder.id
    assert staging.link == staging.folder.web_link


def test_ensure_staging_is_idempotent_and_shares_preflight() -> None:
    store = InMemoryEngagementStorage()
    first = ensure_staging(store, RID)
    again = ensure_staging(store, RID)
    other = ensure_staging(store, RID2)
    assert again.folder.id == first.folder.id
    assert other.folder.id != first.folder.id
    assert other.preflight_folder_id == first.preflight_folder_id


def test_ensure_staging_reuses_starboard_folder_from_account_route() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    existing = store.create_folder(
        root, "starboard", {IDENTITY_PROPERTY: "segment:starboard"}
    )
    ensure_staging(store, RID)
    assert _child(store, root, "starboard").id == existing.id


def test_ensure_staging_rejects_bad_run_id() -> None:
    with pytest.raises(ValueError):
        ensure_staging(InMemoryEngagementStorage(), "not-a-run")


def test_ensure_staging_never_adopts_untagged_run_folder() -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)
    store.add_folder(staging.preflight_folder_id, RID2)  # untagged, same name
    with pytest.raises(FolderConflictError):
        ensure_staging(store, RID2)


@pytest.mark.parametrize(
    "grant",
    [
        Grant("anyone", "reader"),
        Grant("domain", "reader", "example.com"),
        Grant("group", "reader", "example.com"),
        Grant("user", "writer", "example.com"),  # a second user grant
    ],
)
def test_ensure_staging_refuses_widened_acl(grant: Grant) -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)
    store.set_access(staging.preflight_folder_id, grants=(grant,))  # inherited
    with pytest.raises(StagingNotRestrictedError) as info:
        ensure_staging(store, RID)
    assert isinstance(info.value, StagingError)
    assert isinstance(info.value, FolderResolutionError)


def test_ensure_staging_refuses_incomplete_acl() -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)
    store.set_access(staging.folder.id, complete=False)
    with pytest.raises(StagingNotRestrictedError):
        ensure_staging(store, RID)


# ---- put_json -------------------------------------------------------------------


def test_put_json_writes_deterministic_json_and_reads_back() -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)
    obj = put_json(
        store,
        staging.folder.id,
        "storage-preflight.json",
        {"b": 1, "a": [1, 2]},
        properties={"starboard_record": "preflight"},
    )
    raw = b"".join(store.get_stream(obj.id))
    assert raw == b'{\n  "a": [\n    1,\n    2\n  ],\n  "b": 1\n}\n'
    assert json.loads(raw) == {"a": [1, 2], "b": 1}
    assert obj.mime_type == "application/json"
    assert dict(obj.properties) == {"starboard_record": "preflight"}


def test_put_json_same_content_reuses_existing_object() -> None:
    store = InMemoryEngagementStorage()
    parent = ensure_staging(store, RID).folder.id
    props = {"starboard_record": "preflight"}
    first = put_json(store, parent, "p.json", {"a": 1}, properties=props)
    count = store.object_count
    again = put_json(store, parent, "p.json", {"a": 1}, properties=props)
    assert again.id == first.id
    assert again.revision == first.revision
    assert store.object_count == count


def test_put_json_different_content_updates_in_place_as_new_revision() -> None:
    store = InMemoryEngagementStorage()
    parent = ensure_staging(store, RID).folder.id
    props = {"starboard_record": "preflight"}
    first = put_json(store, parent, "p.json", {"a": 1}, properties=props)
    count = store.object_count
    second = put_json(store, parent, "p.json", {"a": 2}, properties=props)
    assert second.id == first.id
    assert second.revision != first.revision
    assert store.object_count == count
    assert json.loads(b"".join(store.get_stream(first.id))) == {"a": 2}


def test_put_json_ignores_same_name_with_other_properties() -> None:
    store = InMemoryEngagementStorage()
    parent = ensure_staging(store, RID).folder.id
    a = put_json(store, parent, "p.json", {"a": 1}, properties={"r": "one"})
    b = put_json(store, parent, "p.json", {"a": 1}, properties={"r": "two"})
    assert a.id != b.id


def test_put_json_identical_twins_collapse_to_one() -> None:
    # Run 13: identical twins are one write a retried upload landed twice.
    store = InMemoryEngagementStorage()
    parent = ensure_staging(store, RID).folder.id
    props = {"r": "one"}
    store.put_stream(parent, "p.json", "application/json", [b"{}"], properties=props)
    store.put_stream(parent, "p.json", "application/json", [b"{}"], properties=props)
    put_json(store, parent, "p.json", {}, properties=props)
    assert len(store.list_children(parent, name="p.json")) == 1


def test_put_json_differing_matches_need_reconciliation() -> None:
    store = InMemoryEngagementStorage()
    parent = ensure_staging(store, RID).folder.id
    props = {"r": "one"}
    store.put_stream(parent, "p.json", "application/json", [b"{}"], properties=props)
    store.put_stream(parent, "p.json", "application/json", [b"[]"], properties=props)
    with pytest.raises(StagingError):
        put_json(store, parent, "p.json", {}, properties=props)


def test_put_json_read_back_mismatch_raises_integrity_error() -> None:
    store = InMemoryEngagementStorage()
    parent = ensure_staging(store, RID).folder.id
    store.corrupt_get_stream = lambda data: data.replace(b"1", b"2")
    with pytest.raises(StorageIntegrityError):
        put_json(store, parent, "p.json", {"a": 1}, properties={"r": "x"})


def test_put_json_update_read_back_mismatch_raises_integrity_error() -> None:
    store = InMemoryEngagementStorage()
    parent = ensure_staging(store, RID).folder.id
    put_json(store, parent, "p.json", {"a": 1}, properties={"r": "x"})
    store.corrupt_get_stream = lambda data: data.replace(b"3", b"4")
    with pytest.raises(StorageIntegrityError):
        put_json(store, parent, "p.json", {"a": 3}, properties={"r": "x"})


def test_put_json_provider_corruption_raises_integrity_error() -> None:
    store = InMemoryEngagementStorage()
    parent = ensure_staging(store, RID).folder.id
    store.corrupt_read_back = lambda data: data[:-1]
    with pytest.raises(StorageIntegrityError):
        put_json(store, parent, "p.json", {"a": 1}, properties={"r": "x"})


# ---- quarantine_staging ---------------------------------------------------------


def test_quarantine_moves_staging_under_quarantine_with_reason() -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)
    put_json(store, staging.folder.id, "p.json", {"a": 1}, properties={"r": "x"})

    moved = quarantine_staging(store, staging, "workspace id differs")

    quarantine = _child(store, staging.preflight_folder_id, QUARANTINE_SEGMENT)
    assert quarantine.properties[IDENTITY_PROPERTY] == "quarantine"
    assert moved.id == staging.folder.id
    assert moved.parent_ids == (quarantine.id,)
    assert moved.properties[QUARANTINE_PROPERTY] == "workspace id differs"
    assert moved.properties[IDENTITY_PROPERTY] == f"staging:{RID}"
    names = [o.name for o in store.list_children(staging.preflight_folder_id)]
    assert RID not in names
    # Contents travel with the folder.
    assert [o.name for o in store.list_children(moved.id)] == ["p.json"]


def test_quarantine_reuses_quarantine_folder_and_caps_reason() -> None:
    store = InMemoryEngagementStorage()
    one = quarantine_staging(store, ensure_staging(store, RID), "x" * 500)
    two = quarantine_staging(store, ensure_staging(store, RID2), "é" * 300)
    assert one.parent_ids == two.parent_ids
    assert one.properties[QUARANTINE_PROPERTY] == "x" * 100
    assert len(two.properties[QUARANTINE_PROPERTY].encode()) <= 100


def test_quarantine_requires_a_reason() -> None:
    store = InMemoryEngagementStorage()
    with pytest.raises(ValueError):
        quarantine_staging(store, ensure_staging(store, RID), "  ")


def test_quarantine_update_dropped_raises_integrity_error() -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)
    store.drop_updates = True
    with pytest.raises(StorageIntegrityError):
        quarantine_staging(store, staging, "host differs")
