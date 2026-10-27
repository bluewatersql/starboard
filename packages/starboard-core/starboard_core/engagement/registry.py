# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Account registry: one create-once registration per run.

Layout::

    My Drive/starboard/<ACCOUNT>/_registry/            operator registry (always)
    <shared root>/<ACCOUNT>/_registry/                 shared registry (preflighted)
        registrations/<registration_id>.json           create-once records
        index/rev-NNNNNN.json                          append-only listing hint

Account, ticket and override runs all register in the operator registry. The
shared registry is written only when it is configured and its preflight passes
(the operator can add children and the ACL is internal-only); otherwise it is
skipped with a warning.

The registrations listing is authoritative; the index is only a hint and is
ignored when missing, corrupt or inconsistent with the listing. Every read
re-checks the registry's access, and every run registration re-checks its target
run folder against the fingerprint recorded in that run's descriptor: any failure
yields ``history_unavailable`` (never "no prior run").

Stdlib + port only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from typing import Any, Literal

from starboard_core.engagement.access import recheck_access
from starboard_core.engagement.commit import CommitError, read_descriptor
from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    STARBOARD_SEGMENT,
    AccountFolder,
    account_folder_from,
    classify_access,
    creation_order,
    ensure_account_folder,
    ensure_folder,
    ensure_starboard_root,
    identity_children_under,
)
from starboard_core.engagement.reads import read_object
from starboard_core.engagement.records import Registration
from starboard_core.engagement.staging import JSON_MIME, encode_json, verify_bytes
from starboard_core.ports.engagement_storage import (
    AccessInfo,
    EngagementStoragePort,
    StorageAuthError,
    StorageError,
    StorageNotFoundError,
    StorageObject,
    StoragePermissionError,
)

__all__ = [
    "INDEX_PROPERTY",
    "INDEX_SEGMENT",
    "REGISTRATIONS_SEGMENT",
    "REGISTRATION_PROPERTY",
    "REGISTRY_SEGMENT",
    "IndexEntry",
    "RegistrationConflictError",
    "RegistrationView",
    "RegistryHandle",
    "RegistryNotFoundError",
    "ViewStatus",
    "ensure_registry",
    "import_registration_id",
    "list_registrations",
    "read_index",
    "rebuild_index",
    "register",
]

_log = logging.getLogger(__name__)

REGISTRY_SEGMENT = "_registry"
REGISTRATIONS_SEGMENT = "registrations"
INDEX_SEGMENT = "index"
REGISTRATION_PROPERTY = "starboard_registration"
INDEX_PROPERTY = "starboard_index"

ViewStatus = Literal["ok", "history_unavailable", "corrupt"]
Location = Literal["operator", "shared"]

_INDEX_NAME_RE = re.compile(r"rev-([0-9]{6})\.json")
_INDEX_VERSION = 1
#: Registration and index files are small; anything larger is not ours.
_MAX_RECORD_BYTES = 4 * 2**20


class RegistrationConflictError(StorageError):
    """A different (or duplicate) registry object already holds this name."""


class RegistryNotFoundError(StorageNotFoundError):
    """The account folder holding the operator registry does not exist."""


@dataclass(frozen=True)
class RegistryHandle:
    """One resolved account registry.

    Attributes:
        folder_id: The ``_registry`` folder.
        account_key: Account the registry belongs to.
        location: ``operator`` (My Drive) or ``shared``.
        access: Access of ``folder_id`` when resolved.
        fingerprint: ``access.fingerprint``; every later read/write re-checks it.
        registrations_folder_id / index_folder_id: The two sub-folders.
    """

    folder_id: str
    account_key: str
    location: Location
    access: AccessInfo
    fingerprint: str
    registrations_folder_id: str
    index_folder_id: str


@dataclass(frozen=True)
class RegistrationView:
    """One listed registry entry (satisfies ``history.UnavailableView``).

    ``registration`` is ``None`` for a corrupt entry and for a registry that could
    not be read at all (then ``object_id`` is the registry folder).

    Attributes:
        registration: The parsed registration, when readable.
        object_id: The registration object (or registry folder).
        handle_location: Registry it was read from.
        status: ``ok``, ``history_unavailable`` or ``corrupt``.
        reason: Why the entry is not ``ok`` (empty when ``ok``).
    """

    registration: Registration | None
    object_id: str
    handle_location: Location
    status: ViewStatus
    reason: str = ""


@dataclass(frozen=True)
class IndexEntry:
    """One registration as recorded in an index revision."""

    registration_id: str
    object_id: str
    md5: str | None
    run_id: str
    task: str
    task_name: str
    route: str
    registered_at: str


def import_registration_id(local_run_id: str) -> str:
    """The ``reg_imp_<hex>`` ID of the ``imported_local`` registration of a local run.

    Derived from ``local_run_id`` alone, so re-importing the same local run can
    never mint a second registration.
    """
    digest = hashlib.sha256(f"import:{local_run_id}".encode()).hexdigest()
    return f"reg_imp_{digest[:32]}"


# --- ensure_registry ------------------------------------------------------------------


def _account_folder(
    storage: EngagementStoragePort,
    parent_id: str,
    account_key: str,
    account_name: str | None,
    *,
    also_under: Sequence[str] = (),
) -> AccountFolder | None:
    """The account folder by identity (any name); with a name, created when missing.

    ``also_under`` lists further parents searched by identity (the duplicate
    ``starboard`` roots); a folder is only ever created under ``parent_id``.
    """
    if account_name:
        return ensure_account_folder(
            storage, parent_id, account_name, account_key, also_under=also_under
        )
    matches = identity_children_under(
        storage, (parent_id, *also_under), f"account:{account_key}"
    )
    if not matches:
        return None
    return account_folder_from(matches, parent_id=parent_id, account_key=account_key)


def _note(warnings: list[str] | None, found: AccountFolder) -> None:
    for text in found.warnings:
        _log.warning(text)
        if warnings is not None and text not in warnings:
            warnings.append(text)


def _existing_child(
    storage: EngagementStoragePort, parent_id: str, name: str, identity_key: str
) -> StorageObject | None:
    """The winner among existing ``name`` folders tagged ``identity_key``; no create."""
    matches = [
        c
        for c in storage.list_children(parent_id, name=name, folders_only=True)
        if c.properties.get(IDENTITY_PROPERTY) == identity_key
    ]
    return min(matches, key=creation_order) if matches else None


def _existing_registry(
    storage: EngagementStoragePort,
    account_folder_id: str,
    account_key: str,
    location: Location,
) -> RegistryHandle | None:
    """A read-only handle on an existing registry under a duplicate account folder.

    Never creates anything: a duplicate folder without a complete registry
    simply contributes no registrations.
    """
    registry = _existing_child(
        storage, account_folder_id, REGISTRY_SEGMENT, f"registry:{account_key}"
    )
    if registry is None:
        return None
    subs = [
        _existing_child(
            storage, registry.id, segment, f"registry-dir:{account_key}:{segment}"
        )
        for segment in (REGISTRATIONS_SEGMENT, INDEX_SEGMENT)
    ]
    if subs[0] is None:
        return None
    access = storage.inspect_access(registry.id)
    return RegistryHandle(
        folder_id=registry.id,
        account_key=account_key,
        location=location,
        access=access,
        fingerprint=access.fingerprint,
        registrations_folder_id=subs[0].id,
        index_folder_id=subs[1].id if subs[1] is not None else "",
    )


def _duplicate_registries(
    storage: EngagementStoragePort,
    found: AccountFolder,
    account_key: str,
    location: Location,
) -> list[RegistryHandle]:
    handles = []
    for dup in found.duplicates:
        handle = _existing_registry(storage, dup.id, account_key, location)
        if handle is not None:
            handles.append(handle)
    return handles


def _registry_under(
    storage: EngagementStoragePort,
    account_folder_id: str,
    account_key: str,
    location: Location,
) -> RegistryHandle:
    registry = ensure_folder(
        storage,
        account_folder_id,
        REGISTRY_SEGMENT,
        f"registry:{account_key}",
        adopt_untagged=False,
    )
    subs = [
        ensure_folder(
            storage,
            registry.id,
            segment,
            f"registry-dir:{account_key}:{segment}",
            adopt_untagged=False,
        )
        for segment in (REGISTRATIONS_SEGMENT, INDEX_SEGMENT)
    ]
    access = storage.inspect_access(registry.id)
    return RegistryHandle(
        folder_id=registry.id,
        account_key=account_key,
        location=location,
        access=access,
        fingerprint=access.fingerprint,
        registrations_folder_id=subs[0].id,
        index_folder_id=subs[1].id,
    )


def _skip_shared(warnings: list[str] | None, message: str) -> None:
    text = f"shared registry skipped: {message}"
    _log.warning(text)
    if warnings is not None:
        warnings.append(text)


def _shared_registry(
    storage: EngagementStoragePort,
    shared_root_id: str,
    account_key: str,
    account_name: str | None,
    internal_domains: frozenset[str],
    warnings: list[str] | None,
    include_duplicates: bool = False,
) -> list[RegistryHandle]:
    if not internal_domains:
        _skip_shared(warnings, "no internal domains are configured to check its ACL")
        return []
    try:
        root = storage.inspect_access(shared_root_id)
    except StorageAuthError:
        raise
    except StorageError as exc:
        _skip_shared(warnings, f"{shared_root_id} is not accessible ({exc})")
        return []
    if not root.can_add_children:
        _skip_shared(warnings, f"the operator cannot add folders to {shared_root_id}")
        return []
    klass = classify_access(root, internal_domains)
    if klass != "internal_only":
        _skip_shared(warnings, f"the ACL of {shared_root_id} is {klass}")
        return []
    try:
        found = _account_folder(storage, shared_root_id, account_key, account_name)
        if found is None:
            found = ensure_account_folder(
                storage, shared_root_id, account_key, account_key
            )
        _note(warnings, found)
        handle = _registry_under(storage, found.folder.id, account_key, "shared")
        extra = (
            _duplicate_registries(storage, found, account_key, "shared")
            if include_duplicates
            else []
        )
    except StoragePermissionError as exc:
        _skip_shared(warnings, f"writing under {shared_root_id} was refused ({exc})")
        return []
    klass = classify_access(handle.access, internal_domains)
    if klass != "internal_only":
        _skip_shared(warnings, f"the ACL of registry {handle.folder_id} is {klass}")
        return []
    return [
        handle,
        *(
            h
            for h in extra
            if classify_access(h.access, internal_domains) == "internal_only"
        ),
    ]


def ensure_registry(
    storage: EngagementStoragePort,
    account_key: str,
    *,
    account_name: str | None = None,
    shared_root_id: str | None = None,
    internal_domains: frozenset[str] = frozenset(),
    warnings: list[str] | None = None,
    include_duplicates: bool = False,
) -> tuple[RegistryHandle, ...]:
    """Find or create the account's registries: operator first, then shared.

    The operator registry lives in ``My Drive/starboard/<ACCOUNT>/``. The account
    folder is found by its identity tag whatever its name (exactly as the account
    route does); with ``account_name`` it is created when missing. When several
    folders carry the identity, the earliest-created one holds the registry that
    is written, and a ``duplicate_account_folders:`` warning is appended. With
    ``include_duplicates`` (reads: history, prior), read-only handles on the
    registries already under the other folders follow each location's primary
    handle, so their registrations merge into the listing; nothing is created
    under them.

    The shared registry is resolved only when ``shared_root_id`` is given and the
    preflight passes (accessible, the operator can add children, internal-only
    ACL against non-empty ``internal_domains``); otherwise a warning is logged
    (and appended to ``warnings``) and it is skipped.

    Raises:
        ValueError: Empty ``account_key``.
        RegistryNotFoundError: No ``account_name`` and no account folder exists.
        FolderConflictError: The account name is taken by a folder with another
            identity, or a registry level is ambiguous.
        StorageAuthError / StoragePermissionError: From the operator side.
    """
    if not account_key or not account_key.strip():
        raise ValueError("account_key must be non-empty")
    account_key = account_key.strip()
    root = ensure_starboard_root(storage)
    for text in root.warnings:
        _log.warning(text)
        if warnings is not None and text not in warnings:
            warnings.append(text)
    found = _account_folder(
        storage,
        root.folder.id,
        account_key,
        account_name,
        also_under=root.all_ids[1:],
    )
    if found is None:
        raise RegistryNotFoundError(
            f"no account folder for {account_key!r} under My Drive/{STARBOARD_SEGMENT}; "
            "pass the account name to create it"
        )
    _note(warnings, found)
    handles = [_registry_under(storage, found.folder.id, account_key, "operator")]
    if include_duplicates:
        handles.extend(_duplicate_registries(storage, found, account_key, "operator"))
    if shared_root_id:
        handles.extend(
            _shared_registry(
                storage,
                shared_root_id,
                account_key,
                account_name,
                internal_domains,
                warnings,
                include_duplicates,
            )
        )
    return tuple(handles)


# --- shared helpers ------------------------------------------------------------------


def _recheck(storage: EngagementStoragePort, handle: RegistryHandle) -> str | None:
    """``None`` when the registry's access is unchanged, else the reason."""
    try:
        current = storage.inspect_access(handle.folder_id)
    except StorageAuthError:
        raise
    except StorageError as exc:
        return f"registry {handle.folder_id} is not accessible ({exc})"
    verdict = recheck_access(handle.fingerprint, current)
    if verdict.ok:
        return None
    return f"registry {handle.folder_id} access {verdict.reason}"


def _require_unchanged(storage: EngagementStoragePort, handle: RegistryHandle) -> None:
    problem = _recheck(storage, handle)
    if problem is not None:
        raise StoragePermissionError(f"{problem}; re-resolve the registry")


def _md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _put_once(
    storage: EngagementStoragePort,
    parent_id: str,
    name: str,
    data: bytes,
    properties: dict[str, str],
) -> StorageObject:
    obj = storage.put_stream(parent_id, name, JSON_MIME, [data], properties=properties)
    if (obj.md5 is not None and obj.md5 != _md5(data)) or (
        obj.size is not None and obj.size != len(data)
    ):
        raise RegistrationConflictError(f"{name} in {parent_id} did not store as sent")
    verify_bytes(storage, obj, data)
    after = [o for o in storage.list_children(parent_id, name=name) if not o.is_folder]
    if len(after) != 1 or after[0].id != obj.id:
        raise RegistrationConflictError(
            f"{len(after)} objects named {name!r} in {parent_id} after write "
            f"(concurrent writer); reconcile in Drive "
            f"(ids: {', '.join(o.id for o in after)})"
        )
    return obj


# --- register -------------------------------------------------------------------------


def register(
    storage: EngagementStoragePort,
    handle: RegistryHandle,
    registration: Registration,
) -> StorageObject:
    """Write ``registrations/<registration_id>.json`` once.

    Re-registering identical bytes returns the existing object (no-op).

    Raises:
        ValueError: The registration belongs to another account.
        StoragePermissionError: The registry's access changed since resolution.
        RegistrationConflictError: A different or duplicate registration exists.
    """
    if registration.account_key != handle.account_key:
        raise ValueError(
            f"registration for account {registration.account_key!r} does not belong "
            f"in the {handle.account_key!r} registry"
        )
    _require_unchanged(storage, handle)
    reg_id = registration.registration_id
    name = f"{reg_id}.json"
    data = encode_json(registration.to_dict())
    parent = handle.registrations_folder_id
    existing = [o for o in storage.list_children(parent, name=name) if not o.is_folder]
    if not existing:
        return _put_once(storage, parent, name, data, {REGISTRATION_PROPERTY: reg_id})
    if len(existing) > 1:
        raise RegistrationConflictError(
            f"{len(existing)} registrations named {name!r} in {parent}; reconcile in "
            f"Drive (ids: {', '.join(o.id for o in existing)})"
        )
    obj = existing[0]
    same = (
        obj.properties.get(REGISTRATION_PROPERTY) == reg_id
        and obj.md5 == _md5(data)
        and obj.size == len(data)
    )
    if not same:
        raise RegistrationConflictError(
            f"registration {reg_id} already exists in {parent} ({obj.id}) with "
            "different content"
        )
    return obj


# --- listing --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scanned:
    obj: StorageObject
    registration: Registration | None
    problem: str


def _parse_registration(
    storage: EngagementStoragePort, obj: StorageObject, account_key: str
) -> Registration:
    if obj.is_folder or not obj.name.endswith(".json"):
        raise ValueError(f"{obj.id} ({obj.name!r}) is not a registration file")
    stem = obj.name[: -len(".json")]
    if obj.properties.get(REGISTRATION_PROPERTY) != stem:
        raise ValueError(
            f"{obj.id} ({obj.name!r}) is not tagged as registration {stem}"
        )
    data = json.loads(read_object(storage, obj, max_bytes=_MAX_RECORD_BYTES))
    if not isinstance(data, dict):
        raise TypeError("not a JSON object")
    reg = Registration.from_dict(data)
    if reg.registration_id != stem:
        raise ValueError(f"{obj.id} holds {reg.registration_id}, not {stem}")
    if reg.account_key != account_key:
        raise ValueError(f"{obj.id} belongs to account {reg.account_key!r}")
    return reg


def _scan(storage: EngagementStoragePort, handle: RegistryHandle) -> list[_Scanned]:
    out: list[_Scanned] = []
    for obj in storage.list_children(handle.registrations_folder_id):
        try:
            reg = _parse_registration(storage, obj, handle.account_key)
        except StorageAuthError:
            raise
        except (StorageError, ValueError, TypeError, KeyError) as exc:
            out.append(_Scanned(obj, None, f"corrupt registration: {exc}"))
        else:
            out.append(_Scanned(obj, reg, ""))
    return out


def _target_problem(
    storage: EngagementStoragePort, registration: Registration
) -> str | None:
    """``None`` when the run folder still matches its recorded access."""
    folder = registration.run_folder_id
    if registration.kind != "run" or folder is None:
        return None
    try:
        auth, _ = read_descriptor(storage, folder)
        if auth.run_id != registration.run_id:
            return f"run folder {folder} holds run {auth.run_id}"
        fingerprint = (
            None
            if auth.drive is None
            else auth.drive.permission_fingerprints.get(folder)
        )
        if not fingerprint:
            return f"run {auth.run_id} recorded no access fingerprint for {folder}"
        verdict = recheck_access(fingerprint, storage.inspect_access(folder))
    except StorageAuthError:
        raise
    except (StorageError, CommitError) as exc:
        return f"run folder {folder} is not readable ({exc})"
    if not verdict.ok:
        return f"run folder {folder} access {verdict.reason}"
    return None


def _sort_key(view: RegistrationView) -> tuple[str, str, str]:
    reg = view.registration
    if reg is None:
        return ("", "", view.object_id)
    return (reg.registered_at, reg.registration_id, view.object_id)


def list_registrations(
    storage: EngagementStoragePort,
    handles: Sequence[RegistryHandle],
    *,
    account_key: str,
    tasks: Iterable[str] | None = None,
) -> tuple[RegistrationView, ...]:
    """List the account's registrations across ``handles`` (the authoritative read).

    A registry whose access changed or that cannot be read yields one
    ``history_unavailable`` view with ``registration=None``. A registration whose
    target run folder is unreadable or whose access no longer matches the
    descriptor's recorded fingerprint is ``history_unavailable``; an unparseable,
    mis-named or foreign object is ``corrupt``. A registration present in several
    registries is listed once, from the first handle (the operator registry).
    ``tasks`` filters parsed registrations; corrupt and unavailable-registry views
    are always included.

    Raises:
        ValueError: A handle belongs to another account.
        StorageAuthError: Authentication failed (no partial listing).
    """
    for handle in handles:
        if handle.account_key != account_key:
            raise ValueError(
                f"registry {handle.folder_id} belongs to {handle.account_key!r}, "
                f"not {account_key!r}"
            )
    wanted = None if tasks is None else frozenset(tasks)
    seen: set[str] = set()
    views: list[RegistrationView] = []
    for handle in handles:
        problem = _recheck(storage, handle)
        scanned: list[_Scanned] = []
        if problem is None:
            try:
                scanned = _scan(storage, handle)
            except StorageAuthError:
                raise
            except StorageError as exc:
                problem = f"registry {handle.folder_id} is not readable ({exc})"
        if problem is not None:
            views.append(
                RegistrationView(
                    None,
                    handle.folder_id,
                    handle.location,
                    "history_unavailable",
                    problem,
                )
            )
            continue
        for item in scanned:
            reg = item.registration
            if reg is None:
                views.append(
                    RegistrationView(
                        None, item.obj.id, handle.location, "corrupt", item.problem
                    )
                )
                continue
            if reg.registration_id in seen:
                continue
            if wanted is not None and reg.task not in wanted:
                continue
            seen.add(reg.registration_id)
            target = _target_problem(storage, reg)
            views.append(
                RegistrationView(
                    reg,
                    item.obj.id,
                    handle.location,
                    "ok" if target is None else "history_unavailable",
                    target or "",
                )
            )
    return tuple(sorted(views, key=_sort_key))


# --- index ----------------------------------------------------------------------------


def _entry(item: _Scanned) -> IndexEntry:
    reg = item.registration
    assert reg is not None
    return IndexEntry(
        registration_id=reg.registration_id,
        object_id=item.obj.id,
        md5=item.obj.md5,
        run_id=reg.run_id,
        task=reg.task,
        task_name=reg.task_name,
        route=reg.route,
        registered_at=reg.registered_at,
    )


def _entries(
    storage: EngagementStoragePort, handle: RegistryHandle
) -> tuple[IndexEntry, ...]:
    items = [i for i in _scan(storage, handle) if i.registration is not None]
    return tuple(sorted((_entry(i) for i in items), key=lambda e: e.registration_id))


def _revisions(
    storage: EngagementStoragePort, handle: RegistryHandle
) -> dict[int, list[StorageObject]]:
    out: dict[int, list[StorageObject]] = {}
    for obj in storage.list_children(handle.index_folder_id):
        match = _INDEX_NAME_RE.fullmatch(obj.name)
        if match and not obj.is_folder:
            out.setdefault(int(match.group(1)), []).append(obj)
    return out


_ENTRY_FIELDS = frozenset(f.name for f in fields(IndexEntry))


def _parse_index(
    storage: EngagementStoragePort,
    handle: RegistryHandle,
    revision: int,
    obj: StorageObject,
) -> tuple[IndexEntry, ...] | None:
    try:
        if obj.properties.get(INDEX_PROPERTY) != f"rev:{revision}":
            return None
        data: Any = json.loads(read_object(storage, obj, max_bytes=_MAX_RECORD_BYTES))
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != _INDEX_VERSION
            or data.get("account_key") != handle.account_key
            or data.get("revision") != revision
            or not isinstance(data.get("entries"), list)
        ):
            return None
        entries: list[IndexEntry] = []
        for raw in data["entries"]:
            if not isinstance(raw, dict) or set(raw) != _ENTRY_FIELDS:
                return None
            entries.append(IndexEntry(**raw))
    except StorageAuthError:
        raise
    except (StorageError, ValueError, TypeError):
        return None
    return tuple(entries)


def _index_bytes(
    account_key: str, revision: int, entries: Sequence[IndexEntry]
) -> bytes:
    return encode_json(
        {
            "schema_version": _INDEX_VERSION,
            "account_key": account_key,
            "revision": revision,
            "entries": [
                {f.name: getattr(e, f.name) for f in fields(IndexEntry)}
                for e in entries
            ],
        }
    )


def rebuild_index(
    storage: EngagementStoragePort, handle: RegistryHandle
) -> StorageObject:
    """Append ``index/rev-NNNNNN.json`` built from the registrations listing.

    Returns the latest revision unchanged when it already records the same
    entries; earlier revisions are never modified.

    Raises:
        StoragePermissionError: The registry's access changed since resolution.
        RegistrationConflictError: A concurrent writer created the same revision.
    """
    _require_unchanged(storage, handle)
    entries = _entries(storage, handle)
    revisions = _revisions(storage, handle)
    latest = max(revisions, default=0)
    if latest and len(revisions[latest]) == 1:
        obj = revisions[latest][0]
        if _parse_index(storage, handle, latest, obj) == entries:
            return obj
    revision = latest + 1
    return _put_once(
        storage,
        handle.index_folder_id,
        f"rev-{revision:06d}.json",
        _index_bytes(handle.account_key, revision, entries),
        {INDEX_PROPERTY: f"rev:{revision}"},
    )


def read_index(
    storage: EngagementStoragePort, handle: RegistryHandle
) -> tuple[IndexEntry, ...] | None:
    """The latest index revision, or ``None`` when it cannot be trusted.

    ``None`` when the registry's access changed, there is no index, the latest
    revision is duplicated, unreadable or malformed, or its entries differ from
    the current registrations listing.
    """
    if _recheck(storage, handle) is not None:
        return None
    try:
        revisions = _revisions(storage, handle)
        if not revisions:
            return None
        latest = max(revisions)
        if len(revisions[latest]) != 1:
            return None
        entries = _parse_index(storage, handle, latest, revisions[latest][0])
        if entries is None:
            return None
        if entries != _entries(storage, handle):
            return None
    except StorageAuthError:
        raise
    except StorageError:
        return None
    return entries
