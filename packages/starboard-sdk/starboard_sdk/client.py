"""Starboard SDK client for multi-turn conversations.

Provides ``StarboardClient`` (factory) and ``ConversationSession`` (stateful
conversation handle). Supports in-process execution using the same agent
stack as the CLI and server.

Example::

    client = await StarboardClient.from_env()
    session = await client.create_session(name="my-analysis")

    r1 = await session.ask("Analyze job 12345")
    r2 = await session.ask("Can we convert it to streaming?")
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.bootstrap import (
    ErrorEvent,
    FinalOutputEvent,
    StreamingEvent,
    ToolEndEvent,
    get_logger,
)

from starboard_sdk.models import AgentResponse

if TYPE_CHECKING:
    from starboard_server.bootstrap import MultiAgentConversationManager, MultiCollectionStore

    from starboard_cli.sessions.session_manager import SessionInfo, SessionManager

logger = get_logger(__name__)


class ConversationSession:
    """A multi-turn conversation session with the Starboard agent.

    Each session wraps a single ``conversation_id``. Successive ``ask()``
    calls send messages to the same conversation so the agent sees prior
    context (conversation history, working memory, discovered entities).

    Instances are created via ``StarboardClient.create_session()`` or
    ``StarboardClient.resume_session()`` — do not instantiate directly.

    Example::

        session = await client.create_session()
        r1 = await session.ask("Help me tune query abc-123")
        r2 = await session.ask("Would liquid clustering help?")
        print(r2.report)
    """

    def __init__(
        self,
        conversation_id: str,
        manager: MultiAgentConversationManager,
        session_name: str | None = None,
        session_mgr: SessionManager | None = None,
        mode: OptimizationMode = OptimizationMode.ONLINE,
    ) -> None:
        self._conversation_id = conversation_id
        self._manager = manager
        self._session_name = session_name
        self._session_mgr = session_mgr
        self._mode = mode
        self._turn_count = 0

    @property
    def session_id(self) -> str:
        """Underlying conversation_id."""
        return self._conversation_id

    @property
    def session_name(self) -> str | None:
        """Human-friendly session name, if any."""
        return self._session_name

    @property
    def turn_count(self) -> int:
        """Number of turns completed in this session."""
        return self._turn_count

    async def ask(
        self,
        message: str,
        mode: OptimizationMode | None = None,
        timeout: float | None = 300.0,
    ) -> AgentResponse:
        """Send a message and collect the full response.

        Args:
            message: User message text.
            mode: Override optimization mode for this turn.
            timeout: Seconds before giving up. Defaults to 5 minutes.
                     Set to None to wait indefinitely.

        Returns:
            AgentResponse with report, raw output, and metadata.

        Raises:
            TimeoutError: If the agent does not respond within ``timeout`` seconds.
            RuntimeError: If the agent returns a non-recoverable error.
        """
        effective_mode = mode or self._mode
        final_output: dict[str, object] | None = None
        tools_used: list[str] = []
        formatted_report: str | None = None
        agent_error: str | None = None
        t0 = time.monotonic()

        async def _consume_stream() -> None:
            nonlocal final_output, agent_error
            stream = self._manager.handle_message_stream(
                conversation_id=self._conversation_id,
                user_message=message,
                mode=effective_mode,
            )
            try:
                async for event in stream:
                    if isinstance(event, ToolEndEvent):
                        tools_used.append(event.tool_name)
                    elif isinstance(event, FinalOutputEvent):
                        final_output = (
                            event.output
                            if isinstance(event.output, dict)
                            else event.output.to_dict()
                        )
                    elif isinstance(event, ErrorEvent) and not event.is_recoverable:
                        # Record the error but don't raise — the agent may still
                        # emit a FinalOutputEvent (e.g. a best-effort report).
                        # Surfaced in AgentResponse.error so callers can inspect.
                        agent_error = f"{event.error_type}: {event.error}"
                        logger.warning(
                            "sdk_agent_error_event",
                            error_type=event.error_type,
                            error=event.error,
                        )
            finally:
                with contextlib.suppress(Exception):
                    await stream.aclose()

        if timeout is not None:
            try:
                await asyncio.wait_for(_consume_stream(), timeout=timeout)
            except TimeoutError as exc:
                raise TimeoutError(
                    f"Agent did not respond within {timeout:.0f}s. "
                    "Increase the timeout or check for backend issues."
                ) from exc
        else:
            await _consume_stream()

        elapsed = time.monotonic() - t0

        if (
            final_output
            and "complete_report" in final_output
            and final_output["complete_report"]
        ):
            with contextlib.suppress(Exception):
                from starboard_server.bootstrap import format_agent_report
                formatted_report = format_agent_report(final_output["complete_report"])

        self._turn_count += 1

        if self._session_mgr and self._session_name:
            with contextlib.suppress(Exception):
                await self._session_mgr.update_session_activity(
                    self._session_name, message
                )

        return AgentResponse(
            question=message,
            report=formatted_report,
            raw_output=final_output or {},
            tools_used=tools_used,
            tokens_used=final_output.get("tokens_used") if final_output else None,  # type: ignore[arg-type]
            cost_usd=final_output.get("cost_usd") if final_output else None,  # type: ignore[arg-type]
            duration_seconds=round(elapsed, 2),
            domain=final_output.get("domain") if final_output else None,  # type: ignore[arg-type]
            conversation_id=self._conversation_id,
            turn_number=self._turn_count,
            error=agent_error,
        )

    async def ask_stream(
        self,
        message: str,
        mode: OptimizationMode | None = None,
    ) -> AsyncIterator[StreamingEvent | FinalOutputEvent]:
        """Send a message and stream raw events.

        Args:
            message: User message text.
            mode: Override optimization mode for this turn.

        Yields:
            StreamingEvent or FinalOutputEvent instances.
        """
        effective_mode = mode or self._mode

        try:
            async for event in self._manager.handle_message_stream(
                conversation_id=self._conversation_id,
                user_message=message,
                mode=effective_mode,
            ):
                yield event
        finally:
            # Always increment turn count and update session activity,
            # even if the stream exits early due to an exception or break.
            self._turn_count += 1

            if self._session_mgr and self._session_name:
                with contextlib.suppress(Exception):
                    await self._session_mgr.update_session_activity(
                        self._session_name, message
                    )


class StarboardClient:
    """Factory for creating multi-turn Starboard conversation sessions.

    Bootstraps the agent stack (LLM client, Databricks client, tool registry,
    intent router, agent factory) and provides session lifecycle management.

    Example::

        # From environment variables
        client = await StarboardClient.from_env()
        session = await client.create_session(name="etl-tuning")
        response = await session.ask("Analyze job 12345")

        # Resume a previous session
        session = await client.resume_session("etl-tuning")
        response = await session.ask("Can we run it as streaming?")
    """

    def __init__(
        self,
        manager: MultiAgentConversationManager,
        session_mgr: SessionManager | None = None,
        resources: tuple[object, ...] = (),
    ) -> None:
        """Initialize client with pre-built components.

        Args:
            manager: MultiAgentConversationManager instance.
            session_mgr: Optional SessionManager for persistent sessions.
            resources: Tuple of closeable resources (api, vector_store, etc.)
                that will be closed when the client is closed.
        """
        self._manager = manager
        self._session_mgr = session_mgr
        self._resources = resources

    @classmethod
    async def from_env(
        cls,
        session_db: str = "~/.starboard/sessions.db",
    ) -> StarboardClient:
        """Create a client configured from environment variables.

        Loads ``.env`` from the current directory (if present) then reads
        ``DATABRICKS_HOST``, ``DATABRICKS_TOKEN``, ``LLM_API_KEY``,
        ``LLM_MODEL``, and related variables — the same set used by the CLI
        and server.  Call ``await client.close()`` (or use ``async with``)
        when done to release background resources.

        Args:
            session_db: Path to the SQLite session database used for
                persistent multi-turn sessions.  Tilde-expanded.  Defaults
                to ``~/.starboard/sessions.db``.

        Returns:
            Configured StarboardClient ready to create sessions.
        """
        from dotenv import load_dotenv

        load_dotenv()

        from starboard_cli.cli.main import create_agent_manager
        from starboard_cli.sessions.session_manager import SessionManager
        from starboard_server.bootstrap import get_config

        config = get_config()

        session_mgr = SessionManager(db_path=session_db)
        await session_mgr.connect()

        manager, api, vector_store = await create_agent_manager(
            config, state_manager=session_mgr.conversation_repo
        )

        resources: tuple[object, ...] = tuple(
            r for r in (api, vector_store) if r is not None
        )

        return cls(
            manager=manager,
            session_mgr=session_mgr,
            resources=resources,
        )

    async def create_session(
        self,
        name: str | None = None,
        mode: OptimizationMode = OptimizationMode.ONLINE,
    ) -> ConversationSession:
        """Create a new conversation session.

        Args:
            name: Optional session name. If provided and a session with
                this name already exists, it will be resumed.
            mode: Default optimization mode for the session.

        Returns:
            ConversationSession ready for ``ask()`` calls.
        """
        from uuid import uuid4

        if self._session_mgr and name:
            info = await self._session_mgr.get_or_create(name)
            return ConversationSession(
                conversation_id=info.conversation_id,
                manager=self._manager,
                session_name=info.session_name,
                session_mgr=self._session_mgr,
                mode=mode,
            )

        conversation_id = f"sdk_{uuid4().hex[:12]}"
        return ConversationSession(
            conversation_id=conversation_id,
            manager=self._manager,
            session_name=name,
            session_mgr=self._session_mgr,
            mode=mode,
        )

    async def resume_session(self, name: str) -> ConversationSession:
        """Resume an existing session by name.

        Args:
            name: Session name to resume.

        Returns:
            ConversationSession with prior context loaded automatically.

        Raises:
            ValueError: If no session with the given name exists and
                no SessionManager is configured.
        """
        if not self._session_mgr:
            raise ValueError(
                "Cannot resume sessions without a SessionManager. "
                "Use StarboardClient.from_env() for persistent sessions."
            )

        info = await self._session_mgr.get_or_create(name)
        return ConversationSession(
            conversation_id=info.conversation_id,
            manager=self._manager,
            session_name=info.session_name,
            session_mgr=self._session_mgr,
        )

    async def list_sessions(self) -> list[SessionInfo]:
        """List all saved sessions.

        Returns:
            List of SessionInfo objects, ordered by most-recently updated.
        """
        if not self._session_mgr:
            return []
        return await self._session_mgr.list_sessions()

    async def close(self) -> None:
        """Close all resources (LLM client, Databricks client, etc.)."""
        if self._session_mgr:
            with contextlib.suppress(Exception):
                await self._session_mgr.close()

        for resource in self._resources:
            if hasattr(resource, "close"):
                with contextlib.suppress(Exception):
                    await resource.close()

    async def __aenter__(self) -> StarboardClient:
        """Support async context manager usage."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Close resources on context manager exit."""
        await self.close()
