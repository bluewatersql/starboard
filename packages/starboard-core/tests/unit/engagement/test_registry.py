# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the account registry (phase-2 spec P2-G5, D-15..D-17)."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from starboard_core.engagement.commit import write_descriptor
from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    FolderResolution,
    resolve_account_route,
    resolve_override_route,
    resolve_ticket_route,
)
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.records import (
    AccountRef,
    DriveContext,
    Registration,
    RunAuthorization,
    registration_id,
)
from starboard_core.engagement.registry import (
    INDEX_SEGMENT,
    REGISTRATION_PROPERTY,
    REGISTRATIONS_SEGMENT,
    REGISTRY_SEGMENT,
    IndexEntry,
    RegistrationConflictError,
    RegistryHandle,
    RegistryNotFoundError,
    ensure_registry,
    list_registrations,
    read_index,
    rebuild_index,
    register,
)
from starboard_core.engagement.staging import encode_json
from starboard_core.ports.engagement_storage import (
    Grant,
    StorageAuthError,
    StoragePermissionError,
)

INTERNAL = frozenset({"example.com"})
STAFF = (Grant("user", "fileOrganizer", "example.com"),)
ACCOUNT = "001ACME"
NAME = "Acme Corp"
SHARED_REG = "shared-registry-root"
TICKET_ROOT = "asqs-root"
OVERRIDE = "override-folder"


def rid(n: int) -> str:
    return f"2026100{n}_12345678-1234-4234-8234-12345678{n:04d}"


def _store() -> InMemoryEngagementStorage:
    store = InMemoryEngagementStorage(root_id="my-root", owner_domain="example.com")
    for folder_id, name in (
        (SHARED_REG, "Registry"),
        (TICKET_ROOT, "ASQs"),
        (OVERRIDE, "Handoff"),
    ):
        store.add_shared_drive(folder_id, name, drive_id=f"d-{folder_id}", grants=STAFF)
    return store


def _registration(res: FolderResolution, run_id: str, **over: Any) -> Registration:
    base: dict[str, Any] = {
        "registration_id": registration_id(run_id),
        "kind": "run",
        "run_id": run_id,
        "engagement_id": f"{ACCOUNT}/review/wh",
        "account_key": ACCOUNT,
        "task": "review",
        "task_name": "wh",
        "route": res.route,
        "source_mode": SourceMode.CUSTOMER_WORKSPACE,
        "storage_policy": StoragePolicy.DRIVE_REQUIRED,
        "run_folder_id": res.run_folder_id,
        "descriptor_ref": None,
        "observation_summary_ref": None,
        "acl_classification": "internal_only",
        "principal_id": "perm-owner-0001",
        "registered_at": "2026-10-08T09:00:00+00:00",
        "provenance": {"origin": "drive_run"},
    }
    base.update(over)
    return Registration(**base)


def _authorize(
    store: InMemoryEngagementStorage, res: FolderResolution, run_id: str
) -> None:
    fp = store.inspect_access(res.run_folder_id).fingerprint
    drive = DriveContext(
        provider="google_drive",
        principal="perm-owner-0001",
        route=res.route,
        base_folder_id=res.base_id,
        root_folder_id=res.base_id,
        run_folder_id=res.run_folder_id,
        registry_folder_id="reg",
        account_key=ACCOUNT,
        acl_classification="internal_only",
        permission_fingerprints={res.run_folder_id: fp},
        capabilities={"upload": True},
        created_at="2026-10-08T09:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
    )
    write_descriptor(
        store,
        res.run_folder_id,
        RunAuthorization(
            engagement_id=f"{ACCOUNT}/review/wh",
            run_id=run_id,
            intent="health_check",
            task="review",
            account=AccountRef(id=ACCOUNT, display_name=NAME, verifier="operator"),
            requested_scope={},
            authorized_scope={"account_key": ACCOUNT},
            reporting_interval="P30D",
            timezone="UTC",
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            audience="internal",
            methodology_version="m1",
            drive=drive,
        ),
    )


def _account_run(store: InMemoryEngagementStorage, run_id: str) -> FolderResolution:
    res = resolve_account_route(
        store,
        account_key=ACCOUNT,
        account_name=NAME,
        task="review",
        task_name="wh",
        run_id=run_id,
    )
    _authorize(store, res, run_id)
    return res


def _operator(store: InMemoryEngagementStorage) -> RegistryHandle:
    (handle,) = ensure_registry(store, ACCOUNT, account_name=NAME)
    return handle


# --- ensure_registry ------------------------------------------------------------------


def test_operator_registry_lives_under_the_account_route_folder() -> None:
    store = _store()
    res = _account_run(store, rid(1))
    handle = _operator(store)
    assert handle.location == "operator"
    assert handle.account_key == ACCOUNT
    registry = store.get(handle.folder_id)
    assert registry.name == REGISTRY_SEGMENT
    assert registry.parent_ids == (res.account_folder_id,)
    assert store.get(handle.registrations_folder_id).name == REGISTRATIONS_SEGMENT
    assert store.get(handle.index_folder_id).name == INDEX_SEGMENT
    assert handle.fingerprint == handle.access.fingerprint
    assert handle.access.object_id == handle.folder_id


def test_ensure_registry_is_idempotent() -> None:
    store = _store()
    first = _operator(store)
    count = store.object_count
    assert _operator(store) == first
    assert store.object_count == count


def test_ensure_registry_finds_the_account_folder_by_identity_without_a_name() -> None:
    store = _store()
    first = _operator(store)
    (again,) = ensure_registry(store, ACCOUNT)
    assert again.folder_id == first.folder_id


def test_ensure_registry_with_a_name_finds_the_differently_named_identity_folder() -> (
    None
):
    store = _store()
    root = store.root_folder_id()
    starboard = store.add_folder(
        root, "starboard", properties={IDENTITY_PROPERTY: "segment:starboard"}
    )
    folder = store.add_folder(
        starboard.id, "Acme Inc", properties={IDENTITY_PROPERTY: f"account:{ACCOUNT}"}
    )
    notes: list[str] = []
    (handle,) = ensure_registry(store, ACCOUNT, account_name="X Corp", warnings=notes)
    assert store.get(handle.folder_id).parent_ids == (folder.id,)
    assert not store.list_children(starboard.id, name="X Corp", folders_only=True)
    assert any(n.startswith("account_name_differs:") for n in notes)


class _HidingStore(InMemoryEngagementStorage):
    """Hides chosen objects from listings (an eventually-consistent sibling)."""

    def __init__(self) -> None:
        super().__init__(root_id="my-root", owner_domain="example.com")
        self.hidden: set[str] = set()

    def list_children(self, parent_id, *, name=None, folders_only=False):  # type: ignore[no-untyped-def]
        out = super().list_children(parent_id, name=name, folders_only=folders_only)
        return [o for o in out if o.id not in self.hidden]


def test_duplicate_account_folders_write_to_the_earliest_and_reads_merge() -> None:
    store = _HidingStore()
    root = store.root_folder_id()
    starboard = store.add_folder(
        root, "starboard", properties={IDENTITY_PROPERTY: "segment:starboard"}
    )
    earliest = store.add_folder(
        starboard.id, "Acme Old", properties={IDENTITY_PROPERTY: f"account:{ACCOUNT}"}
    )
    store.hidden = {earliest.id}
    late_run = _account_run(store, rid(2))
    register(store, _operator(store), _registration(late_run, rid(2)))
    store.hidden = set()
    early_run = _account_run(store, rid(1))
    assert early_run.account_folder_id == earliest.id
    notes: list[str] = []
    (writer,) = ensure_registry(store, ACCOUNT, account_name=NAME, warnings=notes)
    assert store.get(writer.folder_id).parent_ids == (earliest.id,)
    register(store, writer, _registration(early_run, rid(1)))
    assert any(n.startswith("duplicate_account_folders:") for n in notes)

    count = store.object_count
    handles = ensure_registry(store, ACCOUNT, include_duplicates=True)
    assert store.object_count == count  # reads never create
    assert [store.get(h.folder_id).parent_ids for h in handles] == [
        (earliest.id,),
        (late_run.account_folder_id,),
    ]
    views = list_registrations(store, handles, account_key=ACCOUNT)
    assert {v.registration.run_id for v in views if v.registration} == {rid(1), rid(2)}
    assert all(v.status == "ok" for v in views)


def test_ensure_registry_without_name_or_folder_is_not_found() -> None:
    store = _store()
    count = store.object_count
    with pytest.raises(RegistryNotFoundError):
        ensure_registry(store, ACCOUNT)
    assert store.object_count <= count + 1  # at most the shared `starboard` folder


def test_shared_registry_skipped_without_config() -> None:
    store = _store()
    warnings: list[str] = []
    handles = ensure_registry(store, ACCOUNT, account_name=NAME, warnings=warnings)
    assert [h.location for h in handles] == ["operator"]
    assert warnings == []
    assert store.list_children(SHARED_REG) == []


def test_shared_registry_written_when_preflight_passes() -> None:
    store = _store()
    handles = ensure_registry(
        store,
        ACCOUNT,
        account_name=NAME,
        shared_root_id=SHARED_REG,
        internal_domains=INTERNAL,
    )
    assert [h.location for h in handles] == ["operator", "shared"]
    shared = handles[1]
    (account,) = store.list_children(SHARED_REG)
    assert account.properties[IDENTITY_PROPERTY] == f"account:{ACCOUNT}"
    assert store.get(shared.folder_id).parent_ids == (account.id,)


@pytest.mark.parametrize(
    "problem", ["not_writable", "widened", "missing", "no_domains"]
)
def test_shared_registry_skipped_with_warning_when_preflight_fails(
    problem: str,
) -> None:
    store = _store()
    domains = INTERNAL
    root = SHARED_REG
    if problem == "not_writable":
        store.set_access(SHARED_REG, can_add_children=False)
    elif problem == "widened":
        store.set_access(SHARED_REG, grants=(Grant("anyone", "reader"),))
    elif problem == "missing":
        root = "no-such-folder"
    else:
        domains = frozenset()
    warnings: list[str] = []
    handles = ensure_registry(
        store,
        ACCOUNT,
        account_name=NAME,
        shared_root_id=root,
        internal_domains=domains,
        warnings=warnings,
    )
    assert [h.location for h in handles] == ["operator"]
    assert len(warnings) == 1 and "shared registry" in warnings[0]
    assert store.list_children(SHARED_REG) == []


def test_ensure_registry_auth_error_propagates() -> None:
    store = _store()
    store.auth_failed = True
    with pytest.raises(StorageAuthError):
        ensure_registry(store, ACCOUNT, account_name=NAME)


# --- register -------------------------------------------------------------------------


def test_account_ticket_and_override_runs_all_register_under_the_operator_registry() -> (
    None
):
    store = _store()
    acct = _account_run(store, rid(1))
    ticket = resolve_ticket_route(
        store,
        shared_root_id=TICKET_ROOT,
        account_key=ACCOUNT,
        account_name=NAME,
        ar_key="AR-000123456",
        ticket_title="Spike",
        task="review",
        task_name="wh",
        run_id=rid(2),
        internal_domains=INTERNAL,
    )
    _authorize(store, ticket, rid(2))
    override = resolve_override_route(
        store,
        override_folder_id=OVERRIDE,
        account_key=ACCOUNT,
        account_name=NAME,
        task="review",
        task_name="wh",
        run_id=rid(3),
        internal_domains=INTERNAL,
    )
    _authorize(store, override, rid(3))
    assert {acct.route, ticket.route, override.route} == {
        "account",
        "ticket",
        "override",
    }
    handle = _operator(store)
    for res, run_id in ((acct, rid(1)), (ticket, rid(2)), (override, rid(3))):
        obj = register(store, handle, _registration(res, run_id))
        assert obj.name == f"{registration_id(run_id)}.json"
        assert obj.properties[REGISTRATION_PROPERTY] == registration_id(run_id)
        assert obj.parent_ids == (handle.registrations_folder_id,)
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    assert [v.status for v in views] == ["ok", "ok", "ok"]
    assert sorted(v.registration.route for v in views if v.registration) == [
        "account",
        "override",
        "ticket",
    ]


def test_register_writes_encoded_registration_bytes() -> None:
    store = _store()
    res = _account_run(store, rid(1))
    handle = _operator(store)
    reg = _registration(res, rid(1))
    obj = register(store, handle, reg)
    assert b"".join(store.get_stream(obj.id)) == encode_json(reg.to_dict())


def test_duplicate_register_with_equal_bytes_is_a_no_op() -> None:
    store = _store()
    res = _account_run(store, rid(1))
    handle = _operator(store)
    first = register(store, handle, _registration(res, rid(1)))
    count = store.object_count
    again = register(store, handle, _registration(res, rid(1)))
    assert again.id == first.id
    assert again.revision == first.revision
    assert store.object_count == count


def test_duplicate_register_with_different_bytes_conflicts() -> None:
    store = _store()
    res = _account_run(store, rid(1))
    handle = _operator(store)
    register(store, handle, _registration(res, rid(1)))
    count = store.object_count
    with pytest.raises(RegistrationConflictError):
        register(
            store,
            handle,
            _registration(res, rid(1), registered_at="2026-10-09T09:00:00+00:00"),
        )
    assert store.object_count == count


def test_concurrent_duplicate_register_conflicts() -> None:
    store = _store()
    res = _account_run(store, rid(1))
    handle = _operator(store)
    store.duplicate_on_put = {f"{registration_id(rid(1))}.json"}
    with pytest.raises(RegistrationConflictError):
        register(store, handle, _registration(res, rid(1)))


def test_register_rejects_another_accounts_registration() -> None:
    store = _store()
    res = _account_run(store, rid(1))
    handle = _operator(store)
    with pytest.raises(ValueError):
        register(store, handle, _registration(res, rid(1), account_key="OTHER"))


def test_register_refuses_when_registry_access_changed() -> None:
    store = _store()
    res = _account_run(store, rid(1))
    handle = _operator(store)
    store.set_access(handle.folder_id, grants=(Grant("user", "reader", "other.com"),))
    count = store.object_count
    with pytest.raises(StoragePermissionError):
        register(store, handle, _registration(res, rid(1)))
    assert store.object_count == count


# --- list_registrations ---------------------------------------------------------------


def _registered(
    n: int = 2,
) -> tuple[InMemoryEngagementStorage, RegistryHandle, list[FolderResolution]]:
    store = _store()
    runs = [_account_run(store, rid(i)) for i in range(1, n + 1)]
    handle = _operator(store)
    for i, res in enumerate(runs, start=1):
        register(store, handle, _registration(res, rid(i)))
    return store, handle, runs


def test_list_registrations_filters_by_task() -> None:
    store, handle, runs = _registered()
    other = _registration(
        runs[0],
        rid(3),
        task="workspace",
        run_folder_id=runs[0].run_folder_id,
    )
    register(store, handle, other)
    views = list_registrations(store, (handle,), account_key=ACCOUNT, tasks=("review",))
    assert {v.registration.run_id for v in views if v.registration} == {rid(1), rid(2)}


def test_revoked_target_acl_gives_history_unavailable() -> None:
    store, handle, runs = _registered()
    store.set_access(runs[0].run_folder_id, can_add_children=False)
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    by_run = {v.registration.run_id: v for v in views if v.registration}
    assert by_run[rid(1)].status == "history_unavailable"
    assert "revoked" in by_run[rid(1)].reason
    assert by_run[rid(2)].status == "ok"


def test_changed_target_acl_gives_history_unavailable() -> None:
    store, handle, runs = _registered()
    store.set_access(runs[1].run_folder_id, grants=(Grant("user", "reader", "x.com"),))
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    by_run = {v.registration.run_id: v for v in views if v.registration}
    assert by_run[rid(2)].status == "history_unavailable"
    assert "changed" in by_run[rid(2)].reason


def test_missing_target_gives_history_unavailable() -> None:
    store, handle, runs = _registered(1)
    other = _registration(runs[0], rid(5), run_folder_id="gone-folder")
    register(store, handle, other)
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    by_run = {v.registration.run_id: v for v in views if v.registration}
    assert by_run[rid(5)].status == "history_unavailable"
    assert by_run[rid(1)].status == "ok"


def test_target_descriptor_for_another_run_gives_history_unavailable() -> None:
    store, handle, runs = _registered(1)
    other = _registration(runs[0], rid(6))  # points at run 1's folder
    register(store, handle, other)
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    by_run = {v.registration.run_id: v for v in views if v.registration}
    assert by_run[rid(6)].status == "history_unavailable"


def test_registry_access_change_makes_the_whole_registry_unavailable() -> None:
    store, handle, _ = _registered()
    store.set_access(handle.folder_id, grants=(Grant("anyone", "reader"),))
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    assert len(views) == 1
    assert views[0].registration is None
    assert views[0].status == "history_unavailable"
    assert views[0].object_id == handle.folder_id
    assert views[0].handle_location == "operator"


def test_unreadable_registry_gives_history_unavailable_not_no_prior() -> None:
    store, handle, _ = _registered()
    gone = dataclasses.replace(handle, folder_id="missing-registry")
    views = list_registrations(store, (gone,), account_key=ACCOUNT)
    assert [v.status for v in views] == ["history_unavailable"]


def test_corrupt_registration_is_reported() -> None:
    store, handle, _ = _registered(1)
    store.put_stream(
        handle.registrations_folder_id,
        f"{registration_id(rid(7))}.json",
        "application/json",
        [b"{not json"],
        properties={REGISTRATION_PROPERTY: registration_id(rid(7))},
    )
    foreign = store.put_stream(
        handle.registrations_folder_id,
        "notes.txt",
        "text/plain",
        [b"hello"],
        properties={},
    )
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    statuses = sorted(v.status for v in views)
    assert statuses == ["corrupt", "corrupt", "ok"]
    assert any(v.object_id == foreign.id for v in views if v.status == "corrupt")


def test_registration_bytes_corrupted_at_rest_are_reported() -> None:
    store, handle, _ = _registered(1)
    (obj,) = store.list_children(handle.registrations_folder_id)
    store.corrupt_object(obj.id)
    (view,) = list_registrations(store, (handle,), account_key=ACCOUNT)
    assert view.status == "corrupt"


def test_registration_under_the_wrong_name_is_corrupt() -> None:
    store, handle, runs = _registered(1)
    reg = _registration(runs[0], rid(8))
    store.put_stream(
        handle.registrations_folder_id,
        f"{registration_id(rid(9))}.json",
        "application/json",
        [encode_json(reg.to_dict())],
        properties={REGISTRATION_PROPERTY: registration_id(rid(9))},
    )
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    assert sorted(v.status for v in views) == ["corrupt", "ok"]


def test_registrations_in_both_registries_are_listed_once() -> None:
    store = _store()
    res = _account_run(store, rid(1))
    handles = ensure_registry(
        store,
        ACCOUNT,
        account_name=NAME,
        shared_root_id=SHARED_REG,
        internal_domains=INTERNAL,
    )
    for handle in handles:
        register(store, handle, _registration(res, rid(1)))
    views = list_registrations(store, handles, account_key=ACCOUNT)
    assert len(views) == 1
    assert views[0].handle_location == "operator"


def test_list_registrations_rejects_a_handle_for_another_account() -> None:
    store, handle, _ = _registered(1)
    with pytest.raises(ValueError):
        list_registrations(store, (handle,), account_key="OTHER")


def test_imported_local_registration_needs_no_target() -> None:
    store, handle, runs = _registered(1)
    imp = _registration(
        runs[0],
        rid(4),
        registration_id="reg_imp_" + "c" * 24,
        kind="imported_local",
        run_folder_id=None,
        provenance={
            "origin": "local_reference",
            "local_run_id": "local-1",
            "approved_by": "perm-owner-0001",
        },
    )
    register(store, handle, imp)
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    assert {v.status for v in views} == {"ok"}
    assert len(views) == 2


# --- index ------------------------------------------------------------------------------


def test_rebuild_and_read_index() -> None:
    store, handle, _ = _registered()
    assert read_index(store, handle) is None
    obj = rebuild_index(store, handle)
    assert obj.name == "rev-000001.json"
    assert obj.parent_ids == (handle.index_folder_id,)
    entries = read_index(store, handle)
    assert entries is not None
    assert [e.registration_id for e in entries] == sorted(
        registration_id(r) for r in (rid(1), rid(2))
    )
    assert all(isinstance(e, IndexEntry) for e in entries)
    assert {e.run_id for e in entries} == {rid(1), rid(2)}


def test_rebuild_index_is_append_only_and_skips_unchanged() -> None:
    store, handle, runs = _registered(1)
    first = rebuild_index(store, handle)
    assert rebuild_index(store, handle).id == first.id
    register(store, handle, _registration(runs[0], rid(2), run_folder_id="x"))
    second = rebuild_index(store, handle)
    assert second.name == "rev-000002.json"
    assert second.id != first.id
    names = sorted(o.name for o in store.list_children(handle.index_folder_id))
    assert names == ["rev-000001.json", "rev-000002.json"]
    assert b"".join(store.get_stream(first.id))  # the old revision is kept
    entries = read_index(store, handle)
    assert entries is not None and len(entries) == 2


def test_stale_index_is_rejected() -> None:
    store, handle, runs = _registered(1)
    rebuild_index(store, handle)
    register(store, handle, _registration(runs[0], rid(2), run_folder_id="x"))
    assert read_index(store, handle) is None


def test_corrupt_index_is_rejected_and_listing_is_still_correct() -> None:
    store, handle, _ = _registered()
    obj = rebuild_index(store, handle)
    store.corrupt_object(obj.id)
    assert read_index(store, handle) is None
    views = list_registrations(store, (handle,), account_key=ACCOUNT)
    assert [v.status for v in views] == ["ok", "ok"]


def test_unparseable_index_is_rejected() -> None:
    store, handle, _ = _registered(1)
    store.put_stream(
        handle.index_folder_id,
        "rev-000001.json",
        "application/json",
        [json.dumps({"entries": "nope"}).encode()],
        properties={},
    )
    assert read_index(store, handle) is None
    # rebuild ignores the unusable revision and appends after it
    assert rebuild_index(store, handle).name == "rev-000002.json"
    assert read_index(store, handle) is not None


def test_duplicate_latest_index_revision_is_rejected() -> None:
    store, handle, _ = _registered(1)
    store.duplicate_on_put = {"rev-000001.json"}
    with pytest.raises(RegistrationConflictError):
        rebuild_index(store, handle)
    assert read_index(store, handle) is None


# --- helpers / protocol ---------------------------------------------------------------


def test_import_registration_id_is_valid_for_imported_local() -> None:
    from starboard_core.engagement.registry import import_registration_id

    store, _, runs = _registered(1)
    first = import_registration_id("local-1")
    assert first == import_registration_id("local-1")
    assert first != import_registration_id("local-2")
    assert first.startswith("reg_imp_")
    _registration(
        runs[0],
        rid(4),
        registration_id=first,
        kind="imported_local",
        run_folder_id=None,
        provenance={
            "origin": "local_reference",
            "local_run_id": "local-1",
            "approved_by": "perm-owner-0001",
        },
    )


def test_registration_view_satisfies_the_history_protocol() -> None:
    from starboard_core.engagement.history import UnavailableView
    from starboard_core.engagement.registry import RegistrationView

    store, handle, runs = _registered(1)
    store.set_access(runs[0].run_folder_id, can_add_children=False)
    (view,) = list_registrations(store, (handle,), account_key=ACCOUNT)
    assert isinstance(view, RegistrationView)
    typed: UnavailableView = view
    assert typed.registration is not None
    assert typed.object_id == view.object_id
    assert view.status != "ok" and typed.reason
