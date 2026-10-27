# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Restricted Drive staging for engagement preflight (engagement-drive spec §1).

Before any customer-workspace call, a Drive run creates an account-neutral,
owner-only staging folder::

    My Drive -> starboard -> _preflight -> <RUN ID>

and records preflight and identity results there. The run's first own write
(:func:`put_json` with read-back) proves upload capability; there are no probe
writes (owner decision D6). When the identity check disagrees with the
provisional account, :func:`quarantine_staging` moves the staging folder under
``_preflight/_quarantine`` with a reason property and the run stops before any
row, log or code acquisition.

Names are presentation, IDs are authority: every level carries a
``starboard_identity`` property (see :mod:`starboard_core.engagement.folders`).

Standard library only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from starboard_core.engagement.access import is_restricted
from starboard_core.engagement.folders import (
    FolderResolutionError,
    create_and_converge,
    creation_order,
    ensure_folder,
    ensure_starboard_root,
    existing_folders,
    starboard_roots,
)
from starboard_core.engagement.run_id import is_run_id
from starboard_core.ports.engagement_storage import (
    AccessInfo,
    EngagementStoragePort,
    StorageError,
    StorageIntegrityError,
    StorageObject,
)

PREFLIGHT_SEGMENT = "_preflight"
QUARANTINE_SEGMENT = "_quarantine"
QUARANTINE_PROPERTY = "starboard_quarantine"
JSON_MIME = "application/json"
# Drive caps a property's key + value at 124 UTF-8 bytes; the reason is capped
# at 100 bytes so ``starboard_quarantine`` + reason always fits.
_QUARANTINE_REASON_BYTES = 100

StagingState = Literal["staged", "quarantined", "missing"]


class StagingError(FolderResolutionError):
    """Staging could not be established or written; operator action is needed."""


class StagingNotRestrictedError(StagingError):
    """The staging folder's ACL is not owner-only (or cannot be fully read).

    Attributes:
        access: The access summary that failed the check.
    """

    def __init__(self, message: str, *, access: AccessInfo) -> None:
        super().__init__(message)
        self.access = access


@dataclass(frozen=True)
class Staging:
    """The run's restricted ``_preflight/<run-id>`` staging folder.

    Attributes:
        folder: The staging folder.
        preflight_folder_id: Its ``_preflight`` parent.
        access: Access summary that passed :func:`is_restricted`.
        link: Provider link to the staging folder, when available.
    """

    folder: StorageObject
    preflight_folder_id: str
    access: AccessInfo
    link: str | None


@dataclass(frozen=True)
class StagingLocation:
    """Where a run's staging folder is, found by run ID; nothing is created.

    Attributes:
        state: ``staged`` (under ``_preflight``), ``quarantined`` (under
            ``_preflight/_quarantine``) or ``missing``.
        folder: The staging folder; ``None`` when missing.
        preflight_folder_id: The ``_preflight`` folder it belongs to; ``None``
            when missing.
    """

    state: StagingState
    folder: StorageObject | None = None
    preflight_folder_id: str | None = None


def _preflight_folders(
    storage: EngagementStoragePort, roots: Sequence[StorageObject] | None = None
) -> list[StorageObject]:
    """Every ``starboard/_preflight`` folder, the winning root's first. Never creates.

    Two first runs at once can leave duplicate ``starboard`` (or ``_preflight``)
    folders, each holding some runs' staging folders, so a lookup by run ID
    searches all of them.
    """
    return [
        pre
        for root in (starboard_roots(storage) if roots is None else roots)
        for pre in existing_folders(storage, root.id, PREFLIGHT_SEGMENT, "preflight")
    ]


def _staged_under(
    storage: EngagementStoragePort, parent_id: str, run_id: str
) -> StorageObject | None:
    found = existing_folders(
        storage, parent_id, run_id, f"staging:{run_id}", adopt_untagged=False
    )
    return found[0] if found else None


def locate_staging(storage: EngagementStoragePort, run_id: str) -> StagingLocation:
    """Find ``run_id``'s staging folder under any ``_preflight``; never creates.

    A quarantined copy wins over a staged one.

    Raises:
        ValueError: ``run_id`` is malformed.
        FolderConflictError: A level is taken by a folder with another identity.
    """
    if not is_run_id(run_id):
        raise ValueError(f"not a valid run ID: {run_id!r}")
    preflights = _preflight_folders(storage)
    for pre in preflights:
        for quarantine in existing_folders(
            storage, pre.id, QUARANTINE_SEGMENT, "quarantine"
        ):
            held = _staged_under(storage, quarantine.id, run_id)
            if held is not None:
                return StagingLocation("quarantined", held, pre.id)
    for pre in preflights:
        folder = _staged_under(storage, pre.id, run_id)
        if folder is not None:
            return StagingLocation("staged", folder, pre.id)
    return StagingLocation("missing")


def staging_at(
    storage: EngagementStoragePort, folder: StorageObject, preflight_folder_id: str
) -> Staging:
    """The :class:`Staging` for an existing folder, after the owner-only ACL check.

    Raises:
        StagingNotRestrictedError: The staging folder is not owner-only.
    """
    access = storage.inspect_access(folder.id)
    if not is_restricted(access):
        raise StagingNotRestrictedError(
            f"staging folder {folder.id} is not restricted to its owner "
            f"(complete ACL: {access.complete}, grants: "
            f"{', '.join(sorted(g.kind for g in access.grants)) or 'none'}); "
            "remove the extra sharing or use a different Drive account",
            access=access,
        )
    return Staging(
        folder=folder,
        preflight_folder_id=preflight_folder_id,
        access=access,
        link=folder.web_link,
    )


def ensure_staging(storage: EngagementStoragePort, run_id: str) -> Staging:
    """Find or create the restricted staging folder for ``run_id``.

    Idempotent: a retry with the same run ID reuses the same folder, under
    whichever ``starboard/_preflight`` holds it (duplicate roots from two first
    runs at once are all searched). A new folder goes under the winning
    ``starboard`` root, the same one the account route uses.

    Raises:
        ValueError: ``run_id`` is malformed.
        StagingNotRestrictedError: The staging folder is not owner-only.
        FolderConflictError: A level is taken by a folder with another identity.
    """
    if not is_run_id(run_id):
        raise ValueError(f"not a valid run ID: {run_id!r}")
    roots = starboard_roots(storage)
    preflights = _preflight_folders(storage, roots)
    for pre in preflights:
        folder = _staged_under(storage, pre.id, run_id)
        if folder is not None:
            return staging_at(storage, folder, pre.id)
    # Every level below was just listed and found empty, so create directly
    # (one list call per level, as before duplicate roots were searched).
    root = ensure_starboard_root(storage, roots).folder
    preflight = next(
        (p for p in preflights if root.id in p.parent_ids), None
    ) or create_and_converge(storage, root.id, PREFLIGHT_SEGMENT, "preflight")
    folder = create_and_converge(storage, preflight.id, run_id, f"staging:{run_id}")
    return staging_at(storage, folder, preflight.id)


def encode_json(payload: Mapping[str, Any]) -> bytes:
    """Deterministic JSON: sorted keys, 2-space indent, trailing newline."""
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def read_all(storage: EngagementStoragePort, object_id: str) -> bytes:
    """Read an object's full content."""
    return b"".join(storage.get_stream(object_id))


def verify_bytes(
    storage: EngagementStoragePort, obj: StorageObject, sent: bytes
) -> None:
    """Raise ``StorageIntegrityError`` unless ``obj`` reads back as ``sent``."""
    if read_all(storage, obj.id) != sent:
        raise StorageIntegrityError(
            f"content read back from {obj.id} ({obj.name!r}) does not match what was written"
        )


def put_json(
    storage: EngagementStoragePort,
    parent_id: str,
    name: str,
    payload: Mapping[str, Any],
    *,
    properties: Mapping[str, str],
) -> StorageObject:
    """Write ``payload`` as deterministic JSON under ``parent_id`` and verify it.

    Idempotent: an existing file with the same name carrying ``properties`` is
    reused when its content is byte-equal, and otherwise updated in place as a
    new revision (``update_stream``), never re-created. The stored content is
    always read back and compared byte-for-byte.

    Byte-identical same-named copies (a retried upload) are collapsed to the
    earliest one (the others are trashed) before it is reused or updated.

    Raises:
        StagingError: Several same-named files carry ``properties`` and differ, or
            an identical twin could not be trashed.
        StorageIntegrityError: The read-back does not match.
    """
    data = encode_json(payload)
    wanted = dict(properties)
    matches = [
        c
        for c in storage.list_children(parent_id, name=name)
        if not c.is_folder and all(c.properties.get(k) == v for k, v in wanted.items())
    ]
    matches.sort(key=creation_order)
    # Byte-identical copies are one write a retried upload landed twice (run 11).
    if len(matches) > 1 and (
        matches[0].md5 is None
        or any(m.md5 != matches[0].md5 or m.size != matches[0].size for m in matches)
    ):
        raise StagingError(
            f"{len(matches)} files named {name!r} with the same properties under "
            f"{parent_id}; reconcile in Drive (ids: {', '.join(m.id for m in matches)})"
        )
    if len(matches) > 1:
        # Collapse the twins to the earliest copy (as the run sink does) so it can be
        # reused or updated like a single match.
        for extra in matches[1:]:
            try:
                storage.trash(extra.id)
            except StorageError as exc:
                raise StagingError(
                    f"{len(matches)} identical files named {name!r} under {parent_id}; "
                    f"could not trash {extra.id} ({exc}): reconcile in Drive"
                ) from exc
        matches = matches[:1]
    if matches:
        existing = matches[0]
        if read_all(storage, existing.id) == data:
            return existing
        obj = storage.update_stream(existing.id, JSON_MIME, [data])
    else:
        obj = storage.put_stream(parent_id, name, JSON_MIME, [data], properties=wanted)
    verify_bytes(storage, obj, data)
    return obj


def quarantine_staging(
    storage: EngagementStoragePort, staging: Staging, reason: str
) -> StorageObject:
    """Move the staging folder to ``_preflight/_quarantine`` and tag it with ``reason``.

    The folder keeps its contents and identity; the reason is stored in the
    :data:`QUARANTINE_PROPERTY` property, capped at 100 UTF-8 bytes.

    Raises:
        ValueError: ``reason`` is empty.
        StorageIntegrityError: The move or tag did not read back.
    """
    if not reason or not reason.strip():
        raise ValueError("a quarantine reason is required")
    capped = (
        reason.strip()
        .encode("utf-8")[:_QUARANTINE_REASON_BYTES]
        .decode("utf-8", errors="ignore")
    )
    quarantine = ensure_folder(
        storage, staging.preflight_folder_id, QUARANTINE_SEGMENT, "quarantine"
    )
    return storage.update(
        staging.folder.id,
        add_parent_id=quarantine.id,
        remove_parent_id=staging.preflight_folder_id,
        properties={QUARANTINE_PROPERTY: capped},
    )


__all__ = [
    "JSON_MIME",
    "PREFLIGHT_SEGMENT",
    "QUARANTINE_PROPERTY",
    "QUARANTINE_SEGMENT",
    "Staging",
    "StagingError",
    "StagingLocation",
    "StagingNotRestrictedError",
    "StagingState",
    "encode_json",
    "ensure_staging",
    "locate_staging",
    "put_json",
    "quarantine_staging",
    "read_all",
    "staging_at",
    "verify_bytes",
]
