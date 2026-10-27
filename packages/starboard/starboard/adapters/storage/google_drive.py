# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Google Drive adapter for the engagement storage port (engagement-drive spec §3/§4).

Talks to Drive REST v3 directly with a synchronous :class:`httpx.Client`; the
Google MCP cannot move arbitrary bytes (phase-0 fact F4). Every call passes
``supportsAllDrives=true`` because the ASQs root lives in a shared drive (F2).

Uploads use the resumable protocol entirely in memory: at most one chunk is
buffered, a hard ``max_bytes`` cap is enforced, and the stored object is read
back and compared (size + MD5) before it is returned. Nothing is staged on
local disk.

Drive v3 has no etag / ``If-Match`` precondition (F5), so this adapter offers
no compare-and-set; callers reconcile duplicates by parent-scoped listing.

The bearer token comes from an injectable ``token_provider``; the default runs
``gcloud auth print-access-token`` once per process (held in memory only, never
written to disk) and again only after Drive rejects it. Tokens are never logged
or placed in exception messages.

One instance may be shared by several threads: ``httpx.Client`` is thread-safe
and the token is minted under a lock.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, urlsplit

import httpx
from starboard_core.ports.engagement_storage import (
    FOLDER_MIME,
    AccessInfo,
    DriveKind,
    Grant,
    GrantKind,
    StorageAuthError,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StorageObject,
    StoragePermissionError,
    StorageTransientError,
)

from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_core.ports.engagement_storage import EngagementStoragePort

logger = get_logger(__name__)

API_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/files"
UPLOAD_HOST = "www.googleapis.com"

#: Resumable-upload chunks (except the last) must be a multiple of this.
UPLOAD_GRANULARITY = 256 * 1024
DEFAULT_CHUNK_SIZE = 32 * UPLOAD_GRANULARITY  # 8 MiB
DEFAULT_MAX_BYTES = 512 * 1024 * 1024

FILE_FIELDS = (
    "id,name,mimeType,parents,appProperties,webViewLink,size,md5Checksum,"
    "headRevisionId,createdTime"
)
_LIST_FIELDS = f"nextPageToken,incompleteSearch,files({FILE_FIELDS})"
_PERMISSION_FIELDS = "nextPageToken,permissions(type,role,domain,emailAddress)"

AUTH_HINT = (
    "Authenticate Google Drive access with `gcloud auth login --enable-gdrive-access` "
    "(or the fe-google-tools google-auth skill), then retry."
)

_RATE_LIMIT_REASONS = frozenset({"userRateLimitExceeded", "rateLimitExceeded"})
_GRANT_KINDS: frozenset[str] = frozenset({"user", "group", "domain", "anyone"})


class _TransientError(StorageTransientError):
    """A retryable failure (429/5xx/rate-limit/transport) that was not retried away."""


class _SessionExpired(StorageTransientError):
    """Drive no longer knows the resumable session (404/410): restart the upload."""


#: Statuses Drive answers on a resumable-session URI once the session has expired.
_SESSION_GONE = (404, 410)
#: The 403 reason for a drive-wide search by a non-member with folder access.
_MEMBERSHIP_REQUIRED = "teamDriveMembershipRequired"


#: The default provider's token, shared by every adapter in the process (memory only).
_process_token: str | None = None
_process_token_lock = threading.Lock()


def _shared_gcloud_token(rejected: str | None) -> str:
    """The process-wide gcloud token; minted on first use and when ``rejected`` is it."""
    global _process_token
    with _process_token_lock:
        if _process_token is None or _process_token == rejected:
            _process_token = None
            _process_token = gcloud_access_token()
        return _process_token


def gcloud_access_token(
    *, application_default: bool = False, timeout: float = 30.0
) -> str:
    """Return a Google OAuth access token minted by the local ``gcloud`` CLI.

    Args:
        application_default: Use Application Default Credentials
            (``gcloud auth application-default print-access-token``) instead of
            the gcloud user credentials.
        timeout: Seconds to wait for ``gcloud``.

    Raises:
        StorageAuthError: ``gcloud`` is missing, fails, times out or prints
            nothing. The message says how to authenticate; it never contains
            command output that could carry a token.
    """
    binary = shutil.which("gcloud")
    if binary is None:
        raise StorageAuthError(f"gcloud CLI not found on PATH. {AUTH_HINT}")
    argv = [binary, "auth"]
    if application_default:
        argv.append("application-default")
    argv.append("print-access-token")
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise StorageAuthError(
            f"gcloud timed out minting a token. {AUTH_HINT}"
        ) from None
    except OSError as exc:
        raise StorageAuthError(
            f"gcloud could not be run ({type(exc).__name__}). {AUTH_HINT}"
        ) from None
    if result.returncode != 0:
        raise StorageAuthError(
            f"gcloud exited with status {result.returncode} minting a token. {AUTH_HINT}"
        )
    token = (result.stdout or "").strip()
    if not token:
        raise StorageAuthError(f"gcloud returned an empty access token. {AUTH_HINT}")
    return token


def _quote_literal(value: str) -> str:
    """Quote ``value`` as a Drive query string literal (escape ``\\`` then ``'``)."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _error_reason(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return ""
    if not isinstance(error, dict):
        return ""
    errors = error.get("errors") or []
    if errors and isinstance(errors[0], dict) and errors[0].get("reason"):
        return str(errors[0]["reason"])
    return str(error.get("status") or "")


def _is_transient(status: int, reason: str) -> bool:
    return (
        status == 429
        or status >= 500
        or (status == 403 and reason in _RATE_LIMIT_REASONS)
    )


def _to_object(data: Mapping[str, Any]) -> StorageObject:
    size = data.get("size")
    return StorageObject(
        id=str(data["id"]),
        name=str(data.get("name", "")),
        mime_type=str(data.get("mimeType", "")),
        parent_ids=tuple(data.get("parents") or ()),
        properties={
            str(k): str(v) for k, v in (data.get("appProperties") or {}).items()
        },
        web_link=data.get("webViewLink"),
        size=int(size) if size is not None else None,
        md5=data.get("md5Checksum"),
        revision=data.get("headRevisionId"),
        created_time=data.get("createdTime"),
    )


def _grant_domain(perm: Mapping[str, Any]) -> str | None:
    if perm.get("type") == "domain":
        domain = perm.get("domain")
        return str(domain).lower() if domain else None
    email = str(perm.get("emailAddress") or "")
    return email.rsplit("@", 1)[1].lower() if "@" in email else None


def _fingerprint(perms: list[Mapping[str, Any]]) -> str:
    """SHA-256 over the sorted full grants, so ACL changes show without storing names."""
    rows = sorted(
        (
            str(p.get("type", "")),
            str(p.get("role", "")),
            str(p.get("emailAddress") or p.get("domain") or "").lower(),
        )
        for p in perms
    )
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _session_alive(response: httpx.Response) -> httpx.Response:
    """Return ``response``, or raise ``_SessionExpired`` if Drive dropped the session."""
    if response.status_code in _SESSION_GONE:
        raise _SessionExpired(
            f"Drive upload session expired (HTTP {response.status_code}); "
            "the write was not finalized and can be retried"
        )
    return response


def _committed_bytes(response: httpx.Response) -> int:
    """Bytes the server has persisted, from a ``308`` ``Range: bytes=0-N`` header."""
    header = response.headers.get("Range")
    if not header:
        return 0
    try:
        return int(header.rsplit("-", 1)[1]) + 1
    except (IndexError, ValueError):
        raise StorageError(
            f"Drive upload returned a malformed Range header: {header!r}"
        ) from None


class GoogleDriveStorage:
    """:class:`EngagementStoragePort` backed by the Google Drive REST v3 API.

    Args:
        token_provider: Returns a bearer access token. Called lazily and again
            once after an HTTP 401. Defaults to :func:`gcloud_access_token`,
            minted once per process and shared by every instance.
        client: Optional preconfigured ``httpx.Client`` (owned by the caller).
        quota_project: Optional ``x-goog-user-project`` header value, needed
            when the token comes from user Application Default Credentials.
        chunk_size: Resumable-upload chunk size; a multiple of 256 KiB.
        max_bytes: Hard cap on one upload; exceeding it raises
            :class:`StorageError` before the upload is finalized.
        max_retries: Retries after the first attempt for 429/5xx/rate-limit/
            transport failures; the default of 2 is 3 attempts in total. Other
            4xx responses are never retried, nor is ``create_folder`` (a
            non-idempotent create).
        backoff_base: First retry delay in seconds (doubles each attempt).
        backoff_max: Upper bound on a single retry delay (1 s, 2 s, then 4 s
            by default).
        sleep: Sleep function (injectable for tests).
        timeout: Per-request timeout in seconds for the default client.
    """

    def __init__(
        self,
        token_provider: Callable[[], str] | None = None,
        *,
        client: httpx.Client | None = None,
        quota_project: str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_retries: int = 2,
        backoff_base: float = 1.0,
        backoff_max: float = 4.0,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 60.0,
    ) -> None:
        if chunk_size <= 0 or chunk_size % UPLOAD_GRANULARITY:
            raise ValueError("chunk_size must be a positive multiple of 256 KiB")
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        self._token_provider = token_provider
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._quota_project = quota_project
        self._chunk_size = chunk_size
        self._max_bytes = max_bytes
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._sleep = sleep
        self._token: str | None = None
        self._rejected: str | None = None
        self._token_lock = threading.Lock()
        self._principal_id: str | None = None

    def __repr__(self) -> str:
        return f"GoogleDriveStorage(api={API_BASE!r}, max_bytes={self._max_bytes})"

    def close(self) -> None:
        """Close the HTTP client if this adapter created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GoogleDriveStorage:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ transport

    def _access_token(self) -> str:
        with self._token_lock:
            if self._token is None:
                token = (
                    _shared_gcloud_token(self._rejected)
                    if self._token_provider is None
                    else self._token_provider()
                )
                if not token:
                    raise StorageAuthError(
                        f"No Google access token available. {AUTH_HINT}"
                    )
                self._token = token
            return self._token

    def _reject_token(self, token: str) -> None:
        """Drop ``token`` after a 401 so the next request mints a fresh one."""
        with self._token_lock:
            self._rejected = token
            if self._token == token:
                self._token = None

    def _backoff(self, attempt: int, label: str, why: str) -> None:
        delay = min(self._backoff_max, self._backoff_base * (2**attempt))
        logger.warning(
            "drive_request_retry",
            operation=label,
            reason=why,
            attempt=attempt + 1,
            delay_s=delay,
        )
        self._sleep(delay)

    def _send(
        self,
        method: str,
        url: str,
        *,
        label: str,
        params: Mapping[str, str] | None = None,
        json_body: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
        retry: bool = True,
        stream: bool = False,
    ) -> httpx.Response:
        """Send one Drive request with auth refresh, bounded retry and error mapping.

        ``label`` names the operation in messages; URLs (which may carry folder
        names in ``q`` or an upload-session ID) and tokens are never included.
        """
        refreshed = False
        attempt = 0
        while True:
            req_headers = dict(headers or {})
            token = self._access_token()
            req_headers["Authorization"] = f"Bearer {token}"
            if self._quota_project:
                req_headers["x-goog-user-project"] = self._quota_project
            request = self._client.build_request(
                method,
                url,
                params=params,
                json=json_body,
                content=content,
                headers=req_headers,
            )
            try:
                response = self._client.send(request, stream=stream)
            except httpx.TransportError as exc:
                why = type(exc).__name__
                if retry and attempt < self._max_retries:
                    self._backoff(attempt, label, why)
                    attempt += 1
                    continue
                raise _TransientError(f"Drive {label} failed: {why}") from None
            status = response.status_code
            if status in expected:
                return response
            if stream:
                response.read()
                response.close()
            reason = _error_reason(response)
            if status == 401:
                if not refreshed:
                    refreshed = True
                    self._reject_token(token)
                    continue
                raise StorageAuthError(
                    f"Drive {label} was rejected as unauthenticated. {AUTH_HINT}"
                )
            if _is_transient(status, reason):
                if retry and attempt < self._max_retries:
                    self._backoff(attempt, label, f"HTTP {status} {reason}".strip())
                    attempt += 1
                    continue
                raise _TransientError(
                    f"Drive {label} failed: HTTP {status} {reason}".strip()
                )
            detail = f"Drive {label} failed: HTTP {status} {reason}".strip()
            if status == 403:
                raise StoragePermissionError(detail)
            if status == 404:
                raise StorageNotFoundError(detail)
            raise StorageError(detail)

    def _get_json(
        self, path: str, *, label: str, params: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        query = {"supportsAllDrives": "true", **(params or {})}
        return cast(
            dict[str, Any],
            self._send("GET", f"{API_BASE}/{path}", label=label, params=query).json(),
        )

    # ---------------------------------------------------------------------- reads

    def root_folder_id(self) -> str:
        return str(
            self._get_json("files/root", label="get root", params={"fields": "id"})[
                "id"
            ]
        )

    def principal_id(self) -> str:
        """Drive ``permissionId`` of the authenticated principal (never an email); cached."""
        if self._principal_id is None:
            about = self._get_json(
                "about", label="get principal", params={"fields": "user(permissionId)"}
            )
            permission_id = (about.get("user") or {}).get("permissionId")
            if not permission_id:
                raise StorageError("Drive get principal returned no permissionId")
            self._principal_id = str(permission_id)
        return self._principal_id

    def get(self, object_id: str) -> StorageObject:
        data = self._get_json(
            f"files/{quote(object_id, safe='')}",
            label="get file",
            params={"fields": FILE_FIELDS},
        )
        return _to_object(data)

    def list_children(
        self,
        parent_id: str,
        *,
        name: str | None = None,
        folders_only: bool = False,
    ) -> list[StorageObject]:
        clauses = [f"{_quote_literal(parent_id)} in parents", "trashed = false"]
        if name is not None:
            clauses.append(f"name = {_quote_literal(name)}")
        if folders_only:
            clauses.append(f"mimeType = {_quote_literal(FOLDER_MIME)}")
        params = {
            "q": " and ".join(clauses),
            "fields": _LIST_FIELDS,
            "pageSize": "1000",
            "includeItemsFromAllDrives": "true",
        }
        found: list[StorageObject] = []
        while True:
            page = self._get_json("files", label="list children", params=params)
            if page.get("incompleteSearch"):
                # A partial listing could hide an existing folder and cause a duplicate.
                raise StorageError("Drive list children returned an incomplete search")
            found.extend(_to_object(item) for item in page.get("files") or ())
            token = page.get("nextPageToken")
            if not token:
                return found
            params = {**params, "pageToken": str(token)}

    def find_by_property(
        self, key: str, value: str, *, drive_id: str | None = None
    ) -> list[StorageObject]:
        """One paged ``files.list`` on an ``appProperties`` key/value pair.

        ``drive_id`` searches that shared drive (``corpora=drive``); ``None``
        searches the operator's corpus (``corpora=user``). An incomplete search, or a
        shared-drive search refused because the operator has folder access but is not
        a member (``teamDriveMembershipRequired``), raises :class:`StorageError`
        rather than returning a partial result.
        """
        clause = (
            f"appProperties has {{ key={_quote_literal(key)} and "
            f"value={_quote_literal(value)} }}"
        )
        params = {
            "q": f"{clause} and trashed = false",
            "fields": _LIST_FIELDS,
            "pageSize": "1000",
            "includeItemsFromAllDrives": "true",
            "corpora": "user",
        }
        if drive_id:
            params.update({"corpora": "drive", "driveId": drive_id})
        found: list[StorageObject] = []
        while True:
            try:
                page = self._get_json("files", label="find by property", params=params)
            except StoragePermissionError as exc:
                # Folder access without shared-drive membership: a drive-wide search is
                # refused, but parent-scoped listing works. The search could not answer
                # (callers then walk the folder); it is not a permission loss.
                if drive_id and _MEMBERSHIP_REQUIRED in str(exc):
                    raise StorageError(
                        f"{exc}: not a member of shared drive {drive_id}; search the "
                        "folder by parents instead"
                    ) from exc
                raise
            if page.get("incompleteSearch"):
                raise StorageError(
                    "Drive find by property returned an incomplete search"
                )
            found.extend(_to_object(item) for item in page.get("files") or ())
            token = page.get("nextPageToken")
            if not token:
                return found
            params = {**params, "pageToken": str(token)}

    # --------------------------------------------------------------------- writes

    def trash(self, object_id: str) -> None:
        """Move ``object_id`` to the Drive trash (``trashed: true``; recoverable)."""
        self._send(
            "PATCH",
            f"{API_BASE}/files/{quote(object_id, safe='')}",
            label="trash file",
            params={"supportsAllDrives": "true", "fields": "id"},
            json_body={"trashed": True},
        )

    def create_folder(
        self, parent_id: str, name: str, properties: Mapping[str, str]
    ) -> StorageObject:
        body = {
            "name": name,
            "mimeType": FOLDER_MIME,
            "parents": [parent_id],
            "appProperties": dict(properties),
        }
        response = self._send(
            "POST",
            f"{API_BASE}/files",
            label="create folder",
            params={"supportsAllDrives": "true", "fields": FILE_FIELDS},
            json_body=body,
            # Not idempotent: a lost response plus a retry creates a duplicate.
            retry=False,
        )
        return _to_object(response.json())

    def update(
        self,
        object_id: str,
        *,
        name: str | None = None,
        properties: Mapping[str, str] | None = None,
        add_parent_id: str | None = None,
        remove_parent_id: str | None = None,
    ) -> StorageObject:
        """PATCH metadata (``appProperties`` keys merge), then verify via read-back."""
        params = {"supportsAllDrives": "true", "fields": FILE_FIELDS}
        if add_parent_id is not None:
            params["addParents"] = add_parent_id
        if remove_parent_id is not None:
            params["removeParents"] = remove_parent_id
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if properties is not None:
            body["appProperties"] = dict(properties)
        self._send(
            "PATCH",
            f"{API_BASE}/files/{quote(object_id, safe='')}",
            label="update file",
            params=params,
            json_body=body,
        )
        stored = self.get(object_id)
        problems: list[str] = []
        if name is not None and stored.name != name:
            problems.append("name")
        if properties is not None and any(
            stored.properties.get(k) != str(v) for k, v in properties.items()
        ):
            problems.append("properties")
        if add_parent_id is not None and add_parent_id not in stored.parent_ids:
            problems.append("added parent")
        if remove_parent_id is not None and remove_parent_id in stored.parent_ids:
            problems.append("removed parent")
        if problems:
            logger.error(
                "drive_update_integrity_mismatch",
                file_id=object_id,
                mismatched=problems,
            )
            raise StorageIntegrityError(
                f"Drive object {object_id} failed read-back after update: "
                f"{', '.join(problems)} not applied"
            )
        return stored

    # --------------------------------------------------------------------- access

    def inspect_access(self, object_id: str) -> AccessInfo:
        file_id = quote(object_id, safe="")
        meta = self._get_json(
            f"files/{file_id}",
            label="get capabilities",
            params={"fields": "id,driveId,capabilities(canAddChildren)"},
        )
        drive_id = str(meta["driveId"]) if meta.get("driveId") else None
        can_add = bool((meta.get("capabilities") or {}).get("canAddChildren", False))
        drive_kind: DriveKind = "shared_drive" if drive_id else "my_drive"
        perms: list[Mapping[str, Any]] = []
        params = {"fields": _PERMISSION_FIELDS, "pageSize": "100"}
        try:
            while True:
                page = self._get_json(
                    f"files/{file_id}/permissions",
                    label="list permissions",
                    params=params,
                )
                perms.extend(page.get("permissions") or ())
                token = page.get("nextPageToken")
                if not token:
                    break
                params = {**params, "pageToken": str(token)}
        except StoragePermissionError:
            # The operator cannot read the ACL: report it as unknown, not as an error.
            return AccessInfo(object_id, can_add, drive_kind, drive_id, complete=False)
        grants = tuple(
            Grant(
                kind=cast(GrantKind, p["type"]),
                role=str(p.get("role", "")),
                domain=None if p["type"] == "anyone" else _grant_domain(p),
            )
            for p in perms
            if p.get("type") in _GRANT_KINDS
        )
        return AccessInfo(
            object_id,
            can_add,
            drive_kind,
            drive_id,
            grants=grants,
            fingerprint=_fingerprint(perms),
            # An unrecognized grantee type cannot be summarized: treat the ACL as unknown.
            complete=len(grants) == len(perms),
        )

    # --------------------------------------------------------------------- upload

    def put_stream(
        self,
        parent_id: str,
        name: str,
        mime_type: str,
        chunks: Iterable[bytes],
        *,
        properties: Mapping[str, str],
    ) -> StorageObject:
        """Resumable in-memory upload, then read-back verification of size and MD5.

        Protocol: POST metadata to open a session (``Location`` = session URI);
        PUT full ``chunk_size`` slices as ``bytes a-b/*`` only once more data is
        known to follow, so the last request always carries the total
        (``bytes a-b/N``); an empty stream finalizes with ``bytes */0``. A
        ``308`` reply's ``Range`` header says how much was persisted and the
        unacknowledged tail is resent. After a transient failure the session is
        queried with ``bytes */*`` (``bytes */N`` when finalizing) and resumed.
        Until the final request succeeds Drive creates no file, so exceeding
        ``max_bytes`` leaves nothing behind.
        """
        if mime_type.startswith("application/vnd.google-apps."):
            raise StorageError(
                "put_stream uploads raw bytes; native Google types cannot be checksum-verified"
            )
        metadata = {
            "name": name,
            "parents": [parent_id],
            "mimeType": mime_type,
            "appProperties": dict(properties),
        }
        return self._upload_restartable(
            lambda: self._open_session("POST", UPLOAD_BASE, mime_type, metadata),
            chunks,
            landed=lambda: self._landed(parent_id, name, properties, chunks),
        )

    def _landed(
        self,
        parent_id: str,
        name: str,
        properties: Mapping[str, str],
        chunks: Iterable[bytes],
    ) -> StorageObject | None:
        """The file a lost final request already created: same name, properties, size, MD5.

        A final upload request can finalize the file and still lose its reply; when
        the status query then finds the session gone, a restart would create a
        second file (run 10: two ``storage-preflight.json`` records).
        """
        data = b"".join(chunks)
        md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
        same = [
            c
            for c in self.list_children(parent_id, name=name)
            if not c.is_folder
            and all(c.properties.get(k) == v for k, v in properties.items())
            and c.size == len(data)
            and (c.md5 or "").lower() == md5
        ]
        return min(same, key=lambda c: (c.created_time or "", c.id)) if same else None

    def update_stream(
        self, object_id: str, mime_type: str, chunks: Iterable[bytes]
    ) -> StorageObject:
        """Replace the content of an existing file (new head revision), same protocol as put_stream."""
        if mime_type.startswith("application/vnd.google-apps."):
            raise StorageError(
                "update_stream uploads raw bytes; native Google types cannot be checksum-verified"
            )
        url = f"{UPLOAD_BASE}/{quote(object_id, safe='')}"
        return self._upload_restartable(
            lambda: self._open_session("PATCH", url, mime_type, None), chunks
        )

    def _upload_restartable(
        self,
        open_session: Callable[[], str],
        chunks: Iterable[bytes],
        *,
        landed: Callable[[], StorageObject | None] | None = None,
    ) -> StorageObject:
        """Upload through a new session; restart once if Drive expires the session.

        An expired session cannot be resumed, so the content is sent again from
        byte 0. Only content that can be replayed (a sequence of chunks) is
        restarted; otherwise, or on a second expiry, the retryable
        ``StorageTransientError`` propagates. Before a create restarts, ``landed``
        returns the identical file a lost final request already created, if any.
        """
        try:
            return self._upload(open_session(), chunks)
        except _SessionExpired:
            if not isinstance(chunks, Sequence):
                raise
            if landed is not None and (found := landed()) is not None:
                logger.warning("drive_upload_already_finalized", file_id=found.id)
                return found
            logger.warning("drive_upload_restart", reason="upload session expired")
            return self._upload(open_session(), chunks)

    def _upload(self, session: str, chunks: Iterable[bytes]) -> StorageObject:
        digest = hashlib.md5(usedforsecurity=False)
        buffer = bytearray()
        offset = 0  # absolute position of buffer[0]
        total = 0
        for piece in chunks:
            if not piece:
                continue
            if total + len(piece) > self._max_bytes:
                raise StorageError(
                    f"upload exceeds max_bytes={self._max_bytes}; not finalized"
                )
            total += len(piece)
            digest.update(piece)
            view = memoryview(piece)
            while view:
                if len(buffer) == self._chunk_size:
                    offset = self._put_chunk(session, buffer, offset, None)
                take = min(self._chunk_size - len(buffer), len(view))
                buffer += view[:take]
                view = view[take:]
        file_id = self._finish(session, buffer, offset, total)
        return self._verify(file_id, total, digest.hexdigest())

    def _open_session(
        self,
        method: str,
        url: str,
        mime_type: str,
        metadata: Mapping[str, Any] | None,
    ) -> str:
        # Retrying session initiation on 429/5xx is safe, unlike ``create_folder``:
        # Drive creates no file until the final upload request succeeds, so a lost
        # response can only orphan an unused session URI, never a duplicate object.
        response = self._send(
            method,
            url,
            label="open upload session",
            params={
                "uploadType": "resumable",
                "supportsAllDrives": "true",
                "fields": "id",
            },
            json_body=metadata,
            headers={"X-Upload-Content-Type": mime_type},
        )
        location = response.headers.get("Location")
        if not location:
            raise StorageError("Drive open upload session returned no session URI")
        # The bearer token is sent to this URI: only accept the Drive upload host.
        # The URI carries the session ID, so it is never echoed in the error.
        try:
            parts = urlsplit(location)
            trusted = parts.scheme == "https" and parts.hostname == UPLOAD_HOST
        except ValueError:
            trusted = False
        if not trusted:
            raise StorageError(
                f"Drive open upload session returned a session URI outside "
                f"https://{UPLOAD_HOST}; refusing to send credentials to it"
            )
        return location

    def _upload_request(
        self, session: str, content: bytes, content_range: str
    ) -> httpx.Response | None:
        """PUT to the session; ``None`` means a transient failure (caller resyncs)."""
        try:
            response = self._send(
                "PUT",
                session,
                label="upload chunk",
                content=content,
                headers={"Content-Range": content_range},
                expected=(200, 201, 308, *_SESSION_GONE),
                retry=False,
            )
        except _TransientError:
            return None
        return _session_alive(response)

    def _resync(self, session: str, total: int | None, attempt: int) -> httpx.Response:
        """Back off, then ask the session how many bytes it has persisted."""
        if attempt >= self._max_retries:
            raise StorageTransientError(
                "Drive upload failed after repeated transient errors"
            )
        self._backoff(attempt, "upload chunk", "transient failure")
        return _session_alive(
            self._send(
                "PUT",
                session,
                label="query upload status",
                content=b"",
                headers={"Content-Range": f"bytes */{'*' if total is None else total}"},
                expected=(200, 201, 308, *_SESSION_GONE),
            )
        )

    def _apply_ack(
        self, response: httpx.Response, buffer: bytearray, offset: int
    ) -> int:
        """Drop the acknowledged prefix of ``buffer``; return the new offset."""
        committed = _committed_bytes(response)
        if committed < offset or committed > offset + len(buffer):
            raise StorageError(
                "Drive upload session lost acknowledged bytes; restart the upload"
            )
        del buffer[: committed - offset]
        return committed

    def _put_chunk(
        self, session: str, buffer: bytearray, offset: int, total: int | None
    ) -> int:
        """Send ``buffer`` as a non-final chunk until fully acknowledged by a 308."""
        attempts = 0
        while buffer:
            end = offset + len(buffer) - 1
            response = self._upload_request(
                session, bytes(buffer), f"bytes {offset}-{end}/*"
            )
            if response is None:
                response = self._resync(session, total, attempts)
                attempts += 1
            if response.status_code != 308:
                raise StorageError(
                    "Drive finalized the upload before the last chunk was sent"
                )
            before = len(buffer)
            offset = self._apply_ack(response, buffer, offset)
            if len(buffer) == before:
                attempts += 1
                if attempts > self._max_retries:
                    raise StorageError("Drive upload made no progress")
            elif len(buffer) % UPLOAD_GRANULARITY:
                # A non-final request must be a 256 KiB multiple: keep the tail
                # and let the caller refill the buffer before resending.
                return offset
        return offset

    def _finish(self, session: str, buffer: bytearray, offset: int, total: int) -> str:
        """Send the final request (with the known total) and return the file ID."""
        attempts = 0
        while True:
            if buffer:
                content_range = f"bytes {offset}-{offset + len(buffer) - 1}/{total}"
            else:
                content_range = f"bytes */{total}"
            response = self._upload_request(session, bytes(buffer), content_range)
            if response is None:
                response = self._resync(session, total, attempts)
                attempts += 1
            if response.status_code in (200, 201):
                return str(response.json()["id"])
            before = len(buffer)
            offset = self._apply_ack(response, buffer, offset)
            if len(buffer) == before:
                attempts += 1
                if attempts > self._max_retries:
                    raise StorageError("Drive upload made no progress while finalizing")

    def _verify(self, file_id: str, size: int, md5: str) -> StorageObject:
        stored = self.get(file_id)
        if stored.size != size or (stored.md5 or "").lower() != md5:
            logger.error(
                "drive_upload_integrity_mismatch",
                file_id=file_id,
                sent_size=size,
                stored_size=stored.size,
            )
            raise StorageIntegrityError(
                f"Drive object {file_id} failed read-back: sent {size} bytes md5 {md5}, "
                f"stored {stored.size} bytes md5 {stored.md5}"
            )
        return stored

    # ------------------------------------------------------------------- download

    def get_stream(
        self, object_id: str, revision: str | None = None
    ) -> Iterator[bytes]:
        file_id = quote(object_id, safe="")
        if revision is None:
            url = f"{API_BASE}/files/{file_id}"
            params = {"alt": "media", "supportsAllDrives": "true"}
        else:
            url = f"{API_BASE}/files/{file_id}/revisions/{quote(revision, safe='')}"
            params = {"alt": "media"}
        # Open eagerly so auth/not-found errors raise here, not on first next().
        response = self._send("GET", url, label="download", params=params, stream=True)
        return _iter_and_close(response)


def _iter_and_close(response: httpx.Response) -> Iterator[bytes]:
    try:
        yield from response.iter_bytes()
    finally:
        response.close()


if TYPE_CHECKING:

    def _conforms(storage: GoogleDriveStorage) -> EngagementStoragePort:
        return storage
