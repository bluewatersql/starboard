"""Stable CLI contract for ``starboard-helper``.

Centralizes the pieces every domain module and the dispatcher share:

* the JSON *envelope* wrapping all stdout output,
* the documented process *exit codes*,
* typed *exceptions* that map 1:1 to those exit codes, and
* bare-SDK *client* factories (no dependency on the heavy ``starboard`` pkg),
* the *identity scrub* every acquiring verb applies (D3-24), and
* the engagement-storage *writer* plumbing every artifact-writing command shares
  (``--run-folder``, the artifact sink, the bounded stdout envelope). The kernel
  is imported lazily there, so plain fetches stay SDK-only.

Envelope shape (always emitted to stdout, success or failure)::

    {
      "ok": bool,
      "domain": str | None,
      "command": str | None,
      "data": <result> | None,
      "error": str | None,
      "meta": {"format": "json", "contract_version": "1.0"}
    }

A failure that has a machine code also carries ``errors: [{code, message, retryable}]``
(``error`` stays the message); ``retryable`` means the same command can simply be run
again.

Exit codes::

    0  ok
    1  auth   — could not authenticate / build a client
    2  not-found — the requested resource does not exist; also a storage policy
       refusal (``LOCAL_STORAGE_REFUSED`` /
       ``STORAGE_UNAVAILABLE``: the message starts with the code) and a
       ``--profile`` that is not the run's verified one (``PROFILE_MISMATCH``)
    3  api-error — Databricks API / unexpected runtime error
    4  arg-error — bad CLI arguments
    7  storage — a storage / integrity / access failure on an engagement run
       (``BLOCKED_ACCESS`` / ``STORAGE_INTEGRITY`` / ``NOT_FOUND`` / ``STORAGE_ERROR``:
       the message starts with the code)
    8  storage-transient — Drive failed transiently (``STORAGE_TRANSIENT``; retryable,
       nothing refused: run the same command again)
"""
from __future__ import annotations

import argparse
import errno
import os
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:  # kernel types only; imported lazily at runtime
    from starboard_core.engagement.overlay import OverlaySignal
    from starboard_core.engagement.policy import StorageDecision
    from starboard_core.engagement.records import (
        EvidenceRef,
        RunAuthorization,
        StorageRef,
    )
    from starboard_core.engagement.sink import ArtifactSink, LocalDirSink
    from starboard_core.ports.engagement_storage import EngagementStoragePort

CONTRACT_VERSION = "1.0"

# --- Exit codes ----------------------------------------------------------- #
EXIT_OK = 0
EXIT_AUTH = 1
EXIT_NOT_FOUND = 2
EXIT_API = 3
EXIT_ARG = 4
#: A storage policy refusal shares slot 2 with the ``starboard_x`` writers.
EXIT_STORAGE_REFUSED = 2
#: A storage / integrity / access failure (``BLOCKED_ACCESS`` ...): 7, as on every
#: other writer surface (the kernel's ``EXIT_STORAGE_FAILURE``, asserted in the tests).
EXIT_STORAGE_FAILURE = 7
#: A transient Drive failure (``STORAGE_TRANSIENT``): retryable, nothing refused. 8, as
#: on the engagement helper and every other writer surface.
EXIT_STORAGE_TRANSIENT = 8
#: Per-request retry budget (seconds) of a fetch client. The SDK default (300 s) lets one
#: rate-limited call approach the 600 s tool limit. The SDK reads no env var for it, so
#: :func:`_sdk_config` passes it explicitly; ``DATABRICKS_RETRY_TIMEOUT_SECONDS`` overrides.
FETCH_RETRY_TIMEOUT_S = 150


# --- Typed errors --------------------------------------------------------- #
class HelperError(Exception):
    """Base class for helper errors carrying a process exit code."""

    exit_code: int = EXIT_API
    #: Machine code of the failure (``errors[0].code``); ``""`` = the exit code alone.
    code: str = ""
    #: True when the same command can simply be run again.
    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthError(HelperError):
    """Authentication / client-construction failure."""

    exit_code = EXIT_AUTH


class NotFoundError(HelperError):
    """Requested resource does not exist."""

    exit_code = EXIT_NOT_FOUND


class ApiError(HelperError):
    """Databricks API or other unexpected runtime failure."""

    exit_code = EXIT_API


class WorkspaceTimeoutError(ApiError):
    """A workspace call ran out of its retry budget (``WORKSPACE_TIMEOUT``; exit 3).

    The SDK kept retrying a throttled / slow request until its budget ended: the same
    command can be run again (``retryable``), ideally after a pause or narrower.
    """

    code = "WORKSPACE_TIMEOUT"
    retryable = True


class CodeNotInWorkspaceError(NotFoundError):
    """A task's code is not a workspace object ``job code`` can export (exit 2).

    Not a missing resource: the job and task exist, their code just lives elsewhere
    (Git, a wheel, a non-workspace path). ``errors[0].code`` tells it from not-found.
    """

    code = "CODE_NOT_IN_WORKSPACE"


class ArgError(HelperError):
    """Bad CLI arguments."""

    exit_code = EXIT_ARG


class StorageRefusedError(HelperError):
    """A storage policy refusal; the message starts with its ``CODE:``."""

    exit_code = EXIT_STORAGE_REFUSED


class ProfileMismatchError(StorageRefusedError):
    """``--profile`` differs from the run's verified profile (``PROFILE_MISMATCH``).

    A refusal (exit 2): nothing is read or written.
    """


class StorageFailureError(HelperError):
    """A storage / integrity / access failure; the message starts with its ``CODE:``.

    ``STORAGE_TRANSIENT`` (a retryable Drive failure) exits 8 and is ``retryable``.
    """

    exit_code = EXIT_STORAGE_FAILURE

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or ""
        if code == "STORAGE_TRANSIENT":
            self.exit_code = EXIT_STORAGE_TRANSIENT
            self.retryable = True


def storage_failure(exc: BaseException) -> StorageFailureError | None:
    """``exc`` as a :class:`StorageFailureError` (exit 7), or ``None`` if it is not one.

    ``None`` too on a plain public install without the engagement kernel.
    """
    try:
        from starboard_core.engagement.sink import (
            storage_failure_code,  # lazy – kernel dep
        )
    except ModuleNotFoundError:
        return None
    code = storage_failure_code(exc)
    return StorageFailureError(f"{code}: {exc}", code=code) if code else None


# --- Error translation helper -------------------------------------------- #
def raise_api_error(exc: Exception, not_found_message: str | None = None) -> NoReturn:
    """Translate a caught SDK exception into a typed :class:`HelperError`.

    If ``not_found_message`` is provided and the exception text looks like a
    "not found" error, raises :class:`NotFoundError`; otherwise
    :class:`ApiError`. Never returns.

    "Not found" is the SDK's ``NotFound`` family or a message saying the resource
    "does not exist" / "not found" (a missing table is exit 2, not an API error). A
    ``TimeoutError`` (the SDK's retry budget ran out) is a retryable
    :class:`WorkspaceTimeoutError`. A Drive failure raised inside the same ``try``
    keeps its storage code (:func:`storage_failure`: a transient one is exit 8), and a
    Drive 404 is never read as the workspace resource being missing.
    """
    failure = storage_failure(exc)
    if failure is not None:
        raise failure from exc
    if not_found_message and _looks_not_found(exc):
        raise NotFoundError(not_found_message) from exc
    if isinstance(exc, TimeoutError) or "timed out after" in str(exc).lower():
        raise WorkspaceTimeoutError(f"API error: {api_error_text(exc)}") from exc
    raise ApiError(f"API error: {api_error_text(exc)}") from exc


#: The Databricks SDK's debug tail on an API error (``Config.wrap_debug_info``).
_SDK_DEBUG_TAIL = re.compile(r"\.?\s+(?:Config|Env): .*\Z", re.DOTALL)


def api_error_text(exc: BaseException) -> str:
    """``str(exc)`` without the SDK's ``. Config: host=..., account_id=... . Env: ...`` tail.

    The skills show a helper's ``error`` verbatim (run 10: the host, account id, auth type
    and environment variable names landed in a case report).
    """
    return _SDK_DEBUG_TAIL.sub("", str(exc))


_NOT_FOUND_TEXT = re.compile(
    r"not found|does not exist|resource_does_not_exist|table_or_view_not_found|no such",
    re.IGNORECASE,
)


def _looks_not_found(exc: BaseException) -> bool:
    from databricks.sdk.errors import NotFound

    return isinstance(exc, NotFound) or bool(_NOT_FOUND_TEXT.search(str(exc)))


# --- Identity scrub (D3-24) ----------------------------------------------- #
#: SDK identity keys dropped at acquisition (user names, emails and the numeric
#: user ids that resolve to them).
_IDENTITY_KEY = re.compile(
    r"(^|_)user_name$|email|^creator_user_name$|^run_as_user_name$"
    r"|^owner_user_name$|(^|_)user_id$"
)
#: An email-shaped substring; the ``@`` may be percent-encoded (``%40``). Quotes,
#: brackets, ``/``, ``=``, ``%`` and separators end it, so a SQL literal
#: ``'a@x.com'`` keeps its quotes (``'<email>'``) and a ``/Users/a@x.com/nb`` (or
#: ``/Users/a%40x.com/nb``) path keeps its segments.
_EMAIL_PART = r"[^@%\s'\"`(),;:<>\[\]{}/=]+"
# The look-behind pins a match to the start of a token, so a long run with no
# ``@`` (e.g. a log line) is scanned once instead of once per start offset.
_EMAIL_CHAR = _EMAIL_PART[:-1]
_EMAIL = re.compile(
    rf"(?<!{_EMAIL_CHAR}){_EMAIL_PART}(?:@|%40){_EMAIL_PART}\.{_EMAIL_PART}",
    re.IGNORECASE,
)
EMAIL_PLACEHOLDER = "<email>"


def drop_identity_fields(obj: Any) -> Any:
    """A copy of ``obj`` without identity keys, at any depth (tuples become lists)."""
    if isinstance(obj, Mapping):
        return {
            k: drop_identity_fields(v)
            for k, v in obj.items()
            if not (isinstance(k, str) and _IDENTITY_KEY.search(k))
        }
    if isinstance(obj, list | tuple):
        return [drop_identity_fields(v) for v in obj]
    return obj


def redact_emails(text: str | None) -> str | None:
    """``text`` with every email-shaped substring replaced by ``<email>``.

    An address hidden by compatibility forms (fullwidth ``＠``) is caught on the
    NFKC form; ``text`` is returned NFKC-normalised only when that form held one.
    """
    if not text:
        return text
    out = _EMAIL.sub(EMAIL_PLACEHOLDER, text)
    folded = unicodedata.normalize("NFKC", out)
    if folded != out and _EMAIL.search(folded):
        return _EMAIL.sub(EMAIL_PLACEHOLDER, folded)
    return out


def scrub_identity(obj: Any) -> Any:
    """:func:`drop_identity_fields`, then :func:`redact_emails` on every string value."""
    obj = drop_identity_fields(obj)

    def _redact(value: Any) -> Any:
        if isinstance(value, str):
            return redact_emails(value)
        if isinstance(value, dict):
            return {k: _redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_redact(v) for v in value]
        return value

    return _redact(obj)


#: Default and hard cap for acquired free text (``--max-bytes`` / ``--tail-bytes``).
ACQUIRE_DEFAULT_BYTES = 64 * 1024
ACQUIRE_MAX_BYTES = 2**20


def byte_budget(value: str) -> int:
    """argparse ``type=``: a byte budget in ``1..ACQUIRE_MAX_BYTES`` (else exit 4)."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from exc
    if not 1 <= n <= ACQUIRE_MAX_BYTES:
        raise argparse.ArgumentTypeError(f"must be 1..{ACQUIRE_MAX_BYTES} bytes, got {n}")
    return n


def clip_text(text: str | None, max_bytes: int, *, tail: bool = False) -> tuple[str | None, bool]:
    """``(text cut to max_bytes UTF-8 bytes, truncated?)``; keeps the end when ``tail``."""
    if text is None:
        return None, False
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, False
    part = raw[-max_bytes:] if tail else raw[:max_bytes]
    return part.decode("utf-8", errors="ignore"), True


# --- Client factories (bare SDK) ----------------------------------------- #
#: Env vars that steer SDK auth. When an explicit profile is requested they are
#: masked while the client is constructed so the profile wins over ambient
#: DATABRICKS_HOST / DATABRICKS_TOKEN (SDK precedence is kwarg > env > config file,
#: so a bare ``profile=`` would otherwise be overridden by a stale env host/token).
#: Also masked by ``engagement verify-identity --host`` (other workspace).
AUTH_ENV_VARS = (
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "DATABRICKS_USERNAME",
    "DATABRICKS_PASSWORD",
    "DATABRICKS_CLIENT_ID",
    "DATABRICKS_CLIENT_SECRET",
    "DATABRICKS_AUTH_TYPE",
    "DATABRICKS_CONFIG_PROFILE",
    "DATABRICKS_AZURE_CLIENT_ID",
    "DATABRICKS_AZURE_CLIENT_SECRET",
    "DATABRICKS_AZURE_TENANT_ID",
    "DATABRICKS_AZURE_RESOURCE_ID",
)


#: The global ``--profile`` of the running fetch command (see :func:`use_profile`).
_ACTIVE_PROFILE: ContextVar[str | None] = ContextVar("starboard_helper_profile", default=None)


@contextmanager
def use_profile(profile: str | None) -> Iterator[None]:
    """Make ``profile`` the default of every :func:`make_client` /
    :func:`make_account_client` call in this context.

    The dispatcher wraps each fetch in it, so every domain module (current or
    new) reads with the ``--profile`` the operator passed, without per-module
    plumbing. ``None`` keeps the ambient SDK credential chain.
    """
    token = _ACTIVE_PROFILE.set(profile or None)
    try:
        yield
    finally:
        _ACTIVE_PROFILE.reset(token)


def active_profile() -> str | None:
    """The profile set by the enclosing :func:`use_profile`, if any."""
    return _ACTIVE_PROFILE.get()


def retry_budget_s() -> int:
    """The fetch client's per-request retry budget: the env override, else the default."""
    raw = os.environ.get("DATABRICKS_RETRY_TIMEOUT_SECONDS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else FETCH_RETRY_TIMEOUT_S


def _sdk_config(profile: str | None) -> Any:
    """A :class:`databricks.sdk.config.Config` with the bounded retry budget.

    The SDK fixes the retry budget when the client is built and attaches no env
    var to it, so it must be passed here. ``profile=None`` keeps the ambient chain.
    """
    from databricks.sdk.config import Config

    kwargs: dict[str, Any] = {"retry_timeout_seconds": retry_budget_s()}
    if profile:
        kwargs["profile"] = profile
    return Config(**kwargs)


@contextmanager
def _masked_auth_env() -> Iterator[None]:
    saved = {k: os.environ.pop(k) for k in AUTH_ENV_VARS if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def make_client(profile: str | None = None) -> Any:
    """Return a bare :class:`databricks.sdk.WorkspaceClient`.

    ``profile`` (default: the :func:`use_profile` profile, i.e. the global
    ``--profile``) selects a ``~/.databrickscfg`` profile and takes precedence
    over ambient ``DATABRICKS_HOST`` / ``DATABRICKS_TOKEN`` env auth (those are
    masked for the duration of client construction). Without one, the SDK's
    ambient credential chain applies unchanged.

    Raises :class:`AuthError` (exit 1) if the client cannot be constructed.
    """
    profile = profile or active_profile()
    try:
        from databricks.sdk import WorkspaceClient

        if not profile:
            return WorkspaceClient(config=_sdk_config(None))
        with _masked_auth_env():
            return WorkspaceClient(config=_sdk_config(profile))
    except Exception as exc:  # pragma: no cover - exercised via mocks
        raise AuthError(f"Authentication error: {exc}") from exc


def make_account_client(profile: str | None = None) -> Any:
    """Return a bare :class:`databricks.sdk.AccountClient`.

    ``profile`` (default: the :func:`use_profile` profile) must name an
    *account-level* ``~/.databrickscfg`` profile (``host`` = the accounts console,
    plus ``account_id``); ambient auth env is masked as in :func:`make_client`.
    The dispatcher never defaults an account command to a run's verified
    workspace profile, so only an explicit ``--profile`` reaches here.

    Raises :class:`AuthError` (exit 1) if the client cannot be constructed.
    """
    profile = profile or active_profile()
    try:
        from databricks.sdk import AccountClient

        if not profile:
            return AccountClient(config=_sdk_config(None))
        with _masked_auth_env():
            return AccountClient(config=_sdk_config(profile))
    except Exception as exc:  # pragma: no cover - exercised via mocks
        raise AuthError(f"Authentication error: {exc}") from exc


# --- Envelope ------------------------------------------------------------- #
def build_meta(output_format: str = "json") -> dict[str, Any]:
    """Return the standard ``meta`` block for an envelope."""
    return {"format": output_format, "contract_version": CONTRACT_VERSION}


def envelope(
    *,
    ok: bool,
    domain: str | None,
    command: str | None,
    data: Any = None,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
    code: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """Build the stable stdout envelope.

    A failure with a machine ``code`` also carries ``errors: [{code, message,
    retryable}]``; ``error`` stays the message.
    """
    out: dict[str, Any] = {
        "ok": ok,
        "domain": domain,
        "command": command,
        "data": data,
        "error": error,
        "meta": meta if meta is not None else build_meta(),
    }
    if code:
        out["errors"] = [{"code": code, "message": error, "retryable": retryable}]
    return out


# --- Engagement storage (``--run-folder``) -------------------------------- #
#: Input-flag prefix naming a Drive object by ID (``--data drive:<id>``).
DRIVE_PREFIX = "drive:"
#: Largest stdout a run-folder writer prints.
STDOUT_MAX_BYTES = 24_000
_RUN_FOLDER_HELP = (
    "Drive run folder ID (from `engagement route`): outputs go to that folder through "
    "the artifact sink and output flags become run-relative paths"
)
_STDOUT_HELP = (
    "Print the full, unbounded envelope to stdout (refused on a covered run)"
)

_MIME_BY_SUFFIX = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".sql": "application/sql",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


def add_run_folder_args(parser: Any) -> None:
    """Add ``--run-folder ID`` and ``--stdout`` to a writer subcommand."""
    parser.add_argument("--run-folder", default=None, metavar="ID", help=_RUN_FOLDER_HELP)
    parser.add_argument("--stdout", action="store_true", help=_STDOUT_HELP)


def kernel_available() -> bool:
    """Whether the ``starboard_core`` engagement kernel is installed.

    Without it no overlay can be enabled, so a writer keeps the plain public path;
    ``--run-folder`` is refused (``STORAGE_UNAVAILABLE``).
    """
    import importlib.util

    try:
        return importlib.util.find_spec("starboard_core.engagement.enforce") is not None
    except ModuleNotFoundError:
        return False


def mime_for(name: str) -> str:
    """MIME type for an artifact name, by suffix."""
    return _MIME_BY_SUFFIX.get(PurePosixPath(name).suffix.lower(), "application/octet-stream")


def _detect_overlay() -> OverlaySignal:
    """Overlay detection seam (tests pin it)."""
    from starboard_core.engagement.overlay import detect_overlay  # lazy – kernel dep

    return detect_overlay()


def _load_storage() -> EngagementStoragePort:
    """Engagement storage seam (tests inject ``InMemoryEngagementStorage``)."""
    from starboard_core.engagement.sink import load_engagement_storage

    return load_engagement_storage()


@contextmanager
def storage_refusals() -> Iterator[None]:
    """Map kernel storage refusals onto the exit-code contract.

    * ``LOCAL_STORAGE_REFUSED`` / ``STORAGE_UNAVAILABLE`` and a
      guard-refused local write -> :class:`StorageRefusedError` (exit 2).
    * An invalid or missing run descriptor -> :class:`ArgError` (exit 4).
    * Storage auth -> :class:`AuthError`.
    * Any other storage / integrity / access failure (``BLOCKED_ACCESS``,
      ``STORAGE_INTEGRITY``, ``NOT_FOUND``, ``STORAGE_ERROR``) ->
      :class:`StorageFailureError` (exit 7). A Drive object that vanishes during a run
      read or write is ``NOT_FOUND`` exit 7; a missing helper *input* (``--in`` ...) is
      mapped to :class:`NotFoundError` (exit 2) where it is read
      (:meth:`HelperRun.read_input`, :func:`read_drive_object`).
    * A Drive folder that needs operator reconciliation (a name taken by another
      identity, a widened ACL) -> ``STORAGE_ERROR`` :class:`StorageFailureError`
      (exit 7).
    """
    from starboard_core.engagement.commit import CommitError  # lazy – kernel dep
    from starboard_core.engagement.folders import FolderResolutionError
    from starboard_core.engagement.sink import (
        LocalStorageRefused,
        StorageUnavailableError,
    )
    from starboard_core.engagement.write_guard import LocalWriteRefused
    from starboard_core.ports.engagement_storage import (
        StorageAuthError,
        StorageError,
    )

    try:
        yield
    except (
        LocalStorageRefused,
        StorageUnavailableError,
        LocalWriteRefused,
    ) as exc:
        text = str(exc)
        code = getattr(exc, "code", "STORAGE_REFUSED")
        raise StorageRefusedError(text if text.startswith(code) else f"{code}: {text}") from exc
    except CommitError as exc:
        raise ArgError(f"--run-folder: {exc}") from exc
    except FolderResolutionError as exc:
        raise StorageFailureError(f"STORAGE_ERROR: {exc}") from exc
    except StorageAuthError as exc:
        raise AuthError(f"Storage authentication error: {exc}") from exc
    except StorageError as exc:
        failure = storage_failure(exc)
        if failure is None:
            raise
        raise failure from exc


def _refuse_reserved(path: str | os.PathLike[str] | PurePosixPath) -> None:
    """Refuse a reserved kernel record on a generic write (exit 2, ``RESERVED_PATH``).

    A host-chosen ``--out`` must not name a kernel record (``findings-manifest.json``,
    ``run-authorization.json``, ``analysis/identity-check.json`` ...): only the kernel
    writers write those, through :meth:`HelperRun.write_record`. Every trailing
    segment suffix of ``path`` is checked (the same scan :meth:`HelperRun.write_record`
    uses), so ``<run>/analysis/findings.json`` is refused, not just a reserved basename.
    """
    from starboard_core.engagement.sink import reserved_record  # lazy – kernel dep

    parts = PurePosixPath(Path(path).as_posix()).parts
    for depth in range(1, len(parts) + 1):
        rel = "/".join(parts[-depth:])
        kind = reserved_record(rel)
        if kind is not None:
            raise StorageRefusedError(
                f"RESERVED_PATH: {str(path)!r} is a reserved kernel record "
                f"({rel!r}, {kind}); choose another output path"
            )


@dataclass
class HelperRun:
    """One writer invocation: the storage decision and its artifact sink.

    ``decision`` / ``sink`` are ``None`` only on a plain public install without the
    engagement kernel: writes are then plain local writes (no overlay can exist).
    """

    decision: StorageDecision | None
    sink: ArtifactSink | None
    run_folder: str | None
    _storage: Callable[[], EngagementStoragePort]
    _auth: list[RunAuthorization] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        """Drive is mandatory and local writes are refused."""
        if self.decision is None:
            return False
        from starboard_core.engagement.enforce import covered  # lazy – kernel dep

        return covered(self.decision)

    @property
    def drive(self) -> bool:
        """Outputs go to the Drive run folder."""
        return self.sink is not None and self.sink.kind == "drive"

    def drive_sink(self) -> ArtifactSink:
        if self.sink is None or not self.drive:
            raise ArgError("this needs --run-folder")
        return self.sink

    def storage(self) -> EngagementStoragePort:
        """The engagement storage port (created once per invocation)."""
        return self._storage()

    def descriptor(self) -> RunAuthorization:
        """The run's validated descriptor (Drive runs only)."""
        if not self._auth:
            from starboard_core.engagement.commit import read_descriptor

            if not self.run_folder:
                raise ArgError("this command needs --run-folder")
            # The sink's opener already read it; reuse that instead of a second download.
            held = getattr(self.sink, "authorization", None)
            self._auth.append(
                held
                if held is not None
                else read_descriptor(self.storage(), self.run_folder)[0]
            )
        return self._auth[0]

    def scope_workspace_ids(self) -> tuple[str, ...]:
        ids = self.descriptor().authorized_scope.get("workspace_ids") or ()
        return tuple(str(i) for i in ids)

    def _bound_sink(self) -> LocalDirSink | None:
        """The run-dir sink of an internal-only local run, else ``None``.

        On ``internal_only_local`` every local output must stay inside the run dir
        (``local_root``); public local runs keep writing where they are told.
        """
        from starboard_core.engagement.policy import StoragePolicy  # lazy – kernel dep
        from starboard_core.engagement.sink import LocalDirSink

        if (
            self.decision is not None
            and self.decision.policy == StoragePolicy.INTERNAL_ONLY_LOCAL
            and isinstance(self.sink, LocalDirSink)
        ):
            return self.sink
        return None

    def run_relpath(self, path: str | os.PathLike[str]) -> str | None:
        """``path`` relative to the run dir of an internal-only local run (``None`` otherwise).

        Raises:
            StorageRefusedError: ``OUTSIDE_RUN_DIR`` (exit 2): ``path``'s realpath is
                not under the run dir's realpath (a symlink escape counts).
        """
        sink = self._bound_sink()
        if sink is None:
            return None
        root = os.path.realpath(sink.root)
        real = os.path.realpath(Path(path).expanduser())
        if real == root or not real.startswith(root + os.sep):
            raise StorageRefusedError(
                f"OUTSIDE_RUN_DIR: {str(path)!r} is outside the internal-only local run dir "
                f"{root}; write it inside the run"
            )
        return Path(os.path.relpath(real, root)).as_posix()

    def records_root(self, run_dir: Path) -> Path | None:
        """The resolved ``run_dir`` when kernel records may be written under it, else ``None``.

        Two cases keep kernel records (health, cases, actions, plays) in a local run
        dir: an internal-only local run (the :meth:`_bound_sink` run dir), and a
        public local run (overlay off, policy ``local``) whose sink is rooted at
        ``run_dir`` and whose ``analysis/run-authorization.json`` parses and records
        ``storage_policy: local``. A missing, unreadable or non-LOCAL descriptor, a
        covered or Drive run, and a plain install without the kernel are ``None``.
        Ordinary writers are unaffected (:meth:`run_relpath` is unchanged).
        """
        if self.decision is None:
            return None
        from starboard_core.engagement.policy import StoragePolicy  # lazy – kernel dep
        from starboard_core.engagement.sink import LocalDirSink

        real = Path(os.path.realpath(Path(run_dir).expanduser()))
        if not isinstance(self.sink, LocalDirSink) or os.path.realpath(
            self.sink.root
        ) != str(real):
            return None
        if self.decision.policy == StoragePolicy.INTERNAL_ONLY_LOCAL:
            return real
        if self.decision.policy != StoragePolicy.LOCAL:
            return None
        from starboard_skills.helpers.engagement.analysis_cmds import (  # lazy – no cycle
            read_authorization,
        )

        try:
            auth = read_authorization(real)
        except ArgError:
            return None
        return real if auth.storage_policy == StoragePolicy.LOCAL else None

    def write(
        self, path: str | os.PathLike[str] | PurePosixPath, data: bytes, mime: str | None = None
    ) -> StorageRef | None:
        """Write ``data`` at ``path``: a run relpath on Drive, else a local file.

        A local write goes through a :class:`LocalDirSink` rooted at the file's
        directory, so the storage decision still applies (plain write without the
        kernel); on an internal-only local run it goes through the run-dir sink and
        is refused outside the run dir (:meth:`run_relpath`). Returns the ref
        (``None`` for a plain write).
        """
        mime = mime or mime_for(str(path))
        if self.drive:
            _refuse_reserved(path)
            return self.drive_sink().put_bytes(str(path), data, mime)
        local = Path(path)
        if self.decision is None:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
            return None
        from starboard_core.engagement.sink import LocalDirSink  # lazy – kernel dep

        _refuse_reserved(local)
        rel, bound = self.run_relpath(local), self._bound_sink()
        if rel is not None and bound is not None:
            _refuse_reserved(rel)
            return bound.put_bytes(rel, data, mime)
        return LocalDirSink(local.parent, decision=self.decision).put_bytes(
            local.name, data, mime
        )

    def write_record(
        self, path: str | os.PathLike[str] | PurePosixPath, data: bytes, mime: str
    ) -> StorageRef | None:
        """Write a reserved kernel record (``analysis/findings.json`` ...) at ``path``.

        Goes through ``put_record``, so create-once records keep their bytes: on
        Drive ``path`` is the run relpath; locally the sink is rooted where the
        trailing segments of ``path`` name a kernel record. A plain write without the
        kernel. Returns the ref (``None`` for a plain write).

        Raises:
            ValueError: ``path`` is not a kernel record.
            SinkConflictError: A create-once record already holds different bytes.
        """
        if self.drive:
            return self.drive_sink().put_record(str(path), data, mime)
        local = Path(path)
        if self.decision is None:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
            return None
        from starboard_core.engagement.sink import (  # lazy – kernel dep
            LocalDirSink,
            reserved_record,
        )

        rel, bound = self.run_relpath(local), self._bound_sink()
        if rel is not None and bound is not None:
            if reserved_record(rel) in (None, "commit"):
                raise ValueError(f"{str(path)!r} is not a kernel record; write it with write()")
            return bound.put_record(rel, data, mime)
        parts = local.parts
        for depth in range(1, len(parts)):
            rel = "/".join(parts[-depth:])
            if reserved_record(rel) not in (None, "commit"):
                root = Path(*parts[:-depth])
                return LocalDirSink(root, decision=self.decision).put_record(rel, data, mime)
        raise ValueError(f"{str(path)!r} is not a kernel record; write it with write()")

    def read_input(self, flag: str, value: str) -> bytes:
        """Read an input flag: ``drive:<id>`` or a run relpath (Drive), else a local file."""
        if value.startswith(DRIVE_PREFIX):
            if not self.run_folder:
                raise ArgError(f"{flag} {value!r}: a drive: input needs --run-folder")
            return read_drive_object(self.storage(), value[len(DRIVE_PREFIX):], flag=flag)
        if self.drive:
            rel = relpath_flag(flag, value, covered=self.covered)
            from starboard_core.engagement.sink import ReadRefusedError
            from starboard_core.ports.engagement_storage import StorageNotFoundError

            try:
                return self.drive_sink().get_bytes(rel)
            except ReadRefusedError as exc:
                raise ArgError(f"{flag} {rel!r}: {exc}") from exc
            except StorageNotFoundError as exc:
                raise NotFoundError(f"{flag} {rel!r} is not in the run folder") from exc
        path = Path(value).expanduser()
        if not path.is_file():
            raise NotFoundError(f"{flag} file not found: {path}")
        return path.read_bytes()

    def root(self) -> SinkPath:
        """The run root as a :class:`SinkPath` (Drive runs)."""
        return SinkPath(".", view=_SinkView(self.drive_sink()))


@contextmanager
def helper_writer(
    *, run_folder: str | None, local_root: str | None, acquires: bool
) -> Iterator[HelperRun]:
    """Decide, gate, guard and open the sink for one helper writer.

    Wraps :func:`starboard_core.engagement.enforce.writer_context`: on a covered run
    the local write guard stays armed for the whole block. Kernel refusals are mapped
    by :func:`storage_refusals`. Without the kernel installed (a plain public
    install) the block runs unguarded with plain local writes, and ``--run-folder``
    is refused.
    """
    cache: list[EngagementStoragePort] = []

    def factory() -> EngagementStoragePort:
        if not cache:
            cache.append(_load_storage())
        return cache[0]

    if not kernel_available():
        if run_folder:
            raise StorageRefusedError(
                "STORAGE_UNAVAILABLE: --run-folder needs the starboard engagement kernel "
                "(install the starboard package)"
            )
        yield HelperRun(None, None, None, factory)
        return

    with storage_refusals(), ExitStack() as stack:
        from starboard_core.engagement.enforce import writer_context
        from starboard_core.ports.engagement_storage import StorageNotFoundError

        try:
            ctx = stack.enter_context(
                writer_context(
                    run_folder_id=run_folder,
                    local_root=local_root,
                    acquires_customer_data=acquires,
                    storage_factory=factory,
                    overlay=_detect_overlay(),
                )
            )
        except StorageNotFoundError as exc:
            # A missing helper target is exit 2; NOT_FOUND inside the run is exit 7.
            raise NotFoundError(f"--run-folder {run_folder!r}: run folder not found") from exc
        yield HelperRun(ctx.decision, ctx.sink, run_folder, factory)


def refuse_local(run: HelperRun, **flags: object) -> None:
    """On a covered run, refuse any truthy local-output flag (exit 2)."""
    if run.decision is None:
        return
    from starboard_core.engagement.enforce import refuse_local as _refuse

    _refuse(run.decision, **flags)


def relpath_flag(flag: str, value: str, *, covered: bool) -> str:
    """A ``--run-folder`` path flag is a run-relative path (a local path is refused)."""
    from starboard_core.engagement.reads import run_relpath  # lazy – kernel dep

    return run_relpath(flag, value, covered_run=covered, arg_error=ArgError)


#: Largest Drive object read as one input.
MAX_DRIVE_INPUT_BYTES = 64 * 2**20


def read_drive_object(
    storage: EngagementStoragePort,
    object_id: str,
    *,
    flag: str,
    max_bytes: int = MAX_DRIVE_INPUT_BYTES,
) -> bytes:
    """Bytes of one Drive file by ID (at most ``max_bytes``), verified against Drive.

    Raises:
        ArgError: The object is a folder or larger than ``max_bytes``.
        NotFoundError: No such object (a missing helper input, exit 2).
        StorageIntegrityError: The bytes do not match Drive's md5/size.
    """
    from starboard_core.engagement.reads import (  # lazy – kernel dep
        ReadRefusedError,
        read_verified,
    )
    from starboard_core.ports.engagement_storage import StorageNotFoundError

    try:
        return read_verified(storage, object_id, max_bytes=max_bytes)
    except ReadRefusedError as exc:
        raise ArgError(f"{flag} {DRIVE_PREFIX}{exc}") from exc
    except StorageNotFoundError as exc:
        raise NotFoundError(f"{flag} {DRIVE_PREFIX}{object_id}: not found") from exc


def local_run_dir(*paths: str | os.PathLike[str] | None) -> str | None:
    """The nearest ancestor of ``paths`` holding ``analysis/run-authorization.json``.

    Falls back to the first path's parent: the decision then reads no descriptor.
    """
    given = [Path(os.fspath(p)).expanduser() for p in paths if p]
    if not given:
        return None
    for p in given:
        for parent in (p, *p.parents):
            if (parent / "analysis" / "run-authorization.json").is_file():
                return str(parent)
    return str(given[0].parent)


def record_evidence(
    run: HelperRun,
    items: Sequence[tuple[StorageRef, str, int | None, bool]],
    *,
    source_kind: str,
) -> list[EvidenceRef]:
    """Record ``(ref, producer, row_count, truncated)`` items as evidence; Drive runs only.

    The kernel recorder (:func:`starboard_core.engagement.evidence.record_evidence`)
    with the run's authorized scope; the audience follows ``source_kind``.
    """
    if run.sink is None or not run.drive or not items:
        return []
    from starboard_core.engagement.evidence import (  # lazy – kernel dep
        record_evidence as record,
    )

    return record(
        run.sink,
        items,
        source_kind=source_kind,
        scope=run.scope_workspace_ids(),
        method_version=f"starboard-helper/{CONTRACT_VERSION}",
    )


class RunResult(dict[str, Any]):
    """A command result the dispatcher prints bounded and compact (run-folder mode)."""


def run_result(run: HelperRun, data: Mapping[str, Any], *, stdout: bool = False) -> dict[str, Any]:
    """``data`` plus the run IDs; a :class:`RunResult` on Drive unless ``--stdout``."""
    if not run.drive:
        return dict(data)
    sink = run.drive_sink()
    full = {
        "run_id": sink.run_id,
        "run_folder_id": run.run_folder,
        "refs": [r.to_dict() for r in sink.refs()],
        **data,
    }
    return full if stdout else RunResult(full)


def bounded(payload: Mapping[str, Any]) -> dict[str, Any]:
    """``payload`` within :data:`STDOUT_MAX_BYTES`; print it compact."""
    from starboard_core.engagement.stdout_budget import bound  # lazy – kernel dep

    return bound(payload, max_bytes=STDOUT_MAX_BYTES)


# --- Sink-backed paths ---------------------------------------------------- #
# The kernel is imported lazily throughout this section (starboard-skills depends
# only on databricks-sdk; the engagement kernel comes with the starboard package).
class _SinkView:
    """A sink plus a cached listing of its files."""

    def __init__(self, sink: ArtifactSink) -> None:
        self.sink = sink
        self._files: tuple[str, ...] | None = None

    def files(self) -> tuple[str, ...]:
        if self._files is None:
            self._files = tuple(self.sink.list(""))
        return self._files

    def invalidate(self) -> None:
        self._files = None


class SinkPath(PurePosixPath):
    """A run-relative path whose file operations go through an artifact sink.

    It quacks like the subset of :class:`pathlib.Path` the run-directory readers
    use (``is_file``/``is_dir``/``read_text``/``glob``/``write_text``…), so the same
    checks run over a Drive run folder. ``"."`` is the run root. It is never a
    local path: ``os.fspath`` raises.
    """

    def __init__(self, *args: Any, view: _SinkView) -> None:
        super().__init__(*args)
        self._view = view

    def with_segments(self, *pathsegments: Any) -> SinkPath:
        return type(self)(*pathsegments, view=self._view)

    def __fspath__(self) -> str:
        raise TypeError(f"{str(self)!r} is a run-folder path, not a local path")

    def _rel(self) -> str | None:
        text = str(self)
        if text == ".":
            return ""
        from starboard_core.engagement.sink import validate_relpath  # lazy – kernel dep

        try:
            return validate_relpath(text)
        except ValueError:
            return None

    def _children(self) -> Iterator[tuple[str, bool]]:
        """Direct ``(name, is_dir)`` children, each once."""
        rel = self._rel()
        if rel is None:
            return
        prefix = f"{rel}/" if rel else ""
        seen: set[str] = set()
        for f in self._view.files():
            if not f.startswith(prefix):
                continue
            head, sep, _ = f[len(prefix):].partition("/")
            if head and head not in seen:
                seen.add(head)
                yield head, bool(sep)

    # -- queries --
    def is_file(self) -> bool:
        rel = self._rel()
        return bool(rel) and rel in self._view.files()

    def is_dir(self) -> bool:
        rel = self._rel()
        if rel is None:
            return False
        return rel == "" or any(f.startswith(rel + "/") for f in self._view.files())

    def exists(self) -> bool:
        return self.is_file() or self.is_dir()

    def is_symlink(self) -> bool:
        return False

    def resolve(self, strict: bool = False) -> SinkPath:  # noqa: ARG002
        return self

    def absolute(self) -> SinkPath:
        return self

    def expanduser(self) -> SinkPath:
        return self

    def iterdir(self) -> Iterator[SinkPath]:
        for name, _ in self._children():
            yield self / name

    def glob(self, pattern: str) -> Iterator[SinkPath]:
        """Direct children matching ``pattern`` (no ``/`` or ``**`` patterns)."""
        if "/" in pattern:
            raise ValueError(f"SinkPath.glob supports single-segment patterns, not {pattern!r}")
        for name, _ in sorted(self._children()):
            if fnmatchcase(name, pattern):
                yield self / name

    def rglob(self, pattern: str) -> Iterator[SinkPath]:
        """Every file below this path whose name matches ``pattern``."""
        rel = self._rel()
        if rel is None:
            return
        prefix = f"{rel}/" if rel else ""
        for f in self._view.files():
            if f.startswith(prefix) and fnmatchcase(f.rpartition("/")[2], pattern):
                yield self.with_segments(f)

    # -- reads --
    def read_bytes(self) -> bytes:
        rel = self._rel()
        if not rel or not self.is_file():
            raise FileNotFoundError(errno.ENOENT, "not in the run folder", str(self))
        from starboard_core.ports.engagement_storage import StorageNotFoundError

        try:
            return self._view.sink.get_bytes(rel)
        except StorageNotFoundError as exc:
            raise FileNotFoundError(errno.ENOENT, "not in the run folder", str(self)) from exc

    def read_text(self, encoding: str | None = None, errors: str | None = None) -> str:
        return self.read_bytes().decode(encoding or "utf-8", errors or "strict")

    # -- writes (through the sink) --
    def write_bytes(self, data: bytes) -> int:
        rel = self._rel()
        if not rel:
            raise ValueError(f"{str(self)!r} is not a run-relative file path")
        self._view.sink.put_bytes(rel, bytes(data), mime_for(rel))
        self._view.invalidate()
        return len(data)

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,  # noqa: ARG002
    ) -> int:
        self.write_bytes(data.encode(encoding or "utf-8", errors or "strict"))
        return len(data)

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        """No-op: run-folder directories are created by the first write below them."""

    def unlink(self, missing_ok: bool = False) -> None:
        if not self.is_file():
            if missing_ok:
                return
            raise FileNotFoundError(errno.ENOENT, "not in the run folder", str(self))
        raise OSError(errno.EPERM, "run-folder artifacts are revised, never deleted", str(self))
