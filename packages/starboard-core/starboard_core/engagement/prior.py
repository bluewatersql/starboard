# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Prior records of one account workspace, across every task folder (D3-25).

:func:`load_prior` reads every registration of the account registry (health,
troubleshooting and discovery folders alike) and returns the committed
observations, findings, cases and actions of one workspace. :func:`load_prior_local`
does the same over the D-20 local case roots of one account (D4-16): only run dirs
whose own run authorization names the account count. Neither raises for a bad prior:
an unreadable registry, a ``history_unavailable`` registration or a record that
fails to parse becomes an :class:`Unavailable` entry naming the record kinds it
hides. Only an authentication failure propagates.

Resolution across copies: per finding key the highest ``revision`` wins (D3-4),
per case the copy with the most evidence revisions, per action the copy with
the most events; ties go to the later commit (locally: the later run date, then the
later preflight ``created_at``, then the later run ID). Observations are deduplicated by
``(run_id, observation_id)``, keeping the highest committed revision.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starboard_core.engagement.commit import (
    DESCRIPTOR_NAME,
    CommitError,
    latest_manifest,
    read_descriptor,
)
from starboard_core.engagement.folders import FolderResolutionError
from starboard_core.engagement.history import Candidate
from starboard_core.engagement.reads import read_object
from starboard_core.engagement.records import (
    Action,
    Case,
    FindingRecord,
    Observation,
    Play,
    Registration,
    RunAuthorization,
    RunManifest,
    StorageRef,
    registration_id,
)
from starboard_core.engagement.registry import ensure_registry, list_registrations
from starboard_core.engagement.run_id import is_run_id
from starboard_core.engagement.sink import DEFAULT_MAX_BYTES
from starboard_core.ports.engagement_storage import (
    EngagementStoragePort,
    StorageAuthError,
    StorageError,
    StorageObject,
)

__all__ = [
    "RECORD_KINDS",
    "PriorRecords",
    "Unavailable",
    "load_prior",
    "load_prior_local",
    "parse_records",
    "read_ref_json",
]

RECORD_KINDS = ("observations", "findings", "cases", "actions")
_FINDINGS_PATH = "analysis/findings.json"
#: A run that committed this is a recurrence (delta) prior (``run recur``).
_MANIFEST_PATH = "findings-manifest.json"
_CASES_PATH = "analysis/cases.json"
_ACTIONS_PATH = "analysis/actions.json"
_IMPORTED_REASON = "imported_local registration carries observations only"
_LOCAL_AUTHORIZATION = f"analysis/{DESCRIPTOR_NAME}"
_LOCAL_PREFLIGHT = "analysis/storage-preflight.json"
_REASON_MAX = 300
_PARSERS: dict[str, Callable[[Any], Any]] = {
    "observations": Observation.from_dict,
    "findings": FindingRecord.from_dict,
    "cases": Case.from_dict,
    "actions": Action.from_dict,
    "plays": Play.from_dict,
}
_Rank = tuple[str, ...]


@dataclass(frozen=True)
class Unavailable:
    """Prior records that could not be read (satisfies ``history.UnavailableView``).

    Attributes:
        registration: The registration, when one was parsed.
        object_id: The registration object, run folder or local run directory.
        reason: Why nothing (or not everything) was read.
        status: ``history_unavailable`` or ``corrupt``.
        records: The record kinds this entry hides; a baseline gap only when it
            includes ``observations``.
    """

    registration: Registration | None
    object_id: str
    reason: str
    status: str = "history_unavailable"
    records: tuple[str, ...] = RECORD_KINDS


@dataclass(frozen=True)
class PriorRecords:
    """One workspace's prior records, resolved to one copy each.

    Attributes:
        observations: Baseline candidates, sorted by ``(run_id, observation_id)``.
        findings: Latest finding per key (case findings included), by ``finding_id``.
        cases: Latest case copy, by ``case_id``.
        actions: Latest action copy of the loaded findings, by ``action_id``.
        unavailable: What could not be read.
        run_manifests: ``run_id -> (run_folder_id, latest RunManifest)`` of every
            prior Drive run folder read (its ``refs`` locate the run's artifacts
            without listing the folder).
    """

    observations: tuple[Candidate, ...] = ()
    findings: tuple[FindingRecord, ...] = ()
    cases: tuple[Case, ...] = ()
    actions: tuple[Action, ...] = ()
    unavailable: tuple[Unavailable, ...] = ()
    run_manifests: Mapping[str, tuple[str, RunManifest]] = field(default_factory=dict)


def _clip(reason: str) -> str:
    return reason[:_REASON_MAX]


def parse_records(raw: Any, kind: str) -> list[Any]:
    """Parse one record set (``observations``, ``findings``, ``cases``, ``actions``
    or ``plays``), bare or wrapped as ``{"<kind>": [...]}``.

    Raises:
        ValueError: ``raw`` is not a record list, or an item fails ``from_dict``.
    """
    items = raw.get(kind) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(f"{kind} is not a JSON list")
    return [_PARSERS[kind](i) for i in items]


def read_ref_json(storage: EngagementStoragePort, ref: StorageRef) -> Any:
    """The JSON behind a committed ``StorageRef``, verified against its md5/size."""
    obj = StorageObject(
        id=ref.object_id,
        name=ref.path,
        mime_type=ref.mime_type,
        size=ref.size,
        md5=ref.md5,
        revision=ref.revision,
    )
    data = read_object(storage, obj, max_bytes=DEFAULT_MAX_BYTES, revision=ref.revision)
    return json.loads(data)


@dataclass
class _Loader:
    """Accumulates records of one account workspace, filtering and resolving copies."""

    account_key: str
    workspace_id: str | None
    kinds: tuple[str, ...] = RECORD_KINDS
    observations: dict[tuple[str, str], tuple[Candidate, _Rank]] = field(
        default_factory=dict
    )
    findings: dict[str, tuple[FindingRecord, tuple[int, _Rank]]] = field(
        default_factory=dict
    )
    cases: dict[str, tuple[Case, tuple[int, _Rank]]] = field(default_factory=dict)
    manifests: dict[str, tuple[str, RunManifest]] = field(default_factory=dict)
    actions: dict[str, tuple[Action, tuple[int, _Rank]]] = field(default_factory=dict)
    unavailable: list[Unavailable] = field(default_factory=list)

    def _scoped(self, account_key: str, workspace_id: str) -> bool:
        return account_key == self.account_key and (
            self.workspace_id is None or workspace_id == self.workspace_id
        )

    def add(
        self,
        kind: str,
        items: Sequence[Any],
        revision: int,
        reg_id: str,
        rank: _Rank,
        *,
        task: str | None = None,
        manifest: bool | None = None,
    ) -> None:
        for item in items:
            if kind == "observations":
                if self._scoped(item.account_key, item.workspace_id):
                    ident = (item.run_id, item.observation_id)
                    held_o = self.observations.get(ident)
                    if held_o is None or revision > held_o[0].committed_revision:
                        self.observations[ident] = (
                            Candidate(item, revision, reg_id, task or None, manifest),
                            rank,
                        )
            elif kind == "findings":
                if self._scoped(item.account_key, item.workspace_id):
                    _keep(self.findings, item.finding_key, item, (item.revision, rank))
            elif kind == "cases":
                if self._scoped(item.account_key, item.workspace_id):
                    _keep(
                        self.cases,
                        item.case_id,
                        item,
                        (len(item.evidence_revisions), rank),
                    )
            else:
                _keep(self.actions, item.action_id, item, (len(item.events), rank))

    def miss(
        self,
        reg: Registration | None,
        object_id: str,
        reason: str,
        *,
        status: str = "history_unavailable",
        records: tuple[str, ...] = RECORD_KINDS,
    ) -> None:
        self.unavailable.append(
            Unavailable(reg, object_id, _clip(reason), status, records)
        )

    def result(self) -> PriorRecords:
        findings = tuple(
            sorted((f for f, _ in self.findings.values()), key=_finding_id)
        )
        ids = {f.finding_id for f in findings}
        return PriorRecords(
            observations=tuple(
                c
                for _, (c, _r) in sorted(
                    self.observations.items(), key=lambda kv: kv[0]
                )
            ),
            findings=findings,
            cases=tuple(sorted((c for c, _ in self.cases.values()), key=_case_id)),
            actions=tuple(
                sorted(
                    (a for a, _ in self.actions.values() if a.finding_id in ids),
                    key=_action_id,
                )
            ),
            unavailable=tuple(self.unavailable),
            run_manifests=dict(self.manifests),
        )


def _keep(into: dict[str, tuple[Any, Any]], key: str, item: Any, rank: Any) -> None:
    held = into.get(key)
    if held is None or rank > held[1]:
        into[key] = (item, rank)


def _finding_id(f: FindingRecord) -> str:
    return f.finding_id


def _case_id(c: Case) -> str:
    return c.case_id


def _action_id(a: Action) -> str:
    return a.action_id


def _read_folder(
    storage: EngagementStoragePort,
    loader: _Loader,
    folder: str,
    reg: Registration | None,
    object_id: str,
    reg_id: str,
    run_id: str,
) -> None:
    """The latest committed manifest's records of one run folder.

    ``run_id`` comes from the descriptor the caller already checked, so it is not
    read again; only the record sets in ``loader.kinds`` are downloaded.
    """
    try:
        latest = latest_manifest(storage, folder, run_id=run_id)
    except StorageAuthError:
        raise
    except (StorageError, CommitError, ValueError) as exc:
        loader.miss(reg, object_id, f"run folder {folder} is not readable ({exc})")
        return
    if latest is None:
        return
    m, _ = latest
    loader.manifests[m.run_id] = (folder, m)
    rank = (m.committed_at, f"{m.revision:09d}")
    # A phase-2 findings_ref names findings-manifest.json: not finding records.
    refs: dict[str, Sequence[StorageRef]] = {
        "observations": m.observation_refs,
        "findings": _at(m.findings_ref, _FINDINGS_PATH),
        "cases": _at(m.cases_ref, _CASES_PATH),
        "actions": _at(m.actions_ref, _ACTIONS_PATH),
    }
    for kind in loader.kinds:
        try:
            items = [
                i
                for ref in refs[kind]
                for i in parse_records(read_ref_json(storage, ref), kind)
            ]
        except StorageAuthError:
            raise
        except (StorageError, ValueError, TypeError, KeyError) as exc:
            loader.miss(
                reg,
                object_id,
                f"{kind} of {reg_id} are not readable ({exc})",
                records=(kind,),
            )
            continue
        loader.add(
            kind,
            items,
            m.revision,
            reg_id,
            rank,
            task=m.task,
            manifest=any(r.path == _MANIFEST_PATH for r in m.refs),
        )


def _at(ref: StorageRef | None, path: str) -> tuple[StorageRef, ...]:
    return (ref,) if ref is not None and ref.path == path else ()


def _read_imported(
    storage: EngagementStoragePort, loader: _Loader, reg: Registration, object_id: str
) -> None:
    """An ``imported_local`` registration: its observation summary only (revision 1)."""
    loader.miss(reg, object_id, _IMPORTED_REASON, records=RECORD_KINDS[1:])
    ref = reg.observation_summary_ref
    if ref is None:
        return
    try:
        items = parse_records(read_ref_json(storage, ref), "observations")
    except StorageAuthError:
        raise
    except (StorageError, ValueError, TypeError, KeyError) as exc:
        loader.miss(
            reg,
            object_id,
            f"observations of {reg.registration_id} are not readable ({exc})",
            records=("observations",),
        )
        return
    loader.add(
        "observations", items, 1, reg.registration_id, (reg.registered_at,), task=reg.task
    )


def load_prior(
    storage: EngagementStoragePort,
    *,
    account_key: str,
    workspace_id: str | None,
    exclude_run_id: str,
    only_folder: str | None = None,
    shared_root_id: str | None = None,
    internal_domains: frozenset[str] = frozenset(),
    warnings: list[str] | None = None,
    kinds: Sequence[str] = RECORD_KINDS,
) -> PriorRecords:
    """Every prior record of one account workspace, from the account registry.

    Args:
        storage: The engagement storage port.
        account_key: The account; records of other accounts are ignored.
        workspace_id: The workspace; ``None`` loads every workspace of the account.
        exclude_run_id: The current run, never a prior.
        only_folder: Read this run folder only (``--prior``); an unregistered
            folder of the same account is read directly (with a warning).
        shared_root_id: Passed to ``ensure_registry``.
        internal_domains: Passed to ``ensure_registry``.
        warnings: Collects non-fatal notes.
        kinds: The record sets to read (default every kind); ``engagement history``
            reads ``("observations",)`` only. Unread kinds stay empty.

    The account folder is found by its identity tag, never created: a missing
    one is an unavailable registry. Registrations of every folder that carries
    the account identity are merged (``duplicate_account_folders:`` warning); an
    ambiguous registry level is an unavailable registry, not an error.

    Returns:
        The resolved records; registrations that are not ``ok``, unreadable run
        folders or records and ``imported_local`` entries (findings, cases and
        actions) are listed in ``unavailable``.

    Raises:
        StorageAuthError: Authentication failed.
    """
    unknown = sorted(set(kinds) - set(RECORD_KINDS))
    if unknown:
        raise ValueError(f"unknown record kinds: {unknown}")
    loader = _Loader(account_key, workspace_id, tuple(kinds))
    notes = warnings if warnings is not None else []
    views: Sequence[Any] = ()
    try:
        handles = ensure_registry(
            storage,
            account_key,
            shared_root_id=shared_root_id,
            internal_domains=internal_domains,
            warnings=notes,
            include_duplicates=True,
        )
        views = list_registrations(storage, handles, account_key=account_key)
    except StorageAuthError:
        raise
    except (StorageError, FolderResolutionError, ValueError) as exc:
        loader.miss(None, account_key, f"account registry is not readable ({exc})")
        if only_folder is None:
            return loader.result()

    listed = False
    for view in views:
        reg = view.registration
        if only_folder is not None and (
            reg is None or reg.run_folder_id != only_folder
        ):
            continue
        listed = True
        if view.status != "ok" or reg is None:
            loader.miss(reg, view.object_id, view.reason, status=view.status)
            continue
        if reg.run_id == exclude_run_id:
            continue
        if reg.kind == "imported_local":
            _read_imported(storage, loader, reg, view.object_id)
        elif reg.run_folder_id:
            _read_folder(
                storage,
                loader,
                reg.run_folder_id,
                reg,
                view.object_id,
                reg.registration_id,
                reg.run_id,  # list_registrations checked it against the descriptor
            )

    if only_folder is not None and not listed:
        _read_unregistered(storage, loader, only_folder, exclude_run_id, notes)
    return loader.result()


def _read_unregistered(
    storage: EngagementStoragePort,
    loader: _Loader,
    folder: str,
    exclude_run_id: str,
    warnings: list[str],
) -> None:
    """``--prior`` naming a folder the registry does not list: read its descriptor."""
    try:
        auth, _ = read_descriptor(storage, folder)
    except StorageAuthError:
        raise
    except (StorageError, CommitError, ValueError) as exc:
        loader.miss(None, folder, f"{folder} is not a readable run folder ({exc})")
        return
    owner = (
        auth.drive.account_key
        if auth.drive is not None
        else auth.authorized_scope.get("account_key")
    )
    if owner != loader.account_key:
        loader.miss(None, folder, f"{folder} belongs to another account")
        return
    if auth.run_id == exclude_run_id:
        return
    warnings.append(f"{folder} is not in the account registry; read it directly")
    _read_folder(
        storage, loader, folder, None, folder, registration_id(auth.run_id), auth.run_id
    )


def load_prior_local(
    case_roots: Sequence[Path],
    *,
    account_key: str,
    workspace_id: str | None,
    exclude_run_id: str,
    warnings: list[str] | None = None,
) -> PriorRecords:
    """:func:`load_prior` over D-20 local case roots ``<case_root>/<run_id>/analysis/``.

    The caller passes every ``<task>/<task-name>`` case root of the account root
    (D4-16), so a sibling task's records count as Drive's account registry does.
    Only a run dir whose ``analysis/run-authorization.json`` names ``account_key`` is
    read; a run of another account (two accounts can share a display-name slug), or
    one whose authorization is unreadable, is skipped silently -- no record, no
    :class:`Unavailable` entry. Symlinked run dirs are not followed. Each run dir
    counts as committed revision 1 of ``reg_<run_id>``; ties go to the later run date,
    then the later preflight ``created_at``, then the later run ID. A missing case
    root or record file is no record; an unreadable case root is a ``warnings`` note;
    an unreadable record file of an owned run is an :class:`Unavailable` entry for
    that kind.
    """
    loader = _Loader(account_key, workspace_id)
    notes = warnings if warnings is not None else []
    owned: list[tuple[_Rank, Path, str]] = []
    for root in case_roots:
        for run_dir in _local_run_dirs(root, notes):
            name = run_dir.name
            if not is_run_id(name) or name == exclude_run_id:
                continue
            owner, task = _local_owner(run_dir)
            if owner != account_key:
                continue
            owned.append(
                ((name.split("_", 1)[0], _local_created_at(run_dir), name), run_dir, task)
            )
    for rank, run_dir, task in sorted(owned):
        name = run_dir.name
        manifest = (run_dir / _MANIFEST_PATH).is_file()
        for kind in RECORD_KINDS:
            path = run_dir / "analysis" / f"{kind}.json"
            try:
                items = parse_records(
                    json.loads(path.read_text(encoding="utf-8")), kind
                )
            except FileNotFoundError:
                continue
            except (OSError, ValueError, TypeError, KeyError) as exc:
                loader.miss(
                    None,
                    name,
                    f"{kind} of {name} are not readable ({exc})",
                    records=(kind,),
                )
                continue
            loader.add(
                kind, items, 1, registration_id(name), rank, task=task, manifest=manifest
            )
    return loader.result()


def _local_run_dirs(root: Path, notes: list[str]) -> list[Path]:
    """The real (not symlinked) subdirectories of a case root; an unreadable case root
    is a note and no run dirs, a missing one is no run dirs."""
    try:
        with os.scandir(root) as entries:
            return [Path(e.path) for e in entries if e.is_dir(follow_symlinks=False)]
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError as exc:
        notes.append(
            f"prior case root {root} is not readable ({exc.strerror or exc}); skipped"
        )
        return []


def _local_owner(run_dir: Path) -> tuple[str | None, str]:
    """``(account key, task)`` of a local run dir's own run authorization, else
    ``(None, "")``."""
    try:
        auth = RunAuthorization.from_dict(
            json.loads((run_dir / _LOCAL_AUTHORIZATION).read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None, ""
    if auth.drive is not None:
        return auth.drive.account_key, auth.intent
    return str(auth.authorized_scope.get("account_key") or auth.account.id), auth.intent


def _local_created_at(run_dir: Path) -> str:
    """The run's preflight ``created_at`` (bare or ``data``-wrapped), else ``""``."""
    try:
        raw = json.loads((run_dir / _LOCAL_PREFLIGHT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    pre = raw.get("data", raw) if isinstance(raw, dict) else None
    created = pre.get("created_at") if isinstance(pre, dict) else None
    return created if isinstance(created, str) else ""
