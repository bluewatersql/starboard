"""DBFS loader in-memory parse path: no temp copy when the write guard is active."""

from __future__ import annotations

import pytest
from starboard_core.log_parser.loaders import dbfs

pytestmark = pytest.mark.unit

_LOG = b'{"a": 1}\n{"b": 2}\n'


class _FakeClient:
    def __init__(self, files: dict[str, bytes]):
        self.files = files

    def dbfs_path_exists(self, dbfs_path: str) -> bool:
        return True

    def list_dbfs_files(self, dbfs_path: str, recursive: bool = True):
        return [{"path": p, "is_dir": False} for p in self.files]

    def read_dbfs_chunk(self, dbfs_path: str, offset: int, length: int) -> bytes:
        return self.files[dbfs_path][offset : offset + length]


def _lines(loader) -> list[list[bytes | str]]:
    return [list(stream) for _path, stream in loader.load_item("dbfs:/logs")]


def _no_temp_writes(monkeypatch, loader):
    def boom(*_a, **_k):
        raise AssertionError("temp copy attempted")

    monkeypatch.setattr(loader, "_save_buffer_to_disk", boom)


@pytest.mark.parametrize("streaming", [True, False])
def test_guard_active_save_to_disk_parses_in_memory(tmp_path, monkeypatch, streaming):
    monkeypatch.setattr(dbfs, "_write_guard_active", lambda: True)
    temp_dir = tmp_path / "never-created"
    loader = dbfs.DBFSFileLinesDataLoader(
        dbfs_client=_FakeClient({"/logs/a.json": _LOG}),
        save_to_disk=True,
        temp_dir=temp_dir,
        streaming=streaming,
    )
    _no_temp_writes(monkeypatch, loader)

    result = _lines(loader)

    assert len(result) == 1 and len(result[0]) == 2
    assert not temp_dir.exists()
    assert list(tmp_path.iterdir()) == []


def test_guard_inactive_save_to_disk_still_writes_temp_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(dbfs, "_write_guard_active", lambda: False)
    temp_dir = tmp_path / "tmp-copy"
    loader = dbfs.DBFSFileLinesDataLoader(
        dbfs_client=_FakeClient({"/logs/a.json": _LOG}),
        save_to_disk=True,
        temp_dir=temp_dir,
    )

    result = _lines(loader)

    assert len(result) == 1
    assert (temp_dir / "a.json").read_bytes() == _LOG


def test_default_loader_never_touches_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(dbfs, "_write_guard_active", lambda: False)
    loader = dbfs.DBFSFileLinesDataLoader(
        dbfs_client=_FakeClient({"/logs/a.json": _LOG}), temp_dir=tmp_path / "t"
    )
    _no_temp_writes(monkeypatch, loader)

    assert len(_lines(loader)) == 1
    assert not (tmp_path / "t").exists()


def test_real_write_guard_in_memory_parse_is_not_refused(tmp_path):
    from starboard_core.engagement import write_guard

    temp_dir = tmp_path / "never-created"
    with write_guard.guarded(write_guard.default_policy()):
        assert write_guard.active()
        loader = dbfs.DBFSFileLinesDataLoader(
            dbfs_client=_FakeClient({"/logs/a.json": _LOG}),
            save_to_disk=True,
            temp_dir=temp_dir,
        )
        result = _lines(loader)
    assert not write_guard.active()
    assert len(result) == 1 and len(result[0]) == 2
    assert not temp_dir.exists()
