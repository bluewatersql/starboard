# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""In-memory :class:`EngagementStoragePort` for tests and conformance suites.

Holds folders, files and their bytes in process memory; nothing touches disk.
It models the Drive behaviors the folder resolver depends on:

* folder names are not unique (``create_folder`` never deduplicates);
* ACL grants are inherited from ancestors, and ``inspect_access`` reports the
  effective set with a stable fingerprint;
* objects live either in the operator's ``My Drive`` (the configurable root) or
  in a parentless shared-drive root added with :meth:`add_shared_drive`.

Fault-injection attributes, all mutable on the instance:

* ``auth_failed`` - every port call raises :class:`StorageAuthError`;
* ``deny_writes_under`` - folder IDs whose whole subtree rejects writes with
  :class:`StoragePermissionError`;
* ``duplicate_on_create`` - folder names that, on their next ``create_folder``,
  also get a same-named twin with the same properties (a concurrent duplicate
  create; Drive has no compare-and-set). One-shot per name;
* ``corrupt_read_back`` - transforms stored bytes in ``put_stream`` and
  ``update_stream`` so the read-back no longer matches what was sent (raises
  :class:`StorageIntegrityError`; the corrupted object stays stored, as an
  acknowledged-but-wrong provider write would);
* ``corrupt_get_stream`` - transforms the bytes ``get_stream`` returns while the
  stored metadata (size/MD5) stays correct, so a caller's own content
  read-back sees a mismatch;
* ``list_lag`` - a folder ``create_folder`` makes stays out of the next ``n``
  ``list_children`` calls (Drive's listing can lag a create);
* ``duplicate_on_put`` - file names that, on their next ``put_stream``, also get
  a same-named twin with the same properties and content (a concurrent writer).
  One-shot per name;
* ``drop_updates`` - ``update`` is acknowledged but not applied, as a provider
  that silently ignored the change would (raises
  :class:`StorageIntegrityError` on read-back);
* ``fail_put_after`` - once set to ``n``, the next ``n`` content writes
  (``put_stream`` / ``update_stream``) succeed and every later one raises a
  plain :class:`StorageError` before storing anything (a provider failure after
  the adapter's in-process retries are exhausted). ``None`` clears it;
* ``revoke_access_after_writes`` - once set to ``n``, the next ``n`` writes
  (``create_folder`` / ``put_stream`` / ``update_stream`` / ``update``) succeed;
  after that access is revoked mid-run: every write raises
  :class:`StoragePermissionError` and ``inspect_access`` reports
  ``can_add_children=False`` everywhere (reads still work). ``None`` clears it.

:meth:`corrupt_object` flips an object's stored bytes in place (silent at-rest
corruption) while its size/MD5/revision metadata stays unchanged.

``update_stream`` keeps every earlier content revision, so ``get_stream`` with an
older revision ID still returns the bytes that revision held.

``trash`` hides an object from ``list_children`` and ``find_by_property`` (as
Drive does); ``get`` and ``get_stream`` still work on it by ID.

Seeding helpers (:meth:`add_folder`, :meth:`add_shared_drive`,
:meth:`set_access`) bypass fault injection so tests can build fixtures freely.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from starboard_core.ports.engagement_storage import (
    FOLDER_MIME,
    AccessInfo,
    DriveKind,
    Grant,
    StorageAuthError,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StorageObject,
    StoragePermissionError,
)

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_CHUNK = 64 * 1024


@dataclass
class _Entry:
    obj: StorageObject
    can_add_children: bool = True
    grants: tuple[Grant, ...] = ()
    complete: bool = True
    drive_kind: DriveKind = "my_drive"
    drive_id: str | None = None
    content: bytes | None = None
    revisions: dict[str, bytes] = field(default_factory=dict)
    trashed: bool = False


class InMemoryEngagementStorage:
    """Dict-backed engagement storage implementing ``EngagementStoragePort``."""

    def __init__(
        self,
        *,
        root_id: str = "my-drive-root",
        root_name: str = "My Drive",
        owner_domain: str = "example.com",
        principal_id: str = "perm-owner-0001",
    ) -> None:
        self._entries: dict[str, _Entry] = {}
        self._seq = 0
        self._root_id = root_id
        self._principal_id = principal_id
        self.auth_failed = False
        self.deny_writes_under: set[str] = set()
        self.duplicate_on_create: set[str] = set()
        self.corrupt_read_back: Callable[[bytes], bytes] | None = None
        self.corrupt_get_stream: Callable[[bytes], bytes] | None = None
        self.duplicate_on_put: set[str] = set()
        self.list_lag = 0
        self._lagging: dict[str, int] = {}
        self.drop_updates = False
        self._puts = 0
        self._writes = 0
        self._fail_put_set: int | None = None
        self._fail_put_at: int | None = None
        self._revoke_set: int | None = None
        self._revoke_at: int | None = None
        self._insert(
            parent_id=None,
            name=root_name,
            mime_type=FOLDER_MIME,
            properties={},
            object_id=root_id,
            grants=(Grant("user", "owner", owner_domain),),
        )

    # --- seeding helpers (no fault injection) -------------------------------------

    @property
    def object_count(self) -> int:
        """Number of stored objects, roots included."""
        return len(self._entries)

    def add_folder(
        self,
        parent_id: str,
        name: str,
        *,
        properties: Mapping[str, str] | None = None,
        folder_id: str | None = None,
        can_add_children: bool = True,
        grants: tuple[Grant, ...] = (),
        complete: bool = True,
        created_time: str | None = None,
    ) -> StorageObject:
        """Seed a folder under ``parent_id`` with explicit access settings.

        ``created_time`` (RFC 3339) overrides the sequential creation time, so a
        test can seed a folder that a concurrent session created *earlier*.
        """
        self._require(parent_id)
        return self._insert(
            parent_id=parent_id,
            name=name,
            mime_type=FOLDER_MIME,
            properties=properties or {},
            object_id=folder_id,
            can_add_children=can_add_children,
            grants=grants,
            complete=complete,
            created_time=created_time,
        )

    def add_shared_drive(
        self,
        folder_id: str,
        name: str,
        *,
        drive_id: str,
        grants: tuple[Grant, ...] = (),
        can_add_children: bool = True,
        complete: bool = True,
    ) -> StorageObject:
        """Seed a parentless shared-drive root folder."""
        return self._insert(
            parent_id=None,
            name=name,
            mime_type=FOLDER_MIME,
            properties={},
            object_id=folder_id,
            can_add_children=can_add_children,
            grants=grants,
            complete=complete,
            drive_kind="shared_drive",
            drive_id=drive_id,
        )

    def set_access(
        self,
        object_id: str,
        *,
        can_add_children: bool | None = None,
        grants: tuple[Grant, ...] | None = None,
        complete: bool | None = None,
    ) -> None:
        """Change an object's own access settings (``grants`` are its direct grants)."""
        entry = self._require(object_id)
        if can_add_children is not None:
            entry.can_add_children = can_add_children
        if grants is not None:
            entry.grants = grants
        if complete is not None:
            entry.complete = complete

    @property
    def fail_put_after(self) -> int | None:
        """Content writes still allowed when this was set (``None``: no fault)."""
        return self._fail_put_set

    @fail_put_after.setter
    def fail_put_after(self, value: int | None) -> None:
        self._fail_put_set = value
        self._fail_put_at = None if value is None else self._puts + value

    @property
    def revoke_access_after_writes(self) -> int | None:
        """Writes still allowed when this was set (``None``: no fault)."""
        return self._revoke_set

    @revoke_access_after_writes.setter
    def revoke_access_after_writes(self, value: int | None) -> None:
        self._revoke_set = value
        self._revoke_at = None if value is None else self._writes + value

    def corrupt_object(self, object_id: str) -> None:
        """Flip the stored bytes of ``object_id`` (all its revisions), keeping metadata.

        Raises:
            StorageNotFoundError: Unknown object.
            StorageError: The object has no binary content (a folder).
        """
        entry = self._require(object_id)
        if entry.content is None:
            raise StorageError(f"{object_id} has no binary content to corrupt")
        entry.content = _flip(entry.content)
        entry.revisions = {rev: _flip(data) for rev, data in entry.revisions.items()}

    # --- port ------------------------------------------------------------------------

    def root_folder_id(self) -> str:
        self._check_auth()
        return self._root_id

    def get(self, object_id: str) -> StorageObject:
        self._check_auth()
        return self._require(object_id).obj

    def list_children(
        self,
        parent_id: str,
        *,
        name: str | None = None,
        folders_only: bool = False,
    ) -> list[StorageObject]:
        self._check_auth()
        self._require(parent_id)
        hidden = {oid for oid, n in self._lagging.items() if n > 0}
        self._lagging = {oid: n - 1 for oid, n in self._lagging.items() if n > 1}
        return [
            e.obj
            for e in self._entries.values()
            if not e.trashed
            and e.obj.id not in hidden
            and parent_id in e.obj.parent_ids
            and (name is None or e.obj.name == name)
            and (not folders_only or e.obj.is_folder)
        ]

    def find_by_property(
        self, key: str, value: str, *, drive_id: str | None = None
    ) -> list[StorageObject]:
        self._check_auth()
        return [
            e.obj
            for oid, e in self._entries.items()
            if not e.trashed
            and e.obj.properties.get(key) == value
            and self._entries[self._ancestors(oid)[-1]].drive_id == drive_id
        ]

    def trash(self, object_id: str) -> None:
        self._check_auth()
        entry = self._require(object_id)
        self._check_not_denied(object_id)
        entry.trashed = True
        self._writes += 1

    def create_folder(
        self, parent_id: str, name: str, properties: Mapping[str, str]
    ) -> StorageObject:
        self._check_auth()
        self._check_writable(parent_id)
        created = self._insert(
            parent_id=parent_id, name=name, mime_type=FOLDER_MIME, properties=properties
        )
        self._writes += 1
        if self.list_lag:
            self._lagging[created.id] = self.list_lag
        if name in self.duplicate_on_create:
            self.duplicate_on_create.discard(name)
            self._insert(
                parent_id=parent_id,
                name=name,
                mime_type=FOLDER_MIME,
                properties=properties,
            )
        return created

    def inspect_access(self, object_id: str) -> AccessInfo:
        self._check_auth()
        entry = self._require(object_id)
        grants = self._effective_grants(object_id)
        top = self._entries[self._ancestors(object_id)[-1]]
        canonical = "|".join(
            sorted(f"{g.kind}:{g.role}:{g.domain or ''}" for g in grants)
        )
        return AccessInfo(
            object_id=object_id,
            can_add_children=entry.can_add_children
            and entry.obj.is_folder
            and not self._revoked(),
            drive_kind=top.drive_kind,
            drive_id=top.drive_id,
            grants=grants,
            fingerprint=hashlib.sha256(canonical.encode()).hexdigest(),
            complete=entry.complete,
        )

    def put_stream(
        self,
        parent_id: str,
        name: str,
        mime_type: str,
        chunks: Iterable[bytes],
        *,
        properties: Mapping[str, str],
    ) -> StorageObject:
        self._check_auth()
        self._check_writable(parent_id)
        self._check_put()
        sent = _collect(chunks, "put_stream")
        stored = self.corrupt_read_back(sent) if self.corrupt_read_back else sent
        obj = self._insert(
            parent_id=parent_id,
            name=name,
            mime_type=mime_type,
            properties=properties,
            content=stored,
        )
        self._puts += 1
        self._writes += 1
        if name in self.duplicate_on_put:
            self.duplicate_on_put.discard(name)
            self._insert(
                parent_id=parent_id,
                name=name,
                mime_type=mime_type,
                properties=properties,
                content=stored,
            )
        _verify_content(obj, sent)
        return obj

    def get_stream(
        self, object_id: str, revision: str | None = None
    ) -> Iterator[bytes]:
        self._check_auth()
        entry = self._require(object_id)
        if entry.content is None:
            raise StorageNotFoundError(f"{object_id} has no binary content")
        if revision is not None and revision not in entry.revisions:
            raise StorageNotFoundError(f"{object_id} has no revision {revision!r}")
        content = entry.content if revision is None else entry.revisions[revision]
        if self.corrupt_get_stream:
            content = self.corrupt_get_stream(content)
        return iter(
            [content[i : i + _CHUNK] for i in range(0, len(content), _CHUNK)] or [b""]
        )

    def principal_id(self) -> str:
        self._check_auth()
        return self._principal_id

    def update(
        self,
        object_id: str,
        *,
        name: str | None = None,
        properties: Mapping[str, str] | None = None,
        add_parent_id: str | None = None,
        remove_parent_id: str | None = None,
    ) -> StorageObject:
        self._check_auth()
        entry = self._require(object_id)
        self._check_not_denied(object_id)
        parents = list(entry.obj.parent_ids)
        if add_parent_id is not None:
            self._check_writable(add_parent_id)
            if object_id in self._ancestors(add_parent_id):
                raise StorageError(
                    f"cannot move {object_id} under its own descendant {add_parent_id}"
                )
            if add_parent_id not in parents:
                parents.append(add_parent_id)
        if remove_parent_id is not None:
            if remove_parent_id not in entry.obj.parent_ids:
                raise StorageError(f"{remove_parent_id} is not a parent of {object_id}")
            parents.remove(remove_parent_id)
            if not parents:
                raise StorageError(
                    f"removing parent {remove_parent_id} would leave {object_id} orphaned"
                )
        wanted = replace(
            entry.obj,
            name=entry.obj.name if name is None else name,
            properties={**entry.obj.properties, **(properties or {})},
            parent_ids=tuple(parents),
        )
        if not self.drop_updates:
            entry.obj = wanted
        self._writes += 1
        got = entry.obj
        if (
            got.name != wanted.name
            or dict(got.properties) != dict(wanted.properties)
            or got.parent_ids != wanted.parent_ids
        ):
            raise StorageIntegrityError(
                f"update of {object_id} did not read back with the requested changes"
            )
        return got

    def update_stream(
        self, object_id: str, mime_type: str, chunks: Iterable[bytes]
    ) -> StorageObject:
        self._check_auth()
        entry = self._require(object_id)
        if entry.obj.is_folder or entry.content is None:
            raise StorageError(f"{object_id} is not a binary file")
        self._check_not_denied(object_id)
        self._check_put()
        sent = _collect(chunks, "update_stream")
        stored = self.corrupt_read_back(sent) if self.corrupt_read_back else sent
        self._seq += 1
        revision = f"rev-{self._seq}"
        entry.content = stored
        entry.revisions[revision] = stored
        entry.obj = replace(
            entry.obj,
            mime_type=mime_type,
            size=len(stored),
            md5=hashlib.md5(stored, usedforsecurity=False).hexdigest(),
            revision=revision,
        )
        self._puts += 1
        self._writes += 1
        _verify_content(entry.obj, sent)
        return entry.obj

    # --- internals ------------------------------------------------------------------

    def _check_auth(self) -> None:
        if self.auth_failed:
            raise StorageAuthError("not authenticated (injected)")

    def _require(self, object_id: str) -> _Entry:
        entry = self._entries.get(object_id)
        if entry is None:
            raise StorageNotFoundError(f"object {object_id!r} not found")
        return entry

    def _ancestors(self, object_id: str) -> list[str]:
        """``object_id`` followed by its ancestors up to the top-level folder."""
        chain = [object_id]
        parents = self._entries[object_id].obj.parent_ids
        while parents:
            chain.append(parents[0])
            parents = self._entries[parents[0]].obj.parent_ids
        return chain

    def _effective_grants(self, object_id: str) -> tuple[Grant, ...]:
        seen: dict[Grant, None] = {}
        for oid in reversed(self._ancestors(object_id)):
            for grant in self._entries[oid].grants:
                seen.setdefault(grant, None)
        return tuple(seen)

    def _revoked(self) -> bool:
        return self._revoke_at is not None and self._writes >= self._revoke_at

    def _check_put(self) -> None:
        if self._fail_put_at is not None and self._puts >= self._fail_put_at:
            raise StorageError("content write failed (injected fail_put_after)")

    def _check_not_denied(self, object_id: str) -> None:
        if self._revoked():
            raise StoragePermissionError(
                f"access revoked; writes to {object_id} refused (injected)"
            )
        if any(oid in self.deny_writes_under for oid in self._ancestors(object_id)):
            raise StoragePermissionError(f"writes denied under {object_id} (injected)")

    def _check_writable(self, parent_id: str) -> None:
        entry = self._require(parent_id)
        if not entry.obj.is_folder:
            raise StorageError(f"{parent_id} is not a folder")
        self._check_not_denied(parent_id)
        if not entry.can_add_children:
            raise StoragePermissionError(f"cannot add children to {parent_id}")

    def _insert(
        self,
        *,
        parent_id: str | None,
        name: str,
        mime_type: str,
        properties: Mapping[str, str],
        object_id: str | None = None,
        can_add_children: bool = True,
        grants: tuple[Grant, ...] = (),
        complete: bool = True,
        drive_kind: DriveKind = "my_drive",
        drive_id: str | None = None,
        content: bytes | None = None,
        created_time: str | None = None,
    ) -> StorageObject:
        self._seq += 1
        oid = object_id or f"obj-{self._seq:04d}"
        if oid in self._entries:
            raise ValueError(f"object id {oid!r} already exists")
        created = created_time or (
            (_EPOCH + timedelta(seconds=self._seq)).isoformat().replace("+00:00", "Z")
        )
        is_folder = mime_type == FOLDER_MIME
        obj = StorageObject(
            id=oid,
            name=name,
            mime_type=mime_type,
            parent_ids=(parent_id,) if parent_id else (),
            properties=dict(properties),
            web_link=f"memory://{'folders' if is_folder else 'files'}/{oid}",
            size=None if content is None else len(content),
            md5=None
            if content is None
            else hashlib.md5(content, usedforsecurity=False).hexdigest(),
            revision=None if content is None else f"rev-{self._seq}",
            created_time=created,
        )
        self._entries[oid] = _Entry(
            obj=obj,
            can_add_children=can_add_children,
            grants=grants,
            complete=complete,
            drive_kind=drive_kind,
            drive_id=drive_id,
            content=content,
            revisions={}
            if obj.revision is None or content is None
            else {obj.revision: content},
        )
        return obj


def _collect(chunks: Iterable[bytes], op: str) -> bytes:
    buf = bytearray()
    for chunk in chunks:
        if not isinstance(chunk, bytes | bytearray | memoryview):
            raise TypeError(f"{op} chunks must be bytes, got {type(chunk).__name__}")
        buf.extend(chunk)
    return bytes(buf)


def _flip(data: bytes) -> bytes:
    """Different bytes of the same length (one byte for empty content)."""
    if not data:
        return b"\x00"
    return bytes([data[0] ^ 0xFF]) + data[1:]


def _verify_content(obj: StorageObject, sent: bytes) -> None:
    """Read-back verification of stored size/MD5 against what was sent."""
    sent_md5 = hashlib.md5(sent, usedforsecurity=False).hexdigest()
    if obj.size != len(sent) or obj.md5 != sent_md5:
        raise StorageIntegrityError(
            f"read-back mismatch for {obj.id}: sent {len(sent)} bytes md5 {sent_md5}, "
            f"stored {obj.size} bytes md5 {obj.md5}"
        )


__all__ = ["InMemoryEngagementStorage"]
