# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``HelperRun`` I/O: kernel records, the verified Drive read and evidence recording."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.folders import IDENTITY_PROPERTY
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.policy import StorageDecision, StoragePolicy
from starboard_core.engagement.records import EvidenceRef
from starboard_core.engagement.sink import (
    EVIDENCE_INDEX,
    DriveRunSink,
    SinkConflictError,
)
from starboard_skills.helpers import contract as c

RID = "20261008_12345678-1234-4234-8234-123456789abc"


def _drive_run() -> tuple[c.HelperRun, InMemoryEngagementStorage, DriveRunSink]:
    store = InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), RID, {IDENTITY_PROPERTY: f"run:{RID}"})
    sink = DriveRunSink(
        store, folder.id, run_id=RID, access_fingerprint=store.inspect_access(folder.id).fingerprint
    )
    return c.HelperRun(None, sink, folder.id, lambda: store), store, sink


def _local_run() -> c.HelperRun:
    decision = StorageDecision(StoragePolicy.DRIVE_OPTIONAL, False, "test")

    def no_storage() -> Any:
        raise AssertionError("local writes need no storage")

    return c.HelperRun(decision, None, None, no_storage)


@pytest.mark.unit
class TestWriteRecord:
    def test_drive_write_record_writes_a_kernel_record(self) -> None:
        run, _, sink = _drive_run()
        ref = run.write_record("analysis/findings.json", b"[]", "application/json")
        assert ref is not None and ref.path == "analysis/findings.json"
        assert sink.get_bytes("analysis/findings.json") == b"[]"

    def test_drive_write_refuses_a_kernel_record(self) -> None:
        run, store, _ = _drive_run()
        before = store.object_count
        with pytest.raises(c.StorageRefusedError) as info:
            run.write("analysis/findings.json", b"[]")
        assert info.value.message.startswith("RESERVED_PATH: ")
        assert info.value.exit_code == c.EXIT_STORAGE_REFUSED == 2
        assert store.object_count == before

    @pytest.mark.parametrize(
        "name", ["findings-manifest.json", "run-authorization.json", "manifest"]
    )
    def test_local_write_refuses_a_reserved_basename(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(c.StorageRefusedError) as info:
            _local_run().write(tmp_path / name, b"{}")
        assert info.value.message.startswith("RESERVED_PATH: ")
        assert not (tmp_path / name).exists()

    def test_local_write_allows_an_ordinary_basename(self, tmp_path: Path) -> None:
        _local_run().write(tmp_path / "notes.json", b"{}")
        assert (tmp_path / "notes.json").read_bytes() == b"{}"

    @pytest.mark.parametrize(
        "rel", ["analysis/identity-check.json", "analysis/findings.json"]
    )
    def test_local_write_refuses_a_nested_reserved_record(
        self, tmp_path: Path, rel: str
    ) -> None:
        run = _local_run()
        target = tmp_path / "run" / rel
        run.write_record(target, b"[1]", "application/json")
        with pytest.raises(c.StorageRefusedError) as info:
            run.write(target, b"OVERWRITTEN")
        assert info.value.message.startswith("RESERVED_PATH: ")
        assert info.value.exit_code == 2
        assert target.read_bytes() == b"[1]"

    @pytest.mark.parametrize(
        "rel", ["analysis/identity-check.json", "sub/analysis/findings.json"]
    )
    def test_drive_write_refuses_a_nested_reserved_record(self, rel: str) -> None:
        run, store, _ = _drive_run()
        before = store.object_count
        with pytest.raises(c.StorageRefusedError) as info:
            run.write(rel, b"OVERWRITTEN")
        assert info.value.message.startswith("RESERVED_PATH: ")
        assert store.object_count == before

    def test_nested_ordinary_paths_still_write(self, tmp_path: Path) -> None:
        target = tmp_path / "run" / "analysis" / "notes.json"
        _local_run().write(target, b"{}")
        assert target.read_bytes() == b"{}"
        run, _, sink = _drive_run()
        run.write("analysis/notes.json", b"{}")
        assert sink.get_bytes("analysis/notes.json") == b"{}"

    def test_storage_failure_exit_matches_the_kernel(self) -> None:
        from starboard_core.engagement.sink import EXIT_STORAGE_FAILURE

        assert c.EXIT_STORAGE_FAILURE == EXIT_STORAGE_FAILURE == 7
        assert c.EXIT_STORAGE_FAILURE not in (
            c.EXIT_OK, c.EXIT_AUTH, c.EXIT_NOT_FOUND, c.EXIT_API, c.EXIT_ARG,
        )

    def test_write_record_refuses_an_ordinary_artifact(self) -> None:
        run, _, _ = _drive_run()
        with pytest.raises(ValueError, match="not a kernel record"):
            run.write_record("analysis/notes.json", b"[]", "application/json")

    def test_local_write_record_rewrites_an_updatable_record(self, tmp_path: Path) -> None:
        run = _local_run()
        target = tmp_path / "run" / "analysis" / "findings.json"
        run.write_record(target, b"[1]", "application/json")
        run.write_record(target, b"[2]", "application/json")
        assert target.read_bytes() == b"[2]"

    def test_local_write_record_keeps_create_once(self, tmp_path: Path) -> None:
        run = _local_run()
        target = tmp_path / "run" / "analysis" / "identity-check.json"
        run.write_record(target, b"[1]", "application/json")
        assert target.read_bytes() == b"[1]"
        run.write_record(target, b"[1]", "application/json")  # identical bytes reused
        with pytest.raises(SinkConflictError):
            run.write_record(target, b"[2]", "application/json")

    def test_local_write_record_refuses_an_ordinary_path(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a kernel record"):
            _local_run().write_record(tmp_path / "notes.json", b"[]", "application/json")

    def test_plain_install_write_record_is_a_plain_write(self, tmp_path: Path) -> None:
        run = c.HelperRun(None, None, None, lambda: pytest.fail("no storage"))
        target = tmp_path / "analysis" / "findings.json"
        assert run.write_record(target, b"[]", "application/json") is None
        assert target.read_bytes() == b"[]"


@pytest.mark.unit
class TestReadDriveObject:
    def test_folder_is_an_arg_error(self) -> None:
        store = InMemoryEngagementStorage()
        folder = store.create_folder(store.root_folder_id(), "d", {})
        with pytest.raises(c.ArgError, match="--in drive:.*folder"):
            c.read_drive_object(store, folder.id, flag="--in")

    def test_over_the_cap_is_an_arg_error(self) -> None:
        store = InMemoryEngagementStorage()
        obj = store.put_stream(
            store.root_folder_id(), "f", "application/json", [b"x" * 20], properties={}
        )
        with pytest.raises(c.ArgError, match="larger than 10 bytes"):
            c.read_drive_object(store, obj.id, flag="--in", max_bytes=10)

    def test_reads_verified_bytes(self) -> None:
        store = InMemoryEngagementStorage()
        obj = store.put_stream(
            store.root_folder_id(), "f", "application/json", [b"{}"], properties={}
        )
        assert c.read_drive_object(store, obj.id, flag="--in") == b"{}"


@pytest.mark.unit
class TestRecordEvidence:
    def test_records_through_the_kernel_with_computed_audience(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run, _, sink = _drive_run()
        monkeypatch.setattr(c.HelperRun, "scope_workspace_ids", lambda self: ("123",))
        ref = sink.put_text("raw/x.json", "[]", "application/json")
        c.record_evidence(run, [(ref, "helper:x", 0, False)], source_kind="internal_mirror")
        (ev,) = [EvidenceRef.from_dict(d) for d in json.loads(sink.get_bytes(EVIDENCE_INDEX))]
        assert (ev.source_kind, ev.audience_class) == ("internal_mirror", "internal_only")
        assert ev.scope_workspace_ids == ("123",)
        assert ev.method_version == f"starboard-helper/{c.CONTRACT_VERSION}"

    def test_local_run_records_nothing_and_reads_no_descriptor(self) -> None:
        run = _local_run()
        c.record_evidence(run, [], source_kind="customer_workspace")


@pytest.mark.unit
class TestNotFoundExitRule:
    """A missing helper input is exit 2; a Drive storage NOT_FOUND during a run read/write is 7."""

    def test_storage_not_found_inside_a_run_is_a_storage_failure(self) -> None:
        from starboard_core.ports.engagement_storage import StorageNotFoundError

        with pytest.raises(c.StorageFailureError) as info, c.storage_refusals():
            raise StorageNotFoundError("object o1 vanished")
        assert info.value.exit_code == c.EXIT_STORAGE_FAILURE == 7
        assert info.value.message.startswith("NOT_FOUND: ")

    def test_a_missing_run_input_is_not_found(self) -> None:
        run, _, _ = _drive_run()
        with pytest.raises(c.NotFoundError) as info:
            run.read_input("--in", "raw/missing.json")
        assert info.value.exit_code == c.EXIT_NOT_FOUND == 2

    def test_an_over_cap_run_input_is_an_argument_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from starboard_core.engagement.sink import DriveRunSink, ReadRefusedError

        def refuse(self: DriveRunSink, rel: str, *args: object, **kwargs: object) -> bytes:
            raise ReadRefusedError(f"{rel} is larger than the read cap")

        monkeypatch.setattr(DriveRunSink, "get_bytes", refuse)
        run, _, _ = _drive_run()
        with pytest.raises(c.ArgError) as info:
            run.read_input("--in", "raw/huge.json")
        assert info.value.exit_code == c.EXIT_ARG

    def test_a_missing_local_input_is_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(c.NotFoundError) as info:
            _local_run().read_input("--in", str(tmp_path / "missing.json"))
        assert info.value.exit_code == 2

    def test_a_missing_drive_id_input_is_not_found(self) -> None:
        store = InMemoryEngagementStorage()
        with pytest.raises(c.NotFoundError) as info:
            c.read_drive_object(store, "no-such-object", flag="--in")
        assert info.value.exit_code == 2
