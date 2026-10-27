# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the run artifact sink (phase-2 spec P2-G3)."""

from __future__ import annotations

import collections
import dataclasses
import hashlib
import inspect
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import pytest
from starboard_core.engagement import sink as sink_mod
from starboard_core.engagement.commit import (
    DESCRIPTOR_NAME,
    CommitError,
    write_descriptor,
)
from starboard_core.engagement.folders import IDENTITY_PROPERTY
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.policy import (
    SourceMode,
    StorageDecision,
    StoragePolicy,
)
from starboard_core.engagement.reads import ReadRefusedError
from starboard_core.engagement.records import (
    AccountRef,
    DriveContext,
    EvidenceRef,
    RunAuthorization,
    audience_class_for,
    evidence_id,
)
from starboard_core.engagement.sink import (
    ARTIFACT_PROPERTY,
    ENGAGEMENT_STORAGE_GROUP,
    ENGAGEMENT_STORAGE_NAME,
    EVIDENCE_INDEX,
    RUN_PROPERTY,
    AccessRecheckError,
    ArtifactSink,
    DriveRunSink,
    LocalDirSink,
    LocalStorageRefused,
    MemorySink,
    SinkConflictError,
    StorageUnavailableError,
    load_engagement_storage,
    open_sink,
    sink_evidence,
    validate_relpath,
)
from starboard_core.engagement.staging import encode_json
from starboard_core.engagement.write_guard import GuardPolicy, guarded
from starboard_core.ports.engagement_storage import (
    EngagementStoragePort,
    Grant,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StoragePermissionError,
)

RID = "20261008_12345678-1234-4234-8234-123456789abc"
LOCAL = StorageDecision(StoragePolicy.LOCAL, drive_required=False, reason="public")
REQUIRED = StorageDecision(
    StoragePolicy.DRIVE_REQUIRED, drive_required=True, reason="overlay"
)
DEFAULT = StorageDecision(
    StoragePolicy.DRIVE_DEFAULT, drive_required=False, reason="internal"
)
INTERNAL_LOCAL = StorageDecision(
    StoragePolicy.INTERNAL_ONLY_LOCAL, drive_required=False, reason="operator"
)


def _run() -> tuple[InMemoryEngagementStorage, str, str]:
    store = InMemoryEngagementStorage()
    run = store.create_folder(
        store.root_folder_id(), RID, {IDENTITY_PROPERTY: f"run:{RID}"}
    )
    return store, run.id, store.inspect_access(run.id).fingerprint


def _sink(**kw: Any) -> tuple[InMemoryEngagementStorage, str, DriveRunSink]:
    store, run_id, fp = _run()
    return (
        store,
        run_id,
        DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp, **kw),
    )


def _artifacts(store: InMemoryEngagementStorage, folder_id: str) -> list[Any]:
    """Every artifact file below ``folder_id`` (count by artifact property)."""
    found = []
    for child in store.list_children(folder_id):
        if child.is_folder:
            found.extend(_artifacts(store, child.id))
        elif ARTIFACT_PROPERTY in child.properties:
            found.append(child)
    return found


# --- validate_relpath -------------------------------------------------------------------


@pytest.mark.parametrize(
    "good", ["a.json", "raw/w-w01.json", "analysis/verify/qh 1.json"]
)
def test_validate_relpath_accepts_run_relative(good: str) -> None:
    assert validate_relpath(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "/abs.json",
        "~/x.json",
        "a/../b.json",
        "..",
        "./a.json",
        "a//b.json",
        "a/",
        "a\\b.json",
        "C:/x.json",
        "c:x.json",
        "a\x00b",
    ],
)
def test_validate_relpath_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_relpath(bad)


def test_validate_relpath_rejects_non_str() -> None:
    with pytest.raises(ValueError):
        validate_relpath(b"a.json")  # type: ignore[arg-type]


# --- DriveRunSink -----------------------------------------------------------------------


def test_drive_sink_is_an_artifact_sink() -> None:
    _, _, sink = _sink()
    assert isinstance(sink, ArtifactSink)
    assert sink.kind == "drive"
    assert sink.run_id == RID


def test_put_creates_nested_folders_with_identity_and_tags_the_file() -> None:
    store, run_id, sink = _sink()
    ref = sink.put_bytes("analysis/verify/qh.json", b'{"a": 1}', "application/json")
    analysis = store.list_children(run_id, name="analysis", folders_only=True)
    assert [f.properties[IDENTITY_PROPERTY] for f in analysis] == [
        "artifact-dir:analysis"
    ]
    verify = store.list_children(analysis[0].id, name="verify", folders_only=True)
    assert [f.properties[IDENTITY_PROPERTY] for f in verify] == [
        "artifact-dir:analysis/verify"
    ]
    (obj,) = store.list_children(verify[0].id, name="qh.json")
    assert obj.properties == {
        ARTIFACT_PROPERTY: "analysis/verify/qh.json",
        RUN_PROPERTY: RID,
    }
    assert ref.path == "analysis/verify/qh.json"
    assert ref.object_id == obj.id
    assert ref.md5 == hashlib.md5(b'{"a": 1}').hexdigest()
    assert ref.size == 8
    assert ref.revision == obj.revision
    assert ref.mime_type == "application/json"
    assert sink.get_bytes("analysis/verify/qh.json") == b'{"a": 1}'
    assert sink.exists("analysis/verify/qh.json")
    assert not sink.exists("analysis/verify/other.json")
    assert not sink.exists("nope/qh.json")


def test_sibling_files_share_the_folder() -> None:
    store, run_id, sink = _sink()
    sink.put_text("raw/a.md", "a")
    sink.put_text("raw/b.md", "b")
    assert len(store.list_children(run_id, name="raw", folders_only=True)) == 1


def test_same_bytes_are_reused_not_rewritten() -> None:
    store, _, sink = _sink()
    first = sink.put_bytes("facts.json", b"x", "application/json")
    count = store.object_count
    again = sink.put_bytes("facts.json", b"x", "application/json")
    assert again == first
    assert store.object_count == count


def test_reuse_across_processes_counts_one_object() -> None:
    store, run_id, sink = _sink()
    sink.put_json("raw/w.json", {"rows": [1]})
    fp = store.inspect_access(run_id).fingerprint
    rerun = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp)
    rerun.put_json("raw/w.json", {"rows": [1]})
    assert len(_artifacts(store, run_id)) == 1


def test_changed_bytes_write_a_new_revision_in_place() -> None:
    store, _, sink = _sink()
    first = sink.put_bytes("facts.json", b"one", "application/json")
    count = store.object_count
    second = sink.put_bytes("facts.json", b"two", "application/json")
    assert second.object_id == first.object_id
    assert second.revision != first.revision
    assert store.object_count == count
    assert sink.get_bytes("facts.json") == b"two"
    assert sink.refs() == (second,)


def test_refs_are_unique_by_path_in_write_order() -> None:
    _, _, sink = _sink()
    a = sink.put_text("a.md", "1")
    sink.put_text("b.md", "1")
    a2 = sink.put_text("a.md", "2")
    assert [r.path for r in sink.refs()] == ["a.md", "b.md"]
    assert sink.refs()[0] == a2 != a


def test_put_json_uses_deterministic_encoding() -> None:
    _, _, sink = _sink()
    sink.put_json("a.json", {"b": 1, "a": [1, 2]})
    assert sink.get_bytes("a.json") == encode_json({"a": [1, 2], "b": 1})
    ref = sink.put_json("list.json", [3, {"z": 1, "y": 2}])
    assert ref.mime_type == "application/json"
    assert json.loads(sink.get_bytes("list.json")) == [3, {"y": 2, "z": 1}]


@pytest.mark.parametrize("payload", ["text", b"bytes"])
def test_put_json_rejects_scalars(payload: Any) -> None:
    _, _, sink = _sink()
    with pytest.raises(TypeError):
        sink.put_json("a.json", payload)


def test_put_text_defaults_to_markdown() -> None:
    _, _, sink = _sink()
    assert sink.put_text("analysis/review.md", "# hi").mime_type == "text/markdown"
    assert sink.get_bytes("analysis/review.md") == b"# hi"


def test_get_bytes_over_the_cap_is_refused_and_missing_raises() -> None:
    _, _, sink = _sink()
    sink.put_bytes("big.bin", b"0123456789" * 20_000, "application/octet-stream")
    with pytest.raises(ReadRefusedError, match="larger than 5 bytes"):
        sink.get_bytes("big.bin", max_bytes=5)
    assert len(sink.get_bytes("big.bin", max_bytes=200_000)) == 200_000
    with pytest.raises(StorageNotFoundError):
        sink.get_bytes("absent.bin")


def test_read_cap_default_is_the_64_mib_intake_cap() -> None:
    from starboard_x._cli import MAX_INTAKE_BYTES

    assert sink_mod.MAX_READ_BYTES == 64 * 2**20 == MAX_INTAKE_BYTES
    for cls in (DriveRunSink, LocalDirSink, MemorySink):
        default = inspect.signature(cls.get_bytes).parameters["max_bytes"].default
        assert default == sink_mod.MAX_READ_BYTES, cls.__name__


def test_drive_get_bytes_default_cap_refused_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, sink = _sink()
    sink.put_text("raw/a.json", "abc")
    real_lookup = sink._lookup
    monkeypatch.setattr(
        sink,
        "_lookup",
        lambda rel: dataclasses.replace(
            real_lookup(rel), size=sink_mod.MAX_READ_BYTES + 1
        ),
    )
    monkeypatch.setattr(
        store, "get_stream", lambda *_a, **_k: pytest.fail("downloaded")
    )
    with pytest.raises(
        ReadRefusedError, match=f"larger than {sink_mod.MAX_READ_BYTES}"
    ):
        sink.get_bytes("raw/a.json")


def test_drive_get_bytes_cap_enforced_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, sink = _sink()
    sink.put_text("raw/a.json", "abc")  # Drive records 3 bytes; the stream runs on
    pulled: list[int] = []

    def stream(*_a: object, **_k: object) -> Iterator[bytes]:
        for i in range(100):
            pulled.append(i)
            yield b"x" * 4

    monkeypatch.setattr(store, "get_stream", stream)
    with pytest.raises(ReadRefusedError, match="larger than 10 bytes"):
        sink.get_bytes("raw/a.json", max_bytes=10)
    assert len(pulled) == 3


def test_list_walks_artifact_folders_only() -> None:
    store, run_id, sink = _sink()
    sink.put_text("raw/b.json", "1")
    sink.put_text("raw/a.json", "1")
    sink.put_text("analysis/review.md", "1")
    sink.put_text("facts.json", "1")
    store.put_stream(
        run_id, DESCRIPTOR_NAME, "application/json", [b"{}"], properties={}
    )
    assert sink.list() == (
        "analysis/review.md",
        "facts.json",
        "raw/a.json",
        "raw/b.json",
    )
    assert sink.list("raw/") == ("raw/a.json", "raw/b.json")
    assert sink.list("nothing/") == ()


@pytest.mark.parametrize(
    "reserved", [DESCRIPTOR_NAME, "manifest/rev-000001.json", "manifest"]
)
def test_commit_records_are_not_writable_through_the_sink(reserved: str) -> None:
    store, _, sink = _sink()
    count = store.object_count
    with pytest.raises(ValueError):
        sink.put_bytes(reserved, b"{}", "application/json")
    assert store.object_count == count


def test_nested_names_like_reserved_ones_are_fine() -> None:
    _, _, sink = _sink()
    sink.put_text("analysis/manifest/x.json", "1")
    sink.put_text(f"domains/{DESCRIPTOR_NAME}", "1")
    sink.put_text("deliverables/findings-manifest.json", "1")


def test_oversized_write_refused_before_any_call() -> None:
    store, _, sink = _sink(max_bytes=4)
    count = store.object_count
    with pytest.raises(StorageError):
        sink.put_bytes("a.bin", b"12345", "application/octet-stream")
    assert store.object_count == count


def test_read_back_corruption_raises_integrity_on_read() -> None:
    # The upload is verified against Drive's stored size + md5 (no re-download);
    # a corrupted stream is caught by the read's own md5 check.
    store, _, sink = _sink()
    store.corrupt_get_stream = lambda b: b + b"!"
    ref = sink.put_text("a.md", "x")
    assert ref.md5 == hashlib.md5(b"x").hexdigest()
    with pytest.raises(StorageIntegrityError):
        sink.get_bytes("a.md")


def test_provider_side_corruption_raises_integrity() -> None:
    store, _, sink = _sink()
    store.corrupt_read_back = lambda b: b[::-1] + b"?"
    with pytest.raises(StorageIntegrityError):
        sink.put_text("a.md", "xy")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"grants": (Grant("anyone", "reader"),)}, "changed"),
        ({"can_add_children": False}, "revoked"),
        ({"complete": False}, "unknown"),
    ],
)
def test_access_recheck_failure_blocks_writes(
    change: dict[str, Any], reason: str
) -> None:
    store, run_id, sink = _sink()
    store.set_access(run_id, **change)
    count = store.object_count
    with pytest.raises(AccessRecheckError) as info:
        sink.put_text("raw/a.json", "x")
    assert isinstance(info.value, StoragePermissionError)
    assert info.value.verdict.reason == reason
    assert store.object_count == count


def test_acl_change_between_processes_stops_writes() -> None:
    # Access is checked once per sink (one per process); the next process's sink
    # sees the changed ACL and refuses, and stays poisoned (D-24).
    store, run_id, sink = _sink()
    fp = store.inspect_access(run_id).fingerprint
    sink.put_text("raw/a.json", "x")
    store.set_access(run_id, grants=(Grant("domain", "reader", "other.example"),))
    sink.put_text("raw/b.json", "x")  # same process: no recheck
    rerun = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp)
    count = store.object_count
    with pytest.raises(AccessRecheckError):
        rerun.put_text("raw/c.json", "x")
    store.set_access(run_id, grants=())
    with pytest.raises(StoragePermissionError):
        rerun.put_text("raw/c.json", "x")  # the sink stays poisoned (D-24)
    assert store.object_count == count


def test_access_is_inspected_once_per_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    store, run_id, sink = _sink()
    calls: list[str] = []
    real = store.inspect_access
    monkeypatch.setattr(
        store, "inspect_access", lambda oid: calls.append(oid) or real(oid)
    )
    for i in range(5):
        sink.put_text(f"raw/{i}.json", "x")
    assert calls == [run_id]


def test_pre_inspected_access_is_still_checked_against_the_fingerprint() -> None:
    store, run_id, fp = _run()
    store.set_access(run_id, can_add_children=False)
    info = store.inspect_access(run_id)
    sink = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp, access=info)
    with pytest.raises(AccessRecheckError) as err:
        sink.put_text("a.md", "x")
    assert err.value.verdict.reason == "revoked"


def test_provider_refusal_after_an_acl_change_is_blocked_access() -> None:
    store, run_id, sink = _sink()
    sink.put_text("a.md", "x")
    store.set_access(run_id, can_add_children=False)
    store.deny_writes_under.add(run_id)
    with pytest.raises(AccessRecheckError) as err:
        sink.put_text("b.md", "x")
    assert err.value.verdict.reason == "revoked"


def test_permission_error_from_storage_poisons_the_sink() -> None:
    store, run_id, sink = _sink()
    store.deny_writes_under.add(run_id)
    with pytest.raises(StoragePermissionError):
        sink.put_text("a.md", "x")
    store.deny_writes_under.clear()
    with pytest.raises(StoragePermissionError):
        sink.put_text("a.md", "x")
    assert not sink.exists("a.md")  # reads remain available


def test_missing_fingerprint_is_refused() -> None:
    store, run_id, _ = _run()
    sink = DriveRunSink(store, run_id, run_id=RID, access_fingerprint="")
    with pytest.raises(AccessRecheckError):
        sink.put_text("a.md", "x")


def test_duplicate_artifacts_are_a_conflict() -> None:
    store, run_id, sink = _sink()
    props = {ARTIFACT_PROPERTY: "a.md", RUN_PROPERTY: RID}
    store.put_stream(run_id, "a.md", "text/markdown", [b"1"], properties=props)
    store.put_stream(run_id, "a.md", "text/markdown", [b"2"], properties=props)
    with pytest.raises(SinkConflictError):
        sink.put_text("a.md", "3")
    with pytest.raises(SinkConflictError):
        sink.get_bytes("a.md")


def test_foreign_same_named_file_is_a_conflict() -> None:
    store, run_id, sink = _sink()
    store.put_stream(run_id, "a.md", "text/markdown", [b"hand-made"], properties={})
    with pytest.raises(SinkConflictError):
        sink.put_text("a.md", "x")


def test_retried_upload_twin_converges_on_the_earliest_copy() -> None:
    # A retried upload left two identical copies: the run is not wedged.
    store, run_id, sink = _sink()
    store.duplicate_on_put.add("a.md")
    ref = sink.put_text("a.md", "x")
    assert len(_artifacts(store, run_id)) == 2
    assert sink.get_bytes("a.md") == b"x"
    fp = store.inspect_access(run_id).fingerprint
    rerun = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp)
    assert rerun.get_bytes("a.md") == b"x"
    (kept,) = rerun.artifacts().values()
    assert kept.id == ref.object_id  # the earliest copy
    assert len(rerun.warnings) == 1
    assert rerun.warnings[0].startswith("duplicate_artifact: 'a.md' had 2 identical")
    assert [o.id for o in _artifacts(store, run_id)] == [ref.object_id]  # twin trashed
    assert rerun.put_text("a.md", "x") == ref
    assert [r.path for r in rerun.refs()] == ["a.md"]


def test_identical_copies_found_on_write_converge_too() -> None:
    store, run_id, sink = _sink()
    props = {ARTIFACT_PROPERTY: "a.md", RUN_PROPERTY: RID}
    first = store.put_stream(run_id, "a.md", "text/markdown", [b"1"], properties=props)
    store.put_stream(run_id, "a.md", "text/markdown", [b"1"], properties=props)
    ref = sink.put_text("a.md", "1")
    assert ref.object_id == first.id
    assert sink.warnings and sink.warnings[0].startswith("duplicate_artifact:")
    assert len(_artifacts(store, run_id)) == 1


def test_untrashable_twin_is_kept_and_reported() -> None:
    store, run_id, sink = _sink()
    props = {ARTIFACT_PROPERTY: "a.md", RUN_PROPERTY: RID}
    store.put_stream(run_id, "a.md", "text/markdown", [b"1"], properties=props)
    store.put_stream(run_id, "a.md", "text/markdown", [b"1"], properties=props)
    store.deny_writes_under.add(run_id)
    assert sink.get_bytes("a.md") == b"1"
    assert "could not trash" in sink.warnings[0]
    assert len(_artifacts(store, run_id)) == 2


def test_differing_copies_are_a_conflict_on_listing() -> None:
    store, run_id, sink = _sink()
    props = {ARTIFACT_PROPERTY: "raw/a.md", RUN_PROPERTY: RID}
    sink.put_text("raw/b.md", "b")
    (raw,) = store.list_children(run_id, name="raw", folders_only=True)
    store.put_stream(raw.id, "a.md", "text/markdown", [b"1"], properties=props)
    store.put_stream(raw.id, "a.md", "text/markdown", [b"2"], properties=props)
    fp = store.inspect_access(run_id).fingerprint
    rerun = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp)
    assert rerun.list("raw/") == ("raw/a.md", "raw/b.md")
    with pytest.raises(SinkConflictError, match="differing content"):
        rerun.artifacts()
    with pytest.raises(SinkConflictError):
        rerun.get_bytes("raw/a.md")
    assert rerun.get_bytes("raw/b.md") == b"b"
    assert rerun.warnings == []


def test_artifact_of_another_run_is_a_conflict() -> None:
    store, run_id, sink = _sink()
    props = {ARTIFACT_PROPERTY: "a.md", RUN_PROPERTY: "other-run"}
    store.put_stream(run_id, "a.md", "text/markdown", [b"1"], properties=props)
    with pytest.raises(SinkConflictError):
        sink.put_text("a.md", "x")


class _Counting:
    """Delegates to the storage and counts every port call by method name."""

    def __init__(self, inner: InMemoryEngagementStorage) -> None:
        self.inner = inner
        self.calls: collections.Counter[str] = collections.Counter()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if not callable(attr):
            return attr

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.calls[name] += 1
            return attr(*args, **kwargs)

        return counted

    def take(self) -> dict[str, int]:
        out = dict(self.calls)
        self.calls.clear()
        return out


def _counting_sink(
    **kw: Any,
) -> tuple[InMemoryEngagementStorage, str, str, _Counting, DriveRunSink]:
    store, run_id, fp = _run()
    counting = _Counting(store)
    sink = DriveRunSink(
        cast(EngagementStoragePort, counting),
        run_id,
        run_id=RID,
        access_fingerprint=fp,
        **kw,
    )
    return store, run_id, fp, counting, sink


def test_call_counts_per_put_read_and_listing() -> None:
    store, run_id, fp, counting, sink = _counting_sink()
    # First put: one access check, one run query, the new folder, the upload.
    sink.put_text("raw/a.json", "a")
    assert counting.take() == {
        "inspect_access": 1,
        "find_by_property": 1,
        "list_children": 2,  # name probe + created-folder read-back
        "create_folder": 1,
        "put_stream": 1,
    }
    # Next new file in a folder this sink created: the upload only.
    sink.put_text("raw/b.json", "b")
    assert counting.take() == {"put_stream": 1}
    # Same bytes again: no call at all.
    sink.put_text("raw/a.json", "a")
    assert counting.take() == {}
    # Changed bytes: one in-place revision.
    sink.put_text("raw/a.json", "a2")
    assert counting.take() == {"update_stream": 1}
    # A read: no lookup listing, one verified download.
    assert sink.get_bytes("raw/b.json") == b"b"
    assert counting.take() == {"get_stream": 1}
    assert sink.exists("raw/a.json") and not sink.exists("raw/zzz.json")
    assert counting.take() == {}
    # Listing: served from the index.
    assert sink.list() == ("raw/a.json", "raw/b.json")
    assert counting.take() == {}


def test_call_counts_for_a_later_process() -> None:
    store, run_id, fp, counting, sink = _counting_sink()
    for i in range(10):
        sink.put_text(f"raw/d{i % 3}/{i}.json", str(i))
    sink.put_text("facts.json", "f")
    counting.take()
    info = store.inspect_access(run_id)
    rerun = DriveRunSink(
        cast(EngagementStoragePort, counting),
        run_id,
        run_id=RID,
        access_fingerprint=fp,
        access=info,
    )
    # The whole run is listed with ONE query, whatever its folder depth.
    arts = rerun.artifacts()
    assert len(arts) == 11 and list(arts) == sorted(arts)
    assert counting.take() == {"find_by_property": 1}
    # Read: the download only. Reused put: nothing.
    assert rerun.get_bytes("raw/d1/4.json") == b"4"
    rerun.put_text("raw/d1/4.json", "4")
    assert counting.take() == {"get_stream": 1}
    # New file in an existing folder: one name listing (foreign-file check) + upload.
    rerun.put_text("raw/d1/new.json", "n")
    assert counting.take() == {"list_children": 1, "put_stream": 1}


def test_no_download_after_an_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    store, _, sink = _sink()
    monkeypatch.setattr(
        store, "get_stream", lambda *_a, **_k: pytest.fail("downloaded after upload")
    )
    ref = sink.put_bytes("raw/big.bin", b"z" * 100_000, "application/octet-stream")
    assert ref.md5 == hashlib.md5(b"z" * 100_000).hexdigest()
    assert ref.size == 100_000


def test_legacy_untagged_folders_are_indexed() -> None:
    # Folders made before run tagging carry only their artifact-dir identity.
    store, run_id, fp = _run()
    raw = store.create_folder(run_id, "raw", {IDENTITY_PROPERTY: "artifact-dir:raw"})
    props = {ARTIFACT_PROPERTY: "raw/a.json", RUN_PROPERTY: RID}
    store.put_stream(raw.id, "a.json", "application/json", [b"1"], properties=props)
    counting = _Counting(store)
    sink = DriveRunSink(
        cast(EngagementStoragePort, counting), run_id, run_id=RID, access_fingerprint=fp
    )
    assert list(sink.artifacts()) == ["raw/a.json"]
    # inspect_access scopes the query (shared drive); the write check reuses it.
    assert counting.take() == {"inspect_access": 1, "find_by_property": 1, "get": 1}
    sink.put_text("raw/b.json", "2")
    assert sorted(sink.artifacts()) == ["raw/a.json", "raw/b.json"]
    assert len(store.list_children(run_id, name="raw", folders_only=True)) == 1


def test_files_outside_the_run_folder_chain_are_ignored() -> None:
    store, run_id, fp = _run()
    elsewhere = store.create_folder(store.root_folder_id(), "copy", {})
    props = {ARTIFACT_PROPERTY: "a.json", RUN_PROPERTY: RID}
    store.put_stream(
        elsewhere.id, "a.json", "application/json", [b"1"], properties=props
    )
    sink = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp)
    assert sink.artifacts() == {}
    assert not sink.exists("a.json")


def test_incomplete_property_search_falls_back_to_the_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, run_id, fp = _run()
    DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp).put_text(
        "raw/a.json", "1"
    )

    def incomplete(*_a: Any, **_k: Any) -> Any:
        raise StorageError("incomplete search")

    monkeypatch.setattr(store, "find_by_property", incomplete)
    sink = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp)
    assert list(sink.artifacts()) == ["raw/a.json"]


def test_concurrent_puts_from_threads_are_consistent() -> None:
    store, run_id, sink = _sink()
    rels = [f"domains/p{i % 4}/{i}.json" for i in range(32)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = list(pool.map(lambda r: sink.put_text(r, r), rels))
    assert [r.path for r in refs] == rels
    assert sorted(r.path for r in sink.refs()) == sorted(rels)
    assert len(store.list_children(run_id, name="domains", folders_only=True)) == 1
    assert len(_artifacts(store, run_id)) == 32
    fp = store.inspect_access(run_id).fingerprint
    rerun = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp)
    assert sorted(rerun.artifacts()) == sorted(rels)


def test_concurrent_puts_of_one_relpath_create_one_object() -> None:
    store, run_id, sink = _sink()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: sink.put_text("raw/same.json", str(i % 2)), range(16)))
    assert len(_artifacts(store, run_id)) == 1
    assert [r.path for r in sink.refs()] == ["raw/same.json"]


def test_drive_sink_writes_nothing_locally_under_the_guard(tmp_path: Path) -> None:
    _, _, sink = _sink()
    with guarded(GuardPolicy(allow_prefixes=())):
        sink.put_json("raw/w.json", {"rows": list(range(100))})
        assert json.loads(sink.get_bytes("raw/w.json"))["rows"][-1] == 99


# --- LocalDirSink / MemorySink ----------------------------------------------------------


@pytest.mark.parametrize("decision", [REQUIRED, DEFAULT])
def test_local_sink_refuses_drive_policies(
    tmp_path: Path, decision: StorageDecision
) -> None:
    with pytest.raises(LocalStorageRefused) as info:
        LocalDirSink(tmp_path, decision=decision)
    assert info.value.code == "LOCAL_STORAGE_REFUSED"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("decision", [LOCAL, INTERNAL_LOCAL])
def test_local_sink_round_trip(tmp_path: Path, decision: StorageDecision) -> None:
    sink = LocalDirSink(tmp_path / "run", decision=decision, run_id=RID)
    assert isinstance(sink, ArtifactSink)
    assert sink.kind == "local"
    ref = sink.put_json("raw/w.json", {"a": 1})
    data = (tmp_path / "run" / "raw" / "w.json").read_bytes()
    assert data == encode_json({"a": 1})
    assert ref.object_id == "local:raw/w.json"
    assert ref.md5 == hashlib.md5(data).hexdigest()
    assert ref.size == len(data)
    with pytest.raises(ReadRefusedError, match="larger than 1 bytes"):
        sink.get_bytes("raw/w.json", max_bytes=1)
    assert sink.get_bytes("raw/w.json", max_bytes=len(data)) == data
    assert sink.exists("raw/w.json")
    sink.put_text("a.md", "x")
    assert sink.list() == ("a.md", "raw/w.json")
    assert sink.list("raw/") == ("raw/w.json",)
    assert [r.path for r in sink.refs()] == ["raw/w.json", "a.md"]


def test_local_sink_refuses_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    os.symlink(tmp_path / "outside", root / "link")
    sink = LocalDirSink(root, decision=LOCAL)
    with pytest.raises(ValueError):
        sink.put_text("link/x.md", "x")
    assert list((tmp_path / "outside").iterdir()) == []


def test_local_sink_missing_raises_not_found(tmp_path: Path) -> None:
    sink = LocalDirSink(tmp_path, decision=LOCAL)
    with pytest.raises(StorageNotFoundError):
        sink.get_bytes("absent.json")


def test_memory_sink_round_trip() -> None:
    sink = MemorySink(run_id=RID)
    assert isinstance(sink, ArtifactSink)
    assert (sink.kind, sink.run_id) == ("memory", RID)
    ref = sink.put_text("a/b.md", "hello")
    assert ref.object_id == "memory:a/b.md"
    assert sink.get_bytes("a/b.md") == b"hello"
    with pytest.raises(ReadRefusedError, match="larger than 2 bytes"):
        sink.get_bytes("a/b.md", max_bytes=2)
    assert sink.get_bytes("a/b.md", max_bytes=5) == b"hello"
    assert sink.exists("a/b.md")
    assert sink.list() == ("a/b.md",)
    with pytest.raises(StorageNotFoundError):
        sink.get_bytes("x")
    with pytest.raises(ValueError):
        sink.put_text("../x", "x")


# --- open_sink --------------------------------------------------------------------------


def _auth(run_folder_id: str, fingerprints: dict[str, str]) -> RunAuthorization:
    drive = DriveContext(
        provider="google_drive",
        principal="perm-1",
        route="account",
        base_folder_id="base",
        root_folder_id="root",
        run_folder_id=run_folder_id,
        registry_folder_id="reg",
        account_key="acme",
        acl_classification="restricted",
        permission_fingerprints=fingerprints,
        capabilities={"upload": True},
        created_at="2026-10-08T09:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
    )
    return RunAuthorization(
        engagement_id="eng-acme",
        run_id=RID,
        intent="discovery",
        task="workspace",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={"workspace_ids": ["123"]},
        authorized_scope={"account_key": "acme", "workspace_ids": ["123"]},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.DRIVE_REQUIRED,
        audience="internal",
        methodology_version="m1",
        drive=drive,
    )


def test_open_sink_with_run_folder_reads_the_descriptor() -> None:
    store, run_id, fp = _run()
    write_descriptor(store, run_id, _auth(run_id, {run_id: fp}))
    sink = open_sink(
        decision=REQUIRED,
        run_folder_id=run_id,
        local_root=None,
        storage_factory=lambda: store,
    )
    assert isinstance(sink, DriveRunSink)
    assert sink.run_id == RID
    sink.put_text("a.md", "x")  # the recorded fingerprint passes the recheck


def test_open_sink_keeps_the_descriptor_it_read() -> None:
    store, run_id, fp = _run()
    auth = _auth(run_id, {run_id: fp})
    write_descriptor(store, run_id, auth)
    sink = open_sink(
        decision=REQUIRED,
        run_folder_id=run_id,
        local_root=None,
        storage_factory=lambda: store,
    )
    assert isinstance(sink, DriveRunSink)
    assert sink.authorization == auth  # in memory, so a helper does not download it again


def test_absent_folder_lookups_are_listed_once_and_a_create_is_seen() -> None:
    store, run_id, fp, counting, sink = _counting_sink()
    sink.put_text("a.json", "a")
    counting.take()
    # Index misses under a folder that does not exist: one folder listing, not one each.
    assert not sink.exists("analysis/x.json")
    first = counting.take()
    assert not sink.exists("analysis/y.json") and not sink.exists("analysis/z.json")
    assert counting.take() == {}
    assert first.get("list_children") == 1
    # Creating it must not leave the stale miss behind.
    sink.put_text("analysis/x.json", "x")
    counting.take()
    assert sink.exists("analysis/x.json")
    assert sink.get_bytes("analysis/x.json") == b"x"
    sink.put_text("analysis/y.json", "y")
    assert sink.exists("analysis/y.json") and not sink.exists("analysis/z.json")


def test_open_sink_without_descriptor_fails() -> None:
    store, run_id, _ = _run()
    with pytest.raises(CommitError):
        open_sink(
            decision=REQUIRED,
            run_folder_id=run_id,
            local_root=None,
            storage_factory=lambda: store,
        )


def test_open_sink_without_recorded_fingerprint_fails() -> None:
    store, run_id, _ = _run()
    write_descriptor(store, run_id, _auth(run_id, {}))
    with pytest.raises(StoragePermissionError):
        open_sink(
            decision=REQUIRED,
            run_folder_id=run_id,
            local_root=None,
            storage_factory=lambda: store,
        )


@pytest.mark.parametrize("decision", [REQUIRED, DEFAULT])
def test_open_sink_refuses_local_on_drive_policies(
    tmp_path: Path, decision: StorageDecision
) -> None:
    def factory() -> EngagementStoragePort:
        raise AssertionError("storage must not be loaded")

    for local_root in (str(tmp_path), None):
        with pytest.raises(LocalStorageRefused):
            open_sink(
                decision=decision,
                run_folder_id=None,
                local_root=local_root,
                storage_factory=factory,
            )


def test_open_sink_local_and_memory(tmp_path: Path) -> None:
    def factory() -> EngagementStoragePort:
        raise AssertionError("storage must not be loaded")

    local = open_sink(
        decision=LOCAL,
        run_folder_id=None,
        local_root=str(tmp_path),
        storage_factory=factory,
    )
    assert isinstance(local, LocalDirSink)
    memory = open_sink(
        decision=LOCAL, run_folder_id=None, local_root=None, storage_factory=factory
    )
    assert isinstance(memory, MemorySink)


# --- load_engagement_storage ------------------------------------------------------------


def _entry(value: str) -> metadata.EntryPoint:
    return metadata.EntryPoint(
        name=ENGAGEMENT_STORAGE_NAME, value=value, group=ENGAGEMENT_STORAGE_GROUP
    )


def _patch_entry_points(
    monkeypatch: pytest.MonkeyPatch, *entries: metadata.EntryPoint
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> metadata.EntryPoints:
        calls.append(kwargs)
        return metadata.EntryPoints(entries).select(**kwargs)

    monkeypatch.setattr(sink_mod.metadata, "entry_points", fake)
    return calls


def test_group_constants() -> None:
    assert ENGAGEMENT_STORAGE_GROUP == "starboard.engagement_storage"
    assert ENGAGEMENT_STORAGE_NAME == "engagement_storage"


def test_load_engagement_storage_instantiates_the_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_entry_points(
        monkeypatch,
        _entry("starboard_core.engagement.memory_storage:InMemoryEngagementStorage"),
    )
    storage = load_engagement_storage()
    assert isinstance(storage, InMemoryEngagementStorage)
    assert calls == [
        {"group": "starboard.engagement_storage", "name": "engagement_storage"}
    ]


@pytest.mark.parametrize(
    "entries",
    [
        (),
        ("starboard_core.no_such_module:Thing",),
        ("starboard_core.engagement.memory_storage:NoSuchClass",),
        ("builtins:dict",),
        (
            "starboard_core.engagement.memory_storage:InMemoryEngagementStorage",
            "tests.other:Storage",
        ),
    ],
)
def test_load_engagement_storage_fails_closed(
    monkeypatch: pytest.MonkeyPatch, entries: tuple[str, ...]
) -> None:
    _patch_entry_points(monkeypatch, *(_entry(v) for v in entries))
    with pytest.raises(StorageUnavailableError) as info:
        load_engagement_storage()
    assert info.value.code == "STORAGE_UNAVAILABLE"
    assert isinstance(info.value, StorageError)


def test_load_ignores_other_groups_and_names(monkeypatch: pytest.MonkeyPatch) -> None:
    other = metadata.EntryPoint(
        name=ENGAGEMENT_STORAGE_NAME,
        value="starboard_core.engagement.memory_storage:InMemoryEngagementStorage",
        group="starboard.port_adapters",
    )
    _patch_entry_points(monkeypatch, other)
    with pytest.raises(StorageUnavailableError):
        load_engagement_storage()


def _failing_factory() -> EngagementStoragePort:
    raise RuntimeError("no credentials")


def test_constructor_failure_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(
        monkeypatch, _entry("starboard_core.engagement.sink:_test_factory")
    )
    monkeypatch.setattr(sink_mod, "_test_factory", _failing_factory, raising=False)
    with pytest.raises(StorageUnavailableError):
        load_engagement_storage()


# --- sink_evidence ----------------------------------------------------------------------


def _evidence(sink: ArtifactSink, relpath: str, body: str) -> EvidenceRef:
    ref = sink.put_text(relpath, body, "application/json")
    assert ref.md5 is not None
    return EvidenceRef(
        evidence_id=evidence_id(RID, ref.path, ref.md5),
        run_id=RID,
        storage_ref=ref,
        source_kind="customer_workspace",
        scope_workspace_ids=("123",),
        producer="discovery:W-W01",
        row_count=1,
        truncated=False,
        acquired_at="2026-10-08T09:00:00+00:00",
        audience_class=audience_class_for("customer_workspace"),
        method_version="m1",
    )


def test_sink_evidence_appends_and_dedupes() -> None:
    _, _, sink = _sink()
    a = _evidence(sink, "raw/a.json", "[1]")
    b = _evidence(sink, "raw/b.json", "[2]")
    first = sink_evidence(sink, [a])
    second = sink_evidence(sink, [b, a])
    assert first.path == second.path == EVIDENCE_INDEX == "evidence/index.json"
    assert second.object_id == first.object_id
    assert second.revision != first.revision
    stored = json.loads(sink.get_bytes(EVIDENCE_INDEX))
    assert [EvidenceRef.from_dict(d) for d in stored] == [a, b]
    assert sink_evidence(sink, [a]).revision == second.revision  # no-op rewrite reused


def test_sink_evidence_refuses_a_corrupt_index() -> None:
    _, _, sink = _sink()
    sink.put_record(EVIDENCE_INDEX, b"{not json", "application/json")
    with pytest.raises(StorageIntegrityError):
        sink_evidence(sink, [])


def test_sink_evidence_refuses_another_runs_refs() -> None:
    sink = MemorySink(run_id="20261008_00000000-0000-4000-8000-000000000000")
    ev = _evidence(MemorySink(run_id=RID), "raw/a.json", "[1]")
    with pytest.raises(ValueError):
        sink_evidence(sink, [ev])


def test_mid_run_revocation_blocks_further_writes() -> None:
    store, _, sink = _sink()
    sink.put_text("raw/a.json", "a")
    store.revoke_access_after_writes = 0
    with pytest.raises(AccessRecheckError) as info:
        sink.put_text("raw/b.json", "b")
    assert info.value.verdict.reason == "revoked"
    store.revoke_access_after_writes = None
    with pytest.raises(StoragePermissionError):
        sink.put_text("raw/c.json", "c")
    assert sink.list() == ("raw/a.json",)


def test_failed_put_is_not_spooled_and_rerun_reuses_earlier_writes() -> None:
    store, run_id, sink = _sink()
    first = sink.put_text("raw/a.json", "a")
    store.fail_put_after = 0
    with pytest.raises(StorageError):
        sink.put_text("raw/b.json", "b")
    store.fail_put_after = None
    fp = store.inspect_access(run_id).fingerprint
    rerun = DriveRunSink(store, run_id, run_id=RID, access_fingerprint=fp)
    count = store.object_count
    assert rerun.put_text("raw/a.json", "a") == first
    assert store.object_count == count
    rerun.put_text("raw/b.json", "b")
    assert rerun.list() == ("raw/a.json", "raw/b.json")


def test_drive_get_bytes_without_recorded_size_or_md5_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, sink = _sink()
    sink.put_text("raw/a.json", "abc")
    real_lookup = sink._lookup
    monkeypatch.setattr(
        sink, "_lookup", lambda rel: dataclasses.replace(real_lookup(rel), md5=None)
    )
    monkeypatch.setattr(
        store, "get_stream", lambda *_a, **_k: pytest.fail("downloaded")
    )
    with pytest.raises(StorageIntegrityError, match="no recorded size / md5"):
        sink.get_bytes("raw/a.json")


def test_every_read_verifies_md5_capped_or_not() -> None:
    store, _, sink = _sink()
    ref = sink.put_text("raw/a.json", "abc")
    store.corrupt_object(ref.object_id)
    with pytest.raises(StorageIntegrityError):
        sink.get_bytes("raw/a.json")
    with pytest.raises(StorageIntegrityError):
        sink.get_bytes("raw/a.json", max_bytes=3)


def test_corrupt_evidence_index_bytes_are_refused() -> None:
    store, _, sink = _sink()
    ref = sink.put_record(EVIDENCE_INDEX, b"[]", "application/json")
    store.corrupt_object(ref.object_id)
    with pytest.raises(StorageIntegrityError):
        sink_evidence(sink, [])


# --- package re-exports ---------------------------------------------------------------


def test_package_reexports_resolve_lazily_without_shadowing() -> None:
    import subprocess
    import sys

    code = (
        "import sys, starboard_core.engagement.write_guard\n"
        "assert 'starboard_core.engagement.sink' not in sys.modules\n"
        "import dataclasses, starboard_core.engagement as e\n"
        "from starboard_core.engagement import status, sink\n"
        "for n in e.__all__: getattr(e, n)\n"
        "assert e.RunStatus is status.RunStatus and dataclasses.is_dataclass(e.RunStatus)\n"
        "assert e.LocalStorageRefused is sink.LocalStorageRefused\n"
        "assert 'DEFAULT_MAX_BYTES' not in e.__all__\n"
        "assert sorted(e.__all__) == sorted(e._ORIGIN)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


# --- relpath hardening (sec H4) -----------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "manifest /x",  # trailing whitespace in a segment
        " a.json",  # leading whitespace
        "analysis/run-authorization.json\n",  # control character
        "a\tb.json",
        "a​b.json",  # zero-width space (format character)
        "a‮b.json",  # bidi override
        "x./y",  # trailing-dot segment
        "x/y.",
        "analysis／run-authorization.json",  # full-width solidus (NFKC -> '/')
        "analysis∕run-authorization.json",  # division slash (survives NFKC)
        "analysis⁄x.json",  # fraction slash
        "analysis＼x.json",  # full-width reverse solidus
        "ﬁle.json",  # ligature: not NFKC-normalised
    ],
)
def test_validate_relpath_rejects_lookalikes_and_controls(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_relpath(bad)


def test_validate_relpath_keeps_percent_as_a_literal() -> None:
    # ``%`` is never decoded: ``%2e%2e`` is a literal file name, not ``..``.
    assert validate_relpath("%2e%2e") == "%2e%2e"
    assert (
        validate_relpath("deliverables/50%-savings.md") == "deliverables/50%-savings.md"
    )
    assert sink_mod.reserved_record("%2e%2e/run-authorization.json") is None


# --- reserved kernel records (sec H3) ------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "kind"),
    [
        ("evidence/index.json", "kernel_updatable"),
        ("analysis/observations.json", "kernel_updatable"),
        ("analysis/findings.json", "kernel_updatable"),
        ("findings-manifest.json", "kernel_updatable"),
        ("analysis/run-check.json", "kernel_updatable"),
        ("analysis/recur-result.json", "kernel_updatable"),
        ("analysis/baseline-selection.json", "kernel_updatable"),
        ("analysis/health.json", "kernel_updatable"),
        ("analysis/plays.json", "kernel_updatable"),
        ("analysis/changes.json", "kernel_updatable"),
        ("analysis/cases.json", "kernel_updatable"),
        ("analysis/actions.json", "kernel_updatable"),
        ("Analysis/Health.JSON", "kernel_updatable"),
        ("analysis/storage-preflight.json", "create_once"),
        ("analysis/identity-check.json", "create_once"),
        ("analysis/run-authorization.json", "create_once"),
        ("reports/cost-review/rev-000001.json", "create_once"),
        ("reports/cost-review/approvals/apr_1.json", "create_once"),
        ("reports/cost-review/receipts/rcp_1.json", "create_once"),
        ("Analysis/Observations.JSON", "kernel_updatable"),
        ("REPORTS/x/REV-000001.json", "create_once"),
        (DESCRIPTOR_NAME, "commit"),
        ("Manifest/x", "commit"),
        ("RUN-AUTHORIZATION.json", "commit"),
    ],
)
def test_reserved_record_classifies_case_insensitively(rel: str, kind: str) -> None:
    assert sink_mod.reserved_record(rel) == kind


@pytest.mark.parametrize(
    "free",
    [
        "analysis/backlog.json",
        "analysis/review.md",
        "deliverables/report.md",
        "reports/cost-review/draft.md",
        "domains/jobs.md",
        "raw/w-w01.json",
    ],
)
def test_ordinary_paths_are_not_reserved(free: str) -> None:
    assert sink_mod.reserved_record(free) is None


@pytest.mark.parametrize(
    "rel",
    [
        "evidence/index.json",
        "analysis/observations.json",
        "findings-manifest.json",
        "analysis/run-check.json",
        "analysis/health.json",
        "analysis/plays.json",
        "analysis/changes.json",
        "analysis/cases.json",
        "analysis/actions.json",
        "analysis/identity-check.json",
        "reports/r/rev-000001.json",
        "reports/r/approvals/a.json",
        "reports/r/receipts/a.json",
        "Manifest/x",
        "Evidence/Index.json",
    ],
)
@pytest.mark.parametrize("make", ["drive", "local", "memory"])
def test_put_bytes_refuses_reserved_records_on_every_sink(
    tmp_path: Path, make: str, rel: str
) -> None:
    store: InMemoryEngagementStorage | None = None
    s: ArtifactSink
    if make == "drive":
        store, _, s = _sink()
    elif make == "local":
        s = LocalDirSink(tmp_path / "run", decision=LOCAL, run_id=RID)
    else:
        s = MemorySink(run_id=RID)
    count = store.object_count if store is not None else 0
    with pytest.raises(ValueError, match="reserved|commit record"):
        s.put_bytes(rel, b"{}", "application/json")
    with pytest.raises(ValueError):
        s.put_json(rel, {})
    with pytest.raises(ValueError):
        s.put_text(rel, "{}")
    if store is not None:
        assert store.object_count == count
    else:
        assert s.list() == ()


def test_put_record_writes_kernel_records_and_tags_them() -> None:
    store, _, sink = _sink()
    ref = sink.put_record("analysis/observations.json", b"[]", "application/json")
    assert ref.path == "analysis/observations.json"
    again = sink.put_record("analysis/observations.json", b"[1]", "application/json")
    assert again.object_id == ref.object_id and again.md5 != ref.md5
    assert sink.get_bytes("analysis/observations.json") == b"[1]"


def test_put_record_refuses_non_records_and_commit_records() -> None:
    _, _, sink = _sink()
    for rel in ("analysis/backlog.json", DESCRIPTOR_NAME, "manifest/rev-000001.json"):
        with pytest.raises(ValueError):
            sink.put_record(rel, b"{}", "application/json")


def test_create_once_records_refuse_changed_bytes() -> None:
    store, _, sink = _sink()
    rel = "reports/r/rev-000001.json"
    first = sink.put_record(rel, b'{"a":1}', "application/json")
    assert (
        sink.put_record(rel, b'{"a":1}', "application/json").object_id
        == first.object_id
    )
    count = store.object_count
    with pytest.raises(SinkConflictError):
        sink.put_record(rel, b'{"a":2}', "application/json")
    assert store.object_count == count
    assert sink.get_bytes(rel) == b'{"a":1}'


@pytest.mark.parametrize("make", ["local", "memory"])
def test_local_and_memory_sinks_offer_put_record(tmp_path: Path, make: str) -> None:
    s: ArtifactSink = (
        LocalDirSink(tmp_path, decision=LOCAL) if make == "local" else MemorySink()
    )
    s.put_record("analysis/run-check.json", b"{}", "application/json")
    s.put_record("reports/r/approvals/a.json", b"{}", "application/json")
    with pytest.raises(SinkConflictError):
        s.put_record("reports/r/approvals/a.json", b"{ }", "application/json")
    with pytest.raises(ValueError):
        s.put_record("analysis/backlog.json", b"{}", "application/json")


def test_sink_evidence_writes_through_put_record() -> None:
    _, _, sink = _sink()
    ev = _evidence(sink, "raw/a.json", "[1]")
    ref = sink_evidence(sink, [ev])
    assert ref.path == EVIDENCE_INDEX
    with pytest.raises(ValueError):
        sink.put_json(EVIDENCE_INDEX, [])
