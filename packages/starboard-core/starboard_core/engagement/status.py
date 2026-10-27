# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Derived run status.

Pure function of the run descriptor, its committed manifest revisions, the
latest access recheck and the identity verdict. Nothing is spooled locally
(D-23): ``resume`` names the run and the first incomplete stage, which is
re-acquired on re-run.

Precedence: ``quarantined`` (identity mismatch) > ``blocked_access`` (recheck
not ``unchanged``, D-24) > ``staged`` (no manifest) > ``routed`` (revision 1,
nothing started) > first incomplete stage > ``complete``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from starboard_core.engagement.access import AccessVerdict
from starboard_core.engagement.records import (
    MANIFEST_STATE_KEYS,
    RunAuthorization,
    RunManifest,
)

__all__ = ["STATUSES", "RunStatus", "derive_status"]

STATUSES: tuple[str, ...] = (
    "staged",
    "routed",
    "capture_pending",
    "analysis_pending",
    "check_pending",
    "publication_pending",
    "complete",
    "blocked_access",
    "quarantined",
)
_DONE = frozenset({"complete", "skipped"})


@dataclass(frozen=True)
class RunStatus:
    """Derived status of one run.

    Attributes:
        status: One of :data:`STATUSES`.
        states: Stage -> status of the latest manifest (empty before any).
        pending: Incomplete stages in order (``("route",)`` before any manifest).
        resume: ``{run_id, run_folder_id, stage}`` when re-running can make
            progress; ``None`` when complete, quarantined, access-blocked or the
            run is unknown.
        checkpoint_revision: Latest committed manifest revision, if any.
    """

    status: str
    states: Mapping[str, str]
    pending: tuple[str, ...]
    resume: Mapping[str, Any] | None
    checkpoint_revision: int | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(
                f"RunStatus.status must be one of {STATUSES}, got {self.status!r}"
            )
        object.__setattr__(self, "states", MappingProxyType(dict(self.states)))
        object.__setattr__(self, "pending", tuple(self.pending))
        if self.resume is not None:
            object.__setattr__(self, "resume", MappingProxyType(dict(self.resume)))


def derive_status(
    descriptor: RunAuthorization | None,
    manifests: Sequence[RunManifest],
    access: AccessVerdict | None,
    quarantined: bool,
) -> RunStatus:
    """Derive a :class:`RunStatus`.

    Raises:
        ValueError: When manifests (or the descriptor) disagree on the run ID.
    """
    run_ids = {m.run_id for m in manifests}
    if descriptor is not None:
        run_ids.add(descriptor.run_id)
    if len(run_ids) > 1:
        raise ValueError(f"derive_status got mixed run IDs: {sorted(run_ids)}")
    run_id = next(iter(run_ids), None)
    run_folder_id = (
        descriptor.drive.run_folder_id
        if descriptor is not None and descriptor.drive is not None
        else None
    )

    latest = max(manifests, key=lambda m: m.revision) if manifests else None
    states: Mapping[str, str] = dict(latest.states) if latest is not None else {}
    checkpoint = latest.revision if latest is not None else None
    if latest is None:
        pending: tuple[str, ...] = ("route",)
    else:
        pending = tuple(k for k in MANIFEST_STATE_KEYS if states[k] not in _DONE)

    def status(name: str, *, resumable: bool) -> RunStatus:
        resume = None
        if resumable and pending and run_id is not None:
            resume = {
                "run_id": run_id,
                "run_folder_id": run_folder_id,
                "stage": pending[0],
            }
        return RunStatus(
            status=name,
            states=states,
            pending=pending,
            resume=resume,
            checkpoint_revision=checkpoint,
        )

    if quarantined:
        return status("quarantined", resumable=False)
    if access is not None and not access.ok:
        return status("blocked_access", resumable=False)
    if latest is None:
        return status("staged", resumable=True)
    if latest.revision == 1 and all(v == "pending" for v in states.values()):
        return status("routed", resumable=True)
    if not pending:
        return status("complete", resumable=False)
    return status(f"{pending[0]}_pending", resumable=True)
