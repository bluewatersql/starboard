# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run artifact sinks: where a writer's outputs go.

Every writer resolves one :class:`ArtifactSink` and addresses its outputs by
run-relative *relpath* (``raw/w-w01.json``, ``analysis/review.md``). The relpath is
never a local filesystem path:

* :class:`DriveRunSink` stores each relpath as a file in the run's Drive folder,
  with one Drive sub-folder per path segment. Writes are idempotent (md5 reuse,
  in-place revision on change) and read back byte-for-byte. Access is rechecked
  before every write, and a permission failure stops all further writes (D-24).
* :class:`LocalDirSink` is the public path's local run directory. It refuses Drive
  policies.
* :class:`MemorySink` keeps bytes in process memory (dry runs, tests).

:func:`open_sink` picks the sink from the storage decision. :func:`load_engagement_storage`
resolves the Drive adapter through the dedicated ``starboard.engagement_storage``
entry-point group, so the kernel never imports ``starboard`` (D-10).

Stdlib + port only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, cast, runtime_checkable

from starboard_core.engagement.access import AccessVerdict, recheck_access
from starboard_core.engagement.commit import (
    DESCRIPTOR_NAME,
    MANIFEST_SEGMENT,
    read_descriptor,
)
from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    FolderConflictError,
    creation_order,
    list_after_create,
    sanitize_folder_name,
)
from starboard_core.engagement.policy import StorageDecision, StoragePolicy
from starboard_core.engagement.records import EvidenceRef, RunAuthorization, StorageRef
from starboard_core.engagement.staging import JSON_MIME, encode_json
from starboard_core.ports.engagement_storage import (
    AccessInfo,
    EngagementStoragePort,
    StorageAuthError,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StorageObject,
    StoragePermissionError,
    StorageTransientError,
)

__all__ = [
    "ARTIFACT_DIR_PREFIX",
    "ARTIFACT_PROPERTY",
    "DEFAULT_MAX_BYTES",
    "ENGAGEMENT_STORAGE_GROUP",
    "ENGAGEMENT_STORAGE_NAME",
    "EVIDENCE_INDEX",
    "EXIT_STORAGE_FAILURE",
    "EXIT_STORAGE_TRANSIENT",
    "RUN_PROPERTY",
    "AccessRecheckError",
    "ArtifactSink",
    "DriveRunSink",
    "LocalDirSink",
    "LocalStorageRefused",
    "MAX_READ_BYTES",
    "MemorySink",
    "ReadRefusedError",
    "SinkConflictError",
    "SinkKind",
    "StorageUnavailableError",
    "load_engagement_storage",
    "RecordKind",
    "open_sink",
    "reserved_record",
    "sink_evidence",
    "storage_exit_code",
    "storage_failure_code",
    "validate_relpath",
]

#: Dedicated entry-point group for the Drive adapter class. Not
#: ``starboard.port_adapters``: that group's entries must be ``PortAdapterProvider``s.
ENGAGEMENT_STORAGE_GROUP = "starboard.engagement_storage"
ENGAGEMENT_STORAGE_NAME = "engagement_storage"

ARTIFACT_PROPERTY = "starboard_artifact"
RUN_PROPERTY = "starboard_run"
ARTIFACT_DIR_PREFIX = "artifact-dir:"
EVIDENCE_INDEX = "evidence/index.json"
DEFAULT_MAX_BYTES = 512 * 2**20
#: Default cap of :meth:`ArtifactSink.get_bytes`: 64 MiB, the customer-file intake
#: cap (``starboard_x._cli.MAX_INTAKE_BYTES`` is this constant). A read of anything
#: larger must pass an explicit ``max_bytes``; it is refused before download, never
#: loaded and then checked.
MAX_READ_BYTES = 64 * 2**20

SinkKind = Literal["drive", "local", "memory"]

RecordKind = Literal["commit", "create_once", "kernel_updatable"]

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_TEXT_MIME = "text/markdown"
#: Backslashes and slash look-alikes that survive NFKC normalisation.
_SLASH_LOOKALIKES = frozenset("\\\u2044\u2215\u2571\u27cb\u29f8\u29f9\u2afd\u3033")
#: Kernel records rewritten only through ``put_record``.
_KERNEL_UPDATABLE = frozenset(
    {
        EVIDENCE_INDEX,
        "analysis/observations.json",
        "analysis/findings.json",
        "findings-manifest.json",
        "analysis/run-check.json",
        "analysis/recur-result.json",
        "analysis/baseline-selection.json",
        "analysis/health.json",
        "analysis/plays.json",
        "analysis/changes.json",
        "analysis/cases.json",
        "analysis/actions.json",
    }
)
#: Kernel records written once through ``put_record`` (immutable).
_CREATE_ONCE = frozenset(
    {
        "analysis/storage-preflight.json",
        "analysis/identity-check.json",
        "analysis/run-authorization.json",
    }
)
#: ``reports/<id>/rev-*``, ``reports/<id>/approvals/**``, ``reports/<id>/receipts/**``
#: (matched against the casefolded path).
_PUBLICATION_RECORD_RE = re.compile(
    r"reports/[^/]+/(?:rev-[^/]*|(?:approvals|receipts)/.+)"
)


class LocalStorageRefused(Exception):
    """A local output was requested where the storage policy requires Drive.

    ``flag`` names the CLI flag that asked for the local path, when there is one.
    Defined here (and re-exported by :mod:`~starboard_core.engagement.enforce`) so
    the sink can raise it without an import cycle.
    """

    code = "LOCAL_STORAGE_REFUSED"

    def __init__(self, message: str, *, flag: str | None = None) -> None:
        self.flag = flag
        super().__init__(f"{self.code}: {message}")


class StorageUnavailableError(StorageError):
    """The Drive storage adapter cannot be resolved (fail closed)."""

    code = "STORAGE_UNAVAILABLE"


class SinkConflictError(StorageError):
    """A relpath maps to more than one stored object, or to a foreign one."""


class AccessRecheckError(StoragePermissionError):
    """The run folder's access no longer matches the recorded fingerprint.

    ``verdict.reason`` is ``changed``, ``revoked`` or ``unknown``; the run status is
    ``blocked_access``.
    """

    def __init__(self, run_folder_id: str, verdict: AccessVerdict) -> None:
        self.run_folder_id = run_folder_id
        self.verdict = verdict
        super().__init__(
            f"access to run folder {run_folder_id} is {verdict.reason} since the run "
            "was authorized; no further writes (blocked_access)"
        )


#: Exit code of a storage / integrity / access failure on every writer surface
#: (``starboard_x``, the ``starboard-helper`` contract, ``starboard review`` and the
#: ``starboard`` goal agent). 7 collides with no surface's table (0-4 helper contract,
#: 0-6 and 130 ``starboard``). The engagement helper keeps its own table (4 = storage).
EXIT_STORAGE_FAILURE = 7
#: Exit code of a transient Drive failure (``STORAGE_TRANSIENT``: retryable, nothing
#: refused) on every writer surface, matching the engagement helper's exit 8.
EXIT_STORAGE_TRANSIENT = 8


def storage_exit_code(code: str | None) -> int:
    """The exit code of storage failure ``code``: 8 for ``STORAGE_TRANSIENT``, else 7."""
    return EXIT_STORAGE_TRANSIENT if code == "STORAGE_TRANSIENT" else EXIT_STORAGE_FAILURE


def storage_failure_code(exc: BaseException) -> str | None:
    """The code of a storage failure that exits :data:`EXIT_STORAGE_FAILURE`, else ``None``.

    ``BLOCKED_ACCESS`` (the access recheck failed), ``STORAGE_INTEGRITY``,
    ``NOT_FOUND``, ``STORAGE_TRANSIENT`` (retryable: the provider kept failing
    transiently) or ``STORAGE_ERROR``. ``None`` for a non-storage error, an
    unavailable adapter (a refusal, exit 2) and a storage auth error (an auth failure).
    """
    if not isinstance(exc, StorageError) or isinstance(
        exc, StorageUnavailableError | StorageAuthError
    ):
        return None
    if isinstance(exc, AccessRecheckError):
        return "BLOCKED_ACCESS"
    if isinstance(exc, StorageIntegrityError):
        return "STORAGE_INTEGRITY"
    if isinstance(exc, StorageNotFoundError):
        return "NOT_FOUND"
    if isinstance(exc, StorageTransientError):
        return "STORAGE_TRANSIENT"
    return "STORAGE_ERROR"


@runtime_checkable
class ArtifactSink(Protocol):
    """Run-relative artifact store used by every writer.

    Every implementation enforces the same write rule: ``put_bytes`` (and the
    ``put_json`` / ``put_text`` conveniences built on it) refuses any path that
    :func:`reserved_record` classifies, with :class:`ValueError`. Kernel records
    are written only through ``put_record``; commit records (the descriptor and
    ``manifest/``) only by the commit protocol, never through a sink.
    """

    kind: SinkKind
    run_id: str | None

    def put_bytes(self, relpath: str, data: bytes, mime_type: str) -> StorageRef: ...

    def put_record(self, relpath: str, data: bytes, mime_type: str) -> StorageRef: ...

    def put_json(
        self, relpath: str, payload: Mapping[str, Any] | Sequence[Any]
    ) -> StorageRef: ...

    def put_text(
        self, relpath: str, text: str, mime_type: str = _TEXT_MIME
    ) -> StorageRef: ...

    def get_bytes(self, relpath: str, *, max_bytes: int = MAX_READ_BYTES) -> bytes:
        """Bytes of ``relpath``; an object larger than ``max_bytes`` is refused.

        Raises:
            ReadRefusedError: The object is larger than ``max_bytes`` (checked
                before download where the size is recorded, and while reading).
            StorageNotFoundError: No such artifact.
            StorageIntegrityError: Drive bytes do not match the recorded size / md5.
        """
        ...

    def exists(self, relpath: str) -> bool: ...

    def refs(self) -> tuple[StorageRef, ...]: ...

    def list(self, prefix: str = "") -> tuple[str, ...]: ...


def validate_relpath(relpath: str) -> str:
    """Return ``relpath`` if it is a clean run-relative POSIX path.

    Refused: non-strings, empty paths, paths that NFKC normalisation would change
    (full-width ``／``, ligatures ...), absolute or ``~`` paths, Windows drives,
    backslashes and look-alike slashes, control and format characters (``\\n``,
    NUL, zero-width, bidi), empty / ``.`` / ``..`` segments (including a trailing
    ``/``), segments with leading or trailing whitespace, and segments ending in
    ``.``. ``%`` is a literal character: a relpath is never percent-decoded, so
    ``%2e%2e`` names a file, not the parent directory. The path is returned
    unchanged.

    Raises:
        ValueError: The path is not a valid relpath.
    """
    if not isinstance(relpath, str) or not relpath:
        raise ValueError(f"relpath must be a non-empty string, got {relpath!r}")
    if unicodedata.normalize("NFKC", relpath) != relpath:
        raise ValueError(f"relpath must be NFKC-normalised, got {relpath!r}")
    if any(unicodedata.category(ch).startswith("C") for ch in relpath):
        raise ValueError(f"relpath has a control or format character: {relpath!r}")
    if (
        relpath.startswith(("/", "~"))
        or any(ch in _SLASH_LOOKALIKES for ch in relpath)
        or _WINDOWS_DRIVE_RE.match(relpath)
        or PurePosixPath(relpath).is_absolute()
    ):
        raise ValueError(f"relpath must be run-relative, got {relpath!r}")
    for seg in relpath.split("/"):
        if seg in ("", ".", ".."):
            raise ValueError(f"relpath has an empty, '.' or '..' segment: {relpath!r}")
        if seg != seg.strip() or seg.endswith("."):
            raise ValueError(
                f"relpath segment {seg!r} has edge whitespace or a trailing '.': "
                f"{relpath!r}"
            )
    return relpath


def is_local_path(value: str) -> bool:
    """``value`` names a place outside the run: absolute, ``~``, a Windows drive,
    a backslash / look-alike slash, or a ``..`` segment."""
    return bool(
        value.startswith(("/", "~"))
        or any(ch in _SLASH_LOOKALIKES for ch in value)
        or _WINDOWS_DRIVE_RE.match(value)
        or PurePosixPath(value).is_absolute()
        or ".." in value.split("/")
    )


def reserved_record(relpath: str) -> RecordKind | None:
    """How a run-relative path is reserved, or ``None`` for an ordinary artifact.

    * ``"commit"``: the descriptor and ``manifest/``; only the commit protocol
      writes them, never a sink.
    * ``"create_once"``: written once by a kernel writer through
      :meth:`DriveRunSink.put_record`; identical bytes are reused, changed bytes
      are a :class:`SinkConflictError`.
    * ``"kernel_updatable"``: written and rewritten only through ``put_record``.

    Matching is case-insensitive (``casefold``) so ``Manifest/x`` or
    ``Analysis/Observations.JSON`` cannot shadow a record. ``relpath`` is not
    validated here.
    """
    key = relpath.casefold()
    if key == DESCRIPTOR_NAME.casefold() or key.split("/", 1)[0] == (
        MANIFEST_SEGMENT.casefold()
    ):
        return "commit"
    if key in _KERNEL_UPDATABLE:
        return "kernel_updatable"
    if key in _CREATE_ONCE or _PUBLICATION_RECORD_RE.fullmatch(key):
        return "create_once"
    return None


def _record_path(relpath: str) -> tuple[str, RecordKind]:
    rel = validate_relpath(relpath)
    kind = reserved_record(rel)
    if kind is None:
        raise ValueError(f"{rel!r} is not a kernel record; write it with put_bytes")
    if kind == "commit":
        raise ValueError(
            f"{rel!r} is a commit record; it is written by the commit protocol, "
            "not through the sink"
        )
    return rel, kind


def _refuse_reserved(rel: str) -> None:
    kind = reserved_record(rel)
    if kind == "commit":
        raise ValueError(
            f"{rel!r} is a commit record; it is written by the commit protocol, "
            "not through the sink"
        )
    if kind is not None:
        raise ValueError(
            f"{rel!r} is a reserved kernel record ({kind}); only kernel writers "
            "write it, through put_record"
        )


def _create_once_conflict(rel: str, existing_md5: str | None, data: bytes) -> None:
    if existing_md5 is not None and existing_md5 != _md5(data):
        raise SinkConflictError(
            f"{rel!r} is a create-once record and already holds different bytes "
            f"(md5 {existing_md5}); refusing to overwrite it"
        )


def _md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _json_bytes(payload: Mapping[str, Any] | Sequence[Any]) -> bytes:
    if isinstance(payload, str | bytes | bytearray) or not isinstance(
        payload, Mapping | Sequence
    ):
        raise TypeError(
            f"put_json needs a mapping or a sequence, got {type(payload).__name__}"
        )
    # encode_json is the one deterministic encoder; json.dumps handles lists too.
    return encode_json(cast(Mapping[str, Any], payload))


class ReadRefusedError(ValueError):
    """The object cannot be read as an input: a folder, or larger than the cap."""


def _too_big(rel: str, max_bytes: int) -> ReadRefusedError:
    return ReadRefusedError(f"{rel!r} is larger than {max_bytes} bytes")


def _under(prefix: str, relpath: str) -> bool:
    return not prefix or relpath.startswith(prefix)


# --- Drive ------------------------------------------------------------------------------


class DriveRunSink:
    """Artifacts of one run stored in its Drive run folder.

    Every artifact file carries ``starboard_artifact=<relpath>`` and
    ``starboard_run=<run id>``; every artifact sub-folder carries its
    ``artifact-dir:<dirpath>`` identity and the same run tag. The sink lists the run
    once, with one property query (:meth:`EngagementStoragePort.find_by_property`),
    rebuilds each relpath from the folder chain up to the run folder, and keeps that
    index in memory for its lifetime; its own writes update it. A relpath the index
    does not hold is confirmed with one name listing of its folder (skipped for a
    folder this sink created), which also catches foreign or other-run files.

    Several identical (md5 + size) copies of one relpath converge on the earliest
    (:func:`~starboard_core.engagement.folders.creation_order`); the others are
    trashed best-effort and a ``duplicate_artifact:`` line is added to
    :attr:`warnings`. Differing copies, foreign files and other runs' files are a
    :class:`SinkConflictError`.

    Access is checked against the recorded fingerprint once, before the sink's
    first write (or taken from ``access``, the opener's fresh inspection). A
    permission failure from the provider later is re-classified against a fresh
    inspection, and any permission failure stops all further writes (D-24).

    Args:
        storage: The engagement storage port.
        run_folder_id: The run folder (holds ``run-authorization.json``).
        run_id: The run ID; tagged on every file as ``starboard_run``.
        access_fingerprint: The run folder's fingerprint recorded at authorization.
        max_bytes: Largest single artifact accepted.
        access: The run folder's access as the caller just inspected it; saves
            the sink its own inspection (it is still checked against the
            fingerprint).
        authorization: The run descriptor the caller already read (kept in memory
            as :attr:`authorization`; never written anywhere).

    Thread-safe: writers may put distinct relpaths from several threads.
    """

    kind: SinkKind = "drive"

    def __init__(
        self,
        storage: EngagementStoragePort,
        run_folder_id: str,
        *,
        run_id: str,
        access_fingerprint: str,
        max_bytes: int = DEFAULT_MAX_BYTES,
        access: AccessInfo | None = None,
        authorization: RunAuthorization | None = None,
    ) -> None:
        self.run_id: str | None = run_id
        self.run_folder_id = run_folder_id
        #: The run descriptor the opener already read (in process only), so a helper
        #: command downloads it once; ``None`` when the sink was built without it.
        self.authorization = authorization
        self.warnings: list[str] = []
        self._storage = storage
        self._fingerprint = access_fingerprint
        self._max_bytes = max_bytes
        self._access = access
        self._access_ok = False
        self._lock = threading.RLock()
        self._dirs: dict[str, str] = {"": run_folder_id}
        # Folders a lookup found absent (read-only misses), so the next lookup under
        # the same path costs no listing; cleared per path when this sink creates it.
        self._no_dirs: set[str] = set()
        self._fresh: set[str] = set()
        self._index: dict[str, StorageObject] | None = None
        self._conflicts: dict[str, tuple[StorageObject, ...]] = {}
        self._refs: dict[str, StorageRef] = {}
        self._blocked: StoragePermissionError | None = None
        self._rel_locks: dict[str, threading.Lock] = {}

    # -- writes --

    def put_bytes(self, relpath: str, data: bytes, mime_type: str) -> StorageRef:
        """Write a generic artifact. Reserved kernel records are refused.

        Host-driven writers (``engagement put``, ``sanitize --out``, ``--out``
        flags) come through here, so a record the kernel trusts (the evidence
        index, observations, publication records ...) can never be forged by
        choosing its path; kernel writers use :meth:`put_record`.
        """
        rel = validate_relpath(relpath)
        _refuse_reserved(rel)
        return self._write(rel, data, mime_type)

    def put_record(self, relpath: str, data: bytes, mime_type: str) -> StorageRef:
        """Write a kernel-authored record (:func:`reserved_record` is not ``None``).

        ``create_once`` records reuse identical bytes and refuse changed ones with
        :class:`SinkConflictError`; ``kernel_updatable`` records are revised in place.

        Raises:
            ValueError: ``relpath`` is not a kernel record, or is a commit record.
        """
        rel, kind = _record_path(relpath)
        if kind == "create_once":
            existing = self._lookup(rel)
            if existing is not None:
                _create_once_conflict(rel, existing.md5, bytes(data))
        return self._write(rel, data, mime_type)

    def _write(self, rel: str, data: bytes, mime_type: str) -> StorageRef:
        if not isinstance(data, bytes | bytearray | memoryview):
            raise TypeError(f"put_bytes needs bytes, got {type(data).__name__}")
        data = bytes(data)
        if len(data) > self._max_bytes:
            raise StorageError(
                f"{rel!r} is {len(data)} bytes; the sink limit is {self._max_bytes}"
            )
        if self._blocked is not None:
            raise StoragePermissionError(
                f"run folder {self.run_folder_id} refused an earlier write; no further "
                f"writes this run ({self._blocked})"
            ) from self._blocked
        try:
            return self._put(rel, data, mime_type)
        except AccessRecheckError as exc:
            self._blocked = exc
            raise
        except StoragePermissionError as exc:
            blocked = self._denial(exc)
            self._blocked = blocked
            if blocked is exc:
                raise
            raise blocked from exc

    def put_json(
        self, relpath: str, payload: Mapping[str, Any] | Sequence[Any]
    ) -> StorageRef:
        return self.put_bytes(relpath, _json_bytes(payload), JSON_MIME)

    def put_text(
        self, relpath: str, text: str, mime_type: str = _TEXT_MIME
    ) -> StorageRef:
        return self.put_bytes(relpath, text.encode("utf-8"), mime_type)

    def _put(self, rel: str, data: bytes, mime_type: str) -> StorageRef:
        with self._lock:
            rel_lock = self._rel_locks.setdefault(rel, threading.Lock())
        with rel_lock:  # two threads writing one relpath must not both create it
            return self._put_locked(rel, data, mime_type)

    def _put_locked(self, rel: str, data: bytes, mime_type: str) -> StorageRef:
        self._check_access()
        dirpath, _, name = rel.rpartition("/")
        md5 = _md5(data)
        existing = self._indexed(rel)
        parent: str | None = None
        if existing is None:
            with self._lock:
                parent = self._dir(dirpath, create=True)
                fresh = dirpath in self._fresh
            assert parent is not None  # noqa: S101 - create=True always returns an ID
            if not fresh:
                existing = self._file(parent, name, rel)
        if existing is not None and existing.md5 == md5 and existing.size == len(data):
            obj = existing
        else:
            if existing is not None:
                obj = self._storage.update_stream(existing.id, mime_type, [data])
            else:
                assert parent is not None  # noqa: S101 - set on the index-miss path
                # The upload's own response is the object: no re-listing. The
                # adapter verified Drive's size / md5Checksum against the bytes sent.
                obj = self._storage.put_stream(
                    parent,
                    name,
                    mime_type,
                    [data],
                    properties={ARTIFACT_PROPERTY: rel, RUN_PROPERTY: str(self.run_id)},
                )
            if obj.md5 != md5 or obj.size != len(data):
                raise StorageIntegrityError(
                    f"{rel!r} ({obj.id}) stored md5 {obj.md5} / {obj.size} bytes; sent "
                    f"md5 {md5} / {len(data)} bytes"
                )
        ref = StorageRef(
            path=rel,
            object_id=obj.id,
            revision=obj.revision,
            md5=md5,
            size=len(data),
            mime_type=obj.mime_type or mime_type,
        )
        with self._lock:
            self._load()[rel] = obj
            self._refs[rel] = ref
        return ref

    # -- reads --

    def get_bytes(self, relpath: str, *, max_bytes: int = MAX_READ_BYTES) -> bytes:
        """Verified bytes of ``relpath`` (see :func:`reads.read_object`).

        Refused before download when Drive records a size over ``max_bytes`` and
        while streaming otherwise; the bytes must match Drive's size and md5.
        """
        from starboard_core.engagement.reads import read_object  # imports this module

        rel = validate_relpath(relpath)
        obj = self._lookup(rel)
        if obj is None:
            raise StorageNotFoundError(
                f"{rel!r} is not in run folder {self.run_folder_id}"
            )
        if obj.size is None or obj.md5 is None:
            raise StorageIntegrityError(
                f"{rel!r} ({obj.id}) has no recorded size / md5 to verify against"
            )
        try:
            return read_object(self._storage, obj, max_bytes=max_bytes)
        except ReadRefusedError as exc:
            raise ReadRefusedError(f"{rel!r} ({exc})") from exc
        except StorageIntegrityError as exc:
            raise StorageIntegrityError(f"{rel!r} ({exc})") from exc

    def exists(self, relpath: str) -> bool:
        return self._lookup(validate_relpath(relpath)) is not None

    def refs(self) -> tuple[StorageRef, ...]:
        with self._lock:
            return tuple(self._refs.values())

    def list(self, prefix: str = "") -> tuple[str, ...]:
        with self._lock:
            found = set(self._load()) | set(self._conflicts)
        return tuple(sorted(rel for rel in found if _under(prefix, rel)))

    def artifacts(self) -> dict[str, StorageObject]:
        """``relpath -> StorageObject`` for every artifact of the run, sorted by path.

        Raises:
            SinkConflictError: A relpath has differing copies.
        """
        with self._lock:
            index = self._load()
            if self._conflicts:
                rel = min(self._conflicts)
                raise self._conflict(
                    rel, self._conflicts[rel], len(self._conflicts[rel])
                )
            return {rel: index[rel] for rel in sorted(index)}

    # -- access --

    def _check_access(self) -> None:
        """Check the run folder against the fingerprint once per sink (first write)."""
        with self._lock:
            if self._access_ok:
                return
            verdict = recheck_access(self._fingerprint, self._access_info())
            if not verdict.ok:
                raise AccessRecheckError(self.run_folder_id, verdict)
            self._access_ok = True

    def _access_info(self) -> AccessInfo:
        with self._lock:
            if self._access is None:
                self._access = self._storage.inspect_access(self.run_folder_id)
            return self._access

    def _denial(self, exc: StoragePermissionError) -> StoragePermissionError:
        """A provider refusal, as ``blocked_access`` when the folder's access changed."""
        try:
            fresh = self._storage.inspect_access(self.run_folder_id)
        except StorageError:
            return exc
        verdict = recheck_access(self._fingerprint, fresh)
        return exc if verdict.ok else AccessRecheckError(self.run_folder_id, verdict)

    # -- index --

    def _indexed(self, rel: str) -> StorageObject | None:
        with self._lock:
            index = self._load()
            copies = self._conflicts.get(rel)
            if copies is not None:
                raise self._conflict(rel, copies, len(copies))
            return index.get(rel)

    def _lookup(self, rel: str) -> StorageObject | None:
        obj = self._indexed(rel)
        if obj is not None:
            return obj
        dirpath, _, name = rel.rpartition("/")
        with self._lock:
            if dirpath in self._fresh:
                return None  # this sink created the folder and wrote all it holds
            parent = self._dir(dirpath, create=False)
        if parent is None:
            return None
        obj = self._file(parent, name, rel)
        if obj is not None:
            with self._lock:
                self._load().setdefault(rel, obj)
        return obj

    def _load(self) -> dict[str, StorageObject]:
        """The run's artifact index, built on first use (one property query)."""
        with self._lock:
            if self._index is None:
                self._index = self._build(self._run_objects())
            return self._index

    def _run_objects(self) -> Sequence[StorageObject]:
        try:
            return self._storage.find_by_property(
                RUN_PROPERTY, str(self.run_id), drive_id=self._access_info().drive_id
            )
        except (
            StorageAuthError,
            StoragePermissionError,
            StorageNotFoundError,
            StorageTransientError,
        ):
            raise
        except StorageError:
            return self._walk()  # the provider could not answer completely

    def _walk(self) -> Sequence[StorageObject]:
        """Every object below the run folder through artifact folders (fallback)."""
        found: list[StorageObject] = []
        pending = [self.run_folder_id]
        while pending:
            for child in self._storage.list_children(pending.pop()):
                if child.is_folder:
                    if child.properties.get(IDENTITY_PROPERTY, "").startswith(
                        ARTIFACT_DIR_PREFIX
                    ):
                        found.append(child)
                        pending.append(child.id)
                elif child.properties.get(RUN_PROPERTY) == self.run_id:
                    found.append(child)
        return found

    def _build(self, objects: Iterable[StorageObject]) -> dict[str, StorageObject]:
        """Index the run's files by relpath, keeping only those inside the run folder.

        A file counts when its parent folder chain carries the ``artifact-dir:``
        identities its relpath names, up to the run folder. A parent the query did
        not return (a folder written before folders were run-tagged) is read once.
        """
        objects = list(objects)
        folders = {o.id: o for o in objects if o.is_folder}
        paths: dict[str, str | None] = {self.run_folder_id: ""}
        dirs: dict[str, list[StorageObject]] = {}

        def dirpath_of(folder_id: str) -> str | None:
            if folder_id in paths:
                return paths[folder_id]
            paths[folder_id] = None  # also guards against a parent cycle
            folder = folders.get(folder_id)
            if folder is None:
                try:
                    folder = self._storage.get(folder_id)
                except StorageNotFoundError:
                    return None
            identity = folder.properties.get(IDENTITY_PROPERTY, "")
            if not folder.is_folder or not identity.startswith(ARTIFACT_DIR_PREFIX):
                return None
            path = identity[len(ARTIFACT_DIR_PREFIX) :]
            parent_path = path.rpartition("/")[0]
            if path and any(dirpath_of(p) == parent_path for p in folder.parent_ids):
                paths[folder_id] = path
                dirs.setdefault(path, []).append(folder)
            return paths[folder_id]

        groups: dict[str, list[StorageObject]] = {}
        for obj in objects:
            if obj.is_folder:
                dirpath_of(obj.id)
                continue
            rel = obj.properties.get(ARTIFACT_PROPERTY)
            if not rel or obj.properties.get(RUN_PROPERTY) != self.run_id:
                continue
            dirpath, _, name = rel.rpartition("/")
            if obj.name == name and any(
                dirpath_of(p) == dirpath for p in obj.parent_ids
            ):
                groups.setdefault(rel, []).append(obj)
        for path, candidates in dirs.items():
            # Same winner as ensure_folder's convergence on a double create.
            self._dirs.setdefault(path, min(candidates, key=creation_order).id)
        index: dict[str, StorageObject] = {}
        for rel in sorted(groups):
            kept = self._settle(rel, groups[rel])
            if kept is None:
                self._conflicts[rel] = tuple(groups[rel])
            else:
                index[rel] = kept
        return index

    def _settle(
        self, rel: str, copies: Sequence[StorageObject]
    ) -> StorageObject | None:
        """The one object for ``rel``: the earliest of identical copies, else ``None``.

        Extra identical copies (a retried upload) are trashed best-effort and
        reported in :attr:`warnings`; differing copies return ``None`` (a conflict).
        """
        ordered = sorted(copies, key=creation_order)
        keep, extra = ordered[0], ordered[1:]
        if not extra:
            return keep
        if keep.md5 is None or any(
            c.md5 != keep.md5 or c.size != keep.size for c in extra
        ):
            return None
        trashed: list[str] = []
        left: list[str] = []
        for copy in extra:
            try:
                if self._blocked is not None:
                    raise self._blocked
                self._check_access()
                self._storage.trash(copy.id)
                trashed.append(copy.id)
            except StorageError:
                left.append(copy.id)
        note = (
            f"duplicate_artifact: {rel!r} had {len(ordered)} identical copies "
            f"(md5 {keep.md5}) in run {self.run_id}; kept the earliest {keep.id}"
        )
        if trashed:
            note += f", trashed {', '.join(trashed)}"
        if left:
            note += f"; could not trash {', '.join(left)} (trash them in Drive)"
        with self._lock:
            self.warnings.append(note)
        return keep

    def _conflict(
        self, rel: str, copies: Sequence[StorageObject], same_name: int
    ) -> SinkConflictError:
        ids = ", ".join(c.id for c in sorted(copies, key=creation_order))
        return SinkConflictError(
            f"{rel!r} in run folder {self.run_folder_id} matches {same_name} file(s), "
            f"{len(copies)} of them this run's artifact, with differing content; "
            f"reconcile in Drive (ids: {ids})"
        )

    # -- folders --

    def _dir(self, dirpath: str, *, create: bool) -> str | None:
        """Folder ID for ``dirpath`` (``""`` is the run folder). Call under the lock."""
        if dirpath in self._dirs:
            return self._dirs[dirpath]
        if not create and dirpath in self._no_dirs:
            return None
        parent_path, _, segment = dirpath.rpartition("/")
        parent = self._dir(parent_path, create=create)
        if parent is None:
            return None
        identity = ARTIFACT_DIR_PREFIX + dirpath
        clean = sanitize_folder_name(segment)
        listed = self._storage.list_children(parent, name=clean, folders_only=True)
        created: StorageObject | None = None
        if not listed:
            if not create:
                self._no_dirs.add(dirpath)
                return None
            created = self._storage.create_folder(
                parent,
                clean,
                {IDENTITY_PROPERTY: identity, RUN_PROPERTY: str(self.run_id)},
            )
            listed = list_after_create(self._storage, parent, clean, created.id)
            if created.id not in {c.id for c in listed}:
                raise StorageIntegrityError(
                    f"created folder {created.id} is not listed under {parent} on "
                    "read-back"
                )
        matches = [c for c in listed if c.properties.get(IDENTITY_PROPERTY) == identity]
        if len(matches) != len(listed):
            ids = [c.id for c in listed]
            raise FolderConflictError(
                f"folder name {clean!r} is already used by "
                f"{len(listed) - len(matches)} folder(s) with a different or missing "
                f"identity under parent {parent}; reconcile in Drive "
                f"(ids: {', '.join(ids)})",
                parent_id=parent,
                name=clean,
                identity_key=identity,
                object_ids=ids,
                existing_identities=[
                    c.properties.get(IDENTITY_PROPERTY) for c in listed
                ],
            )
        # A concurrent double create converges on the earliest, as ensure_folder does.
        folder = min(matches, key=creation_order)
        if created is not None and folder.id == created.id and len(listed) == 1:
            self._fresh.add(dirpath)
        self._dirs[dirpath] = folder.id
        self._no_dirs.discard(dirpath)
        return folder.id

    def _file(self, parent: str, name: str, rel: str) -> StorageObject | None:
        same_name = [
            c for c in self._storage.list_children(parent, name=name) if not c.is_folder
        ]
        ours = [
            c
            for c in same_name
            if c.properties.get(ARTIFACT_PROPERTY) == rel
            and c.properties.get(RUN_PROPERTY) == self.run_id
        ]
        if len(same_name) > len(ours):
            raise SinkConflictError(
                f"{rel!r} in run folder {self.run_folder_id} matches {len(same_name)} "
                f"file(s), {len(ours)} of them this run's artifact; reconcile in Drive "
                f"(ids: {', '.join(c.id for c in same_name)})"
            )
        if not ours:
            return None
        kept = self._settle(rel, ours)
        if kept is None:
            raise self._conflict(rel, ours, len(same_name))
        return kept


# --- local / memory ---------------------------------------------------------------------


class LocalDirSink:
    """A local run directory (public path / explicit internal-only local runs).

    Raises:
        LocalStorageRefused: The decision requires Drive (``drive_required``) or
            defaults to Drive (``drive_default``: local storage must be asked for
            explicitly, giving ``internal_only_local``).
    """

    kind: SinkKind = "local"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        decision: StorageDecision,
        run_id: str | None = None,
    ) -> None:
        if decision.policy in (
            StoragePolicy.DRIVE_REQUIRED,
            StoragePolicy.DRIVE_DEFAULT,
        ):
            raise LocalStorageRefused(
                f"storage policy {decision.policy.value} does not allow a local run "
                f"directory ({decision.reason})"
            )
        self.run_id = run_id
        self.root = Path(root)
        self._refs: dict[str, StorageRef] = {}

    def _path(self, rel: str) -> Path:
        target = self.root.joinpath(*rel.split("/"))
        real_root = os.path.realpath(self.root)
        real = os.path.realpath(target)
        if real != real_root and not real.startswith(real_root + os.sep):
            raise ValueError(f"{rel!r} resolves outside the run directory {self.root}")
        return target

    def put_record(self, relpath: str, data: bytes, mime_type: str) -> StorageRef:
        """A kernel record (see :meth:`DriveRunSink.put_record`)."""
        rel, kind = _record_path(relpath)
        target = self._path(rel)
        if kind == "create_once" and target.is_file():
            _create_once_conflict(rel, _md5(target.read_bytes()), bytes(data))
        return self._write(rel, data, mime_type)

    def put_bytes(self, relpath: str, data: bytes, mime_type: str) -> StorageRef:
        """A generic artifact; reserved kernel records are refused."""
        rel = validate_relpath(relpath)
        _refuse_reserved(rel)
        return self._write(rel, data, mime_type)

    def _write(self, rel: str, data: bytes, mime_type: str) -> StorageRef:
        target = self._path(rel)
        data = bytes(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        ref = StorageRef(
            path=rel,
            object_id=f"local:{rel}",
            revision=None,
            md5=_md5(data),
            size=len(data),
            mime_type=mime_type,
        )
        self._refs[rel] = ref
        return ref

    def put_json(
        self, relpath: str, payload: Mapping[str, Any] | Sequence[Any]
    ) -> StorageRef:
        return self.put_bytes(relpath, _json_bytes(payload), JSON_MIME)

    def put_text(
        self, relpath: str, text: str, mime_type: str = _TEXT_MIME
    ) -> StorageRef:
        return self.put_bytes(relpath, text.encode("utf-8"), mime_type)

    def get_bytes(self, relpath: str, *, max_bytes: int = MAX_READ_BYTES) -> bytes:
        target = self._path(validate_relpath(relpath))
        if not target.is_file():
            raise StorageNotFoundError(f"{relpath!r} is not in {self.root}")
        with open(target, "rb") as fh:
            if os.fstat(fh.fileno()).st_size > max_bytes:
                raise _too_big(relpath, max_bytes)
            data = fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise _too_big(relpath, max_bytes)
        return data

    def exists(self, relpath: str) -> bool:
        return self._path(validate_relpath(relpath)).is_file()

    def refs(self) -> tuple[StorageRef, ...]:
        return tuple(self._refs.values())

    def list(self, prefix: str = "") -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        found = [
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
        ]
        return tuple(sorted(r for r in found if _under(prefix, r)))


class MemorySink:
    """Artifacts kept in process memory only."""

    kind: SinkKind = "memory"

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id
        self._data: dict[str, bytes] = {}
        self._refs: dict[str, StorageRef] = {}

    def put_record(self, relpath: str, data: bytes, mime_type: str) -> StorageRef:
        """A kernel record (see :meth:`DriveRunSink.put_record`)."""
        rel, kind = _record_path(relpath)
        if kind == "create_once" and rel in self._data:
            _create_once_conflict(rel, _md5(self._data[rel]), bytes(data))
        return self._write(rel, data, mime_type)

    def put_bytes(self, relpath: str, data: bytes, mime_type: str) -> StorageRef:
        """A generic artifact; reserved kernel records are refused."""
        rel = validate_relpath(relpath)
        _refuse_reserved(rel)
        return self._write(rel, data, mime_type)

    def _write(self, rel: str, data: bytes, mime_type: str) -> StorageRef:
        data = bytes(data)
        self._data[rel] = data
        ref = StorageRef(
            path=rel,
            object_id=f"memory:{rel}",
            revision=None,
            md5=_md5(data),
            size=len(data),
            mime_type=mime_type,
        )
        self._refs[rel] = ref
        return ref

    def put_json(
        self, relpath: str, payload: Mapping[str, Any] | Sequence[Any]
    ) -> StorageRef:
        return self.put_bytes(relpath, _json_bytes(payload), JSON_MIME)

    def put_text(
        self, relpath: str, text: str, mime_type: str = _TEXT_MIME
    ) -> StorageRef:
        return self.put_bytes(relpath, text.encode("utf-8"), mime_type)

    def get_bytes(self, relpath: str, *, max_bytes: int = MAX_READ_BYTES) -> bytes:
        rel = validate_relpath(relpath)
        if rel not in self._data:
            raise StorageNotFoundError(f"{rel!r} is not in the memory sink")
        data = self._data[rel]
        if len(data) > max_bytes:
            raise _too_big(rel, max_bytes)
        return data

    def exists(self, relpath: str) -> bool:
        return validate_relpath(relpath) in self._data

    def refs(self) -> tuple[StorageRef, ...]:
        return tuple(self._refs.values())

    def list(self, prefix: str = "") -> tuple[str, ...]:
        return tuple(sorted(r for r in self._data if _under(prefix, r)))


# --- selection --------------------------------------------------------------------------


def open_sink(
    *,
    decision: StorageDecision,
    run_folder_id: str | None,
    local_root: str | None,
    storage_factory: Callable[[], EngagementStoragePort],
) -> ArtifactSink:
    """Pick the sink for a writer.

    * ``run_folder_id`` given: a :class:`DriveRunSink`. The run ID and the recorded
      run-folder fingerprint come from the folder's ``run-authorization.json``.
    * Otherwise, a ``drive_required`` / ``drive_default`` decision is refused
      (:class:`LocalStorageRefused`); the storage factory is never called.
    * Otherwise ``local_root`` gives a :class:`LocalDirSink`, and nothing gives a
      :class:`MemorySink`.

    Raises:
        LocalStorageRefused: A Drive policy without a run folder.
        CommitError: The run folder has no valid descriptor.
        StoragePermissionError: The descriptor records no fingerprint for the folder.
        StorageUnavailableError: From ``storage_factory`` (the adapter is missing).
    """
    if run_folder_id:
        storage = storage_factory()
        auth, _ = read_descriptor(storage, run_folder_id)
        fingerprint = (
            auth.drive.permission_fingerprints.get(run_folder_id)
            if auth.drive is not None and auth.drive.run_folder_id == run_folder_id
            else None
        )
        if not fingerprint:
            raise StoragePermissionError(
                f"the run descriptor in {run_folder_id} records no access fingerprint "
                "for the run folder; re-run preflight"
            )
        return DriveRunSink(
            storage,
            run_folder_id,
            run_id=auth.run_id,
            access_fingerprint=fingerprint,
            authorization=auth,
        )
    if decision.policy in (StoragePolicy.DRIVE_REQUIRED, StoragePolicy.DRIVE_DEFAULT):
        raise LocalStorageRefused(
            f"storage policy {decision.policy.value} needs --run-folder ({decision.reason})",
            flag="--run-folder",
        )
    if local_root:
        return LocalDirSink(local_root, decision=decision)
    return MemorySink()


def load_engagement_storage() -> EngagementStoragePort:
    """Instantiate the Drive adapter from the ``starboard.engagement_storage`` group.

    The entry point named ``engagement_storage`` must name a zero-argument callable
    (the adapter class) returning an :class:`EngagementStoragePort`.

    Raises:
        StorageUnavailableError: No entry point, several distinct ones, a load or
            construction failure, or an object that is not a storage port.
    """
    try:
        found = metadata.entry_points(
            group=ENGAGEMENT_STORAGE_GROUP, name=ENGAGEMENT_STORAGE_NAME
        )
    except Exception as exc:  # noqa: BLE001 - any metadata failure means unavailable
        raise StorageUnavailableError(f"cannot read entry points: {exc}") from exc
    distinct = {ep.value: ep for ep in found}
    if len(distinct) != 1:
        raise StorageUnavailableError(
            f"expected one {ENGAGEMENT_STORAGE_GROUP}:{ENGAGEMENT_STORAGE_NAME} entry "
            f"point, found {len(distinct)}; install the starboard package"
        )
    (entry,) = distinct.values()
    try:
        storage = entry.load()()
    except Exception as exc:  # noqa: BLE001 - fail closed on any adapter failure
        raise StorageUnavailableError(
            f"engagement storage adapter {entry.value} failed to load: {exc}"
        ) from exc
    if not isinstance(storage, EngagementStoragePort):
        raise StorageUnavailableError(
            f"{entry.value} did not produce an EngagementStoragePort"
        )
    return storage


def sink_evidence(sink: ArtifactSink, refs: Iterable[EvidenceRef]) -> StorageRef:
    """Merge ``refs`` into the run's ``evidence/index.json`` (read-modify-write).

    Existing entries keep their order; new evidence IDs are appended. On Drive the
    changed index becomes a new revision of the same object, and an unchanged one
    is reused.

    Raises:
        ValueError: A ref belongs to a different run than the sink.
        StorageIntegrityError: The existing index is not a valid EvidenceRef list.
    """
    new = list(refs)
    for ref in new:
        if sink.run_id is not None and ref.run_id != sink.run_id:
            raise ValueError(
                f"evidence {ref.evidence_id} belongs to run {ref.run_id}, not {sink.run_id}"
            )
    merged: dict[str, EvidenceRef] = {}
    if sink.exists(EVIDENCE_INDEX):
        try:
            stored = json.loads(sink.get_bytes(EVIDENCE_INDEX))
            if not isinstance(stored, list):
                raise TypeError("the index is not a JSON list")
            for item in stored:
                ev = EvidenceRef.from_dict(item)
                merged[ev.evidence_id] = ev
        except (ValueError, TypeError, KeyError) as exc:
            raise StorageIntegrityError(
                f"{EVIDENCE_INDEX} is not a valid EvidenceRef list ({exc}); refusing to "
                "overwrite it"
            ) from exc
    for ref in new:
        merged.setdefault(ref.evidence_id, ref)
    return sink.put_record(
        EVIDENCE_INDEX,
        _json_bytes([ev.to_dict() for ev in merged.values()]),
        JSON_MIME,
    )
