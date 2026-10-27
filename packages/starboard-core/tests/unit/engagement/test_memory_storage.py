# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the in-memory engagement storage fake."""

from __future__ import annotations

import hashlib

import pytest
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.ports.engagement_storage import (
    FOLDER_MIME,
    EngagementStoragePort,
    Grant,
    StorageAuthError,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StoragePermissionError,
)


def test_satisfies_port_protocol() -> None:
    assert isinstance(InMemoryEngagementStorage(), EngagementStoragePort)


def test_configurable_root_id_and_my_drive_kind() -> None:
    store = InMemoryEngagementStorage(root_id="my-root")
    assert store.root_folder_id() == "my-root"
    root = store.get("my-root")
    assert root.is_folder
    access = store.inspect_access("my-root")
    assert access.drive_kind == "my_drive"
    assert access.drive_id is None
    assert access.can_add_children is True


def test_create_and_list_children_by_name_and_kind() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    folder = store.create_folder(root, "alpha", {"k": "v"})
    store.create_folder(root, "beta", {})
    store.put_stream(root, "alpha", "text/plain", [b"x"], properties={})

    assert folder.mime_type == FOLDER_MIME
    assert folder.parent_ids == (root,)
    assert dict(folder.properties) == {"k": "v"}
    assert folder.web_link
    assert [o.name for o in store.list_children(root)] == ["alpha", "beta", "alpha"]
    named = store.list_children(root, name="alpha", folders_only=True)
    assert [o.id for o in named] == [folder.id]


def test_put_get_round_trip_computes_size_and_md5() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    chunks = [b"hello ", b"world", b""]
    obj = store.put_stream(root, "f.txt", "text/plain", chunks, properties={"a": "b"})

    assert obj.size == 11
    assert obj.md5 == hashlib.md5(b"hello world").hexdigest()  # noqa: S324
    assert obj.revision
    assert not obj.is_folder
    assert b"".join(store.get_stream(obj.id)) == b"hello world"
    assert b"".join(store.get_stream(obj.id, obj.revision)) == b"hello world"
    assert store.get(obj.id) == obj


def test_get_stream_unknown_revision_not_found() -> None:
    store = InMemoryEngagementStorage()
    obj = store.put_stream(
        store.root_folder_id(), "f", "text/plain", [b"x"], properties={}
    )
    with pytest.raises(StorageNotFoundError):
        list(store.get_stream(obj.id, "no-such-revision"))


def test_corrupt_read_back_raises_integrity_error() -> None:
    store = InMemoryEngagementStorage()
    store.corrupt_read_back = lambda data: data[:-1]
    with pytest.raises(StorageIntegrityError):
        store.put_stream(
            store.root_folder_id(), "f", "text/plain", [b"abc"], properties={}
        )


def test_unknown_object_not_found() -> None:
    store = InMemoryEngagementStorage()
    with pytest.raises(StorageNotFoundError):
        store.get("missing")
    with pytest.raises(StorageNotFoundError):
        store.create_folder("missing", "x", {})


def test_auth_failed_raises_on_every_operation() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.auth_failed = True
    with pytest.raises(StorageAuthError):
        store.root_folder_id()
    with pytest.raises(StorageAuthError):
        store.list_children(root)
    with pytest.raises(StorageAuthError):
        store.create_folder(root, "x", {})
    with pytest.raises(StorageAuthError):
        store.inspect_access(root)
    with pytest.raises(StorageAuthError):
        store.put_stream(root, "f", "text/plain", [b"x"], properties={})


def test_deny_writes_under_covers_descendants() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    top = store.create_folder(root, "top", {})
    child = store.create_folder(top.id, "child", {})
    store.deny_writes_under = {top.id}
    with pytest.raises(StoragePermissionError):
        store.create_folder(child.id, "grandchild", {})
    with pytest.raises(StoragePermissionError):
        store.put_stream(top.id, "f", "text/plain", [b"x"], properties={})
    # Siblings outside the denied subtree stay writable.
    store.create_folder(root, "other", {})


def test_can_add_children_false_blocks_writes_and_is_reported() -> None:
    store = InMemoryEngagementStorage()
    folder = store.add_folder(store.root_folder_id(), "ro", can_add_children=False)
    assert store.inspect_access(folder.id).can_add_children is False
    with pytest.raises(StoragePermissionError):
        store.create_folder(folder.id, "x", {})


def test_shared_drive_access_inherits_grants() -> None:
    store = InMemoryEngagementStorage()
    grants = (
        Grant("user", "fileOrganizer", "example.com"),
        Grant("group", "writer", "example.com"),
    )
    shared = store.add_shared_drive(
        "asqs-root", "ASQs", drive_id="drive-1", grants=grants
    )
    child = store.create_folder(shared.id, "acct", {})
    store.set_access(child.id, grants=(Grant("anyone", "reader"),))

    root_access = store.inspect_access(shared.id)
    assert root_access.drive_kind == "shared_drive"
    assert root_access.drive_id == "drive-1"
    assert set(root_access.grants) == set(grants)

    child_access = store.inspect_access(child.id)
    assert child_access.drive_kind == "shared_drive"
    assert set(child_access.grants) == {*grants, Grant("anyone", "reader")}
    assert (
        child_access.fingerprint and child_access.fingerprint != root_access.fingerprint
    )


def test_set_access_incomplete() -> None:
    store = InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), "x", {})
    store.set_access(folder.id, complete=False)
    assert store.inspect_access(folder.id).complete is False


def test_duplicate_on_create_injects_one_concurrent_twin() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.duplicate_on_create = {"dup"}
    created = store.create_folder(root, "dup", {"id": "1"})
    twins = store.list_children(root, name="dup", folders_only=True)
    assert len(twins) == 2
    assert created.id in {t.id for t in twins}
    assert all(dict(t.properties) == {"id": "1"} for t in twins)
    # One-shot: a later create of the same name does not duplicate again.
    store.create_folder(root, "dup", {"id": "2"})
    assert len(store.list_children(root, name="dup")) == 3


def test_object_count_tracks_created_objects() -> None:
    store = InMemoryEngagementStorage()
    before = store.object_count
    store.create_folder(store.root_folder_id(), "x", {})
    assert store.object_count == before + 1


# ---- principal_id / update / update_stream ------------------------------------------


def test_principal_id_is_opaque_and_configurable() -> None:
    assert "@" not in InMemoryEngagementStorage().principal_id()
    assert InMemoryEngagementStorage(principal_id="perm-9").principal_id() == "perm-9"


def test_update_renames_and_merges_properties() -> None:
    store = InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), "a", {"k": "v", "x": "1"})
    updated = store.update(folder.id, name="b", properties={"x": "2", "y": "3"})
    assert updated.name == "b"
    assert dict(updated.properties) == {"k": "v", "x": "2", "y": "3"}
    assert store.get(folder.id) == updated


def test_update_moves_between_parents() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    src = store.create_folder(root, "src", {})
    dst = store.create_folder(root, "dst", {})
    item = store.create_folder(src.id, "item", {})
    moved = store.update(item.id, add_parent_id=dst.id, remove_parent_id=src.id)
    assert moved.parent_ids == (dst.id,)
    assert store.list_children(src.id) == []
    assert [o.id for o in store.list_children(dst.id)] == [item.id]


def test_update_move_rejects_bad_moves() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    a = store.create_folder(root, "a", {})
    b = store.create_folder(a.id, "b", {})
    with pytest.raises(StorageError):
        store.update(a.id, add_parent_id=b.id, remove_parent_id=root)  # cycle
    with pytest.raises(StorageError):
        store.update(b.id, remove_parent_id=root)  # not a parent
    with pytest.raises(StorageError):
        store.update(b.id, remove_parent_id=a.id)  # would orphan it
    with pytest.raises(StorageNotFoundError):
        store.update(b.id, add_parent_id="missing", remove_parent_id=a.id)


def test_update_respects_write_denials_and_auth() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    a = store.create_folder(root, "a", {})
    ro = store.add_folder(root, "ro", can_add_children=False)
    with pytest.raises(StoragePermissionError):
        store.update(a.id, add_parent_id=ro.id, remove_parent_id=root)
    store.deny_writes_under = {a.id}
    with pytest.raises(StoragePermissionError):
        store.update(a.id, name="z")
    store.deny_writes_under = set()
    store.auth_failed = True
    with pytest.raises(StorageAuthError):
        store.update(a.id, name="z")
    with pytest.raises(StorageAuthError):
        store.principal_id()


def test_update_dropped_by_provider_raises_integrity_error() -> None:
    store = InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), "a", {})
    store.drop_updates = True
    with pytest.raises(StorageIntegrityError):
        store.update(folder.id, properties={"q": "1"})
    assert dict(store.get(folder.id).properties) == {}


def test_update_stream_creates_new_revision_and_keeps_old() -> None:
    store = InMemoryEngagementStorage()
    obj = store.put_stream(
        store.root_folder_id(), "f.txt", "text/plain", [b"one"], properties={"p": "1"}
    )
    new = store.update_stream(obj.id, "text/plain", [b"two", b"!"])
    assert new.id == obj.id
    assert new.revision and new.revision != obj.revision
    assert new.size == 4
    assert new.md5 == hashlib.md5(b"two!").hexdigest()  # noqa: S324
    assert dict(new.properties) == {"p": "1"}
    assert b"".join(store.get_stream(obj.id)) == b"two!"
    assert b"".join(store.get_stream(obj.id, obj.revision)) == b"one"
    assert b"".join(store.get_stream(obj.id, new.revision)) == b"two!"
    assert store.object_count == 2  # root + the file: updated in place


def test_update_stream_rejects_folders_and_denied_writes() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    folder = store.create_folder(root, "d", {})
    with pytest.raises(StorageError):
        store.update_stream(folder.id, "text/plain", [b"x"])
    obj = store.put_stream(folder.id, "f", "text/plain", [b"x"], properties={})
    store.deny_writes_under = {folder.id}
    with pytest.raises(StoragePermissionError):
        store.update_stream(obj.id, "text/plain", [b"y"])
    store.deny_writes_under = set()
    with pytest.raises(TypeError):
        store.update_stream(obj.id, "text/plain", ["str"])  # type: ignore[list-item]


def test_update_stream_corrupt_read_back_raises() -> None:
    store = InMemoryEngagementStorage()
    obj = store.put_stream(
        store.root_folder_id(), "f", "text/plain", [b"x"], properties={}
    )
    store.corrupt_read_back = lambda data: data + b"?"
    with pytest.raises(StorageIntegrityError):
        store.update_stream(obj.id, "text/plain", [b"y"])


def test_corrupt_get_stream_changes_downloaded_bytes_only() -> None:
    store = InMemoryEngagementStorage()
    obj = store.put_stream(
        store.root_folder_id(), "f", "text/plain", [b"abc"], properties={}
    )
    store.corrupt_get_stream = lambda data: data.upper()
    assert b"".join(store.get_stream(obj.id)) == b"ABC"
    assert store.get(obj.id).md5 == hashlib.md5(b"abc").hexdigest()  # noqa: S324


def test_duplicate_on_put_injects_one_concurrent_twin() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.duplicate_on_put = {"rev.json"}
    obj = store.put_stream(
        root, "rev.json", "application/json", [b"{}"], properties={"m": "1"}
    )
    twins = store.list_children(root, name="rev.json")
    assert len(twins) == 2 and obj.id in {t.id for t in twins}
    assert all(dict(t.properties) == {"m": "1"} for t in twins)
    store.put_stream(root, "rev.json", "application/json", [b"{}"], properties={})
    assert len(store.list_children(root, name="rev.json")) == 3


# --- phase-2 fault injection ---------------------------------------------------------


def test_fail_put_after_counts_from_when_it_is_set() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.put_stream(root, "seed", "text/plain", [b"s"], properties={})
    store.fail_put_after = 2
    assert store.fail_put_after == 2
    first = store.put_stream(root, "a", "text/plain", [b"a"], properties={})
    store.update_stream(first.id, "text/plain", [b"a2"])
    before = store.object_count
    with pytest.raises(StorageError) as info:
        store.put_stream(root, "b", "text/plain", [b"b"], properties={})
    assert not isinstance(info.value, StoragePermissionError | StorageIntegrityError)
    with pytest.raises(StorageError):
        store.update_stream(first.id, "text/plain", [b"a3"])
    assert store.object_count == before  # the failed put stored nothing
    assert b"".join(store.get_stream(first.id)) == b"a2"
    # Folders and metadata updates are not puts.
    store.create_folder(root, "d", {})
    store.update(first.id, properties={"k": "v"})
    store.fail_put_after = None
    store.put_stream(root, "b", "text/plain", [b"b"], properties={})


def test_fail_put_after_zero_fails_the_next_put() -> None:
    store = InMemoryEngagementStorage()
    store.fail_put_after = 0
    with pytest.raises(StorageError):
        store.put_stream(
            store.root_folder_id(), "a", "text/plain", [b"a"], properties={}
        )


def test_revoke_access_after_writes() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    folder = store.create_folder(root, "run", {})
    store.revoke_access_after_writes = 2
    assert store.revoke_access_after_writes == 2
    assert store.inspect_access(folder.id).can_add_children is True
    obj = store.put_stream(folder.id, "a", "text/plain", [b"a"], properties={})
    store.create_folder(folder.id, "sub", {})  # second write: access now revoked
    access = store.inspect_access(folder.id)
    assert access.can_add_children is False
    assert access.complete is True
    with pytest.raises(StoragePermissionError):
        store.put_stream(folder.id, "b", "text/plain", [b"b"], properties={})
    with pytest.raises(StoragePermissionError):
        store.update_stream(obj.id, "text/plain", [b"a2"])
    with pytest.raises(StoragePermissionError):
        store.create_folder(folder.id, "sub2", {})
    with pytest.raises(StoragePermissionError):
        store.update(obj.id, name="renamed")
    # Reads still work.
    assert b"".join(store.get_stream(obj.id)) == b"a"
    assert store.list_children(folder.id, name="a")
    store.revoke_access_after_writes = None
    assert store.inspect_access(folder.id).can_add_children is True


def test_revoke_access_after_zero_writes_revokes_immediately() -> None:
    store = InMemoryEngagementStorage()
    store.revoke_access_after_writes = 0
    assert store.inspect_access(store.root_folder_id()).can_add_children is False
    with pytest.raises(StoragePermissionError):
        store.create_folder(store.root_folder_id(), "x", {})


def test_corrupt_object_changes_stored_bytes_but_not_metadata() -> None:
    store = InMemoryEngagementStorage()
    obj = store.put_stream(
        store.root_folder_id(), "f", "text/plain", [b"abc"], properties={}
    )
    store.corrupt_object(obj.id)
    got = b"".join(store.get_stream(obj.id))
    assert got != b"abc"
    assert len(got) == 3
    assert store.get(obj.id) == obj
    assert b"".join(store.get_stream(obj.id, obj.revision)) == got


def test_corrupt_object_handles_empty_content_and_rejects_folders() -> None:
    store = InMemoryEngagementStorage()
    empty = store.put_stream(
        store.root_folder_id(), "e", "text/plain", [b""], properties={}
    )
    store.corrupt_object(empty.id)
    assert b"".join(store.get_stream(empty.id)) != b""
    folder = store.create_folder(store.root_folder_id(), "d", {})
    with pytest.raises(StorageError):
        store.corrupt_object(folder.id)
    with pytest.raises(StorageNotFoundError):
        store.corrupt_object("missing")


def test_find_by_property_is_scoped_to_the_drive_and_skips_trashed() -> None:
    store = InMemoryEngagementStorage()
    mine = store.create_folder(store.root_folder_id(), "run", {"k": "v"})
    kept = store.put_stream(mine.id, "a", "text/plain", [b"a"], properties={"k": "v"})
    gone = store.put_stream(mine.id, "b", "text/plain", [b"b"], properties={"k": "v"})
    store.put_stream(mine.id, "c", "text/plain", [b"c"], properties={"k": "other"})
    shared = store.add_shared_drive("sd-root", "ASQs", drive_id="drive-1")
    theirs = store.create_folder(shared.id, "run", {"k": "v"})

    store.trash(gone.id)

    assert {o.id for o in store.find_by_property("k", "v")} == {mine.id, kept.id}
    assert [o.id for o in store.find_by_property("k", "v", drive_id="drive-1")] == [
        theirs.id
    ]
    assert gone.id not in {c.id for c in store.list_children(mine.id)}


def test_trash_respects_write_denials_and_auth() -> None:
    store = InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), "x", {})
    f = store.put_stream(folder.id, "f", "text/plain", [b"x"], properties={})
    store.deny_writes_under = {folder.id}
    with pytest.raises(StoragePermissionError):
        store.trash(f.id)
    store.deny_writes_under = set()
    store.auth_failed = True
    with pytest.raises(StorageAuthError):
        store.trash(f.id)
    store.auth_failed = False
    with pytest.raises(StorageNotFoundError):
        store.trash("missing")
