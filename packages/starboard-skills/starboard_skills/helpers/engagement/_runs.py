"""Shared run plumbing: records, Drive staging lookups and the run-folder opener.

Staging lookups are read-only (nothing is created). :func:`_run_command` opens a
run folder with its access rechecked and the local write guard armed by policy.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starboard_skills.helpers.contract import (
    ApiError,
    ArgError,
)
from starboard_skills.helpers.engagement import _envelope
from starboard_skills.helpers.engagement._envelope import (
    ARTIFACT_PROPERTY,
    DEFAULT_REPORTS_ROOT,
    EVIDENCE_PATH,
    OBSERVATIONS_PATH,
    PREFLIGHT_RECORD,
    STAGED_PREFLIGHT,
    RunQuarantined,
    _ctx,
    _storage_errors,
)

if TYPE_CHECKING:  # kernel types only; imported lazily at runtime
    from starboard_core.engagement.policy import StorageDecision
    from starboard_core.engagement.records import RunAuthorization, StorageRef
    from starboard_core.engagement.sink import ArtifactSink, DriveRunSink
    from starboard_core.ports.engagement_storage import (
        EngagementStoragePort,
    )


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()  # Drive md5Checksum


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]


def _put_record(sink: ArtifactSink, rel: str, payload: Mapping[str, Any]) -> StorageRef:
    """Write a helper-owned kernel record through the sink's privileged path."""
    from starboard_core.engagement.staging import encode_json  # lazy – kernel dep

    return sink.put_record(rel, encode_json(payload), "application/json")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    from starboard_core.engagement.staging import encode_json  # lazy – kernel dep

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_json(payload))


def _close(storage: EngagementStoragePort) -> None:
    close: Callable[[], None] | None = getattr(storage, "close", None)
    if close is not None:
        close()


def _decision_of(pre: Mapping[str, Any]) -> StorageDecision:
    """Rebuild the ``StorageDecision`` recorded in a preflight record."""
    from starboard_core.engagement.policy import (  # lazy – kernel dep
        StorageDecision,
        StoragePolicy,
    )

    d = pre.get("decision") or {}
    try:
        return StorageDecision(
            StoragePolicy(d["policy"]),
            bool(d["drive_required"]),
            str(d.get("reason") or ""),
            refusal=d.get("refusal"),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ApiError(
            f"the preflight record has no valid storage decision ({exc})"
        ) from exc


def _guard(decision: StorageDecision) -> AbstractContextManager[object]:
    """The local write guard for a covered run; a no-op otherwise."""
    from starboard_core.engagement.enforce import covered  # lazy – kernel dep
    from starboard_core.engagement.write_guard import default_policy, guarded

    if covered(decision):
        return guarded(default_policy())
    return nullcontext()


def _auth_decision(auth: RunAuthorization) -> StorageDecision:
    """The ``StorageDecision`` a run descriptor's storage policy stands for."""
    from starboard_core.engagement.policy import (  # lazy – kernel dep
        StorageDecision,
        StoragePolicy,
    )

    policy = auth.storage_policy
    return StorageDecision(
        policy, policy is StoragePolicy.DRIVE_REQUIRED, "run authorization"
    )


def _check_run_id(run_id: str, flag: str = "--run-id") -> str:
    from starboard_core.engagement.run_id import is_run_id  # lazy – kernel dep

    run_id = (run_id or "").strip()
    if not is_run_id(run_id):
        raise ArgError(
            f"{flag} must be YYYYMMDD_<uuid4> (from preflight); got {run_id!r}"
        )
    return run_id


def _local_run_dir(args: argparse.Namespace) -> str | None:
    """The local run dir that ``--run-dir`` or ``--run-id`` names; ``None`` for a Drive run.

    A ``--run-id`` names a local run when
    ``starboard-reports/<account>/<task>/<task-name>/<run_id>/`` holds its preflight
    record. Only a run with no such record is a Drive run, so a local run never needs
    the storage adapter.
    """
    if getattr(args, "run_dir", None):
        return str(args.run_dir)
    run_id = _check_run_id(args.run_id)
    found = sorted(
        {
            p.parents[1]
            for p in Path(DEFAULT_REPORTS_ROOT).glob(
                f"*/*/*/{run_id}/{PREFLIGHT_RECORD}"
            )
        }
    )
    if len(found) > 1:
        raise ArgError(
            f"run {run_id} has {len(found)} local run dirs under {DEFAULT_REPORTS_ROOT}/ "
            f"({', '.join(p.as_posix() for p in found)}); pass --run-dir"
        )
    return found[0].as_posix() if found else None


def _drive_storage(run_id: str) -> EngagementStoragePort:
    """The Drive adapter for run ``run_id``; a missing adapter names the local form."""
    from starboard_core.engagement.sink import (  # lazy – kernel dep
        StorageUnavailableError,
    )

    try:
        return _envelope._make_storage()
    except StorageUnavailableError as exc:
        raise StorageUnavailableError(
            f"{exc}. Run {run_id} has no local run dir under {DEFAULT_REPORTS_ROOT}/, so "
            "it is read from Drive; a local run kept elsewhere takes --run-dir <run-dir>"
        ) from exc


def _committed(
    storage: EngagementStoragePort, run_folder_id: str, rel: str, md5: str | None
) -> bool:
    """Whether the latest committed manifest binds ``rel`` at exactly ``md5``."""
    from starboard_core.engagement.commit import latest_manifest  # lazy – kernel dep

    latest = None if md5 is None else latest_manifest(storage, run_folder_id)
    return latest is not None and any(
        r.path == rel and r.md5 == md5 for r in latest[0].refs
    )


def _read_ref(
    storage: EngagementStoragePort, ref: Any, *, max_bytes: int | None = None
) -> bytes:
    """Read the exact committed revision behind a ``StorageRef`` and verify it.

    Streamed under ``max_bytes`` (default: the largest artifact the run sink
    accepts); a larger object is refused as an integrity failure, like
    :func:`_envelope._read_verified`. (The kernel's ``read_object`` reads only the
    head revision, so the committed revision is streamed here.)
    """
    from starboard_core.engagement.sink import DEFAULT_MAX_BYTES  # lazy – kernel dep
    from starboard_core.ports.engagement_storage import StorageIntegrityError

    cap = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes
    too_big = StorageIntegrityError(
        f"{ref.path} ({ref.object_id}) is larger than {cap} bytes"
    )
    if ref.size is not None and ref.size > cap:
        raise too_big
    buf = bytearray()
    for chunk in storage.get_stream(ref.object_id, revision=ref.revision):
        buf += chunk
        if len(buf) > cap:
            raise too_big
    data = bytes(buf)
    if (ref.size is not None and len(data) != ref.size) or (
        ref.md5 is not None and _md5(data) != ref.md5
    ):
        raise StorageIntegrityError(
            f"{ref.path} ({ref.object_id}) no longer matches its committed md5/size"
        )
    return data


def _json(data: bytes, what: str) -> Any:
    from starboard_core.ports.engagement_storage import (  # lazy – kernel dep
        StorageIntegrityError,
    )

    try:
        return json.loads(data)
    except ValueError as exc:
        raise StorageIntegrityError(f"{what} is not valid JSON ({exc})") from exc


def _storage_ref(path: str, obj: Any) -> Any:
    from starboard_core.engagement.records import StorageRef  # lazy – kernel dep

    return StorageRef(
        path=path,
        object_id=obj.id,
        revision=obj.revision,
        md5=obj.md5,
        size=obj.size,
        mime_type=obj.mime_type,
    )


# --------------------------------------------------------------------------- #
# Drive staging lookups (read-only; nothing is created)
# --------------------------------------------------------------------------- #
def _locate_staging(storage: EngagementStoragePort, run_id: str) -> tuple[str, Any]:
    """``("staged" | "quarantined" | "missing", folder)`` for ``_preflight/<run_id>``.

    Searches every ``starboard/_preflight`` folder: two first runs at once can
    leave duplicate ``starboard`` roots, each holding some runs' staging.
    """
    from starboard_core.engagement.staging import locate_staging  # lazy – kernel dep

    found = locate_staging(storage, run_id)
    return found.state, found.folder


def _read_staged(
    storage: EngagementStoragePort, folder_id: str, name: str, tag: str
) -> Any:
    """Parse the staged JSON record ``name`` tagged ``tag``, verified; ``None`` if absent.

    Byte-identical copies are one record a retried upload request landed twice (run
    11): the earliest is read. Copies that differ are a conflict.
    """
    from starboard_core.engagement.folders import creation_order  # lazy – kernel dep
    from starboard_core.ports.engagement_storage import (  # lazy – kernel dep
        StorageIntegrityError,
    )

    found = sorted(
        (
            o
            for o in storage.list_children(folder_id, name=name)
            if not o.is_folder and o.properties.get(ARTIFACT_PROPERTY) == tag
        ),
        key=creation_order,
    )
    if not found:
        return None
    first = found[0]
    if len(found) > 1 and (
        first.md5 is None
        or any(o.md5 != first.md5 or o.size != first.size for o in found[1:])
    ):
        raise StorageIntegrityError(
            f"{len(found)} staged {name!r} records in {folder_id}; reconcile in Drive"
        )
    return _json(_envelope._read_verified(storage, first), f"staged {name}")


def _open_staging(
    storage: EngagementStoragePort, run_id: str, *, require_record: bool = True
) -> tuple[Any, dict[str, Any] | None]:
    """Resolve the run's staging folder and its preflight record from Drive.

    Raises:
        ArgError: Unknown run (nothing is created).
        RunQuarantined: The staging folder was quarantined.
    """
    from starboard_core.engagement.staging import (  # lazy – kernel dep
        QUARANTINE_PROPERTY,
        locate_staging,
        staging_at,
    )

    found = locate_staging(storage, run_id)
    folder = found.folder
    if folder is None:  # state "missing"
        raise ArgError(
            f"unknown run {run_id}: there is no Drive staging folder "
            f"My Drive/starboard/_preflight/{run_id}; start a new run with "
            "`engagement preflight`"
        )
    if found.state == "quarantined":
        reason = folder.properties.get(QUARANTINE_PROPERTY) or "quarantined"
        raise RunQuarantined(
            f"run {run_id} is quarantined ({reason}); start a new run with "
            "`engagement preflight`"
        )
    if found.preflight_folder_id is None:  # always set for a staged folder
        raise ApiError(f"run {run_id} staging folder has no _preflight parent")
    staging = staging_at(storage, folder, found.preflight_folder_id)
    pre = _read_staged(storage, folder.id, STAGED_PREFLIGHT, f"preflight:{run_id}")
    if pre is None and require_record:
        raise ArgError(
            f"run {run_id} has no staged preflight record; re-run "
            f"`engagement preflight --resume-run-id {run_id}` with the full flags"
        )
    if pre is not None and (not isinstance(pre, dict) or pre.get("run_id") != run_id):
        raise ApiError(f"the staged preflight record of run {run_id} is not valid")
    return staging, pre


# --------------------------------------------------------------------------- #
# Account and domain checks
# --------------------------------------------------------------------------- #
def _same_sf_id(a: str, b: str) -> bool:
    """Exact equality; a 15- and an 18-char CRM account ID also match on their prefix.

    Any other length pair (e.g. 16-digit workspace-ID account keys) must be equal.
    """
    if a == b:
        return True
    return {len(a), len(b)} == {15, 18} and a[:15] == b[:15]


def _internal_domains(args: argparse.Namespace) -> frozenset[str]:
    """``--internal-domain`` narrowed to the pinned set; an unpinned domain is a usage error.

    No flag means no domain (callers that need one say so).
    """
    from starboard_core.engagement.folders import (  # lazy – kernel dep
        effective_internal_domains,
    )

    requested = [d for d in getattr(args, "internal_domain", None) or () if d.strip()]
    if not requested:
        return frozenset()
    try:
        return effective_internal_domains(requested)
    except ValueError as exc:
        raise ArgError(f"--internal-domain: {exc}") from exc


# --------------------------------------------------------------------------- #
# Run-folder helpers (status / commit / read / history / publication)
# --------------------------------------------------------------------------- #
#: The sink each open run command holds, by ``(id(storage), run_folder_id)``:
#: :func:`_artifacts` answers from that sink's in-memory index (one listing per
#: command, kept current by its writes). Process memory only; removed when the
#: command ends.
_OPEN_SINKS: dict[tuple[int, str], DriveRunSink] = {}


def _artifacts(
    storage: EngagementStoragePort, run_folder_id: str, run_id: str
) -> dict[str, Any]:
    """``relpath -> StorageObject`` for every artifact the run sink wrote.

    One property query for the whole run (:meth:`DriveRunSink.artifacts`).
    Identical copies of a relpath (a retried upload) converge on the earliest,
    with a ``duplicate_artifact:`` warning; differing copies raise
    :class:`~starboard_core.engagement.sink.SinkConflictError`.
    """
    from starboard_core.engagement.sink import DriveRunSink  # lazy – kernel dep

    sink = _OPEN_SINKS.get((id(storage), run_folder_id))
    if sink is None or sink.run_id != run_id:
        # A read-only view: no fingerprint, so it can never write.
        sink = DriveRunSink(
            storage, run_folder_id, run_id=run_id, access_fingerprint=""
        )
    return sink.artifacts()


def _quarantine_reason(
    storage: EngagementStoragePort, auth: RunAuthorization
) -> str | None:
    from starboard_core.engagement.staging import (  # lazy – kernel dep
        QUARANTINE_PROPERTY,
    )
    from starboard_core.ports.engagement_storage import StorageNotFoundError

    staging_id = None if auth.drive is None else auth.drive.preflight_folder_id
    if not staging_id:
        return None
    try:
        return storage.get(staging_id).properties.get(QUARANTINE_PROPERTY) or None
    except StorageNotFoundError:
        return None


def _fingerprint(auth: RunAuthorization, run_folder_id: str) -> str:
    if auth.drive is None or auth.drive.run_folder_id != run_folder_id:
        raise ApiError(
            f"the descriptor in {run_folder_id} does not authorize that folder; pass the "
            "run_folder_id printed by `engagement route`"
        )
    return str(auth.drive.permission_fingerprints.get(run_folder_id) or "")


def _open_run(
    storage: EngagementStoragePort, run_folder_id: str, ctx: dict[str, Any]
) -> tuple[RunAuthorization, DriveRunSink]:
    """Read the descriptor, refuse a quarantined run, recheck access; return ``(auth, sink)``."""
    from starboard_core.engagement.access import recheck_access  # lazy – kernel dep
    from starboard_core.engagement.commit import read_descriptor
    from starboard_core.engagement.sink import AccessRecheckError, DriveRunSink

    ctx["run_folder_id"] = run_folder_id
    auth, _ = read_descriptor(storage, run_folder_id)
    ctx["run_id"] = auth.run_id
    fingerprint = _fingerprint(auth, run_folder_id)
    reason = _quarantine_reason(storage, auth)
    if reason:
        raise RunQuarantined(
            f"run {auth.run_id} is quarantined ({reason}); start a new run with "
            "`engagement preflight`"
        )
    access = storage.inspect_access(run_folder_id)
    verdict = recheck_access(fingerprint, access)
    if not verdict.ok:
        raise AccessRecheckError(run_folder_id, verdict)
    # The sink reuses this inspection: one access check per command.
    sink = DriveRunSink(
        storage,
        run_folder_id,
        run_id=auth.run_id,
        access_fingerprint=fingerprint,
        access=access,
    )
    _OPEN_SINKS[(id(storage), run_folder_id)] = sink
    return auth, sink


def _latest(
    storage: EngagementStoragePort, run_folder_id: str, run_id: str
) -> tuple[Any, Any]:
    from starboard_core.engagement.commit import latest_manifest  # lazy – kernel dep

    latest = latest_manifest(storage, run_folder_id)
    if latest is None:
        raise ApiError(
            f"run {run_id} has no manifest yet; re-run `engagement route --run-id {run_id}`"
        )
    return latest


def _append(
    storage: EngagementStoragePort,
    run_folder_id: str,
    prev: Any,
    changes: Mapping[str, Any],
) -> tuple[Any, Any, bool]:
    """Append the next manifest revision with ``changes``; reuse ``prev`` when unchanged."""
    from starboard_core.engagement.commit import append_manifest  # lazy – kernel dep

    if dataclasses.replace(prev, **changes).to_dict() == prev.to_dict():
        return prev, None, False
    manifest, obj = append_manifest(
        storage,
        run_folder_id,
        lambda n, prev_id: dataclasses.replace(
            prev,
            revision=n,
            previous_object_id=prev_id,
            committed_at=_envelope._now(),
            **changes,
        ),
    )
    return manifest, obj, True


def _evidence_map(
    storage: EngagementStoragePort, objs: Mapping[str, Any]
) -> dict[str, Any]:
    from starboard_core.engagement.records import EvidenceRef  # lazy – kernel dep
    from starboard_core.ports.engagement_storage import StorageIntegrityError

    obj = objs.get(EVIDENCE_PATH)
    if obj is None:
        return {}
    raw = _json(_envelope._read_verified(storage, obj), EVIDENCE_PATH)
    try:
        if not isinstance(raw, list):
            raise TypeError("not a JSON list")
        refs = [EvidenceRef.from_dict(item) for item in raw]
    except (ValueError, TypeError, KeyError) as exc:
        raise StorageIntegrityError(
            f"{EVIDENCE_PATH} is not a valid EvidenceRef list ({exc})"
        ) from exc
    return {r.evidence_id: r for r in refs}


def _parse_observations(raw: Any, what: str) -> list[Any]:
    from starboard_core.engagement.records import Observation  # lazy – kernel dep
    from starboard_core.ports.engagement_storage import StorageIntegrityError

    items = raw.get("observations") if isinstance(raw, dict) else raw
    try:
        if not isinstance(items, list):
            raise TypeError("not a list of observations")
        parsed = [Observation.from_dict(item) for item in items]
    except (ValueError, TypeError, KeyError) as exc:
        raise StorageIntegrityError(
            f"{what} is not a valid Observation list ({exc})"
        ) from exc
    seen: set[tuple[str, str]] = set()
    unique: list[Any] = []
    for o in parsed:
        key = (o.run_id, o.observation_id)
        if key not in seen:
            seen.add(key)
            unique.append(o)
    return unique


def _run_observations(
    storage: EngagementStoragePort, objs: Mapping[str, Any]
) -> list[Any]:
    obj = objs.get(OBSERVATIONS_PATH)
    if obj is None:
        return []
    return _parse_observations(
        _json(_envelope._read_verified(storage, obj), OBSERVATIONS_PATH),
        OBSERVATIONS_PATH,
    )


def _run_command(
    args: argparse.Namespace,
    body: Callable[
        [EngagementStoragePort, RunAuthorization, DriveRunSink, dict[str, Any]],
        dict[str, Any],
    ],
    *,
    stage: str | None = None,
) -> dict[str, Any]:
    """Open the run folder (access rechecked), arm the guard by policy, run ``body``."""
    ctx = _ctx(args)
    if stage:
        ctx["stage"] = stage
    if not (args.run_folder or "").strip():
        raise ArgError(
            "--run-folder is required (the run_folder_id from `engagement route`)"
        )
    storage = _envelope._make_storage()
    sink: DriveRunSink | None = None
    try:
        with _storage_errors(False, None):
            auth, sink = _open_run(storage, args.run_folder.strip(), ctx)
            with _guard(_auth_decision(auth)):
                data = body(storage, auth, sink, ctx)
            _merge_warnings(data, sink.warnings)
            return data
    except BaseException:
        if sink is not None and sink.warnings:
            _merge_warnings(ctx, sink.warnings)
        raise
    finally:
        if sink is not None:
            _OPEN_SINKS.pop((id(storage), sink.run_folder_id), None)
        _close(storage)


def _merge_warnings(target: dict[str, Any], warnings: list[str]) -> None:
    """Append the sink's warnings (``duplicate_artifact:`` ...) to ``target``."""
    if not warnings:
        return
    existing = target.get("warnings")
    merged = list(existing) if isinstance(existing, list | tuple) else []
    merged.extend(w for w in warnings if w not in merged)
    target["warnings"] = merged
