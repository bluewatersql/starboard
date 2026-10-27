# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""The one evidence recorder, and the source kind computed from a writer's inputs.

Every writer records its outputs with :func:`record_evidence`; the audience class is
always :func:`~starboard_core.engagement.records.audience_class_for` its source kind
(D-14), never declared by the caller.

The source kind comes from the data, not the run:
:func:`input_source_kinds` looks each input up in the run's ``evidence/index.json``
and :func:`derive_source_kind` folds them into one label, the most restrictive
winning. Any internal input makes the output internal, and on a hybrid (or
unclassified) run the output is internal unless every input is customer-sourced.

Stdlib + port only.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime

from starboard_core.engagement.commit import read_descriptor
from starboard_core.engagement.policy import SourceMode
from starboard_core.engagement.records import (
    EvidenceRef,
    StorageRef,
    audience_class_for,
    evidence_id,
)
from starboard_core.engagement.sink import EVIDENCE_INDEX, ArtifactSink, sink_evidence
from starboard_core.ports.engagement_storage import (
    EngagementStoragePort,
    StorageIntegrityError,
)

__all__ = [
    "DEFAULT_INTERNAL_SOURCE",
    "SOURCE_KIND_ORDER",
    "EvidenceItem",
    "derive_source_kind",
    "input_source_kinds",
    "record_evidence",
    "record_run_evidence",
]

#: ``(ref, producer, row_count, truncated)`` of one written object.
EvidenceItem = tuple[StorageRef, str, int | None, bool]

#: Every source kind, most restrictive first.
SOURCE_KIND_ORDER: tuple[str, ...] = (
    "internal_telemetry",
    "internal_mirror",
    "operator_input",
    "drive_object",
    "customer_workspace",
)
#: Label of internal evidence whose exact internal source is not known.
DEFAULT_INTERNAL_SOURCE = "internal_mirror"

_CUSTOMER = "customer_workspace"
_DRIVE_PREFIX = "drive:"


def record_evidence(
    sink: ArtifactSink,
    items: Iterable[EvidenceItem],
    *,
    source_kind: str,
    scope: Sequence[str],
    method_version: str,
) -> list[EvidenceRef]:
    """Append one ``EvidenceRef`` per item to the run's ``evidence/index.json``.

    Drive sinks only: on any other sink (or with no items) nothing is recorded and
    ``[]`` is returned. ``scope`` is the evidence's workspace IDs.

    Raises:
        ValueError: ``source_kind`` is not a known source kind.
    """
    audience = audience_class_for(source_kind)
    entries = list(items)
    run_id = sink.run_id
    if sink.kind != "drive" or run_id is None or not entries:
        return []
    acquired_at = datetime.now(UTC).isoformat(timespec="seconds")
    refs = [
        EvidenceRef(
            evidence_id=evidence_id(run_id, ref.path, str(ref.md5)),
            run_id=run_id,
            storage_ref=ref,
            source_kind=source_kind,
            scope_workspace_ids=tuple(str(w) for w in scope),
            producer=producer,
            row_count=row_count,
            truncated=truncated,
            acquired_at=acquired_at,
            audience_class=audience,
            method_version=method_version,
        )
        for ref, producer, row_count, truncated in entries
    ]
    sink_evidence(sink, refs)
    return refs


def _indexed_kinds(sink: ArtifactSink) -> Mapping[str, str]:
    """Source kind of every indexed object, by relpath and by ``drive:<object id>``."""
    if not sink.exists(EVIDENCE_INDEX):
        return {}
    try:
        stored = json.loads(sink.get_bytes(EVIDENCE_INDEX))
        if not isinstance(stored, list):
            raise TypeError("the index is not a JSON list")
        refs = [EvidenceRef.from_dict(item) for item in stored]
    except (ValueError, TypeError, KeyError) as exc:
        raise StorageIntegrityError(
            f"{EVIDENCE_INDEX} is not a valid EvidenceRef list ({exc})"
        ) from exc
    kinds: dict[str, str] = {}
    for ev in refs:
        kinds[ev.storage_ref.path] = ev.source_kind
        kinds[_DRIVE_PREFIX + ev.storage_ref.object_id] = ev.source_kind
    return kinds


def input_source_kinds(sink: ArtifactSink, values: Iterable[str]) -> list[str | None]:
    """The recorded source kind of each input (a run relpath or ``drive:<object id>``).

    An input recorded in the run's evidence index has that entry's source kind. A
    ``drive:`` object outside the index is a ``drive_object``; an unindexed relpath
    has unknown provenance (``None``).
    """
    wanted = list(values)
    if not wanted:
        return []
    indexed = _indexed_kinds(sink)
    return [
        indexed.get(v, "drive_object" if v.startswith(_DRIVE_PREFIX) else None)
        for v in wanted
    ]


def derive_source_kind(
    input_kinds: Iterable[str | None], *, source_mode: SourceMode | str
) -> str:
    """The source kind of an output derived from inputs of ``input_kinds``.

    ``None`` is an input of unknown provenance. The most restrictive label wins
    (:data:`SOURCE_KIND_ORDER`):

    * any internal input: that internal kind;
    * a customer-workspace run: the most restrictive input kind, unknown and no
      inputs counting as ``customer_workspace``;
    * an internal-only run: internal;
    * a hybrid or unclassified run: ``customer_workspace`` only when there are inputs
      and every one is customer-sourced, otherwise internal.

    Raises:
        ValueError: An input kind is not a known source kind.
    """
    kinds = list(input_kinds)
    for kind in kinds:
        if kind is not None:
            audience_class_for(kind)  # validates the kind
    mode = SourceMode(source_mode)
    known = [k for k in kinds if k is not None]
    internal = [k for k in known if k.startswith("internal_")]
    if internal:
        return min(internal, key=SOURCE_KIND_ORDER.index)
    if mode is SourceMode.CUSTOMER_WORKSPACE:
        return min(known, key=SOURCE_KIND_ORDER.index) if known else _CUSTOMER
    if mode is not SourceMode.INTERNAL_ONLY and kinds and all(k == _CUSTOMER for k in kinds):
        return _CUSTOMER
    return DEFAULT_INTERNAL_SOURCE


def record_run_evidence(
    sink: ArtifactSink,
    storage: EngagementStoragePort,
    run_folder_id: str,
    items: Iterable[EvidenceItem],
    *,
    input_kinds: Iterable[str | None],
    method_version: str,
    scope: Sequence[str] | None = None,
) -> list[EvidenceRef]:
    """Record outputs derived from inputs of ``input_kinds`` on a Drive run.

    The source kind is :func:`derive_source_kind` of ``input_kinds`` under the run
    descriptor's source mode; ``scope`` defaults to the descriptor's authorized
    workspace IDs. Non-Drive sinks record nothing (the descriptor is not read).

    Raises:
        CommitError: The run descriptor is missing or invalid.
        ValueError: An input kind is not a known source kind.
    """
    entries = list(items)
    if sink.kind != "drive" or sink.run_id is None or not entries:
        return []
    auth, _ = read_descriptor(storage, run_folder_id)
    if scope is None:
        scope = tuple(auth.authorized_scope.get("workspace_ids") or ())
    return record_evidence(
        sink,
        entries,
        source_kind=derive_source_kind(input_kinds, source_mode=auth.source_mode),
        scope=scope,
        method_version=method_version,
    )
