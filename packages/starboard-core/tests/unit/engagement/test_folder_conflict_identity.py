"""A folder-name conflict carries the existing folder's identity (run-3 B2-2)."""

from __future__ import annotations

import pytest
from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    FolderConflictError,
    ensure_account_folder,
    ensure_folder,
)
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage


def test_name_owned_by_one_other_account_names_its_key() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    other = store.add_folder(
        root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:1444828305810485"}
    )
    with pytest.raises(FolderConflictError) as exc:
        ensure_account_folder(store, root, "Acme Corp", "Acme Corp")
    err = exc.value
    assert err.other_account_key == "1444828305810485"
    assert err.existing_identities == ("account:1444828305810485",)
    assert err.object_ids == (other.id,)
    message = str(err)
    assert "belongs to account key '1444828305810485'" in message
    assert "--account-key 1444828305810485" in message
    assert "--account-name" in message
    assert "reconcile" not in message


def test_untagged_or_several_folders_keep_the_reconcile_message() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.add_folder(root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:A"})
    store.add_folder(root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:B"})
    with pytest.raises(FolderConflictError) as exc:
        ensure_folder(store, root, "Acme Corp", "account:C")
    assert exc.value.other_account_key is None
    assert "reconcile in Drive" in str(exc.value)
    assert sorted(i or "" for i in exc.value.existing_identities) == [
        "account:A",
        "account:B",
    ]


def test_non_account_identity_has_no_other_account_key() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.add_folder(root, "health_check", properties={IDENTITY_PROPERTY: "segment:x"})
    with pytest.raises(FolderConflictError) as exc:
        ensure_folder(store, root, "health_check", "segment:health_check")
    assert exc.value.other_account_key is None


def test_existing_identities_default_empty() -> None:
    err = FolderConflictError(
        "x", parent_id="p", name="n", identity_key="account:a", object_ids=["f1"]
    )
    assert err.existing_identities == () and err.other_account_key is None
