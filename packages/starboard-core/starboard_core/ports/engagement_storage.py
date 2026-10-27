# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Engagement storage port (engagement-drive spec §4).

A kernel-tier, SDK-free Protocol for the remote store that holds engagement
evidence and outputs when a run is Drive-backed. The operations are byte-stream
and ID based: no method accepts or returns a local filesystem path, so an
adapter cannot satisfy the contract by staging content on disk.

Folder names are presentation; IDs are authority. Identity metadata travels in
``properties`` (string key/value pairs the provider stores on the object), which
is how the folder resolver tells two same-named folders apart.

Existing objects change only through :meth:`EngagementStoragePort.update`
(metadata: rename, merge properties, move between parents) and
:meth:`EngagementStoragePort.update_stream` (new content revision of a file).
Both return a read-back-verified object; :meth:`EngagementStoragePort.trash`
moves a redundant object to the (recoverable) trash. The authenticated principal is exposed
only as an opaque ID (:meth:`EngagementStoragePort.principal_id`), never an
email address.

The public Google Drive adapter lives in ``starboard``; tests use an in-memory
fake. Errors are typed so callers can distinguish "prompt for auth" from "no
write permission, fall back" (owner decision D6).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

FOLDER_MIME = "application/vnd.google-apps.folder"

DriveKind = Literal["my_drive", "shared_drive"]
GrantKind = Literal["user", "group", "domain", "anyone"]


class StorageError(Exception):
    """Base class for engagement-storage failures."""


class StorageAuthError(StorageError):
    """The operator is not authenticated (or the token expired): prompt for auth."""


class StoragePermissionError(StorageError):
    """Authenticated, but not allowed to perform the operation on the target."""


class StorageNotFoundError(StorageError):
    """The referenced object does not exist or is not visible to the operator."""


class StorageIntegrityError(StorageError):
    """A write was acknowledged but read-back did not match (size/checksum)."""


class StorageTransientError(StorageError):
    """A retryable provider failure (HTTP 429/5xx, rate limit, timeout or transport
    error) that the adapter's own bounded retries did not clear.

    Nothing about the request was refused: the same call may succeed if retried
    later.
    """


@dataclass(frozen=True)
class StorageObject:
    """Metadata for one stored folder or file.

    Attributes:
        id: Provider object ID (the authority).
        name: Display name.
        mime_type: MIME type; :data:`FOLDER_MIME` for folders.
        parent_ids: Parent folder IDs.
        properties: Provider-stored identity metadata (string pairs).
        web_link: Human-readable link, when the provider returns one.
        size: Byte size for binary files; ``None`` for folders/native docs.
        md5: Provider-computed MD5 hex digest, when available.
        revision: Head revision ID for binary files, when available.
        created_time: RFC 3339 creation time, when available.
    """

    id: str
    name: str
    mime_type: str
    parent_ids: tuple[str, ...] = ()
    properties: Mapping[str, str] = field(default_factory=dict)
    web_link: str | None = None
    size: int | None = None
    md5: str | None = None
    revision: str | None = None
    created_time: str | None = None

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME


@dataclass(frozen=True)
class Grant:
    """One permission on an object, without the grantee's identity.

    Only the grantee kind, role and email domain are kept, so ACL summaries
    can be recorded without naming people.
    """

    kind: GrantKind
    role: str
    domain: str | None = None


@dataclass(frozen=True)
class AccessInfo:
    """Effective access summary for one object.

    Attributes:
        object_id: The inspected object.
        can_add_children: Whether the operator may create children here.
        drive_kind: ``my_drive`` or ``shared_drive``.
        drive_id: Shared-drive ID, when ``drive_kind == "shared_drive"``.
        grants: Grant summaries (no names or emails).
        fingerprint: Stable digest of the full ACL, used to detect changes.
        complete: False when the provider would not list every permission
            (for example, the operator cannot read the ACL); classification
            must then treat the ACL as unknown.
    """

    object_id: str
    can_add_children: bool
    drive_kind: DriveKind
    drive_id: str | None = None
    grants: tuple[Grant, ...] = ()
    fingerprint: str = ""
    complete: bool = True


@runtime_checkable
class EngagementStoragePort(Protocol):
    """ID- and stream-based remote storage for Drive-backed engagement runs."""

    def root_folder_id(self) -> str:
        """Return the operator's personal root folder ID (``My Drive``)."""
        ...

    def get(self, object_id: str) -> StorageObject:
        """Return metadata for ``object_id``."""
        ...

    def list_children(
        self,
        parent_id: str,
        *,
        name: str | None = None,
        folders_only: bool = False,
    ) -> list[StorageObject]:
        """List non-trashed direct children of ``parent_id`` (optionally by exact name)."""
        ...

    def create_folder(
        self, parent_id: str, name: str, properties: Mapping[str, str]
    ) -> StorageObject:
        """Create a folder under ``parent_id`` carrying ``properties``."""
        ...

    def inspect_access(self, object_id: str) -> AccessInfo:
        """Summarize the operator's capabilities and the object's ACL."""
        ...

    def put_stream(
        self,
        parent_id: str,
        name: str,
        mime_type: str,
        chunks: Iterable[bytes],
        *,
        properties: Mapping[str, str],
    ) -> StorageObject:
        """Upload ``chunks`` from memory and return the read-back-verified object.

        Implementations must not write a temporary file and must raise
        :class:`StorageIntegrityError` when the stored size or checksum does not
        match the bytes sent.
        """
        ...

    def get_stream(
        self, object_id: str, revision: str | None = None
    ) -> Iterator[bytes]:
        """Stream the content of ``object_id`` (optionally a specific revision)."""
        ...

    def principal_id(self) -> str:
        """Opaque ID of the authenticated principal (Drive ``permissionId``); never an email."""
        ...

    def update(
        self,
        object_id: str,
        *,
        name: str | None = None,
        properties: Mapping[str, str] | None = None,
        add_parent_id: str | None = None,
        remove_parent_id: str | None = None,
    ) -> StorageObject:
        """Metadata update (properties merged); returns the read-back object.

        ``properties`` are merged into the existing ones (keys not named are
        kept). ``add_parent_id``/``remove_parent_id`` move the object between
        folders. The returned object is read back after the update and verified
        to carry every requested change; otherwise :class:`StorageIntegrityError`
        is raised.
        """
        ...

    def update_stream(
        self, object_id: str, mime_type: str, chunks: Iterable[bytes]
    ) -> StorageObject:
        """Replace the content of an existing file as a new revision, from memory.

        No temporary file is written. The stored size and MD5 are read back and
        verified against the bytes sent (:class:`StorageIntegrityError`
        otherwise). The object ID, name, parents and properties are unchanged;
        ``revision`` on the result is the new head revision.
        """
        ...

    def find_by_property(
        self, key: str, value: str, *, drive_id: str | None = None
    ) -> list[StorageObject]:
        """Every non-trashed object whose property ``key`` equals ``value``.

        One query, wherever the objects live: ``drive_id`` scopes it to that
        shared drive; ``None`` searches the operator's own corpus (``My Drive``
        and items shared with them). Raises :class:`StorageError` when the
        provider cannot guarantee a complete result, so callers can fall back to
        a parent-scoped walk instead of missing objects.
        """
        ...

    def trash(self, object_id: str) -> None:
        """Move ``object_id`` to the trash (recoverable; never a hard delete)."""
        ...
