# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for the Google Drive engagement-storage adapter (all HTTP mocked)."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from starboard.adapters.storage import google_drive
from starboard.adapters.storage.google_drive import (
    API_BASE,
    UPLOAD_BASE,
    GoogleDriveStorage,
    gcloud_access_token,
)
from starboard_core.ports.engagement_storage import (
    FOLDER_MIME,
    EngagementStoragePort,
    Grant,
    StorageAuthError,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StoragePermissionError,
    StorageTransientError,
)

TOKEN = "ya29.SECRET-TOKEN-do-not-leak"
FILES = f"{API_BASE}/files"
SESSION = f"{UPLOAD_BASE}?uploadType=resumable&upload_id=SESSION123"
KIB256 = 256 * 1024


class _Tokens:
    """Token provider that hands out a fresh token on each call."""

    def __init__(self, *tokens: str) -> None:
        self._tokens = list(tokens) or [TOKEN]
        self.calls = 0

    def __call__(self) -> str:
        token = self._tokens[min(self.calls, len(self._tokens) - 1)]
        self.calls += 1
        return token


def _storage(**kwargs: Any) -> GoogleDriveStorage:
    kwargs.setdefault("token_provider", _Tokens())
    kwargs.setdefault("sleep", lambda _s: None)
    return GoogleDriveStorage(**kwargs)


def _err(status: int, reason: str) -> httpx.Response:
    body = {
        "error": {"code": status, "message": "nope", "errors": [{"reason": reason}]}
    }
    return httpx.Response(status, json=body)


def _file(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "F1",
        "name": "a.json",
        "mimeType": "application/json",
        "parents": ["P1"],
        "appProperties": {"starboard_key": "k1"},
        "webViewLink": "https://drive.google.com/file/d/F1/view",
        "size": "3",
        "md5Checksum": hashlib.md5(b"abc").hexdigest(),
        "headRevisionId": "R1",
        "createdTime": "2026-10-07T00:00:00.000Z",
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- port


def test_conforms_to_port() -> None:
    assert isinstance(_storage(), EngagementStoragePort)


def test_module_does_not_import_tempfile() -> None:
    source = Path(google_drive.__file__).read_text(encoding="utf-8")
    assert "tempfile" not in source


def test_repr_hides_token() -> None:
    storage = _storage(token_provider=lambda: TOKEN)
    storage._access_token()
    assert TOKEN not in repr(storage)


# ------------------------------------------------------------------ simple reads


@respx.mock
def test_root_folder_id() -> None:
    route = respx.get(f"{FILES}/root").mock(
        return_value=httpx.Response(200, json={"id": "ROOT"})
    )
    assert _storage().root_folder_id() == "ROOT"
    req = route.calls.last.request
    assert req.url.params["fields"] == "id"
    assert req.url.params["supportsAllDrives"] == "true"
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"


@respx.mock
def test_get_maps_metadata() -> None:
    respx.get(f"{FILES}/F1").mock(return_value=httpx.Response(200, json=_file()))
    obj = _storage().get("F1")
    assert obj.id == "F1"
    assert obj.parent_ids == ("P1",)
    assert obj.properties == {"starboard_key": "k1"}
    assert obj.size == 3
    assert obj.md5 == hashlib.md5(b"abc").hexdigest()
    assert obj.revision == "R1"
    assert obj.web_link and obj.created_time
    assert not obj.is_folder


@respx.mock
def test_quota_project_header() -> None:
    route = respx.get(f"{FILES}/root").mock(
        return_value=httpx.Response(200, json={"id": "ROOT"})
    )
    _storage(quota_project="my-proj").root_folder_id()
    assert route.calls.last.request.headers["x-goog-user-project"] == "my-proj"


# ----------------------------------------------------------------- list_children


@respx.mock
def test_list_children_query_escaping_and_flags() -> None:
    route = respx.get(FILES).mock(return_value=httpx.Response(200, json={"files": []}))
    _storage().list_children("P'1", name="O'Brien \\ Co", folders_only=True)
    params = route.calls.last.request.url.params
    assert params["q"] == (
        "'P\\'1' in parents and trashed = false"
        " and name = 'O\\'Brien \\\\ Co'"
        f" and mimeType = '{FOLDER_MIME}'"
    )
    assert params["supportsAllDrives"] == "true"
    assert params["includeItemsFromAllDrives"] == "true"
    for f in (
        "appProperties",
        "md5Checksum",
        "headRevisionId",
        "createdTime",
        "parents",
    ):
        assert f in params["fields"]
    assert "nextPageToken" in params["fields"]


@respx.mock
def test_list_children_plain_query() -> None:
    route = respx.get(FILES).mock(return_value=httpx.Response(200, json={"files": []}))
    _storage().list_children("P1")
    assert (
        route.calls.last.request.url.params["q"]
        == "'P1' in parents and trashed = false"
    )


@respx.mock
def test_list_children_paginates_and_maps_app_properties() -> None:
    route = respx.get(FILES).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "files": [_file(id="A", appProperties={"k": "v"})],
                    "nextPageToken": "T2",
                },
            ),
            httpx.Response(200, json={"files": [_file(id="B", appProperties=None)]}),
        ]
    )
    objs = _storage().list_children("P1")
    assert [o.id for o in objs] == ["A", "B"]
    assert objs[0].properties == {"k": "v"}
    assert objs[1].properties == {}
    assert "pageToken" not in route.calls[0].request.url.params
    assert route.calls[1].request.url.params["pageToken"] == "T2"


@respx.mock
def test_list_children_incomplete_search_fails_closed() -> None:
    respx.get(FILES).mock(
        return_value=httpx.Response(200, json={"files": [], "incompleteSearch": True})
    )
    with pytest.raises(StorageError):
        _storage().list_children("P1")


# --------------------------------------------------------------- find_by_property


@respx.mock
def test_find_by_property_queries_app_properties_in_the_user_corpus() -> None:
    route = respx.get(FILES).mock(return_value=httpx.Response(200, json={"files": []}))
    assert _storage().find_by_property("starboard_run", "r'1") == []
    params = route.calls.last.request.url.params
    assert params["q"] == (
        "appProperties has { key='starboard_run' and value='r\\'1' }"
        " and trashed = false"
    )
    assert params["corpora"] == "user"
    assert "driveId" not in params
    assert params["supportsAllDrives"] == "true"
    assert params["includeItemsFromAllDrives"] == "true"
    assert params["pageSize"] == "1000"
    assert "parents" in params["fields"] and "md5Checksum" in params["fields"]


@respx.mock
def test_find_by_property_scopes_a_shared_drive_and_paginates() -> None:
    route = respx.get(FILES).mock(
        side_effect=[
            httpx.Response(200, json={"files": [_file(id="A")], "nextPageToken": "T2"}),
            httpx.Response(200, json={"files": [_file(id="B")]}),
        ]
    )
    objs = _storage().find_by_property("k", "v", drive_id="SD1")
    assert [o.id for o in objs] == ["A", "B"]
    first = route.calls[0].request.url.params
    assert first["corpora"] == "drive" and first["driveId"] == "SD1"
    assert "pageToken" not in first
    assert route.calls[1].request.url.params["pageToken"] == "T2"


@respx.mock
def test_find_by_property_incomplete_search_fails_closed() -> None:
    respx.get(FILES).mock(
        return_value=httpx.Response(200, json={"files": [], "incompleteSearch": True})
    )
    with pytest.raises(StorageError) as exc:
        _storage().find_by_property("k", "v")
    assert not isinstance(exc.value, StorageTransientError)


@respx.mock
def test_find_by_property_without_shared_drive_membership_cannot_answer() -> None:
    # Live customer run 2026-10-22: the ticket folder is in a shared drive the operator
    # can write to but is not a member of; a drive-wide search is 403
    # teamDriveMembershipRequired. That is "the provider could not answer" (the sink
    # then walks the run folder by parents), not a permission loss.
    respx.get(FILES).mock(return_value=_err(403, "teamDriveMembershipRequired"))
    with pytest.raises(StorageError) as exc:
        _storage().find_by_property("k", "v", drive_id="SD1")
    assert not isinstance(exc.value, StoragePermissionError)
    assert "teamDriveMembershipRequired" in str(exc.value)


@respx.mock
def test_find_by_property_other_403_stays_a_permission_error() -> None:
    respx.get(FILES).mock(return_value=_err(403, "insufficientFilePermissions"))
    with pytest.raises(StoragePermissionError):
        _storage().find_by_property("k", "v", drive_id="SD1")


# ------------------------------------------------------------------------- trash


@respx.mock
def test_trash_patches_trashed_true() -> None:
    route = respx.patch(f"{FILES}/F1").mock(
        return_value=httpx.Response(200, json={"id": "F1"})
    )
    _storage().trash("F1")
    req = route.calls.last.request
    assert json.loads(req.content) == {"trashed": True}
    assert req.url.params["supportsAllDrives"] == "true"


@respx.mock
def test_trash_denied_is_permission_error() -> None:
    respx.patch(f"{FILES}/F1").mock(
        return_value=_err(403, "insufficientFilePermissions")
    )
    with pytest.raises(StoragePermissionError):
        _storage().trash("F1")


# ----------------------------------------------------------------- create_folder


@respx.mock
def test_create_folder_payload() -> None:
    route = respx.post(FILES).mock(
        return_value=httpx.Response(
            200,
            json=_file(
                id="NEW",
                name="starboard",
                mimeType=FOLDER_MIME,
                size=None,
                md5Checksum=None,
            ),
        )
    )
    obj = _storage().create_folder("P1", "starboard", {"starboard_id": "abc"})
    req = route.calls.last.request
    assert json.loads(req.content) == {
        "name": "starboard",
        "mimeType": FOLDER_MIME,
        "parents": ["P1"],
        "appProperties": {"starboard_id": "abc"},
    }
    assert req.url.params["supportsAllDrives"] == "true"
    assert obj.is_folder and obj.id == "NEW" and obj.size is None


@respx.mock
def test_create_folder_is_not_retried_on_transient_error() -> None:
    # Non-idempotent: a lost response plus a retry would create a duplicate.
    sleeps: list[float] = []
    route = respx.post(FILES).mock(return_value=httpx.Response(503))
    with pytest.raises(StorageError):
        _storage(sleep=sleeps.append).create_folder("P1", "x", {})
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_create_folder_is_not_retried_on_transport_error() -> None:
    route = respx.post(FILES).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(StorageError):
        _storage().create_folder("P1", "x", {})
    assert route.call_count == 1


# ---------------------------------------------------------------- inspect_access

_PERMS = [
    {"type": "user", "role": "organizer", "emailAddress": "alice@databricks.com"},
    {"type": "group", "role": "writer", "emailAddress": "team@Databricks.com"},
    {"type": "domain", "role": "reader", "domain": "databricks.com"},
    {"type": "anyone", "role": "reader"},
]


def _mock_access(
    perms_responses: list[httpx.Response], meta: dict[str, Any]
) -> respx.Route:
    respx.get(f"{FILES}/F1").mock(return_value=httpx.Response(200, json=meta))
    return respx.get(f"{FILES}/F1/permissions").mock(side_effect=perms_responses)


@respx.mock
def test_inspect_access_grants_without_emails_and_paginates() -> None:
    route = _mock_access(
        [
            httpx.Response(200, json={"permissions": _PERMS[:2], "nextPageToken": "N"}),
            httpx.Response(200, json={"permissions": _PERMS[2:]}),
        ],
        {"id": "F1", "driveId": "D1", "capabilities": {"canAddChildren": True}},
    )
    info = _storage().inspect_access("F1")
    assert info.complete
    assert info.can_add_children
    assert info.drive_kind == "shared_drive" and info.drive_id == "D1"
    assert set(info.grants) == {
        Grant(kind="user", role="organizer", domain="databricks.com"),
        Grant(kind="group", role="writer", domain="databricks.com"),
        Grant(kind="domain", role="reader", domain="databricks.com"),
        Grant(kind="anyone", role="reader", domain=None),
    }
    assert "alice" not in repr(info) and "team@" not in repr(info).lower()
    assert len(info.fingerprint) == 64
    p0 = route.calls[0].request.url.params
    assert p0["supportsAllDrives"] == "true"
    assert "emailAddress" in p0["fields"] and "nextPageToken" in p0["fields"]
    assert route.calls[1].request.url.params["pageToken"] == "N"


@respx.mock
def test_inspect_access_fingerprint_detects_acl_change() -> None:
    meta = {"id": "F1", "capabilities": {"canAddChildren": False}}
    respx.get(f"{FILES}/F1").mock(return_value=httpx.Response(200, json=meta))
    same_domain_other_user = [
        {"type": "user", "role": "organizer", "emailAddress": "bob@databricks.com"},
        *_PERMS[1:],
    ]
    respx.get(f"{FILES}/F1/permissions").mock(
        side_effect=[
            httpx.Response(200, json={"permissions": _PERMS}),
            httpx.Response(200, json={"permissions": list(reversed(_PERMS))}),
            httpx.Response(200, json={"permissions": same_domain_other_user}),
        ]
    )
    storage = _storage()
    a, b, c = (storage.inspect_access("F1") for _ in range(3))
    assert a.drive_kind == "my_drive" and a.drive_id is None
    assert not a.can_add_children
    assert a.fingerprint == b.fingerprint  # order-insensitive
    assert a.grants == c.grants  # summaries identical (no names kept) ...
    assert a.fingerprint != c.fingerprint  # ... but the change is detectable


@respx.mock
def test_inspect_access_permission_list_403_is_incomplete() -> None:
    _mock_access(
        [_err(403, "insufficientFilePermissions")],
        {"id": "F1", "driveId": "D1", "capabilities": {"canAddChildren": True}},
    )
    info = _storage().inspect_access("F1")
    assert info.complete is False
    assert info.grants == ()
    assert info.can_add_children and info.drive_kind == "shared_drive"


# ----------------------------------------------------------------- error mapping


@respx.mock
def test_401_refreshes_once_then_succeeds() -> None:
    tokens = _Tokens("old-token", "new-token")
    route = respx.get(f"{FILES}/root").mock(
        side_effect=[_err(401, "authError"), httpx.Response(200, json={"id": "ROOT"})]
    )
    assert _storage(token_provider=tokens).root_folder_id() == "ROOT"
    assert tokens.calls == 2
    assert route.calls[0].request.headers["Authorization"] == "Bearer old-token"
    assert route.calls[1].request.headers["Authorization"] == "Bearer new-token"


@respx.mock
def test_401_twice_raises_auth_error_without_token() -> None:
    respx.get(f"{FILES}/root").mock(return_value=_err(401, "authError"))
    with pytest.raises(StorageAuthError) as exc:
        _storage(token_provider=lambda: TOKEN).root_folder_id()
    assert TOKEN not in str(exc.value) and TOKEN not in repr(exc.value)


@pytest.mark.parametrize(
    "reason",
    [
        "insufficientFilePermissions",
        "insufficientPermissions",
        "forbidden",
        "cannotAddParent",
        "teamDriveMembershipRequired",
    ],
)
@respx.mock
def test_403_permission_reasons(reason: str) -> None:
    respx.post(FILES).mock(return_value=_err(403, reason))
    with pytest.raises(StoragePermissionError) as exc:
        _storage(token_provider=lambda: TOKEN).create_folder("P1", "x", {})
    assert TOKEN not in str(exc.value)


@respx.mock
def test_429_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    route = respx.get(f"{FILES}/root").mock(
        side_effect=[
            httpx.Response(429),
            _err(403, "userRateLimitExceeded"),
            httpx.Response(503),
            httpx.Response(200, json={"id": "ROOT"}),
        ]
    )
    assert _storage(sleep=sleeps.append, max_retries=5).root_folder_id() == "ROOT"
    assert route.call_count == 4
    assert len(sleeps) == 3 and sleeps == sorted(sleeps)


@respx.mock
def test_retry_exhaustion_raises_storage_error() -> None:
    respx.get(f"{FILES}/root").mock(return_value=_err(403, "rateLimitExceeded"))
    with pytest.raises(StorageError) as exc:
        _storage(max_retries=2).root_folder_id()
    assert not isinstance(exc.value, StoragePermissionError)
    assert isinstance(exc.value, StorageTransientError)


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(429), _err(403, "userRateLimitExceeded")],
)
@respx.mock
def test_exhausted_transient_http_is_storage_transient(
    response: httpx.Response,
) -> None:
    respx.get(f"{FILES}/F1").mock(return_value=response)
    with pytest.raises(StorageTransientError):
        _storage(max_retries=1).get("F1")


@respx.mock
def test_exhausted_transport_errors_are_storage_transient() -> None:
    respx.get(f"{FILES}/F1").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(StorageTransientError):
        _storage(max_retries=1).get("F1")


@respx.mock
def test_exhausted_upload_resyncs_are_storage_transient() -> None:
    _mock_initiate()
    respx.put(SESSION).mock(return_value=httpx.Response(503))
    with pytest.raises(StorageTransientError):
        _storage(max_retries=1).put_stream(
            "P1", "a", "application/octet-stream", [b"abc"], properties={}
        )


@pytest.mark.parametrize("status", [400, 404])
@respx.mock
def test_non_transient_failures_are_not_storage_transient(status: int) -> None:
    respx.get(f"{FILES}/F1").mock(return_value=_err(status, "bad"))
    with pytest.raises(StorageError) as exc:
        _storage().get("F1")
    assert not isinstance(exc.value, StorageTransientError)


@respx.mock
def test_404_maps_to_not_found() -> None:
    respx.get(f"{FILES}/NOPE").mock(return_value=_err(404, "notFound"))
    with pytest.raises(StorageNotFoundError):
        _storage().get("NOPE")


# -------------------------------------------------------------------- put_stream


def _range_308(last_byte: int | None) -> httpx.Response:
    headers = {} if last_byte is None else {"Range": f"bytes=0-{last_byte}"}
    return httpx.Response(308, headers=headers)


def _mock_initiate() -> respx.Route:
    return respx.post(UPLOAD_BASE).mock(
        return_value=httpx.Response(200, headers={"Location": SESSION})
    )


def _chunks(data: bytes, piece: int) -> Iterator[bytes]:
    for i in range(0, len(data), piece):
        yield data[i : i + piece]


@respx.mock
def test_put_stream_multi_chunk_with_308_and_partial_ack() -> None:
    data = bytes(range(256)) * (KIB256 * 3 // 256) + b"tail"  # 768 KiB + 4
    total = len(data)
    md5 = hashlib.md5(data).hexdigest()
    init = _mock_initiate()
    put = respx.put(SESSION).mock(
        side_effect=[
            _range_308(KIB256 - 1),  # chunk 1 fully acked
            _range_308(KIB256 + 1000 - 1),  # chunk 2 only partially acked
            _range_308(2 * KIB256 + 1000 - 1),  # refilled chunk acked
            httpx.Response(200, json={"id": "UP1"}),  # final
        ]
    )
    respx.get(f"{FILES}/UP1").mock(
        return_value=httpx.Response(
            200, json=_file(id="UP1", size=str(total), md5Checksum=md5)
        )
    )
    obj = _storage(chunk_size=KIB256).put_stream(
        "P1",
        "evidence.bin",
        "application/octet-stream",
        _chunks(data, 100_000),
        properties={"kind": "evidence"},
    )
    assert obj.id == "UP1" and obj.size == total and obj.md5 == md5

    init_req = init.calls.last.request
    assert init_req.url.params["uploadType"] == "resumable"
    assert init_req.url.params["supportsAllDrives"] == "true"
    assert init_req.headers["X-Upload-Content-Type"] == "application/octet-stream"
    assert json.loads(init_req.content) == {
        "name": "evidence.bin",
        "parents": ["P1"],
        "mimeType": "application/octet-stream",
        "appProperties": {"kind": "evidence"},
    }
    ranges = [c.request.headers["Content-Range"] for c in put.calls]
    assert ranges == [
        f"bytes 0-{KIB256 - 1}/*",
        f"bytes {KIB256}-{2 * KIB256 - 1}/*",
        f"bytes {KIB256 + 1000}-{2 * KIB256 + 1000 - 1}/*",
        f"bytes {2 * KIB256 + 1000}-{total - 1}/{total}",
    ]
    assert all(len(c.request.content) % KIB256 == 0 for c in put.calls[:-1])
    assert (
        b"".join(
            [
                put.calls[0].request.content,
                put.calls[1].request.content[:1000],
                put.calls[2].request.content,
                put.calls[3].request.content,
            ]
        )
        == data
    )


@respx.mock
def test_put_stream_resumes_after_transient_chunk_failure() -> None:
    data = b"x" * (KIB256 + 10)
    md5 = hashlib.md5(data).hexdigest()
    _mock_initiate()
    put = respx.put(SESSION).mock(
        side_effect=[
            httpx.Response(503),  # chunk 1 fails
            _range_308(None),  # status query: nothing persisted
            _range_308(KIB256 - 1),  # chunk 1 resent and acked
            httpx.Response(201, json={"id": "UP2"}),
        ]
    )
    respx.get(f"{FILES}/UP2").mock(
        return_value=httpx.Response(
            200, json=_file(id="UP2", size=str(len(data)), md5Checksum=md5)
        )
    )
    obj = _storage(chunk_size=KIB256).put_stream(
        "P1", "b", "application/octet-stream", [data], properties={}
    )
    assert obj.id == "UP2"
    ranges = [c.request.headers["Content-Range"] for c in put.calls]
    assert ranges == [
        f"bytes 0-{KIB256 - 1}/*",
        "bytes */*",
        f"bytes 0-{KIB256 - 1}/*",
        f"bytes {KIB256}-{len(data) - 1}/{len(data)}",
    ]


SESSION2 = f"{UPLOAD_BASE}?uploadType=resumable&upload_id=SESSION456"


def _mock_sessions(*uris: str) -> respx.Route:
    return respx.post(UPLOAD_BASE).mock(
        side_effect=[httpx.Response(200, headers={"Location": u}) for u in uris]
    )


def _mock_stored(file_id: str, data: bytes) -> None:
    respx.get(f"{FILES}/{file_id}").mock(
        return_value=httpx.Response(
            200,
            json=_file(
                id=file_id,
                size=str(len(data)),
                md5Checksum=hashlib.md5(data).hexdigest(),
            ),
        )
    )


@pytest.mark.parametrize("gone", [404, 410])
@respx.mock
def test_put_stream_restarts_when_the_status_query_finds_the_session_expired(
    gone: int,
) -> None:
    # Run 7: Drive answered 410 on the status query and the capture stopped exit 7.
    data = b"abc"
    respx.get(FILES).mock(
        return_value=httpx.Response(200, json={"files": []})
    )  # nothing landed
    opened = _mock_sessions(SESSION, SESSION2)
    first = respx.put(SESSION).mock(
        side_effect=[httpx.Response(503), httpx.Response(gone)]
    )
    second = respx.put(SESSION2).mock(
        return_value=httpx.Response(200, json={"id": "UP1"})
    )
    _mock_stored("UP1", data)
    obj = _storage().put_stream(
        "P1", "a.json", "application/json", [data], properties={}
    )
    assert obj.id == "UP1"
    assert opened.call_count == 2 and first.call_count == 2
    assert second.calls.last.request.content == data
    assert second.calls.last.request.headers["Content-Range"] == "bytes 0-2/3"


@respx.mock
def test_put_stream_returns_a_file_the_lost_final_request_created() -> None:
    # Run 10: the final PUT finalized the file but its reply was lost (503), the
    # status query found the session gone, and the restart created a second
    # storage-preflight.json, so every later read failed STORAGE_ERROR.
    data = b"abc"
    opened = _mock_sessions(SESSION, SESSION2)
    respx.put(SESSION).mock(side_effect=[httpx.Response(503), httpx.Response(410)])
    second = respx.put(SESSION2).mock(
        return_value=httpx.Response(200, json={"id": "UP2"})
    )
    landed = _file(
        id="UP1",
        name="a.json",
        appProperties={"starboard_key": "k1"},
        size=str(len(data)),
        md5Checksum=hashlib.md5(data).hexdigest(),
    )
    listing = respx.get(FILES).mock(
        return_value=httpx.Response(200, json={"files": [landed]})
    )
    obj = _storage().put_stream(
        "P1", "a.json", "application/json", [data], properties={"starboard_key": "k1"}
    )
    assert obj.id == "UP1"
    assert opened.call_count == 1 and not second.called and listing.called


@respx.mock
def test_put_stream_restarts_when_no_identical_file_landed() -> None:
    data = b"abc"
    opened = _mock_sessions(SESSION, SESSION2)
    respx.put(SESSION).mock(side_effect=[httpx.Response(503), httpx.Response(410)])
    respx.put(SESSION2).mock(return_value=httpx.Response(200, json={"id": "UP2"}))
    other = _file(id="OLD", size="9", md5Checksum=hashlib.md5(b"different").hexdigest())
    respx.get(FILES).mock(return_value=httpx.Response(200, json={"files": [other]}))
    _mock_stored("UP2", data)
    obj = _storage().put_stream(
        "P1", "a.json", "application/json", [data], properties={"starboard_key": "k1"}
    )
    assert obj.id == "UP2" and opened.call_count == 2


@respx.mock
def test_put_stream_restarts_an_expired_session_from_byte_zero() -> None:
    data = b"x" * (KIB256 + 10)
    _mock_sessions(SESSION, SESSION2)
    respx.get(FILES).mock(
        return_value=httpx.Response(200, json={"files": []})
    )  # nothing landed
    respx.put(SESSION).mock(side_effect=[_range_308(KIB256 - 1), httpx.Response(410)])
    second = respx.put(SESSION2).mock(
        side_effect=[_range_308(KIB256 - 1), httpx.Response(201, json={"id": "UP2"})]
    )
    _mock_stored("UP2", data)
    obj = _storage(chunk_size=KIB256).put_stream(
        "P1", "b", "application/octet-stream", [data], properties={}
    )
    assert obj.id == "UP2"
    assert [c.request.headers["Content-Range"] for c in second.calls] == [
        f"bytes 0-{KIB256 - 1}/*",
        f"bytes {KIB256}-{len(data) - 1}/{len(data)}",
    ]


@respx.mock
def test_update_stream_restarts_an_expired_session() -> None:
    data = b"abc"
    opened = respx.patch(f"{UPLOAD_BASE}/F1").mock(
        side_effect=[
            httpx.Response(200, headers={"Location": SESSION}),
            httpx.Response(200, headers={"Location": SESSION2}),
        ]
    )
    respx.put(SESSION).mock(return_value=httpx.Response(410))
    respx.put(SESSION2).mock(return_value=httpx.Response(200, json={"id": "F1"}))
    _mock_stored("F1", data)
    assert _storage().update_stream("F1", "application/json", [data]).id == "F1"
    assert opened.call_count == 2


@respx.mock
def test_an_expired_one_shot_stream_is_retryable_not_a_hard_failure() -> None:
    _mock_sessions(SESSION)
    respx.put(SESSION).mock(return_value=httpx.Response(410))
    with pytest.raises(StorageTransientError, match="expired"):
        _storage().put_stream(
            "P1", "a", "application/json", iter([b"abc"]), properties={}
        )


@respx.mock
def test_a_second_expired_session_is_retryable_not_a_hard_failure() -> None:
    respx.get(FILES).mock(
        return_value=httpx.Response(200, json={"files": []})
    )  # nothing landed
    opened = _mock_sessions(SESSION, SESSION2)
    respx.put(SESSION).mock(return_value=httpx.Response(410))
    respx.put(SESSION2).mock(return_value=httpx.Response(404))
    with pytest.raises(StorageTransientError, match="expired"):
        _storage().put_stream("P1", "a", "application/json", [b"abc"], properties={})
    assert opened.call_count == 2


@respx.mock
def test_put_stream_md5_mismatch_raises_integrity_error() -> None:
    _mock_initiate()
    respx.put(SESSION).mock(return_value=httpx.Response(200, json={"id": "UP3"}))
    respx.get(f"{FILES}/UP3").mock(
        return_value=httpx.Response(
            200, json=_file(id="UP3", size="3", md5Checksum="0" * 32)
        )
    )
    with pytest.raises(StorageIntegrityError):
        _storage().put_stream("P1", "a", "text/plain", [b"abc"], properties={})


@respx.mock
def test_put_stream_size_mismatch_raises_integrity_error() -> None:
    _mock_initiate()
    respx.put(SESSION).mock(return_value=httpx.Response(200, json={"id": "UP4"}))
    respx.get(f"{FILES}/UP4").mock(
        return_value=httpx.Response(200, json=_file(id="UP4", size="2"))
    )
    with pytest.raises(StorageIntegrityError):
        _storage().put_stream("P1", "a", "text/plain", [b"abc"], properties={})


@respx.mock
def test_put_stream_max_bytes_exceeded_never_finalizes() -> None:
    _mock_initiate()
    put = respx.put(SESSION).mock(return_value=_range_308(KIB256 - 1))
    with pytest.raises(StorageError, match="max_bytes"):
        _storage(chunk_size=KIB256, max_bytes=2 * KIB256 - 1).put_stream(
            "P1",
            "a",
            "application/octet-stream",
            _chunks(b"y" * (2 * KIB256), 1000),
            properties={},
        )
    # Only non-final chunks were sent, so Drive never created the file.
    assert all(c.request.headers["Content-Range"].endswith("/*") for c in put.calls)


@respx.mock
def test_put_stream_empty() -> None:
    _mock_initiate()
    put = respx.put(SESSION).mock(return_value=httpx.Response(200, json={"id": "E1"}))
    respx.get(f"{FILES}/E1").mock(
        return_value=httpx.Response(
            200, json=_file(id="E1", size="0", md5Checksum=hashlib.md5(b"").hexdigest())
        )
    )
    obj = _storage().put_stream(
        "P1", "empty", "text/plain", iter([b"", b""]), properties={}
    )
    assert obj.size == 0
    assert put.call_count == 1
    assert put.calls.last.request.headers["Content-Range"] == "bytes */0"
    assert put.calls.last.request.content == b""


def test_put_stream_rejects_native_google_mime() -> None:
    with pytest.raises(StorageError):
        _storage().put_stream(
            "P1", "doc", "application/vnd.google-apps.document", [b"x"], properties={}
        )


def test_chunk_size_must_be_multiple_of_256k() -> None:
    with pytest.raises(ValueError):
        _storage(chunk_size=KIB256 + 1)


@respx.mock
def test_put_stream_initiate_without_location_fails() -> None:
    respx.post(UPLOAD_BASE).mock(return_value=httpx.Response(200))
    with pytest.raises(StorageError):
        _storage().put_stream("P1", "a", "text/plain", [b"abc"], properties={})


@pytest.mark.parametrize(
    "location",
    [
        "http://www.googleapis.com/upload/drive/v3/files?upload_id=S",
        "https://evil.example.com/upload?upload_id=S",
        "https://www.googleapis.com.evil.example.com/upload?upload_id=S",
        "https://user@evil.example.com/?h=www.googleapis.com",
        "/upload/drive/v3/files?upload_id=S",
    ],
)
@respx.mock
def test_put_stream_refuses_untrusted_session_location(location: str) -> None:
    respx.post(UPLOAD_BASE).mock(
        return_value=httpx.Response(200, headers={"Location": location})
    )
    upload = respx.put(url__regex=r".*").mock(return_value=httpx.Response(200))
    with pytest.raises(StorageError) as exc:
        _storage().put_stream("P1", "a", "text/plain", [b"abc"], properties={})
    assert upload.call_count == 0
    assert TOKEN not in str(exc.value)
    assert "upload_id" not in str(exc.value)


# -------------------------------------------------------------------- get_stream


@respx.mock
def test_get_stream_head_and_revision() -> None:
    head = respx.get(f"{FILES}/F1").mock(
        return_value=httpx.Response(200, content=b"hello")
    )
    rev = respx.get(f"{FILES}/F1/revisions/R7").mock(
        return_value=httpx.Response(200, content=b"older")
    )
    storage = _storage()
    assert b"".join(storage.get_stream("F1")) == b"hello"
    assert b"".join(storage.get_stream("F1", revision="R7")) == b"older"
    assert head.calls.last.request.url.params["alt"] == "media"
    assert head.calls.last.request.url.params["supportsAllDrives"] == "true"
    assert rev.calls.last.request.url.params["alt"] == "media"


@respx.mock
def test_get_stream_404_raises_eagerly() -> None:
    respx.get(f"{FILES}/GONE").mock(return_value=_err(404, "notFound"))
    with pytest.raises(StorageNotFoundError):
        _storage().get_stream("GONE")


# ---------------------------------------------------------------- gcloud provider


def test_gcloud_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google_drive.shutil, "which", lambda _n: None)
    with pytest.raises(StorageAuthError, match="gcloud"):
        gcloud_access_token()


def _fake_run(result: Any) -> Any:
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        assert kwargs.get("shell") in (None, False)
        assert kwargs.get("timeout")
        if isinstance(result, BaseException):
            raise result
        return result

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_gcloud_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google_drive.shutil, "which", lambda _n: "/usr/bin/gcloud")
    run = _fake_run(subprocess.CompletedProcess([], 0, stdout=f"{TOKEN}\n", stderr=""))
    monkeypatch.setattr(google_drive.subprocess, "run", run)
    assert gcloud_access_token() == TOKEN
    assert run.calls[0] == ["/usr/bin/gcloud", "auth", "print-access-token"]


@pytest.mark.parametrize(
    "result",
    [
        subprocess.CompletedProcess([], 1, stdout=TOKEN, stderr="ERROR: reauth needed"),
        subprocess.CompletedProcess([], 0, stdout="  \n", stderr=""),
        subprocess.TimeoutExpired(cmd="gcloud", timeout=30),
        FileNotFoundError("gcloud"),
    ],
)
def test_gcloud_failure_modes(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    monkeypatch.setattr(google_drive.shutil, "which", lambda _n: "/usr/bin/gcloud")
    monkeypatch.setattr(google_drive.subprocess, "run", _fake_run(result))
    with pytest.raises(StorageAuthError) as exc:
        gcloud_access_token()
    assert "gcloud auth login" in str(exc.value)
    assert TOKEN not in str(exc.value)


@respx.mock
def test_empty_token_from_provider_is_auth_error() -> None:
    with pytest.raises(StorageAuthError):
        _storage(token_provider=lambda: "").root_folder_id()


# ------------------------------------------------------------------ principal_id


@respx.mock
def test_principal_id_returns_permission_id_and_caches() -> None:
    route = respx.get(f"{API_BASE}/about").mock(
        return_value=httpx.Response(200, json={"user": {"permissionId": "PERM-42"}})
    )
    storage = _storage()
    assert storage.principal_id() == "PERM-42"
    assert storage.principal_id() == "PERM-42"
    assert route.call_count == 1
    assert route.calls.last.request.url.params["fields"] == "user(permissionId)"


@respx.mock
def test_principal_id_missing_permission_id_fails() -> None:
    respx.get(f"{API_BASE}/about").mock(
        return_value=httpx.Response(200, json={"user": {}})
    )
    with pytest.raises(StorageError):
        _storage().principal_id()


@respx.mock
def test_principal_id_401_maps_to_auth_error() -> None:
    respx.get(f"{API_BASE}/about").mock(return_value=_err(401, "authError"))
    with pytest.raises(StorageAuthError):
        _storage().principal_id()


# ------------------------------------------------------------------------ update


@respx.mock
def test_update_moves_parent_and_merges_properties() -> None:
    patch = respx.patch(f"{FILES}/F1").mock(
        return_value=httpx.Response(200, json=_file())
    )
    respx.get(f"{FILES}/F1").mock(
        return_value=httpx.Response(
            200,
            json=_file(
                name="b.json",
                parents=["P2"],
                appProperties={"starboard_key": "k1", "extra": "v"},
            ),
        )
    )
    obj = _storage().update(
        "F1",
        name="b.json",
        properties={"extra": "v"},
        add_parent_id="P2",
        remove_parent_id="P1",
    )
    assert obj.parent_ids == ("P2",)
    assert obj.properties == {"starboard_key": "k1", "extra": "v"}
    req = patch.calls.last.request
    assert req.url.params["addParents"] == "P2"
    assert req.url.params["removeParents"] == "P1"
    assert req.url.params["supportsAllDrives"] == "true"
    assert req.url.params["fields"] == google_drive.FILE_FIELDS
    assert json.loads(req.content) == {
        "name": "b.json",
        "appProperties": {"extra": "v"},
    }


@respx.mock
def test_update_properties_only_omits_parent_params() -> None:
    patch = respx.patch(f"{FILES}/F1").mock(
        return_value=httpx.Response(200, json=_file())
    )
    respx.get(f"{FILES}/F1").mock(
        return_value=httpx.Response(200, json=_file(appProperties={"a": "1"}))
    )
    _storage().update("F1", properties={"a": "1"})
    params = patch.calls.last.request.url.params
    assert "addParents" not in params and "removeParents" not in params
    assert json.loads(patch.calls.last.request.content) == {"appProperties": {"a": "1"}}


@respx.mock
@pytest.mark.parametrize(
    "kwargs, stored",
    [
        ({"name": "b.json"}, {"name": "a.json"}),
        ({"properties": {"x": "1"}}, {"appProperties": {"x": "2"}}),
        ({"add_parent_id": "P2"}, {"parents": ["P1"]}),
        ({"remove_parent_id": "P1"}, {"parents": ["P1"]}),
    ],
)
def test_update_read_back_mismatch_raises_integrity_error(
    kwargs: dict[str, Any], stored: dict[str, Any]
) -> None:
    respx.patch(f"{FILES}/F1").mock(return_value=httpx.Response(200, json=_file()))
    respx.get(f"{FILES}/F1").mock(
        return_value=httpx.Response(200, json=_file(**stored))
    )
    with pytest.raises(StorageIntegrityError):
        _storage().update("F1", **kwargs)


@respx.mock
def test_update_error_mapping() -> None:
    respx.patch(f"{FILES}/NOPE").mock(return_value=_err(404, "notFound"))
    respx.patch(f"{FILES}/DENIED").mock(return_value=_err(403, "forbidden"))
    with pytest.raises(StorageNotFoundError):
        _storage().update("NOPE", name="x")
    with pytest.raises(StoragePermissionError):
        _storage().update("DENIED", name="x")


@respx.mock
def test_update_retries_transient_then_succeeds() -> None:
    patch = respx.patch(f"{FILES}/F1").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=_file())]
    )
    respx.get(f"{FILES}/F1").mock(return_value=httpx.Response(200, json=_file()))
    _storage().update("F1", name="a.json")
    assert patch.call_count == 2


# ------------------------------------------------------------------ update_stream

UPDATE_URL = f"{UPLOAD_BASE}/UP1"


def _mock_update_initiate() -> respx.Route:
    return respx.patch(UPDATE_URL).mock(
        return_value=httpx.Response(200, headers={"Location": SESSION})
    )


@respx.mock
def test_update_stream_multi_chunk_success() -> None:
    data = bytes(range(256)) * (KIB256 * 2 // 256) + b"tail"
    total = len(data)
    md5 = hashlib.md5(data).hexdigest()
    init = _mock_update_initiate()
    put = respx.put(SESSION).mock(
        side_effect=[
            _range_308(KIB256 - 1),
            _range_308(2 * KIB256 - 1),
            httpx.Response(200, json={"id": "UP1"}),
        ]
    )
    respx.get(f"{FILES}/UP1").mock(
        return_value=httpx.Response(
            200,
            json=_file(id="UP1", size=str(total), md5Checksum=md5, headRevisionId="R2"),
        )
    )
    obj = _storage(chunk_size=KIB256).update_stream(
        "UP1", "application/octet-stream", _chunks(data, 100_000)
    )
    assert obj.id == "UP1" and obj.size == total and obj.md5 == md5
    assert obj.revision == "R2"

    init_req = init.calls.last.request
    assert init_req.url.params["uploadType"] == "resumable"
    assert init_req.url.params["supportsAllDrives"] == "true"
    assert init_req.headers["X-Upload-Content-Type"] == "application/octet-stream"
    assert not init_req.content  # no metadata / parents in the body
    ranges = [c.request.headers["Content-Range"] for c in put.calls]
    assert ranges == [
        f"bytes 0-{KIB256 - 1}/*",
        f"bytes {KIB256}-{2 * KIB256 - 1}/*",
        f"bytes {2 * KIB256}-{total - 1}/{total}",
    ]


@respx.mock
def test_update_stream_resumes_after_transient_failure() -> None:
    data = b"x" * (KIB256 + 10)
    md5 = hashlib.md5(data).hexdigest()
    _mock_update_initiate()
    put = respx.put(SESSION).mock(
        side_effect=[
            httpx.Response(503),
            _range_308(None),
            _range_308(KIB256 - 1),
            httpx.Response(200, json={"id": "UP1"}),
        ]
    )
    respx.get(f"{FILES}/UP1").mock(
        return_value=httpx.Response(
            200, json=_file(id="UP1", size=str(len(data)), md5Checksum=md5)
        )
    )
    obj = _storage(chunk_size=KIB256).update_stream(
        "UP1", "application/octet-stream", [data]
    )
    assert obj.id == "UP1"
    ranges = [c.request.headers["Content-Range"] for c in put.calls]
    assert ranges == [
        f"bytes 0-{KIB256 - 1}/*",
        "bytes */*",
        f"bytes 0-{KIB256 - 1}/*",
        f"bytes {KIB256}-{len(data) - 1}/{len(data)}",
    ]


@respx.mock
def test_update_stream_md5_mismatch_raises_integrity_error() -> None:
    _mock_update_initiate()
    respx.put(SESSION).mock(return_value=httpx.Response(200, json={"id": "UP1"}))
    respx.get(f"{FILES}/UP1").mock(
        return_value=httpx.Response(
            200, json=_file(id="UP1", size="3", md5Checksum="0" * 32)
        )
    )
    with pytest.raises(StorageIntegrityError):
        _storage().update_stream("UP1", "text/plain", [b"abc"])


@respx.mock
@pytest.mark.parametrize(
    "status, reason, exc",
    [
        (401, "authError", StorageAuthError),
        (403, "forbidden", StoragePermissionError),
        (404, "notFound", StorageNotFoundError),
    ],
)
def test_update_stream_error_mapping(
    status: int, reason: str, exc: type[StorageError]
) -> None:
    respx.patch(UPDATE_URL).mock(return_value=_err(status, reason))
    with pytest.raises(exc):
        _storage().update_stream("UP1", "text/plain", [b"abc"])


@respx.mock
def test_update_stream_rejects_native_google_mime() -> None:
    with pytest.raises(StorageError):
        _storage().update_stream("UP1", "application/vnd.google-apps.document", [b"a"])


@respx.mock
def test_update_stream_max_bytes_exceeded_never_finalizes() -> None:
    _mock_update_initiate()
    put = respx.put(SESSION).mock(return_value=httpx.Response(200, json={"id": "UP1"}))
    with pytest.raises(StorageError):
        _storage(max_bytes=2).update_stream("UP1", "text/plain", [b"abc"])
    assert put.call_count == 0


# ------------------------------------------------- default policy: 3 attempts, 1/2/4 s
#
# These build the adapter with only an injected token provider and sleep, so they
# exercise the *default* retry budget (D-23): 3 attempts total, exponential
# backoff 1 s then 2 s (capped at 4 s), 429/5xx only.


def _default_storage(sleeps: list[float]) -> GoogleDriveStorage:
    return GoogleDriveStorage(token_provider=_Tokens(), sleep=sleeps.append)


@respx.mock
def test_get_503_then_200_succeeds_after_one_retry() -> None:
    sleeps: list[float] = []
    route = respx.get(f"{FILES}/F1").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=_file())]
    )
    assert _default_storage(sleeps).get("F1").id == "F1"
    assert route.call_count == 2
    assert sleeps == [1.0]


@respx.mock
def test_get_429_three_times_raises_storage_error_with_three_attempts() -> None:
    sleeps: list[float] = []
    route = respx.get(f"{FILES}/F1").mock(return_value=httpx.Response(429))
    with pytest.raises(StorageError) as exc:
        _default_storage(sleeps).get("F1")
    assert not isinstance(exc.value, StoragePermissionError | StorageNotFoundError)
    assert route.call_count == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize("status", [400, 404, 409])
@respx.mock
def test_other_4xx_is_not_retried(status: int) -> None:
    sleeps: list[float] = []
    route = respx.get(f"{FILES}/F1").mock(return_value=_err(status, "nope"))
    with pytest.raises(StorageError):
        _default_storage(sleeps).get("F1")
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_list_children_retries_5xx_then_succeeds() -> None:
    sleeps: list[float] = []
    route = respx.get(FILES).mock(
        side_effect=[
            httpx.Response(502),
            httpx.Response(200, json={"files": [_file()]}),
        ]
    )
    assert [o.id for o in _default_storage(sleeps).list_children("P1")] == ["F1"]
    assert route.call_count == 2
    assert sleeps == [1.0]


@respx.mock
def test_put_stream_session_initiation_retries_transient_then_succeeds() -> None:
    # Safe to retry: Drive creates no file until the final upload request, so a
    # lost initiation response can orphan a session URI but never an object.
    sleeps: list[float] = []
    data = b"abc"
    init = respx.post(UPLOAD_BASE).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, headers={"Location": SESSION}),
        ]
    )
    respx.put(SESSION).mock(return_value=httpx.Response(200, json={"id": "UP9"}))
    respx.get(f"{FILES}/UP9").mock(
        return_value=httpx.Response(
            200,
            json=_file(id="UP9", size="3", md5Checksum=hashlib.md5(data).hexdigest()),
        )
    )
    obj = _default_storage(sleeps).put_stream(
        "P1", "a", "text/plain", [data], properties={}
    )
    assert obj.id == "UP9"
    assert init.call_count == 2
    assert sleeps == [1.0]


@respx.mock
def test_update_stream_session_initiation_exhausts_after_three_attempts() -> None:
    sleeps: list[float] = []
    init = respx.patch(UPDATE_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(StorageError):
        _default_storage(sleeps).update_stream("UP1", "text/plain", [b"abc"])
    assert init.call_count == 3
    assert sleeps == [1.0, 2.0]


@respx.mock
def test_create_folder_never_retried_under_default_policy() -> None:
    sleeps: list[float] = []
    route = respx.post(FILES).mock(return_value=httpx.Response(429))
    with pytest.raises(StorageError):
        _default_storage(sleeps).create_folder("P1", "x", {})
    assert route.call_count == 1
    assert sleeps == []


# --------------------------------------------------------------- no-arg construction


def test_constructible_with_no_arguments_and_lazy_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("construction must not run a subprocess or look up gcloud")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(google_drive.shutil, "which", boom)
    with respx.mock(assert_all_called=False) as mock:
        storage = GoogleDriveStorage()
        assert not mock.calls
    assert isinstance(storage, EngagementStoragePort)
    storage.close()


@pytest.fixture
def _fresh_process_token(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Reset the process token and count gcloud mints."""
    minted: list[str] = []

    def mint() -> str:
        minted.append(f"tok-{len(minted)}")
        return minted[-1]

    monkeypatch.setattr(google_drive, "_process_token", None)
    monkeypatch.setattr(google_drive, "gcloud_access_token", mint)
    return minted


@respx.mock
def test_default_token_is_minted_once_per_process(
    _fresh_process_token: list[str],
) -> None:
    route = respx.get(f"{FILES}/root").mock(
        return_value=httpx.Response(200, json={"id": "ROOT"})
    )
    for _ in range(3):  # one adapter per command, several commands per process
        storage = GoogleDriveStorage(sleep=lambda _s: None)
        storage.root_folder_id()
        storage.root_folder_id()
        storage.close()
    assert _fresh_process_token == ["tok-0"]
    assert {c.request.headers["Authorization"] for c in route.calls} == {"Bearer tok-0"}


@respx.mock
def test_rejected_process_token_is_reminted_once(
    _fresh_process_token: list[str],
) -> None:
    respx.get(f"{FILES}/root").mock(
        side_effect=[
            httpx.Response(401),
            httpx.Response(200, json={"id": "ROOT"}),
            httpx.Response(200, json={"id": "ROOT"}),
        ]
    )
    GoogleDriveStorage(sleep=lambda _s: None).root_folder_id()
    GoogleDriveStorage(sleep=lambda _s: None).root_folder_id()
    assert _fresh_process_token == ["tok-0", "tok-1"]


def test_process_token_is_never_written_to_disk() -> None:
    source = Path(google_drive.__file__).read_text(encoding="utf-8")
    for needle in ("open(", "write_text", "write_bytes", "keyring"):
        assert needle not in source, needle


def test_engagement_storage_entry_point_resolves_to_adapter() -> None:
    eps = importlib.metadata.entry_points(
        group="starboard.engagement_storage", name="engagement_storage"
    )
    assert len(eps) == 1
    assert next(iter(eps)).load() is GoogleDriveStorage
