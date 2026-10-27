# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run descriptor and append-only manifest for Drive-backed runs (engagement-drive spec §2).

Inside a run folder::

    <RUN ID>/
      run-authorization.json      the frozen RunAuthorization (no credentials)
      manifest/
        rev-000001.json           RunManifest revision 1 (written at route)
        rev-000002.json           one revision per upload commit
        ...

The descriptor is written once and read back; a later write must find a
byte-equal descriptor or stop (:class:`DescriptorConflictError`). Manifest
revisions are immutable files, each naming its predecessor's object ID. Drive
has no compare-and-set (phase-0 fact F5), so after creating revision ``n`` the
folder is re-listed: more than one differing object for ``n`` means a concurrent
writer, and the commit stops with :class:`ManifestConflictError` for operator
reconciliation. Byte-identical copies of ``n`` are one write a retried upload
request landed twice (run 13): they are one revision, and the next revision may
chain to any of them. A manifest is only ever created, never updated.

Standard library only.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    creation_order,
    ensure_folder,
)
from starboard_core.engagement.records import RunAuthorization, RunManifest
from starboard_core.engagement.staging import (
    JSON_MIME,
    encode_json,
    put_json,
    read_all,
    verify_bytes,
)
from starboard_core.ports.engagement_storage import EngagementStoragePort, StorageObject

DESCRIPTOR_NAME = "run-authorization.json"
DESCRIPTOR_PROPERTY = "starboard_descriptor"
MANIFEST_SEGMENT = "manifest"
MANIFEST_PROPERTY = "starboard_manifest"


class CommitError(Exception):
    """The run descriptor or manifest is missing, invalid or inconsistent."""


class DescriptorConflictError(CommitError):
    """A different (or duplicate) run descriptor already exists in the run folder."""


class ManifestConflictError(CommitError):
    """More than one manifest object exists for one revision number."""


# ---- descriptor -----------------------------------------------------------------


def _descriptor_candidates(
    storage: EngagementStoragePort, run_folder_id: str
) -> list[StorageObject]:
    return [
        c
        for c in storage.list_children(run_folder_id, name=DESCRIPTOR_NAME)
        if not c.is_folder
    ]


def write_descriptor(
    storage: EngagementStoragePort, run_folder_id: str, auth: RunAuthorization
) -> StorageObject:
    """Write ``auth`` as the run descriptor, or confirm an equal one exists.

    Raises:
        CommitError: ``auth.drive`` names a different run folder.
        DescriptorConflictError: A descriptor with different content, a foreign
            same-named object or a concurrent duplicate exists.
        StorageIntegrityError: The read-back does not match.
    """
    if auth.drive is not None and auth.drive.run_folder_id != run_folder_id:
        raise CommitError(
            f"descriptor names run folder {auth.drive.run_folder_id}, "
            f"not {run_folder_id}"
        )
    data = encode_json(auth.to_dict())
    tag = f"run:{auth.run_id}"
    existing = _descriptor_candidates(storage, run_folder_id)
    if existing:
        if len(existing) > 1 or existing[0].properties.get(DESCRIPTOR_PROPERTY) != tag:
            raise DescriptorConflictError(
                f"run folder {run_folder_id} already holds {len(existing)} "
                f"{DESCRIPTOR_NAME} object(s) not matching run {auth.run_id}; reconcile "
                f"in Drive (ids: {', '.join(o.id for o in existing)})"
            )
        if read_all(storage, existing[0].id) != data:
            raise DescriptorConflictError(
                f"run folder {run_folder_id} already has a different run descriptor "
                f"({existing[0].id}); the run authorization is immutable"
            )
        return existing[0]
    obj = put_json(
        storage,
        run_folder_id,
        DESCRIPTOR_NAME,
        auth.to_dict(),
        properties={DESCRIPTOR_PROPERTY: tag},
    )
    after = _descriptor_candidates(storage, run_folder_id)
    if len(after) != 1:
        raise DescriptorConflictError(
            f"{len(after)} {DESCRIPTOR_NAME} objects under {run_folder_id} after write "
            f"(concurrent writer); reconcile in Drive (ids: {', '.join(o.id for o in after)})"
        )
    return obj


def read_descriptor(
    storage: EngagementStoragePort, run_folder_id: str
) -> tuple[RunAuthorization, StorageObject]:
    """Read and validate the single run descriptor in ``run_folder_id``.

    Raises:
        CommitError: No descriptor, more than one, unparseable content or a
            property that does not name the descriptor's run.
    """
    found = [
        c
        for c in _descriptor_candidates(storage, run_folder_id)
        if DESCRIPTOR_PROPERTY in c.properties
    ]
    if len(found) != 1:
        raise CommitError(
            f"expected exactly one run descriptor in {run_folder_id}, found {len(found)}"
        )
    obj = found[0]
    try:
        auth = RunAuthorization.from_dict(json.loads(read_all(storage, obj.id)))
    except (ValueError, TypeError, KeyError) as exc:
        raise CommitError(f"run descriptor {obj.id} is not valid: {exc}") from exc
    if obj.properties.get(DESCRIPTOR_PROPERTY) != f"run:{auth.run_id}":
        raise CommitError(
            f"run descriptor {obj.id} is tagged for a different run than {auth.run_id}"
        )
    return auth, obj


# ---- manifest -------------------------------------------------------------------


def _find_manifest_folder(
    storage: EngagementStoragePort, run_folder_id: str, run_id: str
) -> StorageObject | None:
    identity = f"manifest:{run_id}"
    found = [
        c
        for c in storage.list_children(
            run_folder_id, name=MANIFEST_SEGMENT, folders_only=True
        )
        if c.properties.get(IDENTITY_PROPERTY) == identity
    ]
    if len(found) > 1:
        raise ManifestConflictError(
            f"{len(found)} manifest folders for run {run_id} under {run_folder_id}"
        )
    return found[0] if found else None


def _revisions(
    storage: EngagementStoragePort, folder_id: str, run_id: str
) -> dict[int, list[StorageObject]]:
    by_rev: dict[int, list[StorageObject]] = {}
    for child in storage.list_children(folder_id):
        value = child.properties.get(MANIFEST_PROPERTY)
        if child.is_folder or value is None:
            continue
        owner, _, number = value.rpartition(":")
        if owner != run_id or not number.isdigit():
            raise CommitError(
                f"manifest object {child.id} is tagged {value!r}, not run {run_id}"
            )
        by_rev.setdefault(int(number), []).append(child)
    duplicated = sorted(
        n for n, objs in by_rev.items() if len(objs) > 1 and not _identical(objs)
    )
    if duplicated:
        raise ManifestConflictError(
            f"manifest revision(s) {duplicated} of run {run_id} exist more than once "
            "(concurrent writer); reconcile in Drive"
        )
    for objs in by_rev.values():  # identical copies: the earliest first
        objs.sort(key=creation_order)
    if by_rev and sorted(by_rev) != list(range(1, max(by_rev) + 1)):
        raise CommitError(
            f"manifest revisions of run {run_id} are not contiguous: {sorted(by_rev)}"
        )
    return by_rev


def _identical(objs: list[StorageObject]) -> bool:
    """Whether every copy has the first one's MD5 and size (a retried upload's twin)."""
    first = objs[0]
    return first.md5 is not None and all(
        o.md5 == first.md5 and o.size == first.size for o in objs
    )


def _load_latest(
    storage: EngagementStoragePort, folder_id: str, run_id: str
) -> tuple[RunManifest, StorageObject] | None:
    by_rev = _revisions(storage, folder_id, run_id)
    if not by_rev:
        return None
    n = max(by_rev)
    obj = by_rev[n][0]
    try:
        manifest = RunManifest.from_dict(json.loads(read_all(storage, obj.id)))
    except (ValueError, TypeError, KeyError) as exc:
        raise CommitError(
            f"manifest revision {n} ({obj.id}) is not valid: {exc}"
        ) from exc
    # Any identical copy of revision n - 1 is its predecessor.
    expected = {o.id for o in by_rev[n - 1]} if n > 1 else {None}
    if (
        manifest.run_id != run_id
        or manifest.revision != n
        or manifest.previous_object_id not in expected
    ):
        expected_prev = by_rev[n - 1][0].id if n > 1 else None
        raise CommitError(
            f"manifest revision {n} ({obj.id}) does not chain to its predecessor "
            f"{expected_prev!r} for run {run_id}"
        )
    return manifest, obj


def append_manifest(
    storage: EngagementStoragePort,
    run_folder_id: str,
    build: Callable[[int, str | None], RunManifest],
) -> tuple[RunManifest, StorageObject]:
    """Commit the next manifest revision of the run in ``run_folder_id``.

    ``build(n, previous_object_id)`` returns the manifest for revision ``n``; it
    must match the run descriptor (run and engagement IDs, ``descriptor_ref``)
    and the given revision chain.

    Raises:
        CommitError: No valid descriptor, a broken chain or a ``build`` result
            that does not match.
        ManifestConflictError: A revision exists more than once (before or
            after this write).
        StorageIntegrityError: The read-back does not match.
    """
    auth, descriptor = read_descriptor(storage, run_folder_id)
    run_id = auth.run_id
    folder = ensure_folder(
        storage,
        run_folder_id,
        MANIFEST_SEGMENT,
        f"manifest:{run_id}",
        adopt_untagged=False,
    )
    latest = _load_latest(storage, folder.id, run_id)
    n = 1 if latest is None else latest[0].revision + 1
    previous = None if latest is None else latest[1].id

    manifest = build(n, previous)
    mismatches = [
        label
        for label, ok in (
            ("run_id", manifest.run_id == run_id),
            ("engagement_id", manifest.engagement_id == auth.engagement_id),
            ("revision", manifest.revision == n),
            ("previous_object_id", manifest.previous_object_id == previous),
            ("descriptor_ref", manifest.descriptor_ref.object_id == descriptor.id),
        )
        if not ok
    ]
    if mismatches:
        raise CommitError(
            f"manifest for revision {n} of run {run_id} does not match: "
            f"{', '.join(mismatches)}"
        )

    data = encode_json(manifest.to_dict())
    obj = storage.put_stream(
        folder.id,
        f"rev-{n:06d}.json",
        JSON_MIME,
        [data],
        properties={MANIFEST_PROPERTY: f"{run_id}:{n}"},
    )
    _revisions(storage, folder.id, run_id)  # re-list: a concurrent duplicate stops here
    verify_bytes(storage, obj, data)
    return manifest, obj


def latest_manifest(
    storage: EngagementStoragePort, run_folder_id: str, *, run_id: str | None = None
) -> tuple[RunManifest, StorageObject] | None:
    """Return the latest committed manifest revision, or ``None`` when there is none.

    ``run_id`` is the folder's run when the caller already read and checked its
    descriptor (a registry target, ``--prior``): the descriptor is not read again.
    The manifest folder and every revision are still checked against that run.

    Raises:
        CommitError: No valid descriptor, or a broken/non-contiguous chain.
        ManifestConflictError: A revision exists more than once.
    """
    if run_id is None:
        run_id = read_descriptor(storage, run_folder_id)[0].run_id
    folder = _find_manifest_folder(storage, run_folder_id, run_id)
    if folder is None:
        return None
    return _load_latest(storage, folder.id, run_id)


__all__ = [
    "DESCRIPTOR_NAME",
    "DESCRIPTOR_PROPERTY",
    "MANIFEST_PROPERTY",
    "MANIFEST_SEGMENT",
    "CommitError",
    "DescriptorConflictError",
    "ManifestConflictError",
    "append_manifest",
    "latest_manifest",
    "read_descriptor",
    "write_descriptor",
]
