# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for the JSON-file-backed SessionManager (Phase 2 C3).

These tests verify that the CLI session store persists to JSON files (a session
index + per-conversation transcripts) with atomic writes, preserves the public
API byte-for-byte, and no longer depends on ``aiosqlite`` on the CLI hot path.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from starboard.cli.sessions.session_manager import SessionInfo, SessionManager


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point ~ at a temp dir so the default db_path lands under tmp ~/.starboard."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows parity
    return tmp_path


# ---------------------------------------------------------------------------
# Round-trip through the JSON store (default ~/.starboard location)
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_create_list_get_update_delete_roundtrip(home):
    manager = SessionManager()  # default ~/.starboard/sessions.db -> JSON dir
    await manager.connect()
    try:
        # create
        info = await manager.get_or_create("round-trip", user_id="alice")
        assert isinstance(info, SessionInfo)
        assert info.session_name == "round-trip"
        assert info.conversation_id.startswith("cli_session_")
        assert info.user_id == "alice"
        assert info.turn_count == 0

        # list
        sessions = await manager.list_sessions()
        assert [s.session_name for s in sessions] == ["round-trip"]

        # get (idempotent)
        again = await manager.get_or_create("round-trip")
        assert again.conversation_id == info.conversation_id

        # update-activity
        await manager.update_session_activity("round-trip", "hello there")
        updated = await manager.get_or_create("round-trip")
        assert updated.turn_count == 1
        assert updated.last_message_preview == "hello there"

        # delete
        assert await manager.delete_session("round-trip") is True
        assert await manager.list_sessions() == []
    finally:
        await manager.close()


@pytest.mark.unit
async def test_index_written_under_tmp_home(home):
    manager = SessionManager()
    await manager.connect()
    try:
        await manager.get_or_create("s1", user_id="bob")
    finally:
        await manager.close()

    index_path = home / ".starboard" / "sessions" / "index.json"
    assert index_path.is_file(), "index.json should live under ~/.starboard/sessions/"
    doc = json.loads(index_path.read_text())
    assert doc["version"] == 1
    assert isinstance(doc["sessions"], list)
    entry = doc["sessions"][0]
    assert set(entry) == {
        "session_name",
        "conversation_id",
        "user_id",
        "created_at",
        "updated_at",
        "turn_count",
        "last_message_preview",
    }
    assert entry["session_name"] == "s1"
    assert entry["user_id"] == "bob"


@pytest.mark.unit
async def test_transcript_file_created_per_conversation(tmp_path):
    db_path = str(tmp_path / "sessions.db")
    manager = SessionManager(db_path)
    await manager.connect()
    try:
        info = await manager.get_or_create("with-transcript")
        conv_id = info.conversation_id
    finally:
        await manager.close()

    base_dir = tmp_path / "sessions"
    transcript = base_dir / f"{conv_id}.json"
    assert transcript.is_file(), "per-conversation transcript JSON should exist"
    doc = json.loads(transcript.read_text())
    assert doc["version"] == 1
    conv = doc["conversation"]
    assert conv["id"] == conv_id
    assert conv["messages"] == []
    assert "metadata" in conv


@pytest.mark.unit
async def test_delete_removes_transcript_file(tmp_path):
    db_path = str(tmp_path / "sessions.db")
    manager = SessionManager(db_path)
    await manager.connect()
    try:
        info = await manager.get_or_create("doomed")
        transcript = tmp_path / "sessions" / f"{info.conversation_id}.json"
        assert transcript.is_file()
        assert await manager.delete_session("doomed") is True
        assert not transcript.exists()
    finally:
        await manager.close()


# ---------------------------------------------------------------------------
# Persistence across reconnect (two managers, same path)
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_persists_across_reconnect(tmp_path):
    db_path = str(tmp_path / "sessions.db")
    m1 = SessionManager(db_path)
    await m1.connect()
    info1 = await m1.get_or_create("persist", user_id="u1")
    await m1.update_session_activity("persist", "saved message")
    await m1.close()

    m2 = SessionManager(db_path)
    await m2.connect()
    info2 = await m2.get_or_create("persist")
    await m2.close()

    assert info2.conversation_id == info1.conversation_id
    assert info2.user_id == "u1"
    assert info2.turn_count == 1
    assert info2.last_message_preview == "saved message"


# ---------------------------------------------------------------------------
# Atomic write behavior
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_atomic_write_leaves_previous_index_intact(tmp_path, monkeypatch):
    db_path = str(tmp_path / "sessions.db")
    manager = SessionManager(db_path)
    await manager.connect()
    try:
        await manager.get_or_create("first")  # index has one good entry
        index_path = tmp_path / "sessions" / "index.json"
        good = index_path.read_text()

        # Simulate a crash during the atomic replace of the index.
        real_replace = os.replace

        def boom(src, dst):
            if str(dst).endswith("index.json"):
                raise OSError("simulated crash during replace")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", boom)

        with pytest.raises(OSError):
            await manager.get_or_create("second")

        monkeypatch.undo()

        # Previous index is intact (not truncated/partial) and has no 2nd session.
        assert index_path.read_text() == good
        doc = json.loads(index_path.read_text())
        assert [s["session_name"] for s in doc["sessions"]] == ["first"]

        # No stray temp files left behind.
        leftovers = [p.name for p in (tmp_path / "sessions").iterdir()
                     if p.suffix == ".tmp" or ".tmp" in p.name]
        assert leftovers == []
    finally:
        await manager.close()


@pytest.mark.unit
async def test_single_writer_sequential_consistency(tmp_path):
    """CLI is a single-writer; sequential writes stay internally consistent."""
    db_path = str(tmp_path / "sessions.db")
    manager = SessionManager(db_path)
    await manager.connect()
    try:
        for i in range(5):
            await manager.get_or_create(f"s{i}")
        for i in range(5):
            await manager.update_session_activity(f"s{i}", f"msg-{i}")
        sessions = await manager.list_sessions()
        assert len(sessions) == 5
        assert all(s.turn_count == 1 for s in sessions)
    finally:
        await manager.close()


# ---------------------------------------------------------------------------
# aiosqlite is gone from the CLI hot path
# ---------------------------------------------------------------------------
def _import_lines(text: str) -> list[str]:
    """Return the ``import``/``from`` statement lines of a module's source."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]


@pytest.mark.unit
def test_session_manager_source_imports_no_sqlite():
    mod_file = sys.modules[SessionManager.__module__].__file__
    assert mod_file is not None
    imports = _import_lines(Path(mod_file).read_text())
    assert not any("aiosqlite" in line for line in imports)
    assert not any("SQLiteStateStore" in line for line in imports)

    # json_store sibling must also be driver-free.
    json_store = Path(mod_file).parent / "json_store.py"
    assert json_store.is_file()
    js_imports = _import_lines(json_store.read_text())
    assert not any("aiosqlite" in line for line in js_imports)
    assert not any("SQLiteStateStore" in line for line in js_imports)


@pytest.mark.unit
def test_importing_session_manager_does_not_import_aiosqlite():
    """Importing the CLI session path must not pull in aiosqlite."""
    code = (
        "import sys\n"
        "import starboard.cli.sessions.session_manager  # noqa: F401\n"
        "assert 'aiosqlite' not in sys.modules, "
        "'aiosqlite must not be imported on the CLI session path'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"subprocess failed:\nSTDOUT:{result.stdout}\nSTDERR:{result.stderr}"
    )
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Public API preserved byte-for-byte
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_public_api_signatures_unchanged():
    # Methods present
    for name in (
        "connect",
        "close",
        "get_or_create",
        "list_sessions",
        "delete_session",
        "update_session_activity",
    ):
        assert callable(getattr(SessionManager, name)), f"missing {name}"

    # Properties preserved (used by the CLI wiring)
    assert isinstance(SessionManager.state_store, property)
    assert isinstance(SessionManager.conversation_repo, property)

    # Signatures unchanged
    ctor = inspect.signature(SessionManager.__init__)
    assert list(ctor.parameters) == ["self", "db_path"]
    assert ctor.parameters["db_path"].default == "~/.starboard/sessions.db"

    goc = inspect.signature(SessionManager.get_or_create)
    assert list(goc.parameters) == ["self", "session_name", "user_id"]
    assert goc.parameters["session_name"].default is None
    assert goc.parameters["user_id"].default == "cli_user"

    usa = inspect.signature(SessionManager.update_session_activity)
    assert list(usa.parameters) == ["self", "session_name", "last_message"]

    dele = inspect.signature(SessionManager.delete_session)
    assert list(dele.parameters) == ["self", "session_name"]

    # SessionInfo shape unchanged
    fields = {f.name for f in SessionInfo.__dataclass_fields__.values()}
    assert fields == {
        "session_name",
        "conversation_id",
        "user_id",
        "created_at",
        "updated_at",
        "turn_count",
        "last_message_preview",
    }


@pytest.mark.unit
async def test_conversation_repo_property_round_trip(tmp_path):
    """conversation_repo (used by main.py) persists messages to transcript JSON."""
    from starboard_core.models.conversation import Message

    db_path = str(tmp_path / "sessions.db")
    manager = SessionManager(db_path)
    await manager.connect()
    try:
        info = await manager.get_or_create("chat")
        repo = manager.conversation_repo
        await repo.add_message(
            info.conversation_id, Message(role="user", content="hi")
        )
        recent = await repo.get_recent_messages(info.conversation_id)
        assert [m.content for m in recent] == ["hi"]
    finally:
        await manager.close()

    # persisted to disk
    transcript = tmp_path / "sessions" / f"{info.conversation_id}.json"
    doc = json.loads(transcript.read_text())
    assert doc["conversation"]["messages"][0]["content"] == "hi"


@pytest.mark.unit
async def test_update_nonexistent_session_raises(tmp_path):
    manager = SessionManager(str(tmp_path / "sessions.db"))
    await manager.connect()
    try:
        with pytest.raises(ValueError, match="Session 'missing' not found"):
            await manager.update_session_activity("missing", "msg")
    finally:
        await manager.close()
