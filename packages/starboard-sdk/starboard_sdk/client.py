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
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.bootstrap import (
    ErrorEvent as _ServerErrorEvent,
)
from starboard_server.bootstrap import (
    FinalOutputEvent as _ServerFinalOutputEvent,
)
from starboard_server.bootstrap import (
    ToolEndEvent as _ServerToolEndEvent,
)
from starboard_server.bootstrap import (
    get_logger,
)

from starboard_sdk._event_mapper import map_event
from starboard_sdk.event_types import (
    AgentEvent,
)
from starboard_sdk.exceptions import (
    AuthenticationError,
    ConfigError,
    ConnectionError,
    SessionError,
)
from starboard_sdk.models import AgentResponse, RawAgentOutput

if TYPE_CHECKING:
    from starboard_cli.sessions.session_manager import SessionInfo, SessionManager
    from starboard_server.bootstrap import (
        MultiAgentConversationManager,
    )

logger = get_logger(__name__)


@runtime_checkable
class AsyncCloseable(Protocol):
    """Protocol for objects with an async ``close()`` method."""

    async def close(self) -> None: ...


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
            starboard_sdk.exceptions.TimeoutError: If the agent does not
                respond within ``timeout`` seconds.
            AgentError: If the agent returns a non-recoverable error.
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
                    if isinstance(event, _ServerToolEndEvent):
                        tools_used.append(event.tool_name)
                    elif isinstance(event, _ServerFinalOutputEvent):
                        final_output = (
                            event.output
                            if isinstance(event.output, dict)
                            else event.output.to_dict()
                        )
                    elif (
                        isinstance(event, _ServerErrorEvent)
                        and not event.is_recoverable
                    ):
                        agent_error = f"{event.error_type}: {event.error}"
                        logger.warning(
                            "sdk_agent_error_event",
                            error_type=event.error_type,
                            error=event.error,
                        )
            finally:
                with contextlib.suppress(Exception):
                    if hasattr(stream, "aclose"):
                        await stream.aclose()

        if timeout is not None:
            try:
                await asyncio.wait_for(_consume_stream(), timeout=timeout)
            except TimeoutError as exc:
                from starboard_sdk.exceptions import TimeoutError as SdkTimeoutError

                raise SdkTimeoutError(
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

                formatted_report = format_agent_report(
                    final_output["complete_report"]  # type: ignore[arg-type]
                )

        self._turn_count += 1

        if self._session_mgr and self._session_name:
            with contextlib.suppress(Exception):
                await self._session_mgr.update_session_activity(
                    self._session_name, message
                )

        raw: RawAgentOutput = final_output or {}  # type: ignore[assignment]

        return AgentResponse(
            question=message,
            report=formatted_report,
            raw_output=raw,
            tools_used=tools_used,
            tokens_used=raw.get("tokens_used") if raw else None,  # type: ignore[arg-type]
            cost_usd=raw.get("cost_usd") if raw else None,  # type: ignore[arg-type]
            duration_seconds=round(elapsed, 2),
            domain=raw.get("domain") if raw else None,  # type: ignore[arg-type]
            conversation_id=self._conversation_id,
            turn_number=self._turn_count,
            error=agent_error,
        )

    async def ask_stream(
        self,
        message: str,
        mode: OptimizationMode | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Send a message and stream SDK events.

        Args:
            message: User message text.
            mode: Override optimization mode for this turn.
            timeout: Optional timeout in seconds. ``None`` means no limit.

        Yields:
            SDK event instances (``ToolStartEvent``, ``ToolEndEvent``,
            ``ErrorEvent``, ``FinalOutputEvent``, ``StreamingEvent``).
        """
        effective_mode = mode or self._mode

        try:
            async with asyncio.timeout(timeout):
                async for server_event in self._manager.handle_message_stream(
                    conversation_id=self._conversation_id,
                    user_message=message,
                    mode=effective_mode,
                ):
                    sdk_event = map_event(server_event)
                    if sdk_event is not None:
                        yield sdk_event
        finally:
            self._turn_count += 1

            if self._session_mgr and self._session_name:
                with contextlib.suppress(Exception):
                    await self._session_mgr.update_session_activity(
                        self._session_name, message
                    )

    # -- Convenience wrappers for common agent tasks --------------------------

    async def analyze_query(self, statement_id: str, **kwargs: object) -> AgentResponse:
        """Analyze a SQL query by statement ID."""
        return await self.ask(f"Analyze query {statement_id}", **kwargs)  # type: ignore[arg-type]

    async def analyze_job(self, job_id: str | int, **kwargs: object) -> AgentResponse:
        """Analyze a Databricks job by ID."""
        return await self.ask(f"Analyze job {job_id}", **kwargs)  # type: ignore[arg-type]

    async def analyze_table(self, table_name: str, **kwargs: object) -> AgentResponse:
        """Analyze a Unity Catalog table."""
        return await self.ask(f"Analyze table {table_name}", **kwargs)  # type: ignore[arg-type]

    async def analyze_cluster(self, cluster_id: str, **kwargs: object) -> AgentResponse:
        """Analyze a Databricks cluster by ID."""
        return await self.ask(f"Analyze cluster {cluster_id}", **kwargs)  # type: ignore[arg-type]

    async def analyze_warehouse(
        self, warehouse_id: str, **kwargs: object
    ) -> AgentResponse:
        """Analyze a SQL warehouse by ID."""
        return await self.ask(f"Analyze warehouse {warehouse_id}", **kwargs)  # type: ignore[arg-type]

    async def diagnose(self, description: str, **kwargs: object) -> AgentResponse:
        """Diagnose an issue described in natural language."""
        return await self.ask(f"Diagnose: {description}", **kwargs)  # type: ignore[arg-type]


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
        resources: tuple[AsyncCloseable, ...] = (),
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

        Example::

            client = await StarboardClient.from_env()
            async with client:
                session = await client.create_session()
                response = await session.ask("Analyze job 12345")

        Args:
            session_db: Path to the SQLite session database used for
                persistent multi-turn sessions.  Tilde-expanded.  Defaults
                to ``~/.starboard/sessions.db``.

        Returns:
            Configured StarboardClient ready to create sessions.

        Raises:
            ConfigError: If required environment variables are missing.
            AuthenticationError: If credentials are invalid.
            ConnectionError: If a backend service is unreachable.
        """
        from dotenv import load_dotenv

        load_dotenv()

        try:
            from starboard_cli.cli.main import create_agent_manager
            from starboard_cli.sessions.session_manager import SessionManager
            from starboard_server.bootstrap import get_config

            config = get_config()

            if not config.databricks_host or not config.databricks_token:
                raise ConfigError(
                    "Missing required credentials. Set DATABRICKS_HOST and "
                    "DATABRICKS_TOKEN environment variables."
                )

            session_mgr = SessionManager(db_path=session_db)
            await session_mgr.connect()

            manager, api, vector_store = await create_agent_manager(
                config, state_manager=session_mgr.conversation_repo
            )
        except (ConfigError, AuthenticationError, ConnectionError):
            raise
        except Exception as exc:
            msg = str(exc)
            if (
                "token" in msg.lower()
                or "auth" in msg.lower()
                or "credential" in msg.lower()
            ):
                raise AuthenticationError(f"Authentication failed: {msg}") from exc
            if (
                "connect" in msg.lower()
                or "unreachable" in msg.lower()
                or "dns" in msg.lower()
            ):
                raise ConnectionError(f"Could not reach backend: {msg}") from exc
            raise ConfigError(f"Failed to initialize client: {msg}") from exc

        resources: tuple[AsyncCloseable, ...] = tuple(
            r
            for r in (api, vector_store)
            if r is not None and isinstance(r, AsyncCloseable)
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
            SessionError: If no SessionManager is configured.
        """
        if not self._session_mgr:
            raise SessionError(
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

    async def delete_session(self, name: str) -> bool:
        """Delete a session by name.

        Args:
            name: Session name to delete.

        Returns:
            True if deleted, False if session not found.

        Raises:
            SessionError: If no SessionManager is configured.
        """
        if not self._session_mgr:
            raise SessionError(
                "Cannot delete sessions without a SessionManager. "
                "Use StarboardClient.from_env() for persistent sessions."
            )
        return await self._session_mgr.delete_session(name)

    async def health_check(self) -> dict[str, object]:
        """Check connectivity to backend services.

        Returns:
            Dictionary with ``healthy`` (bool), ``version`` (str), and
            per-backend reachability flags.

        Raises:
            ConnectionError: If all backends are unreachable.
        """
        import importlib.metadata

        try:
            sdk_version = importlib.metadata.version("starboard-sdk")
        except importlib.metadata.PackageNotFoundError:
            sdk_version = "0.0.0"

        details: dict[str, str] = {}
        databricks_ok = False
        llm_ok = False

        # Check Databricks connectivity
        try:
            api = getattr(self._manager, "_databricks_client", None)
            if api and hasattr(api, "is_authenticated"):
                databricks_ok = await api.is_authenticated()
                details["databricks"] = "ok" if databricks_ok else "auth_failed"
            else:
                details["databricks"] = "unknown"
        except Exception as exc:
            details["databricks"] = f"error: {exc}"

        # Check LLM connectivity
        try:
            llm = getattr(self._manager, "_llm_client", None)
            if llm is not None:
                llm_ok = True
                details["llm"] = "ok"
            else:
                details["llm"] = "not_configured"
        except Exception as exc:
            details["llm"] = f"error: {exc}"

        healthy = databricks_ok or llm_ok

        if not healthy:
            raise ConnectionError(
                "All backends are unreachable. Check your credentials and network."
            )

        return {
            "healthy": healthy,
            "databricks_reachable": databricks_ok,
            "llm_reachable": llm_ok,
            "version": sdk_version,
            "details": details,
        }

    async def close(self) -> None:
        """Close all resources (LLM client, Databricks client, etc.)."""
        if self._session_mgr:
            with contextlib.suppress(Exception):
                await self._session_mgr.close()

        for resource in self._resources:
            with contextlib.suppress(Exception):
                await resource.close()

    async def __aenter__(self) -> StarboardClient:
        """Support async context manager usage."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Close resources on context manager exit."""
        await self.close()
