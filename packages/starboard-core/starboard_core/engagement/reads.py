# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run inputs: the one verified Drive read and the one run-relative path check.

Every ``drive:<object id>`` input goes through :func:`read_verified`: folders are
refused, the declared size is checked against the cap before any download, the cap
is enforced again while streaming, and the bytes must match the recorded size and
md5. A caller that already holds the listed ``StorageObject`` uses
:func:`read_object`, which applies the same checks against that metadata (optionally
for a pinned ``revision``, or keeping only the first ``keep`` bytes while hashing all
of them). :meth:`DriveRunSink.get_bytes` reads through it too. Every
``--run-folder`` path flag goes through :func:`run_relpath`.

Stdlib + port only.
"""

from __future__ import annotations

import hashlib

from starboard_core.engagement.sink import (
    LocalStorageRefused,
    ReadRefusedError,
    is_local_path,
    validate_relpath,
)
from starboard_core.ports.engagement_storage import (
    EngagementStoragePort,
    StorageIntegrityError,
    StorageObject,
)

__all__ = ["ReadRefusedError", "read_object", "read_verified", "run_relpath"]


def read_verified(
    storage: EngagementStoragePort, object_id: str, *, max_bytes: int
) -> bytes:
    """Bytes of file ``object_id``, at most ``max_bytes``, verified against Drive.

    Raises:
        ReadRefusedError: The object is a folder, or larger than ``max_bytes``.
        StorageIntegrityError: The bytes do not match the recorded size or md5.
        StorageError: Any storage failure (``StorageNotFoundError`` ...) propagates.
    """
    return read_object(storage, storage.get(object_id), max_bytes=max_bytes)


def read_object(
    storage: EngagementStoragePort,
    obj: StorageObject,
    *,
    max_bytes: int,
    revision: str | None = None,
    keep: int | None = None,
) -> bytes:
    """Bytes of the listed file ``obj``, at most ``max_bytes``, verified against ``obj``.

    The size and md5 checked are the ones ``obj`` carries, so the bytes returned are
    exactly the ones the caller's listing described. The cap is checked against
    ``obj.size`` before any download and again while streaming.

    Args:
        storage: The engagement storage port.
        obj: The file's metadata; its ``size`` / ``md5`` are what the bytes must match.
        max_bytes: Largest object read; a larger one is refused.
        revision: Stream this revision instead of the head. ``obj``'s size / md5
            must then describe that revision (e.g. built from a committed
            ``StorageRef``).
        keep: Return only the first ``keep`` bytes. The whole object is still
            streamed (under ``max_bytes``) and hashed, so the size / md5 checks cover
            every byte while only ``keep`` bytes are held in memory.

    Raises:
        ReadRefusedError: ``obj`` is a folder, or larger than ``max_bytes``.
        StorageIntegrityError: The bytes do not match ``obj``'s size or md5.
        StorageError: Any storage failure (``StorageNotFoundError`` ...) propagates.
        ValueError: ``keep`` is negative.
    """
    if keep is not None and keep < 0:
        raise ValueError(f"keep must be >= 0, got {keep}")
    if obj.is_folder:
        raise ReadRefusedError(f"{obj.id} is a folder, not a file")
    too_big = f"{obj.id} is larger than {max_bytes} bytes"
    if obj.size is not None and obj.size > max_bytes:
        raise ReadRefusedError(too_big)
    chunks = (
        storage.get_stream(obj.id)
        if revision is None
        else storage.get_stream(obj.id, revision=revision)
    )
    digest = hashlib.md5(usedforsecurity=False)
    buf = bytearray()
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > max_bytes:
            raise ReadRefusedError(too_big)
        digest.update(chunk)
        if keep is None:
            buf += chunk
        elif len(buf) < keep:
            buf += chunk[: keep - len(buf)]
    md5 = digest.hexdigest()
    if (obj.size is not None and obj.size != total) or (obj.md5 and obj.md5 != md5):
        raise StorageIntegrityError(
            f"{obj.id} downloaded {total} bytes md5 {md5}; Drive records "
            f"{obj.size} bytes md5 {obj.md5}"
        )
    return bytes(buf)


def run_relpath(
    flag: str,
    value: str,
    *,
    covered_run: bool,
    arg_error: type[Exception] = ValueError,
) -> str:
    """``value`` of path flag ``flag`` as a validated run-relative path.

    A local (absolute, ``~``, ``..`` ...) path is refused with
    ``LocalStorageRefused`` on a covered run. Any other invalid path (a trailing
    ``/``, an empty segment ...), and a local path on an uncovered run, is the
    caller's ``arg_error`` (its usage-error type).
    """
    try:
        return validate_relpath(value)
    except ValueError as exc:
        if not is_local_path(value):
            raise arg_error(
                f"{flag} {value!r} is not a valid run-relative path: {exc}"
            ) from exc
        if covered_run:
            raise LocalStorageRefused(
                f"{flag} {value!r} is a local path; on a covered run it must be a "
                f"run-relative path ({exc})",
                flag=flag,
            ) from exc
        raise arg_error(
            f"{flag} must be a run-relative path with --run-folder: {exc}"
        ) from exc
