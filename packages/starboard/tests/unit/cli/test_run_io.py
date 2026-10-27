# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared run-folder I/O of the CLI writers (``starboard.cli.cli._run_io``)."""

from __future__ import annotations

import pytest
from starboard.cli.cli import _run_io
from starboard_core.engagement.enforce import WriterContext
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.policy import StorageDecision, StoragePolicy
from starboard_core.engagement.sink import LocalStorageRefused
from starboard_x.contract import ArgError

from tests.unit.cli._engagement_support import drive_run, sink_for


def _run(*, covered: bool = False) -> tuple[_run_io.CliRun, InMemoryEngagementStorage]:
    store, folder = drive_run()
    policy = StoragePolicy.DRIVE_REQUIRED if covered else StoragePolicy.DRIVE_OPTIONAL
    ctx = WriterContext(StorageDecision(policy, covered, "test"), sink_for(store, folder), None)
    return _run_io.CliRun(ctx, store, folder), store


@pytest.mark.unit
class TestRunInputBytes:
    def test_run_relpath_input(self) -> None:
        run, _ = _run()
        run.ctx.sink.put_bytes("inputs/q.sql", b"SELECT 1", "text/plain")
        assert _run_io.run_input_bytes(run, "--in", "inputs/q.sql") == b"SELECT 1"
        assert run.inputs == ["inputs/q.sql"]

    def test_missing_relpath_is_an_arg_error(self) -> None:
        run, _ = _run()
        with pytest.raises(ArgError, match="not in the run folder"):
            _run_io.run_input_bytes(run, "--in", "inputs/nope.sql")

    def test_drive_object_input_is_verified(self) -> None:
        run, store = _run()
        obj = store.put_stream(
            store.root_folder_id(), "q.sql", "text/plain", [b"SELECT 2"], properties={}
        )
        assert _run_io.run_input_bytes(run, "--in", f"drive:{obj.id}") == b"SELECT 2"
        assert run.inputs == [f"drive:{obj.id}"]

    def test_drive_folder_is_an_arg_error(self) -> None:
        run, store = _run()
        folder = store.create_folder(store.root_folder_id(), "d", {})
        with pytest.raises(ArgError, match="--in: drive:.*folder"):
            _run_io.run_input_bytes(run, "--in", f"drive:{folder.id}")

    def test_drive_object_over_the_cap_is_refused_before_download(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run, store = _run()
        obj = store.put_stream(
            store.root_folder_id(), "big", "text/plain", [b"x" * 32], properties={}
        )
        monkeypatch.setattr(_run_io, "MAX_INPUT_BYTES", 16)
        monkeypatch.setattr(store, "get_stream", lambda *_a, **_k: pytest.fail("downloaded"))
        with pytest.raises(ArgError, match="larger than 16 bytes"):
            _run_io.run_input_bytes(run, "--in", f"drive:{obj.id}")

    def test_run_relpath_over_the_cap_is_refused_before_download(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run, store = _run()
        run.ctx.sink.put_bytes("inputs/big.sql", b"x" * 32, "text/plain")
        monkeypatch.setattr(_run_io, "MAX_INPUT_BYTES", 16)
        monkeypatch.setattr(store, "get_stream", lambda *_a, **_k: pytest.fail("downloaded"))
        with pytest.raises(ArgError, match="--in: .*larger than 16 bytes"):
            _run_io.run_input_bytes(run, "--in", "inputs/big.sql")
        assert run.inputs == []

    def test_missing_drive_object_is_an_arg_error(self) -> None:
        run, _ = _run()
        with pytest.raises(ArgError, match="not found"):
            _run_io.run_input_bytes(run, "--in", "drive:nope")

    def test_local_path_refused_on_a_covered_run(self) -> None:
        run, _ = _run(covered=True)
        with pytest.raises(LocalStorageRefused):
            _run_io.run_input_bytes(run, "--in", "/etc/passwd")


@pytest.mark.unit
class TestRunRelpath:
    def test_uncovered_local_path_is_an_arg_error(self) -> None:
        with pytest.raises(ArgError, match="--out must be a run-relative path"):
            _run_io.run_relpath("--out", "../x", covered_run=False)

    def test_covered_local_path_is_refused(self) -> None:
        with pytest.raises(LocalStorageRefused):
            _run_io.run_relpath("--out", "/x", covered_run=True)


@pytest.mark.unit
def test_cached_storage_factory_loads_once() -> None:
    calls: list[int] = []
    store = InMemoryEngagementStorage()

    def load() -> InMemoryEngagementStorage:
        calls.append(1)
        return store

    factory = _run_io.cached_storage_factory(load)
    assert factory() is store and factory() is store
    assert calls == [1]
