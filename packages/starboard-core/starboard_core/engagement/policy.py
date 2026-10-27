# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Storage-policy classification for engagement runs (engagement-drive spec §1).

A pure function maps (source mode, overlay signal, requested store) to a
:class:`StorageDecision`. The mandatory-Drive rule applies when the internal
overlay is enabled and the run has, or might have, a customer-workspace leg:
Databricks customer data must not land on a Databricks laptop. Unknown origin
uses the stricter path until resolved, and the classifier fails closed.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from starboard_core.engagement.overlay import OverlaySignal

RequestedStore = Literal["drive", "local"]

LOCAL_FILE_INTAKE_GUIDANCE = (
    "Local customer files are not accepted on an install with the internal overlay "
    "enabled. Share the file to Drive and pass the Drive reference instead."
)

_LOCAL_REFUSAL = (
    "Databricks customer data must not be stored on the laptop. This run has (or may "
    "have) a customer-workspace leg on an overlay-enabled install, so results must "
    "go to Drive. Re-run with Drive storage."
)


class SourceMode(StrEnum):
    """Where a run's evidence comes from."""

    CUSTOMER_WORKSPACE = "customer_workspace"
    INTERNAL_ONLY = "internal_only"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class StoragePolicy(StrEnum):
    """Where a run's evidence and outputs are stored."""

    LOCAL = "local"
    DRIVE_OPTIONAL = "drive_optional"
    DRIVE_REQUIRED = "drive_required"
    DRIVE_DEFAULT = "drive_default"
    INTERNAL_ONLY_LOCAL = "internal_only_local"


@dataclass(frozen=True)
class StorageDecision:
    """Outcome of :func:`classify_storage`.

    Attributes:
        policy: The storage policy that applies.
        drive_required: True when the run may not proceed without Drive.
        reason: Why this policy was chosen.
        refusal: Set when the requested store is not permitted; the caller must
            surface it and not honor the request.
    """

    policy: StoragePolicy
    drive_required: bool
    reason: str
    refusal: str | None = None


def classify_storage(
    source_mode: SourceMode,
    overlay: OverlaySignal,
    *,
    requested: RequestedStore | None,
) -> StorageDecision:
    """Decide the storage policy for a run.

    Args:
        source_mode: Classified source of the run's evidence.
        overlay: Overlay detection result.
        requested: Operator's explicit store choice, if any.

    Raises:
        ValueError: if ``requested`` is not ``"drive"``, ``"local"`` or None.
    """
    if requested not in ("drive", "local", None):
        raise ValueError(
            f"requested must be 'drive', 'local' or None, got {requested!r}"
        )

    if source_mode is SourceMode.INTERNAL_ONLY:
        if requested == "local":
            return StorageDecision(
                StoragePolicy.INTERNAL_ONLY_LOCAL,
                False,
                "internal-only run with explicit local storage and no customer-workspace leg",
            )
        return StorageDecision(
            StoragePolicy.DRIVE_DEFAULT, False, "internal-only runs default to Drive"
        )

    if source_mode is SourceMode.HYBRID and not overlay.enabled:
        return _drive_required(
            "hybrid run without the internal overlay: hybrid implies internal data, "
            "failing closed to Drive",
            requested,
        )

    if overlay.enabled:
        return _drive_required(
            f"overlay enabled and source mode is {source_mode.value}: customer-workspace "
            "collection must go to Drive",
            requested,
        )

    # Public install (overlay disabled); customer-workspace or unknown origin.
    if requested == "drive":
        return StorageDecision(
            StoragePolicy.DRIVE_OPTIONAL, False, "public run; operator chose Drive"
        )
    return StorageDecision(
        StoragePolicy.LOCAL, False, "public run; local store is the default"
    )


def _drive_required(reason: str, requested: RequestedStore | None) -> StorageDecision:
    return StorageDecision(
        StoragePolicy.DRIVE_REQUIRED,
        True,
        reason,
        _LOCAL_REFUSAL if requested == "local" else None,
    )


def local_file_intake_allowed(overlay: OverlaySignal) -> bool:
    """Whether local customer files may be ingested (never on overlay installs)."""
    return not overlay.enabled
