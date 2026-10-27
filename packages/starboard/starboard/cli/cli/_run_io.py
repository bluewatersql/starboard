# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-folder I/O shared by the CLI writers (``starboard`` goal/discover, ``review``).

A ``--run-folder`` command reads its inputs from the run (a run-relative path or
``drive:<object id>``) and validates every path flag as run-relative. The verified
Drive read and the relpath check are the kernel's
(:mod:`starboard_core.engagement.reads`); this module binds them to the CLI's
``ArgError`` and storage adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from starboard_core.engagement import reads
from starboard_core.engagement.commit import read_descriptor
from starboard_core.engagement.enforce import WriterContext, covered
from starboard_core.engagement.identity import ProfileMismatch, run_profile
from starboard_core.ports.engagement_storage import (
    EngagementStoragePort,
    StorageNotFoundError,
)
from starboard_x.cli import RefusedError
from starboard_x.contract import ArgError

__all__ = [
    "MAX_INPUT_BYTES",
    "CliRun",
    "ProfileMismatchRefused",
    "cached_storage_factory",
    "resolve_run_profile",
    "run_input_bytes",
    "run_relpath",
]

#: Largest run input read into memory.
MAX_INPUT_BYTES = 64 * 2**20
_DRIVE_PREFIX = "drive:"


@dataclass(frozen=True)
class CliRun:
    """A ``--run-folder`` command: the writer context and the storage it reads from.

    ``inputs`` lists every run input read through :func:`run_input_bytes` (a run
    relpath or ``drive:<object id>``): the provenance of what the command writes.
    """

    ctx: WriterContext
    storage: EngagementStoragePort
    run_folder: str
    inputs: list[str] = field(default_factory=list, compare=False)

    @property
    def is_covered(self) -> bool:
        return covered(self.ctx.decision)


def cached_storage_factory(
    load: Callable[[], EngagementStoragePort],
) -> Callable[[], EngagementStoragePort]:
    """One engagement-storage adapter per command: ``load`` is called on first use only.

    ``load`` is the caller's ``load_engagement_storage`` (its module-level seam).
    """
    cache: list[EngagementStoragePort] = []

    def factory() -> EngagementStoragePort:
        if not cache:
            cache.append(load())
        return cache[0]

    return factory


class ProfileMismatchRefused(RefusedError):
    """A ``--profile`` / ``--host`` other than the run's verified identity (exit 2)."""

    code = "PROFILE_MISMATCH"


def resolve_run_profile(
    storage: EngagementStoragePort,
    run_folder: str,
    profile: str | None,
    host: str | None = None,
) -> str | None:
    """The ``--profile`` a ``--run-folder`` command must use for workspace reads.

    On a run whose customer identity was verified, an omitted ``profile`` becomes the
    profile ``engagement verify-identity`` recorded; another profile, or ``--host`` on
    a profile-verified run, is refused. Other runs return ``profile`` unchanged.
    Reads the run descriptor only; call before any client is built.

    Raises:
        ProfileMismatchRefused: ``PROFILE_MISMATCH`` (exit 2).
        CommitError: The run descriptor is missing or invalid.
    """
    auth, _ = read_descriptor(storage, run_folder)
    try:
        resolved = run_profile(auth, profile)
    except ProfileMismatch as exc:
        raise ProfileMismatchRefused(str(exc)) from exc
    if host and resolved and not profile:
        raise ProfileMismatchRefused(
            f"PROFILE_MISMATCH: run {auth.run_id} was verified with --profile "
            f"{resolved!r}; drop --host {host!r} (reads use the verified profile)"
        )
    return resolved


def run_relpath(flag: str, value: str, *, covered_run: bool) -> str:
    """A ``--run-folder`` path flag is run-relative; a local path is refused.

    Raises:
        LocalStorageRefused: A local path on a covered run.
        ArgError: A local path otherwise.
    """
    return reads.run_relpath(flag, value, covered_run=covered_run, arg_error=ArgError)


def run_input_bytes(run: CliRun, flag: str, value: str) -> bytes:
    """Bytes of a run input: ``drive:<object id>`` or a run-relative path.

    At most :data:`MAX_INPUT_BYTES`; a ``drive:`` object is read with the kernel's
    verified read, a run relpath through the run's sink.

    Raises:
        ArgError: Not found, a folder, too large, or a local path (uncovered run).
        LocalStorageRefused: A local path on a covered run.
        StorageIntegrityError: The bytes do not match Drive's size / md5.
    """
    if value.startswith(_DRIVE_PREFIX):
        object_id = value[len(_DRIVE_PREFIX) :]
        try:
            data = reads.read_verified(run.storage, object_id, max_bytes=MAX_INPUT_BYTES)
        except StorageNotFoundError as exc:
            raise ArgError(f"{flag}: {value} not found: {exc}") from exc
        except reads.ReadRefusedError as exc:
            raise ArgError(f"{flag}: {_DRIVE_PREFIX}{exc}") from exc
        run.inputs.append(value)
        return data
    rel = run_relpath(flag, value, covered_run=run.is_covered)
    try:
        data = run.ctx.sink.get_bytes(rel, max_bytes=MAX_INPUT_BYTES)
    except StorageNotFoundError as exc:
        raise ArgError(f"{flag}: {rel} is not in the run folder") from exc
    except reads.ReadRefusedError as exc:
        raise ArgError(f"{flag}: {exc}") from exc
    run.inputs.append(rel)
    return data
