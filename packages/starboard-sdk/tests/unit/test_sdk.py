"""Tests for Starboard SDK client and session."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_sdk.client import ConversationSession, StarboardClient
from starboard_sdk.models import AgentResponse


def _make_final_event(output: dict | None = None):
    """Create a mock FinalOutputEvent."""
    event = MagicMock()
    event.__class__.__name__ = "FinalOutputEvent"
    # Make isinstance check work
    from starboard_server.agents.events import FinalOutputEvent

    event.__class__ = FinalOutputEvent
    mock_output = MagicMock()
    mock_output.to_dict.return_value = output or {
        "summary": "Test summary",
        "tokens_used": 500,
        "cost_usd": 0.01,
        "domain": "query",
    }
    event.output = mock_output
    return event


def _make_tool_end_event(name: str = "resolve_query"):
    """Create a mock ToolEndEvent."""
    from starboard_server.agents.events import ToolEndEvent

    event = MagicMock(spec=ToolEndEvent)
    event.__class__ = ToolEndEvent
    event.tool_name = name
    event.success = True
    event.duration_seconds = 1.5
    event.friendly_name = name
    return event


async def _mock_stream(*events):
    """Create an async generator yielding events."""
    for e in events:
        yield e


async def _mock_stream_then_hang(*events):
    """Yield events then block forever (simulates a hung stream)."""
    for e in events:
        yield e
    await asyncio.sleep(9999)


def _make_error_event(error: str = "connection failed", recoverable: bool = False):
    """Create a mock ErrorEvent."""
    from starboard_server.agents.events import ErrorEvent

    event = MagicMock(spec=ErrorEvent)
    event.__class__ = ErrorEvent
    event.error = error
    event.error_type = "TestError"
    event.is_recoverable = recoverable
    return event


@pytest.fixture
def mock_manager():
    """Create a mock MultiAgentConversationManager."""
    manager = AsyncMock()
    return manager


@pytest.fixture
def mock_session_mgr():
    """Create a mock SessionManager."""
    mgr = AsyncMock()
    mgr.get_or_create = AsyncMock()
    mgr.list_sessions = AsyncMock(return_value=[])
    mgr.update_session_activity = AsyncMock()
    mgr.close = AsyncMock()
    return mgr


class TestAgentResponse:
    @pytest.mark.unit
    def test_response_str_with_report(self):
        r = AgentResponse(
            question="Analyze query abc",
            report="# Report",
            raw_output={},
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=2.5,
            domain="query",
            conversation_id="conv1",
            turn_number=1,
        )
        assert str(r) == "# Report"
        assert r.markdown == "# Report"

    @pytest.mark.unit
    def test_response_str_without_report(self):
        r = AgentResponse(
            question="Analyze job 456",
            report=None,
            raw_output={"summary": "Job analysis complete"},
            tools_used=["resolve_job"],
            tokens_used=200,
            cost_usd=0.02,
            duration_seconds=3.1,
            domain="job",
            conversation_id="conv2",
            turn_number=2,
        )
        assert "Job analysis complete" in str(r)
        assert r.question == "Analyze job 456"

    @pytest.mark.unit
    def test_response_is_frozen(self):
        r = AgentResponse(
            question="test",
            report=None,
            raw_output={},
            tools_used=[],
            tokens_used=None,
            cost_usd=None,
            duration_seconds=0.0,
            domain=None,
            conversation_id="x",
            turn_number=1,
        )
        with pytest.raises(AttributeError):
            r.report = "changed"  # type: ignore[misc]

    @pytest.mark.unit
    def test_response_duration_and_question(self):
        r = AgentResponse(
            question="How fast?",
            report=None,
            raw_output={},
            tools_used=[],
            tokens_used=None,
            cost_usd=None,
            duration_seconds=4.56,
            domain=None,
            conversation_id="x",
            turn_number=1,
        )
        assert r.duration_seconds == 4.56
        assert r.question == "How fast?"


class TestConversationSession:
    @pytest.mark.unit
    async def test_ask_returns_response(self, mock_manager):
        tool_event = _make_tool_end_event("resolve_query")
        final_event = _make_final_event()
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(tool_event, final_event)
        )

        session = ConversationSession(
            conversation_id="conv_test",
            manager=mock_manager,
        )

        response = await session.ask("Analyze query abc123")

        assert isinstance(response, AgentResponse)
        assert response.conversation_id == "conv_test"
        assert response.turn_number == 1
        assert "resolve_query" in response.tools_used

    @pytest.mark.unit
    async def test_ask_increments_turn_count(self, mock_manager):
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(_make_final_event())
        )

        session = ConversationSession(
            conversation_id="conv_test",
            manager=mock_manager,
        )
        assert session.turn_count == 0

        await session.ask("Turn 1")
        assert session.turn_count == 1

        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(_make_final_event())
        )
        await session.ask("Turn 2")
        assert session.turn_count == 2

    @pytest.mark.unit
    async def test_ask_passes_conversation_id(self, mock_manager):
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(_make_final_event())
        )

        session = ConversationSession(
            conversation_id="conv_keep_this",
            manager=mock_manager,
        )

        await session.ask("Hello")

        mock_manager.handle_message_stream.assert_called_once_with(
            conversation_id="conv_keep_this",
            user_message="Hello",
            mode=OptimizationMode.ONLINE,
        )

    @pytest.mark.unit
    async def test_ask_raises_on_fatal_error_event(self, mock_manager):
        error_event = _make_error_event("LLM timed out", recoverable=False)
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(error_event)
        )

        session = ConversationSession(
            conversation_id="conv_test",
            manager=mock_manager,
        )

        with pytest.raises(RuntimeError, match="LLM timed out"):
            await session.ask("Trigger error")

    @pytest.mark.unit
    async def test_ask_continues_on_recoverable_error_event(self, mock_manager):
        recoverable = _make_error_event("Retrying tool", recoverable=True)
        final = _make_final_event()
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(recoverable, final)
        )

        session = ConversationSession(
            conversation_id="conv_test",
            manager=mock_manager,
        )

        response = await session.ask("Handle recoverable error")
        assert isinstance(response, AgentResponse)

    @pytest.mark.unit
    async def test_ask_times_out(self, mock_manager):
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream_then_hang()
        )

        session = ConversationSession(
            conversation_id="conv_test",
            manager=mock_manager,
        )

        with pytest.raises(TimeoutError, match="did not respond"):
            await session.ask("Will hang", timeout=0.05)

    @pytest.mark.unit
    async def test_session_updates_activity(self, mock_manager, mock_session_mgr):
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(_make_final_event())
        )

        session = ConversationSession(
            conversation_id="conv_test",
            manager=mock_manager,
            session_name="my-session",
            session_mgr=mock_session_mgr,
        )

        await session.ask("Test message")

        mock_session_mgr.update_session_activity.assert_called_once_with(
            "my-session", "Test message"
        )


def _make_tool_start_event(name: str = "resolve_query"):
    """Create a mock ToolStartEvent."""
    from starboard_server.agents.events import ToolStartEvent

    event = MagicMock(spec=ToolStartEvent)
    event.__class__ = ToolStartEvent
    event.tool_name = name
    event.friendly_name = f"Resolving {name}"
    event.tool_call_id = f"call_{name}"
    event.arguments = {}
    return event


class TestAskStream:
    """Tests for ConversationSession.ask_stream() used by notebook streaming."""

    @pytest.mark.unit
    async def test_ask_stream_yields_all_events(self, mock_manager):
        """ask_stream yields every event from handle_message_stream."""
        tool_start = _make_tool_start_event("resolve_query")
        tool_end = _make_tool_end_event("resolve_query")
        final = _make_final_event()

        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(tool_start, tool_end, final)
        )

        session = ConversationSession(
            conversation_id="conv_stream",
            manager=mock_manager,
        )

        events = []
        async for event in session.ask_stream("Analyze query abc"):
            events.append(event)

        assert len(events) == 3
        assert events[0] is tool_start
        assert events[1] is tool_end
        assert events[2] is final

    @pytest.mark.unit
    async def test_ask_stream_increments_turn_count(self, mock_manager):
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(_make_final_event())
        )

        session = ConversationSession(
            conversation_id="conv_stream",
            manager=mock_manager,
        )
        assert session.turn_count == 0

        async for _ in session.ask_stream("Turn 1"):
            pass
        assert session.turn_count == 1

    @pytest.mark.unit
    async def test_ask_stream_updates_session_activity(
        self, mock_manager, mock_session_mgr
    ):
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(_make_final_event())
        )

        session = ConversationSession(
            conversation_id="conv_stream",
            manager=mock_manager,
            session_name="nb-session",
            session_mgr=mock_session_mgr,
        )

        async for _ in session.ask_stream("Stream me"):
            pass

        mock_session_mgr.update_session_activity.assert_called_once_with(
            "nb-session", "Stream me"
        )

    @pytest.mark.unit
    async def test_ask_stream_yields_error_events(self, mock_manager):
        """Error events are yielded (not swallowed) so callers can handle them."""
        error = _make_error_event("timeout", recoverable=False)
        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(error)
        )

        session = ConversationSession(
            conversation_id="conv_stream",
            manager=mock_manager,
        )

        events = []
        async for event in session.ask_stream("Fail"):
            events.append(event)

        assert len(events) == 1
        from starboard_server.agents.events import ErrorEvent

        assert isinstance(events[0], ErrorEvent)

    @pytest.mark.unit
    async def test_ask_stream_yields_tool_lifecycle(self, mock_manager):
        """Verifies tool start→end pairs are streamed for notebook progress display."""
        start = _make_tool_start_event("get_job_config")
        end = _make_tool_end_event("get_job_config")
        final = _make_final_event()

        mock_manager.handle_message_stream = MagicMock(
            return_value=_mock_stream(start, end, final)
        )

        session = ConversationSession(
            conversation_id="conv_stream",
            manager=mock_manager,
        )

        from starboard_server.agents.events import (
            FinalOutputEvent,
            ToolEndEvent,
            ToolStartEvent,
        )

        types_seen = []
        async for event in session.ask_stream("Analyze job"):
            if isinstance(event, ToolStartEvent):
                types_seen.append("start")
            elif isinstance(event, ToolEndEvent):
                types_seen.append("end")
            elif isinstance(event, FinalOutputEvent):
                types_seen.append("final")

        assert types_seen == ["start", "end", "final"]


class TestStarboardClient:
    @pytest.mark.unit
    async def test_create_session_without_name(self, mock_manager):
        client = StarboardClient(manager=mock_manager)
        session = await client.create_session()

        assert session.session_id.startswith("sdk_")
        assert session.session_name is None

    @pytest.mark.unit
    async def test_create_session_with_session_mgr(self, mock_manager, mock_session_mgr):
        from datetime import UTC, datetime

        from starboard_cli.sessions.session_manager import SessionInfo

        mock_session_mgr.get_or_create.return_value = SessionInfo(
            session_name="test-session",
            conversation_id="cli_session_abc123",
            user_id="cli_user",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            turn_count=0,
            last_message_preview=None,
        )

        client = StarboardClient(
            manager=mock_manager,
            session_mgr=mock_session_mgr,
        )
        session = await client.create_session(name="test-session")

        assert session.session_id == "cli_session_abc123"
        assert session.session_name == "test-session"

    @pytest.mark.unit
    async def test_resume_without_session_mgr_raises(self, mock_manager):
        client = StarboardClient(manager=mock_manager)

        with pytest.raises(ValueError, match="Cannot resume"):
            await client.resume_session("nonexistent")

    @pytest.mark.unit
    async def test_close_cleans_resources(self, mock_manager, mock_session_mgr):
        mock_resource = AsyncMock()
        mock_resource.close = AsyncMock()

        client = StarboardClient(
            manager=mock_manager,
            session_mgr=mock_session_mgr,
            resources=(mock_resource,),
        )

        await client.close()

        mock_session_mgr.close.assert_called_once()
        mock_resource.close.assert_called_once()

    @pytest.mark.unit
    async def test_context_manager(self, mock_manager, mock_session_mgr):
        client = StarboardClient(
            manager=mock_manager,
            session_mgr=mock_session_mgr,
        )

        async with client as c:
            assert c is client

        mock_session_mgr.close.assert_called_once()

    @pytest.mark.unit
    async def test_list_sessions_empty(self, mock_manager):
        client = StarboardClient(manager=mock_manager)
        sessions = await client.list_sessions()
        assert sessions == []
