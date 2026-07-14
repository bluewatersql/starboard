# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for SessionManager."""

import pytest
from starboard.cli.sessions.session_manager import SessionManager


@pytest.fixture
async def session_manager():
    """SessionManager using in-memory DB, connected and closed on teardown."""
    manager = SessionManager(":memory:")
    await manager.connect()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.mark.unit
async def test_create_new_session(session_manager):
    info = await session_manager.get_or_create("my-session", user_id="user-1")
    assert info.session_name == "my-session"
    assert info.conversation_id.startswith("cli_session_")
    assert len(info.conversation_id) == len("cli_session_") + 12
    assert info.user_id == "user-1"
    assert info.created_at is not None
    assert info.updated_at is not None
    assert info.turn_count == 0
    assert info.last_message_preview is None


@pytest.mark.unit
async def test_create_auto_named_session(session_manager):
    info = await session_manager.get_or_create(session_name=None)
    assert info.session_name.startswith("session-")
    assert len(info.session_name) == len("session-") + 8
    assert info.conversation_id.startswith("cli_session_")
    assert info.user_id == "cli_user"


@pytest.mark.unit
async def test_get_existing_session(session_manager):
    info1 = await session_manager.get_or_create("same-session")
    info2 = await session_manager.get_or_create("same-session")
    assert info1.conversation_id == info2.conversation_id
    assert info1.session_name == info2.session_name


@pytest.mark.unit
async def test_list_sessions_empty(session_manager):
    sessions = await session_manager.list_sessions()
    assert sessions == []


@pytest.mark.unit
async def test_list_sessions_multiple(session_manager):
    await session_manager.get_or_create("first")
    await session_manager.get_or_create("second")
    await session_manager.get_or_create("third")
    await session_manager.update_session_activity("first", "updated first")
    sessions = await session_manager.list_sessions()
    names = [s.session_name for s in sessions]
    assert names[0] == "first"
    assert set(names[1:]) == {"second", "third"}


@pytest.mark.unit
async def test_delete_session(session_manager):
    await session_manager.get_or_create("to-delete")
    sessions_before = await session_manager.list_sessions()
    assert len(sessions_before) == 1
    result = await session_manager.delete_session("to-delete")
    assert result is True
    sessions_after = await session_manager.list_sessions()
    assert sessions_after == []


@pytest.mark.unit
async def test_delete_nonexistent_session(session_manager):
    result = await session_manager.delete_session("nonexistent")
    assert result is False


@pytest.mark.unit
async def test_update_session_activity(session_manager):
    await session_manager.get_or_create("active-session")
    await session_manager.update_session_activity("active-session", "Hello world")
    info = await session_manager.get_or_create("active-session")
    assert info.turn_count == 1
    assert info.last_message_preview == "Hello world"


@pytest.mark.unit
async def test_update_session_activity_truncates_preview(session_manager):
    await session_manager.get_or_create("long-preview")
    long_msg = "x" * 150
    await session_manager.update_session_activity("long-preview", long_msg)
    info = await session_manager.get_or_create("long-preview")
    assert info.last_message_preview == "x" * 100


@pytest.mark.unit
async def test_update_nonexistent_session_raises(session_manager):
    with pytest.raises(ValueError, match="Session 'missing' not found"):
        await session_manager.update_session_activity("missing", "msg")


@pytest.mark.unit
async def test_session_persists_across_reconnect(tmp_path):
    db_path = str(tmp_path / "sessions.db")
    manager1 = SessionManager(db_path)
    await manager1.connect()
    info1 = await manager1.get_or_create("persistent-session", user_id="u1")
    await manager1.update_session_activity("persistent-session", "saved message")
    await manager1.close()

    manager2 = SessionManager(db_path)
    await manager2.connect()
    info2 = await manager2.get_or_create("persistent-session")
    await manager2.close()

    assert info2.conversation_id == info1.conversation_id
    assert info2.session_name == info1.session_name
    assert info2.user_id == info1.user_id
    assert info2.turn_count == 1
    assert info2.last_message_preview == "saved message"
