"""Envelope, errors and injection seams shared by every ``engagement`` subcommand.

Holds the domain constants and exit codes, the helper error types, the
``(exit code, error code)`` classification, the bounded envelope wrapper
(:func:`_entry`), the storage-error mapping (:func:`_storage_errors`), and the
seams tests replace: :func:`_detect_overlay`, :func:`_make_storage`,
:func:`_make_workspace_client`, :func:`_now` and :func:`_read_verified`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, NoReturn

from starboard_skills.helpers.contract import (
    AUTH_ENV_VARS,
    ApiError,
    ArgError,
    AuthError,
    HelperError,
    NotFoundError,
    make_client,
)

if TYPE_CHECKING:  # kernel types only; imported lazily at runtime
    from starboard_core.engagement.overlay import OverlaySignal
    from starboard_core.engagement.records import RunAuthorization
    from starboard_core.ports.engagement_storage import (
        EngagementStoragePort,
        StorageObject,
    )

DOMAIN = "engagement"
PrincipalKind = Literal["service_principal", "user"]
SOURCE_MODES = ("customer_workspace", "internal_only", "hybrid", "unknown")
TASKS = ("health_check", "troubleshooting", "discovery", "action_plan", "review")
PROVISIONAL_SOURCES = ("operator", "mapping", "salesforce", "ticket")
STAGES = ("capture", "analysis", "check")
STAGE_STATES = ("complete", "failed")
AUDIENCES = ("internal", "customer")
RECEIPT_CHANNELS = ("google_doc", "slides", "slack", "drive")
ARTIFACT_PROPERTY = "starboard_artifact"
RUN_FOLDER_PROPERTY = "starboard_run_folder"
DELIVERY_PROPERTY = "starboard_delivery"
_ANCESTOR_LIMIT = 32  # folder hops checked when proving a receipt is outside the run
SHARED_REGISTRY_ENV = "STARBOARD_SHARED_REGISTRY_ID"

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_AUTH_PROMPT = 3
EXIT_STORAGE = 4
EXIT_IDENTITY = 5
EXIT_WORKSPACE = 6  # the Databricks workspace API failed (retryable; not storage)
# 7 is skipped: on the other helper surfaces it is a definite storage failure.
EXIT_STORAGE_TRANSIENT = 8  # Drive failed transiently (retryable; nothing refused)
# Error codes whose failure attempted nothing irreversible: retry the same command.
RETRYABLE_CODES = frozenset({"STORAGE_TRANSIENT", "WORKSPACE_API_ERROR"})

_FALLBACK_AUTH_HINT = (
    "Authenticate Google Drive access with `gcloud auth login --enable-gdrive-access`, "
    "then retry."
)
_UNATTENDED_HINT = (
    "This is an unattended run, so no sign-in prompt is possible: configure valid "
    "Google Drive auth for the scheduled job first."
)
_APPROVED_DESTINATION = (
    "configure an approved destination (and valid auth) for unattended runs first"
)
_TICKET_SCHEMA_VERSION = "1"
# Only these TicketRef keys are kept in results and the run descriptor.
_TICKET_FIELDS = (
    "schema_version",
    "ar_key",
    "record_id",
    "object_name",
    "title",
    "account_id",
    "account_name",
    "status_value",
    "looked_up_at",
    "resolution",
    "reason",
)
DEFAULT_REPORTS_ROOT = "starboard-reports"
# Local run-dir records (``local`` / ``internal_only_local`` runs only).
PREFLIGHT_RECORD = "analysis/storage-preflight.json"
IDENTITY_RECORD = "analysis/identity-check.json"
AUTHORIZATION_RECORD = "analysis/run-authorization.json"
# Drive staging and run-folder names.
STAGED_PREFLIGHT = "storage-preflight.json"
STAGED_IDENTITY = "identity-check.json"
EVIDENCE_PATH = "evidence/index.json"
OBSERVATIONS_PATH = "analysis/observations.json"
FINDINGS_PATH = "analysis/findings.json"
FINDINGS_MANIFEST_PATH = "findings-manifest.json"
BASELINE_PATH = "analysis/baseline-selection.json"
HEALTH_PATH = "analysis/health.json"
PLAYS_PATH = "analysis/plays.json"
CHANGES_PATH = "analysis/changes.json"
CASES_PATH = "analysis/cases.json"
ACTIONS_PATH = "analysis/actions.json"
# The phase-3 record sets a commit cites as ``<name>_ref``.
RECORD_PATHS = {
    "health": HEALTH_PATH,
    "plays": PLAYS_PATH,
    "changes": CHANGES_PATH,
    "cases": CASES_PATH,
    "actions": ACTIONS_PATH,
}
IMPORT_SUMMARY = "summary.json"
METHODOLOGY_VERSION = "engagement-v1"
# Room the envelope keeps around a ``read`` excerpt inside the stdout budget.
_ENVELOPE_RESERVE = 2_048
# The ``read`` excerpt cap: the kernel stdout budget (24_000) less the reserve.
DEFAULT_READ_BYTES = 24_000 - _ENVELOPE_RESERVE
DEFAULT_PUT_BYTES = 5 * 2**20
_PUT_MIME = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".html": "text/html",
    ".py": "text/x-python",
    ".sql": "application/sql",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}
_TASK_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*-[A-Za-z0-9._-]+$")
_WS_TASK_NAME_RE = re.compile(r"^ws-(\d+)$")
_REV_RE = re.compile(r"reports/([^/]+)/rev-(\d{6})\.json")
_APPROVAL_RE = re.compile(r"reports/([^/]+)/approvals/[^/]+\.json")
_RECEIPT_RE = re.compile(r"reports/([^/]+)/receipts/[^/]+\.json")
# Top-level folders a report body may never come from (raw captures, evidence).
_REPORT_REFUSED_TOPS = frozenset({"raw", "evidence"})


# --------------------------------------------------------------------------- #
# Injection seams (patched in tests on this module). Every other module calls
# them as ``_envelope.<seam>(...)`` so one ``monkeypatch.setattr(_envelope, ...)``
# reaches every caller.
# --------------------------------------------------------------------------- #
def _detect_overlay() -> OverlaySignal:
    from starboard_core.engagement.overlay import detect_overlay  # lazy – kernel dep

    return detect_overlay()


def _make_storage() -> EngagementStoragePort:
    """The Drive adapter from the ``starboard.engagement_storage`` entry point.

    Raises ``StorageUnavailableError`` (exit 2) when it cannot be loaded.
    """
    from starboard_core.engagement import sink  # lazy – kernel dep

    return sink.load_engagement_storage()


def _auth_hint() -> str:
    try:
        from starboard import DRIVE_AUTH_HINT
    except ImportError:
        return _FALLBACK_AUTH_HINT
    return str(DRIVE_AUTH_HINT)


def _make_workspace_client(profile: str | None, host: str | None) -> Any:
    """Build a workspace client from exactly the given ``--profile`` or ``--host``.

    A profile goes through :func:`make_client` (ambient auth env masked). A host
    masks the ambient ``DATABRICKS_CONFIG_PROFILE``; other ambient auth env is
    kept only when ``DATABRICKS_HOST`` names the same host. No profile is ever
    chosen on the operator's behalf.
    """
    from starboard_core.engagement.identity import normalize_host  # lazy – kernel dep

    if profile:
        try:
            return make_client(profile)
        except AuthError as exc:
            raise WorkspaceAuthError(exc.message) from exc
    if not host:
        raise ArgError("pass --profile or --host for the workspace to verify")
    try:
        wanted = normalize_host(host)
    except ValueError as exc:
        raise ArgError(f"--host: {exc}") from exc
    try:
        env_host = os.environ.get("DATABRICKS_HOST") or ""
        same_host = bool(env_host) and normalize_host(env_host) == wanted
    except ValueError:
        same_host = False
    masked = ("DATABRICKS_CONFIG_PROFILE",) if same_host else AUTH_ENV_VARS
    saved = {k: os.environ.pop(k) for k in masked if k in os.environ}
    try:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient(host=host)
    except Exception as exc:
        raise WorkspaceAuthError(f"Authentication error: {exc}") from exc
    finally:
        os.environ.update(saved)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_verified(storage: EngagementStoragePort, obj: StorageObject) -> bytes:
    """Download the listed file ``obj`` and check its bytes against its md5 and size.

    The kernel's :func:`~starboard_core.engagement.reads.read_object`, capped at the
    largest artifact the run sink accepts. A refused read (folder, over the cap)
    is reported as an integrity failure, like a mismatch.
    """
    from starboard_core.engagement.reads import (  # lazy – kernel dep
        ReadRefusedError,
        read_object,
    )
    from starboard_core.engagement.sink import DEFAULT_MAX_BYTES
    from starboard_core.ports.engagement_storage import StorageIntegrityError

    try:
        return read_object(storage, obj, max_bytes=DEFAULT_MAX_BYTES)
    except ReadRefusedError as exc:
        raise StorageIntegrityError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Errors and the envelope
# --------------------------------------------------------------------------- #
class IdentityMismatch(ApiError):
    """The workspace is not the expected one (exit 5)."""

    code = "IDENTITY_MISMATCH"
    exit_code = EXIT_IDENTITY


class RunQuarantined(ApiError):
    """The run's staging folder is quarantined (exit 5)."""

    code = "RUN_QUARANTINED"
    exit_code = EXIT_IDENTITY


class WorkspaceApiError(ApiError):
    """A Databricks workspace API call failed or returned no usable answer (exit 6).

    Distinct from storage failures (exit 4): Drive was never touched, so the
    run folder is intact and the stage can simply be retried.
    """

    code = "WORKSPACE_API_ERROR"
    exit_code = EXIT_WORKSPACE


class StorageTransient(ApiError):
    """Drive failed transiently after the adapter's retries (exit 8, retryable).

    Distinct from a refusal (exit 2) and a definite storage failure (exit 4):
    nothing was refused, so the same command can simply be retried.
    """

    code = "STORAGE_TRANSIENT"
    exit_code = EXIT_STORAGE_TRANSIENT


class WorkspaceAuthError(AuthError):
    """Databricks workspace authentication failed (exit 3, ``WORKSPACE_AUTH_REQUIRED``).

    Shares exit 3 with Google Drive auth (``AUTH_REQUIRED``); the ``code`` says which.
    """

    code = "WORKSPACE_AUTH_REQUIRED"


class Refusal(ArgError):
    """A lifecycle step that the run's state does not permit (exit 2)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _ctx(args: argparse.Namespace) -> dict[str, Any]:
    """Per-call context (run ID, run folder, stage) for the failure envelope."""
    ctx: dict[str, Any] = args.__dict__.setdefault("_ctx", {})
    return ctx


def _account_key(auth: RunAuthorization) -> str:
    """The account key a run's records carry (the Drive account, else the scope's)."""
    if auth.drive is not None:
        return auth.drive.account_key
    return str(auth.authorized_scope.get("account_key") or auth.account.id)


def _classify(exc: BaseException) -> tuple[int, str]:
    """Map a failure onto ``(exit code, error code)``.

    Only helper and kernel error types (plus ``ValueError`` argument checks and
    local ``OSError``) are expected; anything else is a bug, reported as
    ``INTERNAL`` (exit 1) with its traceback on stderr.
    """
    from starboard_core.engagement.commit import CommitError  # lazy – kernel dep
    from starboard_core.engagement.folders import FolderResolutionError
    from starboard_core.engagement.sink import (
        AccessRecheckError,
        LocalStorageRefused,
        StorageUnavailableError,
    )
    from starboard_core.engagement.write_guard import LocalWriteRefused
    from starboard_core.ports.engagement_storage import (
        StorageAuthError,
        StorageError,
        StorageTransientError,
    )

    if isinstance(exc, IdentityMismatch | RunQuarantined):
        return EXIT_IDENTITY, exc.code
    if isinstance(exc, WorkspaceApiError):
        return EXIT_WORKSPACE, exc.code
    if isinstance(
        exc,
        LocalStorageRefused
        | LocalWriteRefused
        | StorageUnavailableError,
    ):
        return EXIT_USAGE, str(getattr(exc, "code", "REFUSED"))
    if isinstance(exc, AccessRecheckError):
        return EXIT_STORAGE, "BLOCKED_ACCESS"
    if isinstance(exc, Refusal):
        return EXIT_USAGE, exc.code
    if isinstance(exc, ArgError | ValueError):
        return EXIT_USAGE, "USAGE"
    if isinstance(exc, WorkspaceAuthError):
        return EXIT_AUTH_PROMPT, exc.code
    if isinstance(exc, AuthError | StorageAuthError):
        return EXIT_AUTH_PROMPT, "AUTH_REQUIRED"  # Google Drive sign-in
    if isinstance(exc, NotFoundError):
        return EXIT_STORAGE, "NOT_FOUND"
    if isinstance(exc, StorageTransient | StorageTransientError) or isinstance(
        exc.__cause__, StorageTransientError
    ):
        return EXIT_STORAGE_TRANSIENT, StorageTransient.code
    if isinstance(
        exc, HelperError | StorageError | FolderResolutionError | CommitError | OSError
    ):
        return EXIT_STORAGE, "STORAGE_ERROR"
    return EXIT_INTERNAL, "INTERNAL"


def _emit(envelope: Mapping[str, Any]) -> None:
    from starboard_core.engagement.stdout_budget import bound  # lazy – kernel dep

    print(json.dumps(bound(envelope), default=str))


def _current_status(
    args: argparse.Namespace, ctx: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The run's ``engagement status`` data, or ``None`` when it cannot be read.

    Best effort, read-only: used only to echo an unchanged status on a refusal.
    """
    from starboard_skills.helpers.engagement.lifecycle import (  # lazy – no cycle
        cmd_status,
    )

    probe = argparse.Namespace(run_id=None, run_dir=None, run_folder=None)
    if ctx.get("run_folder_id"):
        probe.run_folder = ctx["run_folder_id"]
    elif getattr(args, "run_dir", None):
        probe.run_dir = args.run_dir
    else:
        probe.run_id = ctx["run_id"]
    try:
        return cmd_status(probe)
    except Exception:  # noqa: BLE001 - the refusal is what matters; omit the status
        return None


def _entry(
    fn: Callable[[argparse.Namespace], dict[str, Any]], command: str
) -> Callable[[argparse.Namespace], NoReturn]:
    """Wrap a subcommand: print the bounded envelope and exit with its code."""

    def run(args: argparse.Namespace) -> NoReturn:
        ctx = _ctx(args)
        try:
            data = fn(args)
        except Exception as exc:  # noqa: BLE001 - every failure gets an envelope
            code, error = _classify(exc)
            message = getattr(exc, "message", None) or str(exc)
            if code == EXIT_INTERNAL:
                traceback.print_exception(exc, file=sys.stderr)
                message = f"internal error ({type(exc).__name__}): {message}"
            failure: dict[str, Any] = {
                "run_id": ctx.get("run_id"),
                "run_folder_id": ctx.get("run_folder_id"),
            }
            if error == "BLOCKED_ACCESS":
                failure["run_status"] = "blocked_access"
                failure["resume"] = None
                failure["access"] = getattr(
                    getattr(exc, "verdict", None), "reason", None
                )
            elif code == EXIT_USAGE and ctx.get("run_id"):
                # A usage refusal attempted nothing: echo the run's status unchanged.
                current = _current_status(args, ctx)
                if current is not None:
                    failure["run_status"] = current.get("run_status")
                    failure["resume"] = current.get("resume")
            elif ctx.get("stage") and ctx.get("run_id") and code != EXIT_IDENTITY:
                failure["run_status"] = f"{ctx['stage']}_pending"
                failure["resume"] = {
                    "run_id": ctx["run_id"],
                    "run_folder_id": ctx.get("run_folder_id"),
                    "stage": ctx["stage"],
                }
            _emit(
                {
                    "ok": False,
                    "domain": DOMAIN,
                    "command": command,
                    "data": failure,
                    "warnings": list(ctx.get("warnings") or []),
                    "errors": [
                        {
                            "code": error,
                            "message": message,
                            "retryable": error in RETRYABLE_CODES,
                        }
                    ],
                }
            )
            sys.exit(code)
        _emit(
            {
                "ok": True,
                "domain": DOMAIN,
                "command": command,
                "data": data,
                "warnings": list(data.get("warnings") or []),
                "errors": [],
            }
        )
        sys.exit(EXIT_OK)

    run.__name__ = f"engagement_{command.replace('-', '_')}"
    return run


@contextmanager
def _storage_errors(
    unattended: bool = False, run_id: str | None = None
) -> Iterator[None]:
    """Map storage, folder-resolution and commit errors onto helper errors.

    Access-recheck failures and a missing storage adapter pass through unchanged:
    the envelope gives them their own codes.
    """
    from starboard_core.engagement.commit import (  # lazy – kernel dep
        CommitError,
        DescriptorConflictError,
    )
    from starboard_core.engagement.folders import (
        FolderAccessError,
        FolderConflictError,
        FolderResolutionError,
    )
    from starboard_core.engagement.sink import (
        AccessRecheckError,
        StorageUnavailableError,
    )
    from starboard_core.engagement.staging import StagingNotRestrictedError
    from starboard_core.ports.engagement_storage import (
        StorageAuthError,
        StorageError,
        StorageIntegrityError,
        StorageNotFoundError,
        StoragePermissionError,
        StorageTransientError,
    )

    resume = (
        f"`engagement preflight --resume-run-id {run_id}`"
        if run_id
        else "`engagement preflight --resume-run-id <run_id>`"
    )
    try:
        yield
    except (AccessRecheckError, StorageUnavailableError):
        raise
    except StorageTransientError as exc:
        raise StorageTransient(
            f"Drive is temporarily unavailable: {exc}. Nothing was refused; retry the "
            "same command."
        ) from exc
    except StorageAuthError as exc:
        hint = _UNATTENDED_HINT if unattended else _auth_hint()
        raise AuthError(f"Google Drive authentication required: {exc}. {hint}") from exc
    except StorageNotFoundError as exc:
        raise NotFoundError(f"Drive object not found: {exc}") from exc
    except StoragePermissionError as exc:
        raise ApiError(f"Drive permission denied: {exc}") from exc
    except StorageIntegrityError as exc:
        raise ApiError(f"Drive read-back verification failed: {exc}") from exc
    except FolderConflictError as exc:
        if exc.other_account_key is not None:
            raise Refusal(
                "ACCOUNT_NAME_TAKEN",
                f"Drive folder {exc.name!r} belongs to account key "
                f"{exc.other_account_key!r}, not {exc.identity_key.removeprefix('account:')!r}. "
                "If this is the same account, start over with `engagement preflight "
                f"--account-key {exc.other_account_key}` (the key never changes "
                "mid-run); otherwise choose a different --account-name.",
            ) from exc
        raise ApiError(
            f"{exc} Folders {list(exc.object_ids)} under {exc.parent_id} clash with "
            f"identity {exc.identity_key!r}: the same account kept under different "
            "names or keys, or a name another account already uses. Reconcile in "
            "Drive: move the contents into one folder, trash the other, then run "
            "`engagement rebuild-index` and retry. For a genuinely different "
            "account, route it under a different account name."
        ) from exc
    except FolderAccessError as exc:
        raise ApiError(f"Drive folder access is not internal-only: {exc}") from exc
    except StagingNotRestrictedError as exc:
        raise ApiError(
            f"Drive staging folder check failed: {exc}. Fix the sharing, then re-run "
            f"{resume} with the same flags."
        ) from exc
    except (FolderResolutionError, StorageError) as exc:
        raise ApiError(f"Drive error: {exc}") from exc
    except DescriptorConflictError as exc:
        raise ApiError(
            f"Drive run descriptor conflict: {exc}. Restore the run folder's previous "
            "sharing, or start a new run with `engagement preflight`."
        ) from exc
    except CommitError as exc:
        raise ApiError(
            f"Drive run record error: {exc}. Reconcile the run folder in Drive, or "
            "start a new run with `engagement preflight`."
        ) from exc
