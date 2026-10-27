# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-descriptor loaders and storage gating for the ``starboard_x`` writers.

Shared by ``python -m starboard_x.discovery``, ``python -m starboard_x.review`` and
``starboard --discover`` so every entry point reads the authorized scope and maps
storage refusals the same way. Two descriptor forms:

* :func:`load_authorized_workspace_ids`: a **local** run directory (public path).
* :func:`load_authorized_workspace_ids_from_run_folder`: the run folder in **Drive**
  (``--run-folder``). Same checks, no local file.

Also home to :func:`storage_refusals` (storage refusals leave with exit code 2 and
their ``code``) and :func:`bounded_stdout` (the covered-run stdout budget).
Standard library plus the kernel engagement package.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from starboard_core.engagement.commit import CommitError, read_descriptor
from starboard_core.engagement.enforce import LocalStorageRefused
from starboard_core.engagement.identity import ProfileMismatch, run_profile
from starboard_core.engagement.policy import StorageDecision, StoragePolicy
from starboard_core.engagement.records import IdentityCheck
from starboard_core.engagement.sink import LocalDirSink, StorageUnavailableError
from starboard_core.engagement.staging import read_all
from starboard_core.engagement.stdout_budget import DEFAULT_MAX_BYTES, bound
from starboard_core.ports.engagement_storage import EngagementStoragePort, StorageError

from starboard_x._cli import BoundedData
from starboard_x.contract import ArgError, HelperError

__all__ = [
    "AUTHORIZATION_HELP",
    "AUTHORIZATION_RELPATH",
    "EXIT_STORAGE_REFUSED",
    "IDENTITY_RELPATH",
    "OVERLAY_AUTHORIZATION_REQUIRED",
    "ENVELOPE_RESERVE",
    "StorageRefusedError",
    "authorization_run_dir",
    "bounded_stdout",
    "load_authorized_workspace_ids",
    "load_authorized_workspace_ids_from_run_folder",
    "local_capture_sink",
    "resolve_run_folder_profile",
    "storage_refusals",
]

AUTHORIZATION_HELP = (
    "Run directory (reads analysis/run-authorization.json) or that file. "
    "Requires a verified analysis/identity-check.json for the same run, refuses "
    "unless the connected workspace is the verified one, and limits every "
    "workspace-grained system.* read to it."
)

#: Run descriptor location inside a run directory (``--authorization <run-dir>``).
AUTHORIZATION_RELPATH = Path("analysis") / "run-authorization.json"

#: Identity check written by ``starboard-helper engagement verify-identity``.
IDENTITY_RELPATH = Path("analysis") / "identity-check.json"

#: Usage error when an internal-overlay install runs customer discovery unscoped.
OVERLAY_AUTHORIZATION_REQUIRED = (
    "--authorization is required on an internal-overlay install: run "
    "`starboard-helper engagement preflight`, then `starboard-helper engagement "
    "verify-identity`, then `starboard-helper engagement route`, and pass "
    "--authorization <run-dir>"
)

#: Process exit code of a storage refusal (``LOCAL_STORAGE_REFUSED`` ...).
EXIT_STORAGE_REFUSED = 2

_IDENTITY_NAME = IDENTITY_RELPATH.name
_ANALYSIS_SEGMENT = IDENTITY_RELPATH.parent.name


class StorageRefusedError(HelperError):
    """A storage policy refusal; the message starts with its ``CODE:``."""

    exit_code = EXIT_STORAGE_REFUSED


@contextmanager
def storage_refusals() -> Iterator[None]:
    """Map kernel storage refusals onto the CLI exit-code contract.

    * ``LOCAL_STORAGE_REFUSED`` / ``STORAGE_UNAVAILABLE``
      -> :class:`StorageRefusedError` (exit 2, message starts with the code).
    * An invalid or missing run descriptor -> :class:`ArgError` (exit 4).
    """
    try:
        yield
    except (LocalStorageRefused, StorageUnavailableError) as exc:
        text = str(exc)
        code = getattr(exc, "code", "STORAGE_REFUSED")
        raise StorageRefusedError(text if text.startswith(code) else f"{code}: {text}") from exc
    except CommitError as exc:
        raise ArgError(f"--run-folder: {exc}") from exc


#: Bytes the envelope wraps around ``data`` when printed compact (``ok``, ``domain``,
#: ``command``, ``error``, ``meta``), reserved out of the budget.
ENVELOPE_RESERVE = 512


def bounded_stdout(
    data: Mapping[str, Any],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> BoundedData:
    """``data`` bounded so the printed envelope fits ``max_bytes``.

    The result is a :class:`~starboard_x._cli.BoundedData`, which ``_cli.emit`` prints
    as compact JSON: the form ``bound`` measures, plus a fixed envelope reserve.
    """
    return BoundedData(bound(data, max_bytes=max_bytes - ENVELOPE_RESERVE))


def _run_dir(location: str) -> Path:
    """Resolve ``--authorization`` (run dir or its descriptor file) to the run dir."""
    path = Path(location)
    if path.is_dir():
        return path
    if path.name == AUTHORIZATION_RELPATH.name and path.parent.name == "analysis":
        return path.parent.parent
    raise ArgError(
        f"--authorization: expected a run directory or "
        f"<run-dir>/{AUTHORIZATION_RELPATH.as_posix()}, got {path}"
    )


authorization_run_dir = _run_dir


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ArgError(f"--authorization: {what} not found: {path}") from None
    except (OSError, ValueError) as exc:
        raise ArgError(f"--authorization: cannot read {what} {path}: {exc}") from exc


_LOCAL_CAPTURE = StorageDecision(
    StoragePolicy.LOCAL, False, "local run directory (resumable discovery capture)"
)


def local_capture_sink(location: str) -> LocalDirSink:
    """The local run directory of ``--authorization``, as a discovery capture sink.

    The capture record goes to ``<run-dir>/capture/``, keyed by the descriptor's
    ``run_id``, so a budget-stopped local capture resumes like a ``--run-folder`` one.

    Raises:
        ArgError: the run descriptor is missing, unreadable or has no ``run_id``.
    """
    run_dir = _run_dir(location)
    path = run_dir / AUTHORIZATION_RELPATH
    doc = _read_json(path, "run descriptor")
    run_id = doc.get("run_id") if isinstance(doc, dict) else None
    if not isinstance(run_id, str) or not run_id:
        raise ArgError(f"--authorization: {path} has no run_id")
    return LocalDirSink(run_dir, decision=_LOCAL_CAPTURE, run_id=run_id)


def load_authorized_workspace_ids(location: str) -> tuple[str, ...]:
    """Read the authorized workspace ID bound to a verified identity check.

    ``location`` is a run directory or its ``analysis/run-authorization.json``.
    The run's ``analysis/identity-check.json`` must be verified, belong to the
    same run, and name exactly the one workspace the descriptor authorizes.

    Raises:
        ArgError: the descriptor or identity check is missing or invalid, the
            identity is not verified or is for another run, or
            ``authorized_scope.workspace_ids`` is not exactly the verified
            workspace. Never falls back to an unscoped run.
    """
    run_dir = _run_dir(location)
    path = run_dir / AUTHORIZATION_RELPATH
    doc = _read_json(path, "run descriptor")
    scope = doc.get("authorized_scope") if isinstance(doc, dict) else None
    if not isinstance(scope, dict):
        raise ArgError(f"--authorization: {path} has no authorized_scope object")
    ids = scope.get("workspace_ids")
    if (
        not isinstance(ids, list)
        or not ids
        or not all(isinstance(i, str) and i.isascii() and i.isdigit() for i in ids)
    ):
        raise ArgError(
            f"--authorization: {path} authorized_scope.workspace_ids must be a "
            f"non-empty list of digit strings, got {ids!r}"
        )
    run_id = doc.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ArgError(f"--authorization: {path} has no run_id")

    identity_path = run_dir / IDENTITY_RELPATH
    if not identity_path.is_file():
        raise ArgError(
            f"--authorization: identity check not found: {identity_path} "
            "(run `starboard-helper engagement verify-identity` first)"
        )
    raw = _read_json(identity_path, "identity check")
    try:
        if not isinstance(raw, dict):
            raise TypeError("not a JSON object")
        check = IdentityCheck.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise ArgError(
            f"--authorization: invalid identity check {identity_path}: {exc}"
        ) from exc
    if check.status != "verified":
        raise ArgError(
            f"--authorization: identity check status is {check.status!r}, not "
            f"'verified': {'; '.join(check.reasons)}"
        )
    if check.run_id != run_id:
        raise ArgError(
            f"--authorization: identity check is for run {check.run_id!r}, "
            f"not this run {run_id!r}"
        )
    verified = check.observed_workspace_id
    if ids != [verified]:
        raise ArgError(
            f"--authorization: authorized_scope.workspace_ids must be exactly the "
            f"verified workspace [{verified!r}], got {ids!r}"
        )
    return (verified,)


def _identity_in_run(
    storage: EngagementStoragePort, run_folder_id: str, staging_id: str | None
) -> tuple[bytes, str]:
    """The identity check's bytes and where they were found.

    ``<run folder>/analysis/identity-check.json`` first (the route copies the check
    next to the descriptor), else ``identity-check.json`` in the restricted staging
    folder the descriptor names.
    """
    candidates: list[tuple[str, str]] = []
    for analysis in storage.list_children(
        run_folder_id, name=_ANALYSIS_SEGMENT, folders_only=True
    ):
        candidates.append((analysis.id, f"{_ANALYSIS_SEGMENT}/{_IDENTITY_NAME}"))
    if staging_id:
        candidates.append((staging_id, f"staging/{_IDENTITY_NAME}"))
    for parent, where in candidates:
        found = [
            c
            for c in storage.list_children(parent, name=_IDENTITY_NAME)
            if not c.is_folder
        ]
        if len(found) > 1:
            raise ArgError(
                f"--run-folder: {len(found)} {where} objects in run folder "
                f"{run_folder_id}; reconcile in Drive (ids: "
                f"{', '.join(c.id for c in found)})"
            )
        if found:
            return read_all(storage, found[0].id), where
    raise ArgError(
        f"--run-folder: identity check not found in run folder {run_folder_id} "
        "(run `starboard-helper engagement verify-identity` and `route` first)"
    )


def load_authorized_workspace_ids_from_run_folder(
    storage: EngagementStoragePort, run_folder_id: str
) -> tuple[str, ...]:
    """Read the authorized workspace ID of a Drive run, bound to its identity check.

    The Drive form of :func:`load_authorized_workspace_ids`: the immutable run
    descriptor comes from ``read_descriptor`` and the verified identity check from
    the run folder in Drive; nothing is read from local disk. Same checks as the
    local form: the descriptor belongs to this run folder and names a non-empty list
    of digit-string workspace IDs; the identity check is verified, is for the same
    run, and observed exactly the one workspace the descriptor authorizes.

    Raises:
        ArgError: the descriptor or identity check is missing or invalid, the
            identity is not verified or is for another run, or
            ``authorized_scope.workspace_ids`` is not exactly the verified
            workspace. Never falls back to an unscoped run.
    """
    where = f"--run-folder {run_folder_id}"
    try:
        auth, _ = read_descriptor(storage, run_folder_id)
    except CommitError as exc:
        raise ArgError(f"{where}: {exc}") from exc
    if auth.drive is None or auth.drive.run_folder_id != run_folder_id:
        raise ArgError(
            f"{where}: the run descriptor is not bound to this run folder "
            f"(it names {auth.drive.run_folder_id if auth.drive else 'none'})"
        )
    ids = auth.authorized_scope.get("workspace_ids")
    if (
        not isinstance(ids, list | tuple)
        or not ids
        or not all(isinstance(i, str) and i.isascii() and i.isdigit() for i in ids)
    ):
        raise ArgError(
            f"{where}: authorized_scope.workspace_ids must be a non-empty list of "
            f"digit strings, got {ids!r}"
        )

    try:
        raw_bytes, found_in = _identity_in_run(
            storage, run_folder_id, auth.drive.preflight_folder_id
        )
    except StorageError as exc:
        raise ArgError(f"{where}: cannot read the identity check: {exc}") from exc
    try:
        raw = json.loads(raw_bytes)
        if not isinstance(raw, dict):
            raise TypeError("not a JSON object")
        check = IdentityCheck.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise ArgError(f"{where}: invalid identity check ({found_in}): {exc}") from exc
    if check.status != "verified":
        raise ArgError(
            f"{where}: identity check status is {check.status!r}, not 'verified': "
            f"{'; '.join(check.reasons)}"
        )
    if check.run_id != auth.run_id:
        raise ArgError(
            f"{where}: identity check is for run {check.run_id!r}, not this run "
            f"{auth.run_id!r}"
        )
    verified = check.observed_workspace_id
    if list(ids) != [verified]:
        raise ArgError(
            f"{where}: authorized_scope.workspace_ids must be exactly the verified "
            f"workspace [{verified!r}], got {list(ids)!r}"
        )
    return (verified,)


def resolve_run_folder_profile(
    storage: EngagementStoragePort,
    run_folder_id: str,
    profile: str | None,
    host: str | None = None,
) -> str | None:
    """The ``--profile`` a ``--run-folder`` workspace read must use.

    The run's verified identity reads: an omitted ``profile`` becomes the profile
    ``engagement verify-identity`` recorded, and another profile, or a ``--host``
    on a profile-verified run, is refused. Unverified (declared) runs return
    ``profile`` unchanged.

    Raises:
        StorageRefusedError: ``PROFILE_MISMATCH`` (exit 2).
        ArgError: the run descriptor cannot be read.
    """
    try:
        auth, _ = read_descriptor(storage, run_folder_id)
    except CommitError as exc:
        raise ArgError(f"--run-folder {run_folder_id}: {exc}") from exc
    try:
        resolved = run_profile(auth, profile)
    except ProfileMismatch as exc:
        raise StorageRefusedError(str(exc)) from exc
    if host and resolved and not profile:
        raise StorageRefusedError(
            f"PROFILE_MISMATCH: run {auth.run_id} was verified with --profile "
            f"{resolved!r}; drop --host {host!r} (reads use the verified profile)"
        )
    return resolved
