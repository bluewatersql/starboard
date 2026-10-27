# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live-run-6 fix: duplicate ``My Drive/starboard`` roots from two first runs at once.

Run 6 started with no ``starboard`` folder; concurrent preflights each created one
(1.5 s apart) before either saw the other, and every later lookup by run ID
stopped with ``STORAGE_ERROR`` "2 folder(s) named 'starboard'". Same-identity
roots now converge on the earliest-created one, and lookups by run ID or account
search every root.
"""

from __future__ import annotations

import pytest
from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    FolderConflictError,
    ensure_folder,
    ensure_starboard_root,
    existing_folders,
    resolve_account_route,
)
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.registry import RegistryNotFoundError, ensure_registry
from starboard_core.engagement.staging import (
    PREFLIGHT_SEGMENT,
    ensure_staging,
    locate_staging,
    quarantine_staging,
)
from starboard_core.ports.engagement_storage import StorageObject

RID = "20261014_9db61567-82a8-4057-b1b4-dbf0b153b0e5"
RID2 = "20261014_eb444f38-aee4-460b-b1fb-f20fdf47414a"
EARLIER = "2000-01-01T00:00:00Z"
ROOT_TAG = {IDENTITY_PROPERTY: "segment:starboard"}


def _roots(store: InMemoryEngagementStorage) -> list[StorageObject]:
    return store.list_children(
        store.root_folder_id(), name="starboard", folders_only=True
    )


def _earlier_root(store: InMemoryEngagementStorage) -> StorageObject:
    """A ``starboard`` root a concurrent session created before ours."""
    return store.add_folder(
        store.root_folder_id(), "starboard", properties=ROOT_TAG, created_time=EARLIER
    )


# ---- existing_folders ----------------------------------------------------------------


def test_existing_folders_empty_when_absent() -> None:
    store = InMemoryEngagementStorage()
    assert (
        existing_folders(
            store, store.root_folder_id(), "starboard", "segment:starboard"
        )
        == []
    )


def test_existing_folders_returns_every_same_identity_folder_winner_first() -> None:
    store = InMemoryEngagementStorage()
    later = store.add_folder(store.root_folder_id(), "starboard", properties=ROOT_TAG)
    earlier = _earlier_root(store)

    found = existing_folders(
        store, store.root_folder_id(), "starboard", "segment:starboard"
    )

    assert [f.id for f in found] == [earlier.id, later.id]


def test_existing_folders_adopts_one_untagged_folder() -> None:
    store = InMemoryEngagementStorage()
    untagged = store.add_folder(store.root_folder_id(), "starboard")
    found = existing_folders(
        store, store.root_folder_id(), "starboard", "segment:starboard"
    )
    assert [f.id for f in found] == [untagged.id]


def test_existing_folders_still_refuses_a_foreign_identity() -> None:
    store = InMemoryEngagementStorage()
    store.add_folder(store.root_folder_id(), "starboard", properties=ROOT_TAG)
    store.add_folder(
        store.root_folder_id(), "starboard", properties={IDENTITY_PROPERTY: "account:x"}
    )
    with pytest.raises(FolderConflictError):
        existing_folders(
            store, store.root_folder_id(), "starboard", "segment:starboard"
        )


def test_existing_folders_never_creates() -> None:
    store = InMemoryEngagementStorage()
    before = store.object_count
    existing_folders(store, store.root_folder_id(), "starboard", "segment:starboard")
    assert store.object_count == before


def test_ensure_folder_converges_on_the_earliest_duplicate() -> None:
    store = InMemoryEngagementStorage()
    store.add_folder(store.root_folder_id(), "starboard", properties=ROOT_TAG)
    earlier = _earlier_root(store)
    got = ensure_folder(store, store.root_folder_id(), "starboard", "segment:starboard")
    assert got.id == earlier.id


# ---- ensure_starboard_root ----------------------------------------------------------


def test_ensure_starboard_root_creates_one_without_warnings() -> None:
    store = InMemoryEngagementStorage()
    root = ensure_starboard_root(store)
    assert [r.id for r in _roots(store)] == [root.folder.id]
    assert root.duplicates == () and root.warnings == ()


def test_ensure_starboard_root_reports_duplicates_and_picks_the_earliest() -> None:
    store = InMemoryEngagementStorage()
    later = store.add_folder(store.root_folder_id(), "starboard", properties=ROOT_TAG)
    earlier = _earlier_root(store)

    root = ensure_starboard_root(store)

    assert root.folder.id == earlier.id
    assert [d.id for d in root.duplicates] == [later.id]
    assert root.all_ids == (earlier.id, later.id)
    (warning,) = root.warnings
    assert warning.startswith("duplicate_starboard_roots:")
    assert earlier.id in warning and later.id in warning
    assert len(_roots(store)) == 2  # nothing trashed or created


# ---- staging lookups by run ID ------------------------------------------------------


def test_locate_staging_finds_a_run_staged_under_the_later_root() -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)  # our root, created first in this store
    _earlier_root(store)  # the other session's root wins on created_time

    found = locate_staging(store, RID)

    assert found.state == "staged"
    assert found.folder is not None and found.folder.id == staging.folder.id
    assert found.preflight_folder_id == staging.preflight_folder_id


def test_locate_staging_finds_a_quarantined_run_under_the_later_root() -> None:
    store = InMemoryEngagementStorage()
    staging = ensure_staging(store, RID)
    quarantine_staging(store, staging, "identity_mismatch")
    _earlier_root(store)

    found = locate_staging(store, RID)

    assert found.state == "quarantined"
    assert found.folder is not None and found.folder.id == staging.folder.id


def test_locate_staging_missing_with_duplicate_roots() -> None:
    store = InMemoryEngagementStorage()
    ensure_staging(store, RID)
    _earlier_root(store)
    assert locate_staging(store, RID2).state == "missing"


def test_locate_staging_rejects_a_bad_run_id() -> None:
    with pytest.raises(ValueError):
        locate_staging(InMemoryEngagementStorage(), "not-a-run")


def test_ensure_staging_reuses_a_folder_under_the_later_root() -> None:
    store = InMemoryEngagementStorage()
    first = ensure_staging(store, RID)
    _earlier_root(store)
    before = store.object_count

    again = ensure_staging(store, RID)

    assert again.folder.id == first.folder.id
    assert again.preflight_folder_id == first.preflight_folder_id
    assert store.object_count == before  # no second staging folder


def test_ensure_staging_puts_a_new_run_under_the_winning_root() -> None:
    store = InMemoryEngagementStorage()
    ensure_staging(store, RID)  # later root holds _preflight
    winner = _earlier_root(store)  # earlier root has no _preflight yet

    staging = ensure_staging(store, RID2)

    (pre,) = store.list_children(winner.id, name=PREFLIGHT_SEGMENT, folders_only=True)
    assert staging.preflight_folder_id == pre.id
    assert staging.folder.parent_ids == (pre.id,)


# ---- account route and registry -----------------------------------------------------


def _route(store: InMemoryEngagementStorage, run_id: str = RID):
    return resolve_account_route(
        store,
        account_key="1444828305810485-opus",
        account_name="e2-demo-field-eng-opus",
        task="health_check",
        task_name="ws-1444828305810485",
        run_id=run_id,
    )


def test_account_route_reuses_an_account_folder_under_the_later_root() -> None:
    store = InMemoryEngagementStorage()
    first = _route(store, RID)
    _earlier_root(store)

    second = _route(store, RID2)

    assert second.account_folder_id == first.account_folder_id
    assert any(w.startswith("duplicate_starboard_roots:") for w in second.warnings)


def test_account_route_creates_a_new_account_under_the_winning_root() -> None:
    store = InMemoryEngagementStorage()
    store.add_folder(store.root_folder_id(), "starboard", properties=ROOT_TAG)
    winner = _earlier_root(store)

    route = _route(store)

    account = store.get(route.account_folder_id)
    assert account.parent_ids == (winner.id,)
    assert route.path_names[1] == "starboard"


def test_registry_finds_the_account_under_the_later_root() -> None:
    store = InMemoryEngagementStorage()
    _route(store, RID)
    ensure_registry(
        store, "1444828305810485-opus", account_name="e2-demo-field-eng-opus"
    )
    _earlier_root(store)
    warnings: list[str] = []

    handles = ensure_registry(store, "1444828305810485-opus", warnings=warnings)

    assert handles  # found without an account name: nothing was recreated
    assert any(w.startswith("duplicate_starboard_roots:") for w in warnings)


def test_registry_without_a_name_still_reports_a_missing_account() -> None:
    store = InMemoryEngagementStorage()
    store.add_folder(store.root_folder_id(), "starboard", properties=ROOT_TAG)
    _earlier_root(store)
    with pytest.raises(RegistryNotFoundError):
        ensure_registry(store, "1444828305810485-opus")


# ---- review follow-ups ----------------------------------------------------------------


class _CountingStore(InMemoryEngagementStorage):
    """Counts ``list_children`` calls (the Drive list requests that cost latency)."""

    lists = 0

    def list_children(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.lists += 1
        return super().list_children(*args, **kwargs)


def test_first_ever_staging_lists_once_per_level() -> None:
    store = _CountingStore()
    ensure_staging(store, RID)
    # starboard, _preflight, run folder: one list each, plus one read-back per create.
    assert store.lists == 4


def test_new_run_staging_with_one_root_lists_once_per_level() -> None:
    store = _CountingStore()
    ensure_staging(store, RID)
    store.lists = 0
    ensure_staging(store, RID2)
    # roots, _preflight, the run ID (none yet), the new folder's read-back.
    assert store.lists == 4


def test_locate_staging_with_one_root_stays_cheap() -> None:
    store = _CountingStore()
    ensure_staging(store, RID)
    store.lists = 0
    assert locate_staging(store, RID).state == "staged"
    # roots, _preflight, _quarantine (none), the run ID.
    assert store.lists == 4


def test_two_preflight_folders_under_one_root_are_both_searched() -> None:
    store = InMemoryEngagementStorage()
    ensure_staging(store, RID)
    (root,) = _roots(store)
    other = store.add_folder(
        root.id,
        PREFLIGHT_SEGMENT,
        properties={IDENTITY_PROPERTY: "preflight"},
        created_time=EARLIER,
    )
    staging = ensure_staging(store, RID2)  # new runs go to the winning _preflight
    assert staging.preflight_folder_id == other.id

    found = locate_staging(store, RID)  # the earlier run, under the later _preflight

    assert found.state == "staged"
    assert found.preflight_folder_id != other.id


def test_account_folders_under_both_roots_warn_with_both_parents() -> None:
    store = InMemoryEngagementStorage()
    first = _route(store, RID)
    later_root = store.get(first.account_folder_id).parent_ids[0]
    winner = _earlier_root(store)
    store.add_folder(
        winner.id,
        "e2-demo-field-eng-opus",
        properties={IDENTITY_PROPERTY: "account:1444828305810485-opus"},
        created_time=EARLIER,
    )

    second = _route(store, RID2)

    dup = [w for w in second.warnings if w.startswith("duplicate_account_folders:")]
    assert len(dup) == 1
    assert winner.id in dup[0] and later_root in dup[0]
    assert store.get(second.account_folder_id).parent_ids == (winner.id,)


def test_registry_merges_account_folders_across_roots() -> None:
    store = InMemoryEngagementStorage()
    _route(store, RID)
    ensure_registry(
        store, "1444828305810485-opus", account_name="e2-demo-field-eng-opus"
    )
    winner = _earlier_root(store)
    store.add_folder(
        winner.id,
        "e2-demo-field-eng-opus",
        properties={IDENTITY_PROPERTY: "account:1444828305810485-opus"},
        created_time=EARLIER,
    )
    _route(store, RID2)
    ensure_registry(
        store, "1444828305810485-opus", account_name="e2-demo-field-eng-opus"
    )

    handles = ensure_registry(store, "1444828305810485-opus", include_duplicates=True)

    assert len({h.folder_id for h in handles}) == 2  # one registry under each root
