# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""W30 customer-file intake + F2 storage exit codes of :mod:`starboard_x._cli`.

The overlay seam is ``starboard_x._cli.detect_overlay``: every test pins it (the
dev venv ships ``starboard_internal``, so real detection reports an overlay). The
subprocess CLI suites (``test_{uc,warehouse,diagnostic,sparklog}_cli.py``) pin it
OFF through a ``runpy`` prelude.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starboard_core.engagement import sink
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.policy import LOCAL_FILE_INTAKE_GUIDANCE
from starboard_core.ports.engagement_storage import StorageIntegrityError
from starboard_x import _cli
from starboard_x.contract import EXIT_API, ArgError


def _pin(monkeypatch: pytest.MonkeyPatch, *, overlay: bool) -> None:
    monkeypatch.setattr(
        _cli, "detect_overlay", lambda **_k: OverlaySignal(enabled=overlay)
    )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> InMemoryEngagementStorage:
    """An in-memory Drive resolved through the engagement-storage entry point."""
    s = InMemoryEngagementStorage(owner_domain="databricks.com")
    entry = SimpleNamespace(value="tests:InMemory", load=lambda: lambda: s)
    monkeypatch.setattr(
        sink, "metadata", SimpleNamespace(entry_points=lambda **_kw: [entry])
    )
    return s


def _share(store: InMemoryEngagementStorage, data: bytes) -> str:
    obj = store.put_stream(
        store.root_folder_id(), "rows.json", "application/json", [data], properties={}
    )
    return f"drive:{obj.id}"


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


@pytest.mark.unit
class TestLocalIntake:
    def test_overlay_refuses_a_local_customer_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _pin(monkeypatch, overlay=True)
        path = tmp_path / "rows.json"
        path.write_text("[]")
        with pytest.raises(_cli.LocalFileIntakeRefused) as info:
            _cli.read_json_file(str(path), flag="--input")
        assert info.value.exit_code == 2
        assert info.value.code == _cli.LOCAL_FILE_INTAKE_REFUSED
        assert info.value.message.startswith("LOCAL_FILE_INTAKE_REFUSED: --input ")
        assert LOCAL_FILE_INTAKE_GUIDANCE in info.value.message
        assert "--input drive:<object id>" in info.value.message

    def test_public_reads_a_local_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _pin(monkeypatch, overlay=False)
        path = tmp_path / "rows.json"
        path.write_text('[{"a": 1}]')
        assert _cli.read_json_file(str(path)) == [{"a": 1}]

    def test_public_missing_file_message_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _pin(monkeypatch, overlay=False)
        with pytest.raises(ArgError, match="--text file not found"):
            _cli.read_text_file(str(tmp_path / "nope.txt"), flag="--text")

    def test_non_customer_input_is_not_gated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _pin(monkeypatch, overlay=True)
        path = tmp_path / "rows.json"
        path.write_text("[]")
        assert _cli.read_json_file(str(path), customer_file=False) == []

    def test_refusal_hint_replaces_drive_advice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(monkeypatch, overlay=True)
        with pytest.raises(_cli.LocalFileIntakeRefused) as info:
            _cli.refuse_local_intake("/x.log", flag="--path", hint="Use --source s3.")
        assert info.value.message.endswith("Use --source s3.")
        assert "drive:<object id>" not in info.value.message


@pytest.mark.unit
class TestDriveIntake:
    def test_reads_a_drive_object_in_memory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        store: InMemoryEngagementStorage,
    ) -> None:
        _pin(monkeypatch, overlay=True)
        monkeypatch.chdir(tmp_path)
        ref = _share(store, json.dumps([{"a": 1}]).encode())
        assert _cli.read_json_file(ref) == [{"a": 1}]
        assert _files(tmp_path) == []

    def test_empty_id_is_an_arg_error(self, store: InMemoryEngagementStorage) -> None:
        with pytest.raises(ArgError, match="drive:<object id>"):
            _cli.read_text_file("drive:")

    def test_unknown_id_is_an_arg_error(self, store: InMemoryEngagementStorage) -> None:
        with pytest.raises(ArgError, match="not found"):
            _cli.read_text_file("drive:nope")

    def test_oversize_object_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, store: InMemoryEngagementStorage
    ) -> None:
        monkeypatch.setattr(_cli, "MAX_INTAKE_BYTES", 4)
        ref = _share(store, b"0123456789")
        with pytest.raises(ArgError, match="larger than 4 bytes"):
            _cli.read_text_file(ref)

    def test_folder_is_an_arg_error(self, store: InMemoryEngagementStorage) -> None:
        folder = store.create_folder(store.root_folder_id(), "d", {})
        with pytest.raises(ArgError, match=f"--path drive:{folder.id} is a folder"):
            _cli.read_text_file(f"drive:{folder.id}")

    def test_md5_mismatch_is_a_storage_failure(
        self, store: InMemoryEngagementStorage
    ) -> None:
        ref = _share(store, b"[1, 2, 3]")
        store.corrupt_get_stream = lambda data: data[::-1]
        with pytest.raises(_cli.StorageFailureError) as info:
            _cli.read_text_file(ref)
        assert info.value.exit_code == 7
        assert info.value.message.startswith("STORAGE_INTEGRITY:")

    def test_no_storage_adapter_is_a_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sink, "metadata", SimpleNamespace(entry_points=lambda **_kw: [])
        )
        with pytest.raises(_cli.RefusedError) as info:
            _cli.read_text_file("drive:abc")
        assert info.value.exit_code == 2
        assert info.value.message.startswith("STORAGE_UNAVAILABLE:")


def _run(func, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    parser = _cli.ArgumentParser(prog="t")
    parser.set_defaults(func=func, command="go")
    with pytest.raises(SystemExit) as info:
        _cli.run(domain="t", parser=parser, argv=[])
    return int(info.value.code), json.loads(capsys.readouterr().out)


@pytest.mark.unit
class TestRunExitCodes:
    def test_storage_integrity_error_exits_7(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(_args: argparse.Namespace) -> None:
            raise StorageIntegrityError("read-back mismatch")

        code, env = _run(boom, capsys)
        assert code == 7
        assert env["ok"] is False
        assert env["error"].startswith("STORAGE_INTEGRITY: ")

    def test_other_errors_stay_api_errors(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(_args: argparse.Namespace) -> None:
            raise RuntimeError("upstream 500")

        code, env = _run(boom, capsys)
        assert code == EXIT_API
        assert env["error"] == "API error: upstream 500"

    def test_local_intake_refusal_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _pin(monkeypatch, overlay=True)

        def read(_args: argparse.Namespace) -> str:
            return _cli.read_text_file("/etc/hosts")

        code, env = _run(read, capsys)
        assert code == 2
        assert env["error"].startswith("LOCAL_FILE_INTAKE_REFUSED:")
