# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Drive folder resolver (engagement-drive spec §3)."""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import replace

import pytest
from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    FolderAccessError,
    FolderConflictError,
    FolderResolution,
    OverrideNotRestrictedError,
    classify_access,
    creation_order,
    ensure_account_folder,
    ensure_folder,
    resolve_account_route,
    resolve_override_route,
    resolve_ticket_route,
    sanitize_folder_name,
)
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.ports.engagement_storage import (
    AccessInfo,
    Grant,
    StorageAuthError,
    StoragePermissionError,
)

INTERNAL = frozenset({"example.com"})
STAFF_GRANTS = (
    Grant("user", "fileOrganizer", "example.com"),
    Grant("group", "writer", "example.com"),
)
SHARED_ROOT = "asqs-root"
AR = "AR-000123456"

ACCOUNT_KW = {
    "account_key": "001ACME",
    "account_name": "Acme Corp",
    "task": "review",
    "task_name": "Warehouse review",
    "run_id": "20261007_6f1c0e1e-5b7a-4d2e-9c1a-0d6e4b3f2a10",
}


def _ticket_kw(**overrides: object) -> dict[str, object]:
    kw: dict[str, object] = {
        "shared_root_id": SHARED_ROOT,
        "ar_key": AR,
        "ticket_title": "Cost spike",
        "internal_domains": INTERNAL,
        **ACCOUNT_KW,
    }
    kw.update(overrides)
    return kw


def _store_with_shared(*, can_add_children: bool = True) -> InMemoryEngagementStorage:
    store = InMemoryEngagementStorage(root_id="my-root")
    store.add_shared_drive(
        SHARED_ROOT,
        "ASQs",
        drive_id="drive-asqs",
        grants=STAFF_GRANTS,
        can_add_children=can_add_children,
    )
    return store


def _chain(store: InMemoryEngagementStorage, folder_id: str) -> list[str]:
    """Names from the top-level ancestor down to ``folder_id``."""
    names: list[str] = []
    current: str | None = folder_id
    while current is not None:
        obj = store.get(current)
        names.append(obj.name)
        current = obj.parent_ids[0] if obj.parent_ids else None
    return list(reversed(names))


# --- sanitize_folder_name ---------------------------------------------------------


def test_sanitize_strips_control_chars_and_collapses_whitespace() -> None:
    assert sanitize_folder_name("  Acme\x00\x07 \t Corp\n\r  ") == "Acme Corp"


def test_sanitize_removes_path_separators() -> None:
    result = sanitize_folder_name("a/b\\c")
    assert "/" not in result and "\\" not in result
    assert result == "a-b-c"


def test_sanitize_keeps_colon_and_punctuation() -> None:
    assert sanitize_folder_name("AR-000123456:Cost (Q3), spike!") == (
        "AR-000123456:Cost (Q3), spike!"
    )


def test_sanitize_caps_length() -> None:
    result = sanitize_folder_name("x" * 500)
    assert len(result) == 120
    assert len(sanitize_folder_name("abc def", max_len=4)) <= 4
    assert sanitize_folder_name("abc def", max_len=4) == "abc"


def test_sanitize_nfc_normalizes() -> None:
    decomposed = "Cafe\u0301"
    result = sanitize_folder_name(decomposed)
    assert result == "Caf\u00e9"
    assert unicodedata.is_normalized("NFC", result)


@pytest.mark.parametrize("bad", ["", "   ", "\x00\x01", "\u200b"])
def test_sanitize_rejects_empty(bad: str) -> None:
    with pytest.raises(ValueError):
        sanitize_folder_name(bad)


# --- ensure_folder ----------------------------------------------------------------


def test_ensure_folder_creates_on_zero_matches() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    obj = ensure_folder(store, root, "Acme Corp", "account:001")
    assert obj.name == "Acme Corp"
    assert obj.parent_ids == (root,)
    assert obj.properties[IDENTITY_PROPERTY] == "account:001"


def test_ensure_folder_reuses_single_identity_match() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    existing = store.add_folder(
        root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001"}
    )
    count = store.object_count
    assert ensure_folder(store, root, "Acme Corp", "account:001").id == existing.id
    assert store.object_count == count


def test_ensure_folder_uses_sanitized_name() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    obj = ensure_folder(store, root, "  Acme\tCorp ", "account:001")
    assert obj.name == "Acme Corp"
    assert ensure_folder(store, root, "Acme Corp", "account:001").id == obj.id


def test_ensure_folder_display_name_collision_conflicts() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.add_folder(root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:OTHER"})
    with pytest.raises(FolderConflictError):
        ensure_folder(store, root, "Acme Corp", "account:001")


def test_ensure_folder_adopts_single_untagged_folder() -> None:
    # Hand-made ASQ folders and earlier Starboard deliveries carry no identity tag;
    # a single exact-name, untagged folder is adopted, not a conflict.
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    existing = store.add_folder(root, "Acme Corp")
    count = store.object_count
    assert ensure_folder(store, root, "Acme Corp", "account:001").id == existing.id
    assert store.object_count == count


def test_ensure_folder_without_adoption_conflicts_on_untagged() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.add_folder(root, "Acme Corp")
    with pytest.raises(FolderConflictError):
        ensure_folder(store, root, "Acme Corp", "account:001", adopt_untagged=False)


def test_ensure_folder_multiple_untagged_conflict() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.add_folder(root, "Acme Corp")
    store.add_folder(root, "Acme Corp")
    with pytest.raises(FolderConflictError):
        ensure_folder(store, root, "Acme Corp", "account:001")


def test_account_route_never_adopts_an_untagged_run_folder() -> None:
    store = InMemoryEngagementStorage()
    first = resolve_account_route(store, **ACCOUNT_KW)
    parent = store.get(first.run_folder_id).parent_ids[0]
    next_run = "20261007_" + str(uuid.uuid4())
    store.add_folder(parent, next_run)  # stray untagged folder with the next run's name
    with pytest.raises(FolderConflictError):
        resolve_account_route(store, **{**ACCOUNT_KW, "run_id": next_run})


def test_ensure_folder_identity_match_plus_foreign_same_name_conflicts() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.add_folder(root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001"})
    store.add_folder(root, "Acme Corp")
    with pytest.raises(FolderConflictError):
        ensure_folder(store, root, "Acme Corp", "account:001")


def test_ensure_folder_multiple_preexisting_matches_converge_on_earliest() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    first = store.add_folder(
        root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001"}
    )
    store.add_folder(root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001"})
    assert ensure_folder(store, root, "Acme Corp", "account:001").id == first.id


def test_ensure_folder_concurrent_duplicate_after_create_converges() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.duplicate_on_create = {"Acme Corp"}
    obj = ensure_folder(store, root, "Acme Corp", "account:001")
    matches = store.list_children(root, name="Acme Corp", folders_only=True)
    assert len(matches) == 2
    assert obj.id == min(matches, key=lambda m: (m.created_time, m.id)).id


def test_ensure_folder_mixed_identity_still_conflicts() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.add_folder(root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001"})
    store.add_folder(root, "Acme Corp", properties={IDENTITY_PROPERTY: "account:002"})
    with pytest.raises(FolderConflictError) as exc:
        ensure_folder(store, root, "Acme Corp", "account:001")
    assert len(exc.value.object_ids) == 2


def test_ensure_folder_ignores_files_and_other_parents() -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.put_stream(root, "Acme Corp", "text/plain", [b"x"], properties={})
    other = store.add_folder(root, "elsewhere")
    store.add_folder(
        other.id, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001"}
    )
    obj = ensure_folder(store, root, "Acme Corp", "account:001")
    assert obj.parent_ids == (root,)


# --- classify_access ----------------------------------------------------------------


def _access(*grants: Grant, complete: bool = True) -> AccessInfo:
    return AccessInfo(
        object_id="x",
        can_add_children=True,
        drive_kind="shared_drive",
        grants=grants,
        complete=complete,
    )


def test_classify_internal_only() -> None:
    assert classify_access(_access(*STAFF_GRANTS), INTERNAL) == "internal_only"
    assert classify_access(
        _access(Grant("domain", "reader", "EXAMPLE.com")), INTERNAL
    ) == ("internal_only")


@pytest.mark.parametrize(
    "grant",
    [
        Grant("anyone", "reader"),
        Grant("domain", "reader", "other.org"),
        Grant("user", "writer", "gmail.com"),
        Grant("group", "reader", "partner.io"),
    ],
)
def test_classify_widened(grant: Grant) -> None:
    assert classify_access(_access(*STAFF_GRANTS, grant), INTERNAL) == "widened"


def test_classify_incomplete_is_unknown() -> None:
    assert (
        classify_access(_access(*STAFF_GRANTS, complete=False), INTERNAL) == "unknown"
    )


def test_classify_grant_without_domain_is_unknown() -> None:
    assert classify_access(_access(Grant("user", "writer")), INTERNAL) == "unknown"


# --- account route -----------------------------------------------------------------


def test_account_route_path() -> None:
    store = InMemoryEngagementStorage(root_id="my-root")
    res = resolve_account_route(store, **ACCOUNT_KW)

    assert isinstance(res, FolderResolution)
    assert res.route == "account"
    assert res.base_id == "my-root"
    assert res.ticket_folder_id is None
    assert res.fallback_warning is None
    run_id = str(ACCOUNT_KW["run_id"])
    assert res.path_names == (
        "My Drive",
        "starboard",
        "Acme Corp",
        "review",
        "Warehouse review",
        run_id,
    )
    assert _chain(store, res.run_folder_id) == [
        "My Drive",
        "starboard",
        "Acme Corp",
        "review",
        "Warehouse review",
        run_id,
    ]
    assert _chain(store, res.account_folder_id)[-1] == "Acme Corp"
    assert (
        store.get(res.account_folder_id).properties[IDENTITY_PROPERTY]
        == "account:001ACME"
    )
    assert store.get(res.run_folder_id).properties[IDENTITY_PROPERTY] == f"run:{run_id}"
    assert res.access.object_id == res.run_folder_id
    assert res.links["run"]


def test_account_route_idempotent_rerun_reuses_all_folders() -> None:
    store = InMemoryEngagementStorage()
    first = resolve_account_route(store, **ACCOUNT_KW)
    count = store.object_count
    second = resolve_account_route(store, **ACCOUNT_KW)
    assert store.object_count == count
    assert second == first


def test_account_route_permission_error_propagates() -> None:
    store = InMemoryEngagementStorage(root_id="my-root")
    store.deny_writes_under = {"my-root"}
    with pytest.raises(StoragePermissionError):
        resolve_account_route(store, **ACCOUNT_KW)


def _starboard(store: InMemoryEngagementStorage) -> str:
    root = store.root_folder_id()
    return store.add_folder(
        root, "starboard", properties={IDENTITY_PROPERTY: "segment:starboard"}
    ).id


def test_account_route_reuses_differently_named_identity_folder() -> None:
    store = InMemoryEngagementStorage()
    existing = store.add_folder(
        _starboard(store), "Acme Inc", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    res = resolve_account_route(store, **ACCOUNT_KW)
    assert res.account_folder_id == existing.id
    assert res.path_names[2] == "Acme Inc"
    assert not [
        o
        for o in store.list_children(existing.parent_ids[0], folders_only=True)
        if o.name == "Acme Corp"
    ]
    assert any(w.startswith("account_name_differs:") for w in res.warnings)


def test_account_route_duplicate_identity_folders_warn_and_use_earliest() -> None:
    store = InMemoryEngagementStorage()
    parent = _starboard(store)
    first = store.add_folder(
        parent, "Acme Inc", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    store.add_folder(
        parent, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    res = resolve_account_route(store, **ACCOUNT_KW)
    assert res.account_folder_id == first.id
    dup = [w for w in res.warnings if w.startswith("duplicate_account_folders:")]
    assert dup and "rebuild-index" in dup[0] and "trash" in dup[0]


class _HidingStorage(InMemoryEngagementStorage):
    """Hides one folder from listings until this process has created a folder."""

    def __init__(self) -> None:
        super().__init__()
        self.hidden: str | None = None

    def list_children(self, parent_id, *, name=None, folders_only=False):  # type: ignore[no-untyped-def]
        out = super().list_children(parent_id, name=name, folders_only=folders_only)
        return [o for o in out if o.id != self.hidden]

    def create_folder(self, parent_id, name, properties):  # type: ignore[no-untyped-def]
        created = super().create_folder(parent_id, name, properties)
        self.hidden = None
        return created


def test_concurrent_account_creates_converge_on_earliest() -> None:
    store = _HidingStorage()
    parent = _starboard(store)
    # Another process created the account folder (under another name) first; this
    # process does not see it until after its own create.
    sibling = store.add_folder(
        parent, "Acme Inc", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    store.hidden = sibling.id
    found = ensure_account_folder(store, parent, "Acme Corp", "001ACME")
    assert found.folder.id == sibling.id
    assert len(found.duplicates) == 1
    assert any(w.startswith("duplicate_account_folders:") for w in found.warnings)
    # A rerun (both visible) lands on the same winner.
    again = ensure_account_folder(store, parent, "Acme Corp", "001ACME")
    assert again.folder.id == sibling.id


def test_creation_order_ties_break_on_smallest_id() -> None:
    store = InMemoryEngagementStorage()
    a = store.add_folder(store.root_folder_id(), "x")
    b = store.add_folder(store.root_folder_id(), "y")
    same_a = replace(a, created_time="2026-01-01T00:00:00Z")
    same_b = replace(b, created_time="2026-01-01T00:00:00Z")
    assert min([same_b, same_a], key=creation_order).id == min(a.id, b.id)


# --- ticket route ------------------------------------------------------------------


def test_ticket_route_path() -> None:
    store = _store_with_shared()
    res = resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]

    run_id = str(ACCOUNT_KW["run_id"])
    expected = [
        "ASQs",
        "Acme Corp",
        f"{AR}: Cost spike",
        "starboard",
        "review",
        "Warehouse review",
        run_id,
    ]
    assert res.route == "ticket"
    assert res.base_id == SHARED_ROOT
    assert res.fallback_warning is None
    assert res.path_names == tuple(expected)
    assert _chain(store, res.run_folder_id) == expected
    assert res.ticket_folder_id is not None
    assert (
        store.get(res.ticket_folder_id).properties[IDENTITY_PROPERTY] == f"ticket:{AR}"
    )
    assert store.get(res.account_folder_id).parent_ids == (SHARED_ROOT,)
    assert res.access.drive_kind == "shared_drive"


def test_ticket_route_adopts_the_hand_made_asq_folder() -> None:
    """ASQ folders are named ``AR-NNNNNNNNN: <title>`` (a space after the colon); a
    run must land in that hand-made folder, not create an unspaced twin beside it."""
    store = _store_with_shared()
    acct = store.add_folder(
        SHARED_ROOT, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    asq = store.add_folder(acct.id, f"{AR}: Cost spike")
    res = resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]
    assert res.ticket_folder_id == asq.id
    assert [c.name for c in store.list_children(acct.id)] == [f"{AR}: Cost spike"]


def test_ticket_route_reuses_the_tagged_folder_under_another_name() -> None:
    """A ticket folder an earlier run made (``AR-NNNNNNNNN:<title>``, no space) or one
    whose ticket title changed is found by its ``ticket:<AR>`` tag, not twinned."""
    store = _store_with_shared()
    acct = store.add_folder(
        SHARED_ROOT, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    legacy = store.add_folder(
        acct.id, f"{AR}:Cost spike", properties={IDENTITY_PROPERTY: f"ticket:{AR}"}
    )
    res = resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]
    assert res.ticket_folder_id == legacy.id
    assert [c.name for c in store.list_children(acct.id)] == [f"{AR}:Cost spike"]


def test_ticket_route_prefers_the_named_asq_folder_over_a_tagged_one() -> None:
    store = _store_with_shared()
    acct = store.add_folder(
        SHARED_ROOT, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    store.add_folder(
        acct.id, f"{AR}:Cost spike", properties={IDENTITY_PROPERTY: f"ticket:{AR}"}
    )
    asq = store.add_folder(acct.id, f"{AR}: Cost spike")
    res = resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]
    assert res.ticket_folder_id == asq.id


def test_ticket_route_idempotent_rerun_reuses_all_folders() -> None:
    store = _store_with_shared()
    first = resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]
    count = store.object_count
    second = resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]
    assert store.object_count == count
    assert second == first


def _assert_fell_back(store: InMemoryEngagementStorage, res: FolderResolution) -> None:
    assert res.route == "account"
    assert res.ticket_folder_id is None
    assert res.base_id == store.root_folder_id()
    assert res.fallback_warning
    assert "My Drive" in res.fallback_warning
    assert _chain(store, res.run_folder_id)[:3] == [
        "My Drive",
        "starboard",
        "Acme Corp",
    ]


def test_ticket_route_falls_back_when_root_not_writable() -> None:
    store = _store_with_shared(can_add_children=False)
    res = resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]
    _assert_fell_back(store, res)
    # Nothing was created under the shared root.
    assert store.list_children(SHARED_ROOT) == []


def test_ticket_route_falls_back_on_permission_error_mid_route() -> None:
    store = _store_with_shared()
    acct = store.add_folder(
        SHARED_ROOT, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    store.deny_writes_under = {acct.id}
    res = resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]
    _assert_fell_back(store, res)


def test_ticket_route_auth_error_propagates() -> None:
    store = _store_with_shared()
    store.auth_failed = True
    with pytest.raises(StorageAuthError):
        resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]


def test_ticket_route_widened_acl_raises() -> None:
    store = _store_with_shared()
    acct = store.add_folder(
        SHARED_ROOT,
        "Acme Corp",
        properties={IDENTITY_PROPERTY: "account:001ACME"},
        grants=(Grant("user", "reader", "customer.com"),),
    )
    with pytest.raises(FolderAccessError):
        resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]
    # No starboard subtree was created under the widened ticket folder.
    (ticket,) = store.list_children(acct.id)
    assert store.list_children(ticket.id) == []


def test_ticket_route_incomplete_acl_raises() -> None:
    store = _store_with_shared()
    ticket_name = f"{AR}: Cost spike"
    acct = store.add_folder(
        SHARED_ROOT, "Acme Corp", properties={IDENTITY_PROPERTY: "account:001ACME"}
    )
    store.add_folder(
        acct.id,
        ticket_name,
        properties={IDENTITY_PROPERTY: f"ticket:{AR}"},
        complete=False,
    )
    with pytest.raises(FolderAccessError):
        resolve_ticket_route(store, **_ticket_kw())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "ar_key",
    ["ASQ-000123456", "AAR-000123456", "AR-12345", "AR-0001234567", "ar-000123456", ""],
)
def test_ticket_route_rejects_invalid_ar_key(ar_key: str) -> None:
    store = _store_with_shared()
    with pytest.raises(ValueError):
        resolve_ticket_route(store, **_ticket_kw(ar_key=ar_key))  # type: ignore[arg-type]
    assert store.list_children(SHARED_ROOT) == []


def test_ticket_route_requires_internal_domains() -> None:
    store = _store_with_shared()
    with pytest.raises(ValueError):
        resolve_ticket_route(store, **_ticket_kw(internal_domains=frozenset()))  # type: ignore[arg-type]


# --- override route (D-8) -----------------------------------------------------------

OVERRIDE = "override-folder"


def _override_kw(**overrides: object) -> dict[str, object]:
    kw: dict[str, object] = {
        "override_folder_id": OVERRIDE,
        "internal_domains": INTERNAL,
        **ACCOUNT_KW,
    }
    kw.update(overrides)
    return kw


def _store_with_override(
    *,
    can_add_children: bool = True,
    grants: tuple[Grant, ...] = STAFF_GRANTS,
    complete: bool = True,
) -> InMemoryEngagementStorage:
    store = InMemoryEngagementStorage(root_id="my-root")
    store.add_shared_drive(
        OVERRIDE,
        "Team handoff",
        drive_id="drive-team",
        grants=grants,
        can_add_children=can_add_children,
        complete=complete,
    )
    return store


def test_override_route_path() -> None:
    store = _store_with_override()
    res = resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    assert res.route == "override"
    assert res.base_id == OVERRIDE
    assert res.account_folder_id == OVERRIDE
    assert res.ticket_folder_id is None
    assert res.fallback_warning is None
    assert res.path_names == (
        "Team handoff",
        "starboard",
        "review",
        "Warehouse review",
        ACCOUNT_KW["run_id"],
    )
    assert _chain(store, res.run_folder_id) == list(res.path_names)
    run = store.get(res.run_folder_id)
    assert run.properties[IDENTITY_PROPERTY] == f"run:{ACCOUNT_KW['run_id']}"
    assert res.access.object_id == res.run_folder_id
    assert set(res.links) == {"base", "run"}


def test_override_route_idempotent_rerun() -> None:
    store = _store_with_override()
    first = resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    count = store.object_count
    second = resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    assert second.run_folder_id == first.run_folder_id
    assert store.object_count == count


def test_override_route_falls_back_when_not_writable() -> None:
    store = _store_with_override(can_add_children=False)
    res = resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    assert res.route == "account"
    assert res.fallback_warning and OVERRIDE in res.fallback_warning
    assert "My Drive" in res.fallback_warning
    assert _chain(store, res.run_folder_id)[:3] == [
        "My Drive",
        "starboard",
        "Acme Corp",
    ]
    assert store.list_children(OVERRIDE) == []


def test_override_route_falls_back_when_inaccessible() -> None:
    store = InMemoryEngagementStorage(root_id="my-root")
    res = resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    assert res.route == "account"
    assert res.fallback_warning


def test_override_route_falls_back_on_permission_error_mid_route() -> None:
    store = _store_with_override()
    store.deny_writes_under = {OVERRIDE}
    res = resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    assert res.route == "account"
    assert res.fallback_warning


@pytest.mark.parametrize(
    "grants",
    [
        (Grant("anyone", "reader"),),
        (*STAFF_GRANTS, Grant("user", "reader", "customer.com")),
        (Grant("domain", "reader", "customer.com"),),
    ],
)
def test_override_route_refuses_broad_acl_without_fallback(
    grants: tuple[Grant, ...],
) -> None:
    store = _store_with_override(grants=grants)
    count = store.object_count
    with pytest.raises(OverrideNotRestrictedError) as info:
        resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    assert isinstance(info.value, FolderAccessError)
    assert info.value.classification == "widened"
    assert info.value.object_id == OVERRIDE
    assert store.object_count == count  # nothing created, not even in My Drive


def test_override_route_refuses_unverifiable_acl() -> None:
    store = _store_with_override(complete=False)
    with pytest.raises(OverrideNotRestrictedError) as info:
        resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    assert info.value.classification == "unknown"


def test_override_route_refuses_widened_run_folder() -> None:
    store = _store_with_override()
    starboard = store.add_folder(
        OVERRIDE,
        "starboard",
        properties={IDENTITY_PROPERTY: "segment:starboard"},
        grants=(Grant("user", "reader", "customer.com"),),
    )
    with pytest.raises(OverrideNotRestrictedError):
        resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]
    assert store.list_children(starboard.id)  # the tail was built, then refused


def test_override_route_auth_error_propagates() -> None:
    store = _store_with_override()
    store.auth_failed = True
    with pytest.raises(StorageAuthError):
        resolve_override_route(store, **_override_kw())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [{"internal_domains": frozenset()}, {"override_folder_id": " "}, {"run_id": ""}],
)
def test_override_route_rejects_bad_arguments(bad: dict[str, object]) -> None:
    store = _store_with_override()
    count = store.object_count
    with pytest.raises(ValueError):
        resolve_override_route(store, **_override_kw(**bad))  # type: ignore[arg-type]
    assert store.object_count == count


def test_pinned_internal_domains_default_to_databricks() -> None:
    from starboard_core.engagement.folders import (
        PINNED_INTERNAL_DOMAINS,
        effective_internal_domains,
    )

    assert frozenset({"databricks.com"}) == PINNED_INTERNAL_DOMAINS
    assert effective_internal_domains(()) == PINNED_INTERNAL_DOMAINS
    assert effective_internal_domains(["Databricks.COM"]) == frozenset(
        {"databricks.com"}
    )


@pytest.mark.parametrize("caller", [["gmail.com"], ["databricks.com", "evil.example"]])
def test_effective_internal_domains_refuses_unpinned(caller: list[str]) -> None:
    from starboard_core.engagement.folders import effective_internal_domains

    with pytest.raises(ValueError, match="not a pinned internal domain"):
        effective_internal_domains(caller)


def test_effective_internal_domains_is_the_intersection_with_a_custom_pin() -> None:
    from starboard_core.engagement.folders import effective_internal_domains

    pinned = frozenset({"a.example", "b.example"})
    assert effective_internal_domains(["b.example"], pinned=pinned) == {"b.example"}
    assert effective_internal_domains([], pinned=pinned) == pinned
