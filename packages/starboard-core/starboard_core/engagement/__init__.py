# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Engagement contracts: storage policy, run records, Drive routing and enforcement.

Pure, SDK-free building blocks for the engagement-drive design. The overlay
signal decides whether direct customer-workspace collection must be Drive-backed;
the records freeze each run's authorization and track its state; the folder
resolver maps a verified account (or validated ticket / override folder) to
remote folder IDs over
:class:`~starboard_core.ports.engagement_storage.EngagementStoragePort`.

The writer enforcement layer: :func:`writer_context` decides the
storage policy, arms the local :mod:`write guard <.write_guard>` on covered runs
and opens an :class:`ArtifactSink`; the account :mod:`registry <.registry>` lists
prior runs for history, status and publication.

The names below are re-exported lazily (PEP 562) so importing one submodule (for
example ``write_guard``) does not import the rest. Two names are deliberately not
re-exported: ``records.RunStatus`` (a ``Literal``; ``RunStatus`` here is the
:mod:`status` dataclass) and ``DEFAULT_MAX_BYTES`` (defined by both ``sink`` and
``stdout_budget``); import those from their modules.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starboard_core.engagement.enforce import (
        WriterContext,
        covered,
        decide_for_writer,
        refuse_local,
        writer_context,
    )
    from starboard_core.engagement.folders import (
        FolderAccessError,
        FolderConflictError,
        FolderResolution,
        FolderResolutionError,
        OverrideNotRestrictedError,
        resolve_account_route,
        resolve_override_route,
        resolve_ticket_route,
    )
    from starboard_core.engagement.history import (
        TRIGGER_UNIT,
        Candidate,
        UnavailableView,
        comparison_key,
        finding_states,
        select_baselines,
    )
    from starboard_core.engagement.observations import (
        FINDINGS_METHOD,
        from_findings_manifest,
    )
    from starboard_core.engagement.publication import (
        approval_matches,
        audience_gate,
        can_approve,
        can_deliver,
        publication_state,
        receipt_delivers,
        revision_state,
    )
    from starboard_core.engagement.registry import (
        IndexEntry,
        RegistrationConflictError,
        RegistrationView,
        RegistryHandle,
        RegistryNotFoundError,
        ensure_registry,
        import_registration_id,
        list_registrations,
        read_index,
        rebuild_index,
        register,
    )
    from starboard_core.engagement.sink import (
        ENGAGEMENT_STORAGE_GROUP,
        ENGAGEMENT_STORAGE_NAME,
        AccessRecheckError,
        ArtifactSink,
        DriveRunSink,
        LocalDirSink,
        LocalStorageRefused,
        MemorySink,
        SinkConflictError,
        StorageUnavailableError,
        load_engagement_storage,
        open_sink,
        sink_evidence,
    )
    from starboard_core.engagement.status import STATUSES, RunStatus, derive_status
    from starboard_core.engagement.stdout_budget import (
        MAX_LIST_ITEMS,
        bound,
        encoded_size,
    )
    from starboard_core.engagement.write_guard import (
        GuardPolicy,
        LocalWriteRefused,
        default_policy,
        guarded,
    )

_EXPORTS: dict[str, tuple[str, ...]] = {
    "enforce": (
        "WriterContext",
        "covered",
        "decide_for_writer",
        "refuse_local",
        "writer_context",
    ),
    "folders": (
        "FolderAccessError",
        "FolderConflictError",
        "FolderResolution",
        "FolderResolutionError",
        "OverrideNotRestrictedError",
        "resolve_account_route",
        "resolve_override_route",
        "resolve_ticket_route",
    ),
    "history": (
        "TRIGGER_UNIT",
        "Candidate",
        "UnavailableView",
        "comparison_key",
        "finding_states",
        "select_baselines",
    ),
    "observations": (
        "FINDINGS_METHOD",
        "from_findings_manifest",
    ),
    "publication": (
        "approval_matches",
        "audience_gate",
        "can_approve",
        "can_deliver",
        "publication_state",
        "receipt_delivers",
        "revision_state",
    ),
    "registry": (
        "IndexEntry",
        "RegistrationConflictError",
        "RegistrationView",
        "RegistryHandle",
        "RegistryNotFoundError",
        "ensure_registry",
        "import_registration_id",
        "list_registrations",
        "read_index",
        "rebuild_index",
        "register",
    ),
    "sink": (
        "ENGAGEMENT_STORAGE_GROUP",
        "ENGAGEMENT_STORAGE_NAME",
        "AccessRecheckError",
        "ArtifactSink",
        "DriveRunSink",
        "LocalDirSink",
        "LocalStorageRefused",
        "MemorySink",
        "SinkConflictError",
        "StorageUnavailableError",
        "load_engagement_storage",
        "open_sink",
        "sink_evidence",
    ),
    "status": ("STATUSES", "RunStatus", "derive_status"),
    "stdout_budget": ("MAX_LIST_ITEMS", "bound", "encoded_size"),
    "write_guard": (
        "GuardPolicy",
        "LocalWriteRefused",
        "default_policy",
        "guarded",
    ),
}

_ORIGIN = {name: module for module, names in _EXPORTS.items() for name in names}

__all__ = [
    "AccessRecheckError",
    "ArtifactSink",
    "Candidate",
    "DriveRunSink",
    "ENGAGEMENT_STORAGE_GROUP",
    "ENGAGEMENT_STORAGE_NAME",
    "FINDINGS_METHOD",
    "FolderAccessError",
    "FolderConflictError",
    "FolderResolution",
    "FolderResolutionError",
    "GuardPolicy",
    "IndexEntry",
    "LocalDirSink",
    "LocalStorageRefused",
    "LocalWriteRefused",
    "MAX_LIST_ITEMS",
    "MemorySink",
    "OverrideNotRestrictedError",
    "RegistrationConflictError",
    "RegistrationView",
    "RegistryHandle",
    "RegistryNotFoundError",
    "RunStatus",
    "STATUSES",
    "SinkConflictError",
    "StorageUnavailableError",
    "TRIGGER_UNIT",
    "UnavailableView",
    "WriterContext",
    "approval_matches",
    "audience_gate",
    "bound",
    "can_approve",
    "can_deliver",
    "comparison_key",
    "covered",
    "decide_for_writer",
    "default_policy",
    "derive_status",
    "encoded_size",
    "ensure_registry",
    "finding_states",
    "from_findings_manifest",
    "guarded",
    "import_registration_id",
    "list_registrations",
    "load_engagement_storage",
    "open_sink",
    "publication_state",
    "read_index",
    "rebuild_index",
    "receipt_delivers",
    "refuse_local",
    "register",
    "resolve_account_route",
    "resolve_override_route",
    "resolve_ticket_route",
    "revision_state",
    "select_baselines",
    "sink_evidence",
    "writer_context",
]


def __getattr__(name: str) -> Any:
    module = _ORIGIN.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
