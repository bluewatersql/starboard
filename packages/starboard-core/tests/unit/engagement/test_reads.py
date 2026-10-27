# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the one verified Drive object read."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.reads import (
    ReadRefusedError,
    read_object,
    read_verified,
    run_relpath,
)
from starboard_core.engagement.sink import LocalStorageRefused
from starboard_core.ports.engagement_storage import (
    StorageIntegrityError,
    StorageNotFoundError,
)


def _file(data: bytes) -> tuple[InMemoryEngagementStorage, str]:
    store = InMemoryEngagementStorage()
    obj = store.put_stream(
        store.root_folder_id(), "f.json", "application/json", [data], properties={}
    )
    return store, obj.id


@pytest.mark.unit
class TestReadVerified:
    def test_reads_the_bytes(self) -> None:
        store, oid = _file(b'{"a": 1}')
        assert read_verified(store, oid, max_bytes=100) == b'{"a": 1}'

    def test_folder_refused(self) -> None:
        store = InMemoryEngagementStorage()
        folder = store.create_folder(store.root_folder_id(), "d", {})
        with pytest.raises(ReadRefusedError, match="folder"):
            read_verified(store, folder.id, max_bytes=100)

    def test_declared_size_over_the_cap_refused_before_download(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, oid = _file(b"x" * 50)
        monkeypatch.setattr(
            store, "get_stream", lambda *_a, **_k: pytest.fail("downloaded")
        )
        with pytest.raises(ReadRefusedError, match="larger than 10 bytes"):
            read_verified(store, oid, max_bytes=10)

    def test_cap_enforced_while_streaming(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, oid = _file(b"x" * 5)
        pulled: list[int] = []

        def stream(*_a: object, **_k: object) -> Iterator[bytes]:
            for i in range(100):
                pulled.append(i)
                yield b"x" * 4

        monkeypatch.setattr(store, "get_stream", stream)
        with pytest.raises(ReadRefusedError, match="larger than 10 bytes"):
            read_verified(store, oid, max_bytes=10)
        assert len(pulled) == 3  # stopped at the first chunk over the cap

    def test_md5_mismatch_is_an_integrity_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, oid = _file(b"abc")
        monkeypatch.setattr(store, "get_stream", lambda *_a, **_k: iter([b"abd"]))
        with pytest.raises(StorageIntegrityError, match=oid):
            read_verified(store, oid, max_bytes=100)

    def test_size_mismatch_is_an_integrity_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, oid = _file(b"abc")
        monkeypatch.setattr(store, "get_stream", lambda *_a, **_k: iter([b"ab"]))
        with pytest.raises(StorageIntegrityError):
            read_verified(store, oid, max_bytes=100)

    def test_missing_object_propagates(self) -> None:
        store = InMemoryEngagementStorage()
        with pytest.raises(StorageNotFoundError):
            read_verified(store, "nope", max_bytes=100)


@pytest.mark.unit
class TestReadObject:
    def test_verifies_against_the_listed_object_without_a_fresh_get(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, oid = _file(b'{"a": 1}')
        obj = store.get(oid)
        monkeypatch.setattr(store, "get", lambda *_a, **_k: pytest.fail("re-fetched"))
        assert read_object(store, obj, max_bytes=100) == b'{"a": 1}'

    def test_bytes_that_differ_from_the_listing_are_an_integrity_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, oid = _file(b"abc")
        obj = store.get(oid)
        monkeypatch.setattr(store, "get_stream", lambda *_a, **_k: iter([b"abd"]))
        with pytest.raises(StorageIntegrityError, match=oid):
            read_object(store, obj, max_bytes=100)


    def test_reads_and_verifies_a_given_revision(self) -> None:
        store, oid = _file(b"v1")
        first = store.get(oid)
        store.update_stream(oid, "application/json", [b"v2-longer"])
        assert read_object(store, store.get(oid), max_bytes=100) == b"v2-longer"
        assert read_object(store, first, max_bytes=100, revision=first.revision) == b"v1"
        # The listing describes the head, not v1: the revision's bytes do not match it.
        with pytest.raises(StorageIntegrityError):
            read_object(store, store.get(oid), max_bytes=100, revision=first.revision)

    def test_keep_returns_the_head_but_hashes_everything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, oid = _file(b"0123456789" * 10)
        obj = store.get(oid)
        assert read_object(store, obj, max_bytes=1000, keep=5) == b"01234"
        assert read_object(store, obj, max_bytes=1000, keep=500) == b"0123456789" * 10
        monkeypatch.setattr(
            store, "get_stream", lambda *_a, **_k: iter([b"0123456789" * 9, b"x" * 10])
        )
        with pytest.raises(StorageIntegrityError):
            read_object(store, obj, max_bytes=1000, keep=5)

    def test_keep_still_enforces_the_cap(self) -> None:
        store, oid = _file(b"x" * 50)
        with pytest.raises(ReadRefusedError, match="larger than 10 bytes"):
            read_object(store, store.get(oid), max_bytes=10, keep=1)

    def test_negative_keep_rejected(self) -> None:
        store, oid = _file(b"x")
        with pytest.raises(ValueError, match="keep"):
            read_object(store, store.get(oid), max_bytes=10, keep=-1)


class _Arg(Exception):
    pass


@pytest.mark.unit
class TestRunRelpath:
    def test_valid_relpath_is_normalized(self) -> None:
        assert run_relpath("--out", "analysis/x.json", covered_run=True) == "analysis/x.json"

    def test_covered_run_refuses_a_local_path(self) -> None:
        with pytest.raises(LocalStorageRefused, match="--out '/tmp/x' is a local path") as e:
            run_relpath("--out", "/tmp/x", covered_run=True, arg_error=_Arg)
        assert e.value.flag == "--out"

    def test_uncovered_run_raises_the_callers_arg_error(self) -> None:
        with pytest.raises(_Arg, match="--out must be a run-relative path with --run-folder"):
            run_relpath("--out", "../x", covered_run=False, arg_error=_Arg)

    def test_default_arg_error_is_value_error(self) -> None:
        with pytest.raises(ValueError, match="run-relative"):
            run_relpath("--out", "/x", covered_run=False)

    @pytest.mark.parametrize("value", ["../x", "analysis/../../x", "~/x", "C:\\x"])
    def test_covered_run_refuses_every_local_form(self, value: str) -> None:
        with pytest.raises(LocalStorageRefused, match="is a local path"):
            run_relpath("--out", value, covered_run=True, arg_error=_Arg)

    def test_a_malformed_run_relative_path_is_a_usage_error_not_a_local_path(
        self,
    ) -> None:
        # A trailing "/" is a bad run-relative path, never a local one.
        with pytest.raises(_Arg, match="is not a valid run-relative path"):
            run_relpath("--out", "analysis/verify/", covered_run=True, arg_error=_Arg)
