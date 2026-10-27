"""Run setup: ``preflight``, ``verify-identity`` and ``route``."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starboard_skills.helpers.contract import (
    ApiError,
    ArgError,
)
from starboard_skills.helpers.engagement import _envelope
from starboard_skills.helpers.engagement._envelope import (
    _APPROVED_DESTINATION,
    _TASK_NAME_RE,
    _TICKET_FIELDS,
    _TICKET_SCHEMA_VERSION,
    _WS_TASK_NAME_RE,
    ARTIFACT_PROPERTY,
    AUTHORIZATION_RECORD,
    DEFAULT_REPORTS_ROOT,
    IDENTITY_RECORD,
    METHODOLOGY_VERSION,
    PREFLIGHT_RECORD,
    PROVISIONAL_SOURCES,
    RUN_FOLDER_PROPERTY,
    SHARED_REGISTRY_ENV,
    SOURCE_MODES,
    STAGED_IDENTITY,
    STAGED_PREFLIGHT,
    TASKS,
    IdentityMismatch,
    PrincipalKind,
    WorkspaceApiError,
    WorkspaceAuthError,
    _ctx,
    _storage_errors,
)
from starboard_skills.helpers.engagement._runs import (
    _check_run_id,
    _close,
    _decision_of,
    _drive_storage,
    _guard,
    _internal_domains,
    _local_run_dir,
    _open_staging,
    _put_record,
    _read_staged,
    _same_sf_id,
    _storage_ref,
    _write_json,
)

if TYPE_CHECKING:  # kernel types only; imported lazily at runtime
    from starboard_core.engagement.policy import SourceMode, StorageDecision
    from starboard_core.ports.engagement_storage import EngagementStoragePort


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #
def local_segment(name: str) -> str:
    """Filesystem-safe, lowercase path segment for a display name (``LM Arena`` → ``lm-arena``)."""
    seg = re.sub(r"[^a-z0-9._]+", "-", name.strip().lower()).strip("-.")
    if not seg:
        raise ArgError(f"{name!r} has no usable characters for a path segment")
    return seg


_WORKSPACE_TASK_NAME_RE = re.compile(r"^workspace-(\d+)$")


def _check_task_name(task_name: str) -> None:
    spelled_out = _WORKSPACE_TASK_NAME_RE.fullmatch(task_name or "")
    if spelled_out:
        raise ArgError(
            f"--task-name {task_name!r}: a workspace case is named "
            f"ws-<workspace_id>; use --task-name ws-{spelled_out.group(1)}"
        )
    if not _TASK_NAME_RE.fullmatch(task_name or ""):
        raise ArgError(
            "--task-name must be a stable case name such as ws-<workspace_id>, job-<id>, "
            "query-<id> or pipeline-<id>, or the searched scope when the target is not "
            "known yet (queries-<workspace_id>, jobs-<workspace_id>, "
            f"warehouse-<warehouse_id>); no dates, spaces or slashes; got {task_name!r}"
        )


def _check_internal_workspace_id(
    args: argparse.Namespace, source_mode: SourceMode
) -> str | None:
    """D4-15: the one workspace an ``internal_only`` run declares at preflight.

    Required for ``internal_only``: without it the run's scope is empty and every
    internal capture, verify and case on it is refused (``INTERNAL_SCOPE_REFUSED``),
    so preflight refuses before any run is opened (live customer run 2026-10-21).
    """
    raw = getattr(args, "internal_workspace_id", None)
    if raw is None:
        if source_mode.value == "internal_only":
            raise ArgError(
                "--internal-workspace-id <workspace_id> is required for an internal_only "
                "run: it declares the run's one workspace, and a run without it has an "
                "empty scope, so every internal capture is refused (INTERNAL_SCOPE_REFUSED)"
            )
        return None
    if source_mode.value != "internal_only":
        raise ArgError(
            "--internal-workspace-id declares the scope of an internal_only run; "
            f"a {source_mode.value} run is scoped by verify-identity instead"
        )
    value = str(raw).strip()
    if not value.isdigit():
        raise ArgError(
            f"--internal-workspace-id must be a numeric workspace id; got {raw!r}"
        )
    return value


def _new_preflight(
    args: argparse.Namespace, run_id: str | None = None
) -> tuple[dict[str, Any], Any]:
    """Validate the flags and build a new preflight record (no I/O)."""
    from starboard_core.engagement.enforce import refuse_local  # lazy – kernel dep
    from starboard_core.engagement.policy import (
        LOCAL_FILE_INTAKE_GUIDANCE,
        SourceMode,
        StoragePolicy,
        classify_storage,
        local_file_intake_allowed,
    )
    from starboard_core.engagement.run_id import idempotency_key, new_run_id
    from starboard_core.engagement.sink import LocalStorageRefused

    try:
        source_mode = SourceMode(args.source_mode)
    except ValueError as exc:
        raise ArgError(
            f"--source-mode must be one of {', '.join(SOURCE_MODES)}; got {args.source_mode!r}"
        ) from exc
    if args.task not in TASKS:
        raise ArgError(f"--task must be one of {', '.join(TASKS)}; got {args.task!r}")
    _check_task_name(args.task_name)
    internal_ws = _check_internal_workspace_id(args, source_mode)
    account_key = (args.account_key or "").strip()
    if not account_key:
        raise ArgError("--account-key is required (the stable account identity)")
    account_name = (args.account_name or "").strip()
    if not account_name:
        raise ArgError("--account-name is required (the account's display name)")

    overlay = _envelope._detect_overlay()
    try:
        decision = classify_storage(source_mode, overlay, requested=args.storage)
    except ValueError as exc:
        raise ArgError(f"--storage: {exc}") from exc
    covered = decision.policy is StoragePolicy.DRIVE_REQUIRED
    if covered and args.storage == "local":
        raise LocalStorageRefused(
            decision.refusal
            or f"--storage local is refused on a covered run ({decision.reason})",
            flag="--storage",
        )
    refuse_local(decision, run_dir=args.run_dir, reports_root=args.reports_root)
    if args.unattended and decision.refusal:
        raise ArgError(
            f"unattended run: the operator storage override was refused "
            f"({decision.refusal}); {_APPROVED_DESTINATION}"
        )
    local = decision.policy in (StoragePolicy.LOCAL, StoragePolicy.INTERNAL_ONLY_LOCAL)
    if not local and (args.run_dir or args.reports_root):
        raise ArgError(
            "--run-dir and --reports-root are for local runs; this run stores to Drive"
        )
    intake_ok = local_file_intake_allowed(overlay)
    created = datetime.now(UTC)
    run_id = run_id or new_run_id(created)
    data: dict[str, Any] = {
        "run_id": run_id,
        "created_at": created.isoformat(timespec="seconds"),
        "task": args.task,
        "task_name": args.task_name,
        "account_key": account_key,
        "account_name": account_name,
        "source_mode": source_mode.value,
        "internal_workspace_id": internal_ws,
        "overlay": {"enabled": overlay.enabled, "reasons": list(overlay.reasons)},
        "decision": {
            "policy": decision.policy.value,
            "drive_required": decision.drive_required,
            "reason": decision.reason,
            "refusal": decision.refusal,
        },
        "storage_decision": decision.policy.value,
        "covered": covered,
        "destination": "local" if local else "drive",
        "run_dir": None,
        "case_root": None,
        "local_run_dir": None,
        "drive_path": None
        if local
        else f"My Drive/starboard/{account_name}/{args.task}/{args.task_name}/{run_id}",
        "local_file_intake_allowed": intake_ok,
        "local_file_intake_guidance": None if intake_ok else LOCAL_FILE_INTAKE_GUIDANCE,
        "idempotency_key": idempotency_key(run_id, "run"),
        "unattended": bool(args.unattended),
        "staging_folder_id": None,
        "staging_link": None,
        "drive_principal": None,
    }
    return data, decision


def _account_key_warnings(account_key: str, account_name: str) -> list[str]:
    """A warning when ``--account-key`` looks like a display name, not a stable key.

    The key is the account's identity in Drive (``account:<key>``) and never
    changes mid-run; a name-like key splits one account across folders.
    """
    name_like = (
        account_key.casefold() == account_name.casefold()
        or any(ch.isspace() for ch in account_key)
        or not any(ch.isdigit() for ch in account_key)
    )
    if not name_like:
        return []
    return [
        f"account_key_looks_like_name: --account-key {account_key!r} looks like a "
        "display name; the key is the stable account identity (the operator's "
        "account key, else the workspace id) and never changes mid-run. If it is "
        "wrong, start over with `engagement preflight --account-key <key>`."
    ]


def cmd_preflight(args: argparse.Namespace) -> dict[str, Any]:
    ctx = _ctx(args)
    ctx["stage"] = "preflight"
    if getattr(args, "resume_run_id", None):
        return _resume_preflight(args)
    data, decision = _new_preflight(args)
    if data["destination"] == "local":
        ctx["run_id"] = data["run_id"]
        case_root = (
            Path(args.reports_root or DEFAULT_REPORTS_ROOT)
            / local_segment(data["account_name"])
            / args.task
            / args.task_name
        )
        run_dir = Path(args.run_dir) if args.run_dir else case_root / data["run_id"]
        data.update(
            run_dir=run_dir.as_posix(),
            case_root=case_root.as_posix(),
            local_run_dir=run_dir.as_posix(),
        )
        record = run_dir / PREFLIGHT_RECORD
        if record.exists():
            raise ArgError(
                f"{run_dir} already holds a preflight record; a new run needs a new run dir"
            )
        _write_json(record, data)
        return {
            **data,
            "preflight_record": record.as_posix(),
            "resumed": False,
            "warnings": _account_key_warnings(data["account_key"], data["account_name"]),
        }
    # Load the adapter before the run ID is reported: a missing adapter stages
    # nothing, so there is no run to resume (re-run preflight once it is installed).
    storage = _envelope._make_storage()
    try:
        # Prove Drive sign-in before the run ID is reported too: a token failure
        # here has staged nothing, so the fix is to sign in and re-run preflight.
        with _storage_errors(data["unattended"]):
            storage.principal_id()
        ctx["run_id"] = data["run_id"]
        with _storage_errors(data["unattended"], data["run_id"]):
            _stage_preflight(storage, data, decision, staging=None)
    finally:
        _close(storage)
    return {
        **data,
        "preflight_record": None,
        "resumed": False,
        "warnings": _account_key_warnings(data["account_key"], data["account_name"]),
    }


def _stage_preflight(
    storage: EngagementStoragePort,
    data: dict[str, Any],
    decision: StorageDecision,
    staging: Any,
) -> None:
    """Ensure the restricted staging folder and stage the preflight record in it."""
    from starboard_core.engagement.staging import (  # lazy – kernel dep
        ensure_staging,
        put_json,
    )

    with _guard(decision):
        staging = staging or ensure_staging(storage, data["run_id"])
        data["staging_folder_id"] = staging.folder.id
        data["staging_link"] = staging.link
        data["drive_principal"] = storage.principal_id()
        put_json(
            storage,
            staging.folder.id,
            STAGED_PREFLIGHT,
            data,
            properties={ARTIFACT_PROPERTY: f"preflight:{data['run_id']}"},
        )


def _resume_preflight(args: argparse.Namespace) -> dict[str, Any]:
    ctx = _ctx(args)
    if args.run_dir or args.reports_root:
        raise ArgError(
            "--resume-run-id resumes a Drive run; drop --run-dir and --reports-root"
        )
    run_id = _check_run_id(args.resume_run_id, "--resume-run-id")
    ctx["run_id"] = run_id
    storage = _envelope._make_storage()
    try:
        with _storage_errors(bool(args.unattended), run_id):
            staging, data = _open_staging(storage, run_id, require_record=False)
            if data is None:
                # An earlier staging write failed: rebuild the record from the flags.
                data, decision = _new_preflight(args, run_id=run_id)
                if data["destination"] != "drive":
                    raise ArgError(
                        "--resume-run-id resumes a Drive run; these flags give a local run"
                    )
            else:
                if args.storage:
                    raise ArgError(
                        "--resume-run-id reuses the recorded storage decision; drop --storage"
                    )
                for field in (
                    "source_mode",
                    "task",
                    "task_name",
                    "account_key",
                    "account_name",
                    "internal_workspace_id",
                ):
                    given = (getattr(args, field, None) or "").strip()
                    if given and given != data.get(field):
                        raise ArgError(
                            f"--{field.replace('_', '-')} {given!r} disagrees with the run "
                            f"being resumed ({data.get(field)!r}); drop the flag or start "
                            "a new run"
                        )
                data = {
                    k: v
                    for k, v in data.items()
                    if k not in ("preflight_record", "resumed")
                }
                if args.unattended:
                    data["unattended"] = True
                decision = _decision_of(data)
            _stage_preflight(storage, data, decision, staging)
    finally:
        _close(storage)
    return {**data, "preflight_record": None, "resumed": True}


def _load_local_preflight(
    source: str, flag: str = "--run-dir"
) -> tuple[dict[str, Any], Path]:
    """Read a local preflight record (the file, or a run dir holding one) and its run dir."""
    path = Path(source)
    if path.is_dir():
        path = path / PREFLIGHT_RECORD
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArgError(f"{flag}: cannot read {path}: {exc}") from exc
    data = payload.get("data", payload) if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("run_id"):
        raise ArgError(f"{flag}: {path} is not an engagement preflight record")
    if data.get("destination") != "local":
        raise ArgError(
            f"{flag}: run {data['run_id']} stores to Drive; pass --run-id {data['run_id']}"
        )
    data = {k: v for k, v in data.items() if k not in ("preflight_record", "resumed")}
    _refuse_stale_local(data, flag)
    return data, path.parent.parent


def _refuse_stale_local(pre: Mapping[str, Any], flag: str) -> None:
    """Re-decide a local run's storage now: a record does not outlive the policy.

    A local record written on a public install (or edited) does not exempt a customer
    run once the overlay is on: that run is covered, so the local write is refused.
    """
    from starboard_core.engagement.policy import (  # lazy – kernel dep
        SourceMode,
        classify_storage,
    )
    from starboard_core.engagement.sink import LocalStorageRefused

    try:
        mode = SourceMode(str(pre.get("source_mode") or ""))
    except ValueError as exc:
        raise ArgError(
            f"{flag}: the preflight record has no valid source mode"
        ) from exc
    decision = classify_storage(mode, _envelope._detect_overlay(), requested="local")
    if decision.drive_required:
        raise LocalStorageRefused(
            f"run {pre['run_id']} is a local run, but this install requires Drive "
            f"({decision.refusal or decision.reason}); start a new run with "
            "`engagement preflight`",
            flag=flag,
        )


def _one_run(args: argparse.Namespace) -> None:
    if bool(getattr(args, "run_id", None)) == bool(getattr(args, "run_dir", None)):
        raise ArgError(
            "pass exactly one of --run-id or --run-dir (a local run kept outside "
            f"{DEFAULT_REPORTS_ROOT}/)"
        )


# --------------------------------------------------------------------------- #
# verify-identity
# --------------------------------------------------------------------------- #
def _expected_workspace_id(flag: str | None, task_name: str) -> str:
    match = _WS_TASK_NAME_RE.fullmatch(task_name or "")
    if flag:
        flag = flag.strip()
        if not flag.isdigit():
            raise ArgError(
                f"--expected-workspace-id must be a numeric workspace ID; got {flag!r}"
            )
        if match and match.group(1) != flag:
            raise ArgError(
                f"--expected-workspace-id {flag} disagrees with the task name {task_name!r}"
            )
        return flag
    if match:
        return match.group(1)
    raise ArgError(
        f"no expected workspace ID: the task name {task_name!r} is not ws-<id>; pass "
        "--expected-workspace-id"
    )


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _principal_kind(me: Mapping[str, Any]) -> PrincipalKind:
    """``service_principal`` or ``user`` from the SCIM ``Me`` body.

    A service principal is a body with a ``ServicePrincipal`` SCIM schema, an
    ``applicationId``, or a UUID ``userName`` and no emails; anything else is a user.
    """
    schemas = me.get("schemas") or []
    if any("ServicePrincipal" in str(s) for s in schemas) or me.get("applicationId"):
        return "service_principal"
    if not me.get("emails") and _is_uuid(me.get("userName")):
        return "service_principal"
    return "user"


def _observe_identity(client: Any) -> tuple[str, str, str, PrincipalKind]:
    """Return ``(workspace_id, host, principal_id, principal_kind)`` from one read-only call."""
    from databricks.sdk.errors import PermissionDenied, Unauthenticated
    from starboard_core.engagement.identity import (  # lazy – kernel dep
        ORG_ID_HEADER,
        SCIM_ME_PATH,
        parse_org_id,
    )

    try:
        me = client.api_client.do("GET", SCIM_ME_PATH, response_headers=[ORG_ID_HEADER])
    except (Unauthenticated, PermissionDenied) as exc:
        raise WorkspaceAuthError(f"Databricks authentication failed: {exc}") from exc
    except Exception as exc:  # any SDK or transport failure is a workspace failure
        raise WorkspaceApiError(f"Databricks workspace API call failed: {exc}") from exc
    if not isinstance(me, Mapping):
        raise WorkspaceApiError("the workspace returned no current-principal record")
    try:
        workspace_id = parse_org_id(me.get(ORG_ID_HEADER))
    except ValueError as exc:
        raise WorkspaceApiError(f"{exc}; cannot prove which workspace this is") from exc
    principal_id = str(me.get("id") or "").strip()
    if not principal_id or "@" in principal_id:
        raise WorkspaceApiError("the workspace returned no opaque principal ID")
    host = getattr(getattr(client, "config", None), "host", None)
    if not host:
        raise WorkspaceApiError("the workspace client has no host")
    return workspace_id, str(host), principal_id, _principal_kind(me)


def _identity_inputs(
    args: argparse.Namespace, pre: Mapping[str, Any]
) -> tuple[str, str, str, str | None]:
    """Validate the verify-identity flags against the preflight record."""
    from starboard_core.engagement.identity import normalize_host  # lazy – kernel dep

    if pre.get("source_mode") == "internal_only":
        raise ArgError(
            "verify-identity is for customer-workspace runs; this run is internal_only"
        )
    if bool(args.profile) == bool(args.host):
        raise ArgError("pass exactly one of --profile or --host")
    recorded = (pre.get("account_key") or "").strip()
    given = (args.account_key or "").strip()
    if given and recorded and not _same_sf_id(given, recorded):
        raise ArgError(
            f"--account-key {given!r} disagrees with the preflight record ({recorded!r})"
        )
    account_key = given or recorded
    if not account_key:
        raise ArgError("--account-key is required (the provisional account key)")
    account_name = pre.get("account_name") or ""
    if args.account_name and args.account_name.strip() != account_name:
        raise ArgError(
            f"--account-name {args.account_name!r} disagrees with the preflight record "
            f"({account_name!r})"
        )
    if args.account_source not in PROVISIONAL_SOURCES:
        raise ArgError(
            f"--account-source must be one of {', '.join(PROVISIONAL_SOURCES)}; "
            f"got {args.account_source!r}"
        )
    expected_ws = _expected_workspace_id(args.workspace_id, pre.get("task_name") or "")
    try:
        expected_host = (
            None if not args.expected_host else normalize_host(args.expected_host)
        )
    except ValueError as exc:
        raise ArgError(f"--expected-host: {exc}") from exc
    return account_key, account_name, expected_ws, expected_host


def _run_identity_check(
    args: argparse.Namespace,
    pre: Mapping[str, Any],
    inputs: tuple[str, str, str, str | None],
) -> Any:
    from starboard_core.engagement.identity import check_identity  # lazy – kernel dep

    account_key, account_name, expected_ws, expected_host = inputs
    client = _envelope._make_workspace_client(args.profile, args.host)
    observed_ws, observed_host, principal_id, kind = _observe_identity(client)
    try:
        return check_identity(
            run_id=pre["run_id"],
            provisional_account_key=account_key,
            provisional_account_name=account_name,
            provisional_source=args.account_source,
            expected_workspace_id=expected_ws,
            expected_host=expected_host,
            observed_workspace_id=observed_ws,
            observed_host=observed_host,
            principal_id=principal_id,
            principal_kind=kind,
            # Recorded so later --run-folder fetches default to (and are held to)
            # the verified identity; never used to derive the expected workspace.
            workspace_profile=args.profile or None,
        )
    except ValueError as exc:
        raise ApiError(f"identity check could not be recorded: {exc}") from exc


def cmd_verify_identity(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.staging import (  # lazy – kernel dep
        put_json,
        quarantine_staging,
    )

    ctx = _ctx(args)
    ctx["stage"] = "verify-identity"
    _one_run(args)
    staging: Any = None
    record: str | None = None
    local = _local_run_dir(args)
    if local:
        pre, run_dir = _load_local_preflight(local)
        ctx["run_id"] = pre["run_id"]
        check = _run_identity_check(args, pre, _identity_inputs(args, pre))
        path = run_dir / IDENTITY_RECORD
        _write_json(path, check.to_dict())
        record = path.as_posix()
        if check.status != "verified":
            raise IdentityMismatch(
                f"identity check failed: {'; '.join(check.reasons)}. Fix --profile/--host "
                "or the expected workspace, then re-run verify-identity."
            )
    else:
        run_id = _check_run_id(args.run_id)
        ctx["run_id"] = run_id
        storage = _drive_storage(run_id)
        try:
            with _storage_errors(False, run_id):
                staging, staged = _open_staging(storage, run_id)
                assert staged is not None
                pre = staged
                decision = _decision_of(pre)
                inputs = _identity_inputs(args, pre)
                with _guard(decision):
                    check = _run_identity_check(args, pre, inputs)
                    obj = put_json(
                        storage,
                        staging.folder.id,
                        STAGED_IDENTITY,
                        check.to_dict(),
                        properties={ARTIFACT_PROPERTY: f"identity:{run_id}"},
                    )
                    record = f"drive:{obj.id}"
                    if check.status != "verified":
                        reasons = "; ".join(check.reasons)
                        quarantine_staging(storage, staging, reasons)
                        raise IdentityMismatch(
                            f"identity check failed: {reasons}. The run's Drive staging "
                            "folder was moved to quarantine; fix --profile/--host or the "
                            "expected workspace and start a new run with "
                            "`engagement preflight`."
                        )
        finally:
            _close(storage)

    return {
        "run_id": pre["run_id"],
        "status": check.status,
        "reasons": list(check.reasons),
        "expected_workspace_id": check.expected_workspace_id,
        "observed_workspace_id": check.observed_workspace_id,
        "expected_host": check.expected_host,
        "observed_host": check.observed_host,
        "principal_id": check.principal_id,
        "principal_kind": check.principal_kind,
        "provisional_account_key": check.provisional_account_key,
        "provisional_account_name": check.provisional_account_name,
        "provisional_source": check.provisional_source,
        "checked_at": check.checked_at,
        "workspace_profile": check.workspace_profile,
        "identity_check": record,
        "staging_folder_id": None if staging is None else staging.folder.id,
    }


# --------------------------------------------------------------------------- #
# route
# --------------------------------------------------------------------------- #
def _load_ticket_ref(source: str) -> dict[str, Any]:
    """Read a ``TicketRef v1`` (bare, or the ``ticket validate`` output) from a file or '-'."""
    try:
        raw = (
            sys.stdin.read()
            if source == "-"
            else Path(source).read_text(encoding="utf-8")
        )
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ArgError(
            f"--ticket-ref: cannot read ticket JSON from {source!r}: {exc}"
        ) from exc
    ref = payload.get("ticket_ref", payload) if isinstance(payload, dict) else None
    if not isinstance(ref, dict) or ref.get("schema_version") != _TICKET_SCHEMA_VERSION:
        raise ArgError("--ticket-ref must hold a TicketRef with schema_version '1'")
    for key in ("ar_key", "resolution"):
        if not ref.get(key):
            raise ArgError(f"--ticket-ref is missing {key!r}")
    return {k: ref[k] for k in _TICKET_FIELDS if k in ref}


_RESOLUTION_KEYS = (
    "route",
    "path",
    "path_names",
    "base_id",
    "account_folder_id",
    "ticket_folder_id",
    "run_folder_id",
    "run_folder_link",
    "links",
    "drive_kind",
    "fallback_warning",
)


def _resolution_dict(result: Any) -> dict[str, Any]:
    if result is None:
        return dict.fromkeys(_RESOLUTION_KEYS)
    return {
        "route": result.route,
        "path": "/".join(result.path_names),
        "path_names": list(result.path_names),
        "base_id": result.base_id,
        "account_folder_id": result.account_folder_id,
        "ticket_folder_id": result.ticket_folder_id,
        "run_folder_id": result.run_folder_id,
        "run_folder_link": result.links.get("run"),
        "links": dict(result.links),
        "drive_kind": result.access.drive_kind,
        "fallback_warning": result.fallback_warning,
    }


def _check_identity_record(
    check: Any, run_id: str, account_key: str, where: str
) -> Any:
    first = "run verify-identity first"
    if check.run_id != run_id:
        raise ArgError(f"{first}: {where} belongs to run {check.run_id}, not {run_id}")
    if check.status != "verified":
        raise ArgError(
            f"{first}: the identity check is {check.status} ({'; '.join(check.reasons)})"
        )
    if not _same_sf_id(check.provisional_account_key, account_key):
        raise ArgError(
            f"{first}: the identity check verified account {check.provisional_account_key!r}, "
            f"not {account_key!r}"
        )
    return check


def _local_identity(run_dir: Path, run_id: str, account_key: str) -> Any:
    """The run's verified local ``IdentityCheck`` for ``account_key``, or refuse."""
    from starboard_core.engagement.records import IdentityCheck  # lazy – kernel dep

    path = run_dir / IDENTITY_RECORD
    try:
        check = IdentityCheck.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise ArgError(
            f"run verify-identity first: no identity check at {path}"
        ) from exc
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ApiError(
            f"cannot read the identity check {path} ({exc}); re-run verify-identity "
            "for this run"
        ) from exc
    return _check_identity_record(check, run_id, account_key, str(path))


def _staged_identity(
    storage: EngagementStoragePort, staging: Any, run_id: str, account_key: str
) -> Any:
    """The run's verified staged ``IdentityCheck`` for ``account_key``, or refuse."""
    from starboard_core.engagement.records import IdentityCheck  # lazy – kernel dep

    raw = _read_staged(
        storage, staging.folder.id, STAGED_IDENTITY, f"identity:{run_id}"
    )
    if raw is None:
        raise ArgError(
            f"run verify-identity first: run {run_id} has no staged identity check"
        )
    try:
        check = IdentityCheck.from_dict(raw)
    except (ValueError, TypeError, KeyError) as exc:
        raise ApiError(
            f"the staged identity check of run {run_id} is not valid ({exc}); re-run "
            "verify-identity"
        ) from exc
    return _check_identity_record(
        check, run_id, account_key, "the staged identity check"
    )


def _route_inputs(args: argparse.Namespace, pre: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the route flags (ticket, override, account) against the preflight."""
    unattended = bool(args.unattended or pre.get("unattended"))
    drive = pre.get("destination") == "drive"
    ticket = _load_ticket_ref(args.ticket_ref) if args.ticket_ref else None
    validated = ticket is not None and ticket["resolution"] == "validated"
    override = (getattr(args, "override_folder_id", None) or "").strip() or None
    internal_domains = _internal_domains(args)
    recorded_key = (pre.get("account_key") or "").strip()
    account_key = (args.account_key or "").strip() or recorded_key
    if (
        args.account_key
        and recorded_key
        and not _same_sf_id(args.account_key, recorded_key)
    ):
        raise ArgError(
            f"--account-key {args.account_key!r} disagrees with the preflight record "
            f"({recorded_key!r})"
        )
    recorded_name = pre.get("account_name") or ""
    if args.account_name and recorded_name and args.account_name != recorded_name:
        raise ArgError(
            f"--account-name {args.account_name!r} disagrees with the preflight record "
            f"({recorded_name!r}); drop the flag or re-run preflight"
        )
    account_name = args.account_name or recorded_name
    ticket_warning: str | None = None

    if validated:
        assert ticket is not None
        if override:
            raise ArgError(
                "pass either a validated --ticket-ref or --override-folder-id, not both"
            )
        ticket_account = ticket.get("account_id") or ""
        if (
            account_key
            and ticket_account
            and not _same_sf_id(account_key, ticket_account)
        ):
            raise ArgError(
                f"--account-key {account_key!r} does not match the ticket account "
                f"{ticket_account!r}; re-validate the ticket against the verified account"
            )
        account_key = account_key or ticket_account
        account_name = account_name or ticket.get("account_name")
        if not ticket.get("title"):
            raise ArgError("validated --ticket-ref has no title")
        if drive and not args.shared_root_id:
            raise ArgError("a validated --ticket-ref needs --shared-root-id")
        if drive and not internal_domains:
            raise ArgError(
                "a validated --ticket-ref needs at least one --internal-domain"
            )
    elif ticket is not None and ticket["resolution"] != "skipped":
        ticket_warning = (
            f"Ticket {ticket['ar_key']} was not used ({ticket['resolution']}: "
            f"{ticket.get('reason', '')}). Results go to the account route instead."
        )
        if unattended:
            raise ArgError(f"unattended run: {ticket_warning} {_APPROVED_DESTINATION}")
    if override and not internal_domains:
        raise ArgError("--override-folder-id needs at least one --internal-domain")
    if not account_key or not account_name:
        raise ArgError(
            "--account-key and --account-name are required without a validated ticket"
        )
    return {
        "unattended": unattended,
        "ticket": ticket,
        "validated": validated,
        "override": override,
        "internal_domains": internal_domains,
        "account_key": account_key,
        "account_name": account_name,
        "ticket_warning": ticket_warning,
        "shared_root_id": args.shared_root_id,
    }


def _authorization(
    pre: Mapping[str, Any], inputs: Mapping[str, Any], check: Any, drive_ctx: Any
) -> Any:
    from starboard_core.engagement.records import (  # lazy – kernel dep
        AccountRef,
        RunAuthorization,
    )

    # D4-15: an internal_only run declares its one workspace at preflight. The record
    # is a file, so it is re-validated rather than trusted.
    declared = pre.get("internal_workspace_id")
    if declared is not None and not (
        pre.get("source_mode") == "internal_only"
        and isinstance(declared, str)
        and declared.isascii()
        and declared.isdigit()
    ):
        raise ArgError(
            "the preflight record's internal_workspace_id must be the numeric "
            "workspace id of an internal_only run; re-run preflight"
        )
    if check is not None:
        workspace_ids = [check.expected_workspace_id]
        verifier = "identity_check"
        basis = "verified"
    else:
        workspace_ids = [declared] if declared else []
        verifier = "ticket" if inputs["validated"] else "operator"
        basis = "declared"
    scope = {
        "account_key": inputs["account_key"],
        "workspace_ids": workspace_ids,
        "basis": basis,
    }
    try:
        return RunAuthorization(
            engagement_id=f"{inputs['account_key']}/{pre['task']}/{pre['task_name']}",
            run_id=pre["run_id"],
            intent=pre["task"],
            task=pre["task_name"],
            account=AccountRef(
                id=inputs["account_key"],
                display_name=inputs["account_name"],
                verifier=verifier,
            ),
            requested_scope=scope,
            authorized_scope=scope,
            reporting_interval="unspecified",
            timezone="UTC",
            source_mode=pre["source_mode"],
            storage_policy=pre["decision"]["policy"],
            audience="internal"
            if pre.get("overlay", {}).get("enabled")
            else "operator",
            methodology_version=METHODOLOGY_VERSION,
            drive=drive_ctx,
            ticket=inputs["ticket"],
            workspace_profile=None if check is None else check.workspace_profile,
        )
    except ValueError as exc:
        raise ArgError(str(exc)) from exc


def cmd_route(args: argparse.Namespace) -> dict[str, Any]:
    ctx = _ctx(args)
    ctx["stage"] = "route"
    _one_run(args)
    local = _local_run_dir(args)
    if local:
        return _route_local(args, local)
    run_id = _check_run_id(args.run_id)
    ctx["run_id"] = run_id
    storage = _drive_storage(run_id)
    try:
        with _storage_errors(bool(args.unattended), run_id):
            staging, pre = _open_staging(storage, run_id)
            assert pre is not None
            inputs = _route_inputs(args, pre)
            decision = _decision_of(pre)
            with _guard(decision):
                return _route_drive(storage, staging, pre, inputs, ctx)
    finally:
        _close(storage)


def _resolve(
    storage: EngagementStoragePort, pre: Mapping[str, Any], inputs: Mapping[str, Any]
) -> Any:
    from starboard_core.engagement.folders import (  # lazy – kernel dep
        resolve_account_route,
        resolve_override_route,
        resolve_ticket_route,
    )

    common = {
        "account_key": inputs["account_key"],
        "account_name": inputs["account_name"],
        "task": pre["task"],
        "task_name": pre["task_name"],
        "run_id": pre["run_id"],
    }
    try:
        if inputs["validated"]:
            ticket = inputs["ticket"]
            return resolve_ticket_route(
                storage,
                shared_root_id=inputs["shared_root_id"],
                ar_key=ticket["ar_key"],
                ticket_title=ticket["title"],
                internal_domains=inputs["internal_domains"],
                **common,
            )
        if inputs["override"]:
            return resolve_override_route(
                storage,
                override_folder_id=inputs["override"],
                internal_domains=inputs["internal_domains"],
                **common,
            )
        return resolve_account_route(storage, **common)
    except ValueError as exc:
        raise ArgError(str(exc)) from exc


def _route_drive(
    storage: EngagementStoragePort,
    staging: Any,
    pre: dict[str, Any],
    inputs: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    from starboard_core.engagement.access import is_restricted  # lazy – kernel dep
    from starboard_core.engagement.commit import (
        DESCRIPTOR_NAME,
        append_manifest,
        latest_manifest,
        write_descriptor,
    )
    from starboard_core.engagement.folders import FolderAccessError, classify_access
    from starboard_core.engagement.profiles import profile_for_task
    from starboard_core.engagement.records import (
        MANIFEST_STATE_KEYS,
        DriveContext,
        Registration,
        RunManifest,
        registration_id,
    )
    from starboard_core.engagement.registry import ensure_registry, register
    from starboard_core.engagement.run_id import idempotency_key
    from starboard_core.engagement.sink import DriveRunSink

    run_id = pre["run_id"]
    customer_leg = pre.get("source_mode") != "internal_only"
    check = (
        _staged_identity(storage, staging, run_id, inputs["account_key"])
        if customer_leg
        else None
    )
    result = _resolve(storage, pre, inputs)
    if inputs["unattended"] and result.fallback_warning:
        raise ArgError(
            f"unattended run: {result.fallback_warning} {_APPROVED_DESTINATION}"
        )
    rf = result.run_folder_id
    ctx["run_folder_id"] = rf
    access = storage.inspect_access(rf)
    if result.route in ("ticket", "override"):
        acl = "internal_only"  # the kernel refuses anything wider
    elif is_restricted(access):
        acl = "owner_only"
    else:
        shared = classify_access(access, inputs["internal_domains"])
        if shared != "internal_only":
            raise FolderAccessError(
                f"run folder {rf} access is {shared}, not owner-only or internal-only; "
                "the account route needs a private run folder or one shared only with "
                "--internal-domain staff. Remove the extra sharing, then re-run route",
                object_id=rf,
                classification=shared,
                fingerprint=access.fingerprint,
            )
        acl = shared

    warnings: list[str] = [
        w
        for w in (result.fallback_warning, inputs["ticket_warning"], *result.warnings)
        if w
    ]
    ctx["warnings"] = warnings
    shared_root = os.environ.get(SHARED_REGISTRY_ENV, "").strip() or None
    handles = ensure_registry(
        storage,
        inputs["account_key"],
        account_name=inputs["account_name"],
        shared_root_id=shared_root,
        internal_domains=inputs["internal_domains"],
        warnings=warnings,
    )
    principal = storage.principal_id()
    try:
        drive_ctx = DriveContext(
            provider="google_drive",
            principal=principal,
            route=result.route,
            base_folder_id=result.base_id,
            root_folder_id=result.ticket_folder_id or result.account_folder_id,
            run_folder_id=rf,
            registry_folder_id=handles[0].folder_id,
            account_key=inputs["account_key"],
            acl_classification=acl,
            permission_fingerprints={rf: access.fingerprint},
            capabilities={"add_children": bool(access.can_add_children)},
            created_at=pre["created_at"],
            idempotency_key=pre.get("idempotency_key")
            or idempotency_key(run_id, "run"),
            links=dict(result.links),
            preflight_folder_id=staging.folder.id,
            fallback_warning=result.fallback_warning,
        )
    except ValueError as exc:
        raise ArgError(str(exc)) from exc
    auth = _authorization(pre, inputs, check, drive_ctx)
    descriptor = write_descriptor(storage, rf, auth)
    descriptor_ref = _storage_ref(DESCRIPTOR_NAME, descriptor)
    refs: list[Any] = []
    if check is not None:
        sink = DriveRunSink(
            storage, rf, run_id=run_id, access_fingerprint=access.fingerprint
        )
        refs.append(_put_record(sink, IDENTITY_RECORD, check.to_dict()))
    latest = latest_manifest(storage, rf)
    if latest is None:
        pending = dict.fromkeys(MANIFEST_STATE_KEYS, "pending")
        latest = append_manifest(
            storage,
            rf,
            lambda n, prev: RunManifest(
                engagement_id=auth.engagement_id,
                run_id=run_id,
                revision=n,
                previous_object_id=prev,
                task=auth.intent,
                task_name=auth.task,
                source_mode=auth.source_mode,
                storage_policy=auth.storage_policy,
                descriptor_ref=descriptor_ref,
                refs=tuple(sorted(refs, key=lambda r: r.path)),
                states=pending,
                committed_at=_envelope._now(),
                workflow_profile=profile_for_task(auth.intent),
            ),
        )
    manifest, manifest_obj = latest
    reg = Registration(
        registration_id=registration_id(run_id),
        kind="run",
        run_id=run_id,
        engagement_id=auth.engagement_id,
        account_key=inputs["account_key"],
        task=pre["task"],
        task_name=pre["task_name"],
        route=result.route,
        source_mode=pre["source_mode"],
        storage_policy=pre["decision"]["policy"],
        run_folder_id=rf,
        descriptor_ref=descriptor_ref,
        observation_summary_ref=None,
        acl_classification=acl,
        principal_id=principal,
        registered_at=pre["created_at"],
        provenance={"origin": "drive_run"},
    )
    for handle in handles:
        register(storage, handle, reg)
    storage.update(staging.folder.id, properties={RUN_FOLDER_PROPERTY: rf})

    data = _resolution_dict(result)
    data.update(
        {
            "run_id": run_id,
            "account_key": inputs["account_key"],
            "account_name": inputs["account_name"],
            "task": pre["task"],
            "task_name": pre["task_name"],
            "ticket": inputs["ticket"],
            "ticket_warning": inputs["ticket_warning"],
            "destination": "drive",
            "authorized_scope": _scope_dict(auth.authorized_scope),
            "acl_classification": acl,
            "run_link": result.links.get("run"),
            "registry_folder_id": handles[0].folder_id,
            "registries": [
                {"location": h.location, "folder_id": h.folder_id} for h in handles
            ],
            "registration_id": reg.registration_id,
            "staging_folder_id": staging.folder.id,
            "run_authorization": None,
            "descriptor_id": descriptor.id,
            "manifest_revision": manifest.revision,
            "manifest_id": manifest_obj.id,
            "warnings": warnings,
        }
    )
    return data


def _scope_dict(scope: Mapping[str, Any]) -> dict[str, Any]:
    """The authorized scope as JSON-native values (lists, not tuples)."""
    return {k: list(v) if isinstance(v, tuple) else v for k, v in scope.items()}


def _route_local(args: argparse.Namespace, local: str) -> dict[str, Any]:
    from starboard_core.engagement.staging import encode_json  # lazy – kernel dep

    ctx = _ctx(args)
    pre, run_dir = _load_local_preflight(local)
    ctx["run_id"] = pre["run_id"]
    if args.override_folder_id:
        raise ArgError("--override-folder-id is a Drive route; this run is local")
    inputs = _route_inputs(args, pre)
    check = (
        _local_identity(run_dir, pre["run_id"], inputs["account_key"])
        if pre.get("source_mode") != "internal_only"
        else None
    )
    auth = _authorization(pre, inputs, check, None)
    local_auth = run_dir / AUTHORIZATION_RECORD
    payload = encode_json(auth.to_dict())
    if local_auth.exists() and local_auth.read_bytes() != payload:
        raise ArgError(
            f"{local_auth} already authorizes this run differently; the run "
            "authorization is immutable, so start a new run with `engagement preflight`"
        )
    local_auth.parent.mkdir(parents=True, exist_ok=True)
    local_auth.write_bytes(payload)
    # The run's deliverables land here; the first write must not need a mkdir.
    (run_dir / "deliverables").mkdir(parents=True, exist_ok=True)
    data = _resolution_dict(None)
    data.update(
        {
            "run_id": pre["run_id"],
            "account_key": inputs["account_key"],
            "account_name": inputs["account_name"],
            "task": pre["task"],
            "task_name": pre["task_name"],
            "ticket": inputs["ticket"],
            "ticket_warning": inputs["ticket_warning"],
            "destination": "local",
            "authorized_scope": _scope_dict(auth.authorized_scope),
            "run_link": None,
            "registry_folder_id": None,
            "registration_id": None,
            "staging_folder_id": None,
            "run_authorization": local_auth.as_posix(),
            "descriptor_id": None,
            "manifest_revision": None,
            "manifest_id": None,
            "warnings": [w for w in (inputs["ticket_warning"],) if w],
        }
    )
    return data
