# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""StarboardMCPServer — transport-agnostic MCP handler layer.

Wraps the ``FastMCP`` SDK server and registers tool, resource, and prompt
handlers.  Phase A quick-lookup tools are dynamically registered from
``tool_bridge`` metadata so that ``list_tools`` and ``call_tool`` work
out of the box.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import Context, FastMCP

from starboard_server.infra.observability.logging import get_logger
from starboard_server.mcp.agent_bridge import (
    AGENT_TOOL_METADATA,
    TOOL_NAME_TO_DOMAIN,
    MCPAgentExecutor,
)
from starboard_server.mcp.circuit_breaker_registry import MCPCircuitBreakerRegistry
from starboard_server.mcp.composite_tools import (
    COMPOSITE_TOOL_METADATA,
    get_job_summary,
    get_query_analysis,
    get_table_profile,
    get_workspace_overview,
)
from starboard_server.mcp.config import MCPServerConfig
from starboard_server.mcp.exceptions import (
    AuthenticationError,
    ExecutionError,
    RateLimitError,
)
from starboard_server.mcp.models import MCPError
from starboard_server.mcp.observability import (
    TokenBudgetTracker,
    create_root_span,
    log_auth_failed,
    log_circuit_open,
    log_rate_limited,
    log_tool_completed,
    log_tool_error,
    log_tool_started,
    log_tool_truncated,
    set_mcp_request_id,
)
from starboard_server.mcp.prompt_bridge import PROMPT_METADATA, build_prompt_messages
from starboard_server.mcp.protocols import MCPAuthProvider, WorkspaceResolver
from starboard_server.mcp.rate_limiter import MCPRateLimiter
from starboard_server.mcp.resource_providers import StarboardResourceProvider
from starboard_server.mcp.result_formatter import format_tool_result
from starboard_server.mcp.sanitizer import MCPSanitizer
from starboard_server.mcp.tool_bridge import (
    get_mcp_tools,
    resolve_allowed_tools,
)

if TYPE_CHECKING:
    from starboard_server.agents.agent_factory import AgentFactory
    from starboard_server.agents.routing.intent_router import IntentRouter
    from starboard_server.agents.tools.tool_registry import ToolRegistry

logger = get_logger(__name__)


class StarboardMCPServer:
    """MCP server exposing Starboard tools, resources, and prompts.

    This class owns the ``FastMCP`` instance and registers all MCP
    handlers.  It is transport-agnostic — callers choose stdio or HTTP
    via the transport helpers in ``transports.py``.

    Args:
        config: Validated MCP server configuration.
        workspace_resolver: Resolves workspace IDs to profiles.
        auth_provider: Provides credentials for workspaces.
        rate_limiter: Enforces per-session and global rate limits.
        sanitizer: Redacts PII from responses.
        circuit_breakers: Per-workspace circuit breaker instances.
        tool_registry: Optional ToolRegistry for executing tools.
    """

    def __init__(
        self,
        config: MCPServerConfig,
        workspace_resolver: WorkspaceResolver | None = None,
        auth_provider: MCPAuthProvider | None = None,
        rate_limiter: MCPRateLimiter | None = None,
        sanitizer: MCPSanitizer | None = None,
        circuit_breakers: MCPCircuitBreakerRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        token_budget_tracker: TokenBudgetTracker | None = None,
        agent_factory: AgentFactory | None = None,
        intent_router: IntentRouter | None = None,
        api_key: str | None = None,
    ) -> None:
        self._config = config
        self._workspace_resolver = workspace_resolver
        self._auth_provider = auth_provider
        self._rate_limiter = rate_limiter
        self._sanitizer = sanitizer
        self._circuit_breakers = circuit_breakers
        self._tool_registry = tool_registry
        self._token_budget_tracker = token_budget_tracker or TokenBudgetTracker(
            default_budget=config.token_budget,
        )
        self._agent_factory = agent_factory
        self._intent_router = intent_router
        self._api_key = api_key
        self._agent_executor: MCPAgentExecutor | None = None
        if agent_factory is not None:
            self._agent_executor = MCPAgentExecutor(
                agent_factory=agent_factory,
                intent_router=intent_router,
                token_budget_tracker=self._token_budget_tracker,
                default_timeout=config.agent_timeout,
            )
        self._resource_provider = StarboardResourceProvider(
            config=config,
            circuit_breakers=circuit_breakers,
        )
        self._mcp = FastMCP(
            name="starboard-mcp",
            instructions=(
                "Starboard AI Agent — Databricks workload analysis and "
                "optimization via MCP tools, agents, resources, and prompts."
            ),
        )
        self._register_ping()
        self._register_tools()
        self._register_composite_tools()
        self._register_agent_tools()
        self._register_resources()
        self._register_prompts()
        logger.info(
            "mcp_server_initialized",
            default_workspace=config.default_workspace_id,
            workspace_count=len(config.workspaces),
            safe_mode=config.safe_mode,
            agent_tools_enabled=self._agent_executor is not None,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> MCPServerConfig:
        """Return the server configuration."""
        return self._config

    @property
    def mcp(self) -> FastMCP:
        """Return the underlying FastMCP instance."""
        return self._mcp

    @property
    def workspace_resolver(self) -> WorkspaceResolver | None:
        """Return the workspace resolver."""
        return self._workspace_resolver

    @property
    def auth_provider(self) -> MCPAuthProvider | None:
        """Return the auth provider."""
        return self._auth_provider

    @property
    def rate_limiter(self) -> MCPRateLimiter | None:
        """Return the rate limiter."""
        return self._rate_limiter

    @property
    def sanitizer(self) -> MCPSanitizer | None:
        """Return the PII sanitizer."""
        return self._sanitizer

    @property
    def circuit_breakers(self) -> MCPCircuitBreakerRegistry | None:
        """Return the circuit breaker registry."""
        return self._circuit_breakers

    @property
    def tool_registry(self) -> ToolRegistry | None:
        """Return the tool registry."""
        return self._tool_registry

    @property
    def agent_executor(self) -> MCPAgentExecutor | None:
        """Return the agent executor."""
        return self._agent_executor

    # ------------------------------------------------------------------
    # Runtime dependency injection
    # ------------------------------------------------------------------

    def inject_runtime_deps(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        agent_factory: AgentFactory | None = None,
        intent_router: IntentRouter | None = None,
    ) -> None:
        """Inject runtime dependencies after construction.

        Call this to wire in ``ToolRegistry``, ``AgentFactory``, and
        ``IntentRouter`` when they are not available at construction time
        (e.g. when the MCP server is mounted before the FastAPI lifespan
        initializes the full dependency stack).

        Args:
            tool_registry: Tool registry for executing tools.
            agent_factory: Factory for domain-specialist agents.
            intent_router: Router for classifying user intent.
        """
        if tool_registry is not None:
            self._tool_registry = tool_registry
        if agent_factory is not None:
            self._agent_factory = agent_factory
        if intent_router is not None:
            self._intent_router = intent_router
        if agent_factory is not None:
            self._agent_executor = MCPAgentExecutor(
                agent_factory=agent_factory,
                intent_router=intent_router or self._intent_router,
                token_budget_tracker=self._token_budget_tracker,
                default_timeout=self._config.agent_timeout,
            )
            logger.info(
                "mcp_server_deps_injected",
                tool_count=(
                    len(tool_registry.list_tools()) if tool_registry else 0
                ),
                agent_tools_enabled=True,
            )

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_ping(self) -> None:
        """Register the health-check ping tool."""

        @self._mcp.tool(
            name="starboard_ping",
            description="Health-check ping for the Starboard MCP server.",
        )
        async def starboard_ping() -> str:
            return "pong"

    def _register_tools(self) -> None:
        """Dynamically register tools from tool_bridge metadata based on tool_scope."""
        tool_defs = get_mcp_tools(safe_mode=self._config.safe_mode, tool_scope=self._config.tool_scope)
        for tool_def in tool_defs:
            self._register_single_tool(tool_def)
        logger.info(
            "mcp_tools_registered",
            count=len(tool_defs),
            safe_mode=self._config.safe_mode,
        )

    def _register_single_tool(self, tool_def: dict[str, Any]) -> None:
        """Register one MCP tool backed by the execution pipeline."""
        tool_name = tool_def["name"]

        # Create a closure that captures tool_name for call_tool dispatch.
        async def _handler(**kwargs: Any) -> str:
            return await self._execute_tool(tool_name, kwargs)

        # Give the function a distinct __name__ for FastMCP
        _handler.__name__ = tool_name
        _handler.__qualname__ = f"StarboardMCPServer._handler.{tool_name}"
        _handler.__doc__ = tool_def.get("description", "")

        self._mcp.add_tool(
            _handler,
            name=tool_name,
            description=tool_def.get("description", ""),
        )

    def _register_composite_tools(self) -> None:
        """Register composite tools that chain multiple quick-lookup tools."""
        _composite_fns = {
            "get_job_summary": get_job_summary,
            "get_query_analysis": get_query_analysis,
            "get_table_profile": get_table_profile,
            "get_workspace_overview": get_workspace_overview,
        }
        for tool_def in COMPOSITE_TOOL_METADATA:
            self._register_single_composite_tool(
                tool_def, _composite_fns[tool_def["name"]]
            )
        logger.info(
            "mcp_composite_tools_registered", count=len(COMPOSITE_TOOL_METADATA)
        )

    def _register_single_composite_tool(
        self, tool_def: dict[str, Any], composite_fn: Any
    ) -> None:
        """Register one composite tool with its chained execution function."""
        tool_name = tool_def["name"]

        async def _handler(**kwargs: Any) -> str:
            workspace_id = (
                kwargs.pop("workspace_id", None) or self._config.default_workspace_id
            )

            async def _executor(
                inner_tool_name: str, **inner_kwargs: Any
            ) -> dict[str, Any]:
                """Adapter that routes composite sub-calls through _execute_tool."""
                result_json = await self._execute_tool(
                    inner_tool_name, {"workspace_id": workspace_id, **inner_kwargs}
                )
                parsed = json.loads(result_json)
                if parsed.get("isError"):
                    raise ExecutionError(
                        parsed.get("message", "sub-tool failed"),
                        code=parsed.get("code", "EXEC_FAILED"),
                    )
                return parsed.get("data", parsed)

            try:
                result = await composite_fn(_executor, **kwargs)
                return json.dumps(
                    {
                        "status": result.status,
                        "data": result.data,
                        "errors": result.errors,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - MCP error boundary
                return json.dumps(
                    {
                        "isError": True,
                        "code": "EXEC_COMPOSITE_FAILED",
                        "message": str(exc),
                    }
                )

        _handler.__name__ = tool_name
        _handler.__qualname__ = f"StarboardMCPServer._composite_handler.{tool_name}"
        _handler.__doc__ = tool_def.get("description", "")

        self._mcp.add_tool(
            _handler,
            name=tool_name,
            description=tool_def.get("description", ""),
        )

    def _register_resources(self) -> None:
        """Register MCP resources for catalog and health introspection."""
        provider = self._resource_provider

        for resource_meta in provider.list_resources():
            uri = resource_meta["uri"]
            name = resource_meta["name"]
            description = resource_meta["description"]

            # Capture uri in closure via factory function
            def _make_handler(resource_uri: str) -> Any:
                async def _handler() -> str:
                    data = provider.read_resource(resource_uri)
                    return json.dumps(data)

                fn_name = resource_uri.replace("://", "_").replace("/", "_")
                _handler.__name__ = fn_name
                _handler.__qualname__ = (
                    f"StarboardMCPServer._resource_handler.{fn_name}"
                )
                return _handler

            handler = _make_handler(uri)
            self._mcp.resource(
                uri,
                name=name,
                description=description,
                mime_type="application/json",
            )(handler)

        logger.info("mcp_resources_registered", count=len(provider.list_resources()))

    def _register_agent_tools(self) -> None:
        """Register 8 domain agent tools from agent_bridge metadata."""
        if self._agent_executor is None:
            logger.info("mcp_agent_tools_skipped", reason="no agent_factory configured")
            return
        for tool_def in AGENT_TOOL_METADATA:
            self._register_single_agent_tool(tool_def)
        logger.info("mcp_agent_tools_registered", count=len(AGENT_TOOL_METADATA))

    def _register_single_agent_tool(self, tool_def: dict[str, Any]) -> None:
        """Register one MCP agent tool backed by MCPAgentExecutor."""
        tool_name = tool_def["name"]

        async def _handler(ctx: Context, **kwargs: Any) -> str:
            return await self._execute_agent_tool(tool_name, kwargs, ctx=ctx)

        _handler.__name__ = tool_name
        _handler.__qualname__ = f"StarboardMCPServer._agent_handler.{tool_name}"
        _handler.__doc__ = tool_def.get("description", "")

        self._mcp.add_tool(
            _handler,
            name=tool_name,
            description=tool_def.get("description", ""),
        )

    def _register_prompts(self) -> None:
        """Register 8 domain agent prompts from prompt_bridge metadata."""
        for prompt_def in PROMPT_METADATA:
            self._register_single_prompt(prompt_def)
        logger.info("mcp_prompts_registered", count=len(PROMPT_METADATA))

    def _register_single_prompt(self, prompt_def: dict[str, Any]) -> None:
        """Register one MCP prompt backed by prompt_bridge."""
        prompt_name = prompt_def["name"]
        domain = prompt_def["domain"]

        def _handler(
            goal: str = "",
            workspace_id: str = "",
        ) -> list[dict[str, str]]:
            return build_prompt_messages(domain, goal=goal, workspace_id=workspace_id)

        _handler.__name__ = prompt_name
        _handler.__qualname__ = f"StarboardMCPServer._prompt_handler.{prompt_name}"
        _handler.__doc__ = prompt_def.get("description", "")

        self._mcp.prompt(
            name=prompt_name,
            description=prompt_def.get("description", ""),
        )(_handler)

    # ------------------------------------------------------------------
    # Execution pipeline
    # ------------------------------------------------------------------

    async def _execute_agent_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        ctx: Context | None = None,
    ) -> str:
        """Execute an agent tool through MCPAgentExecutor.

        Args:
            tool_name: MCP agent tool name (e.g. ``query_agent``).
            arguments: Caller-supplied arguments (message, workspace_id, etc.).
            ctx: Optional FastMCP context for progress notifications.

        Returns:
            JSON string of the ``MCPAgentResponse``.
        """
        if self._agent_executor is None:
            error = MCPError(
                code="EXEC_NO_AGENT_FACTORY",
                message="Agent tools are not configured on this server.",
            )
            return json.dumps(error.model_dump())

        domain = TOOL_NAME_TO_DOMAIN.get(tool_name)
        if domain is None:
            error = MCPError(
                code="EXEC_UNKNOWN_AGENT",
                message=f"Unknown agent tool: {tool_name!r}",
            )
            return json.dumps(error.model_dump())

        message = arguments.pop("message", "")
        session_id = str(arguments.pop("_session_id", "default"))
        workspace_id = (
            arguments.pop("workspace_id", None) or self._config.default_workspace_id
        )
        conversation_id = arguments.pop("conversation_id", None)
        config_overrides = arguments.pop("config_overrides", None)

        response = await self._agent_executor.execute(
            message=message,
            workspace_id=workspace_id,
            domain=domain,
            session_id=session_id,
            conversation_id=conversation_id,
            config_overrides=config_overrides,
            mcp_context=ctx,
        )

        response_dict = response.model_dump(mode="json")
        if self._sanitizer is not None:
            response_dict = self._sanitizer.redact_output(response_dict)

        return json.dumps(response_dict)

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Execute the full tool pipeline with observability.

        Flow: span-create → rate-limit → validate-name → validate-inputs →
              resolve-workspace → auth → circuit-breaker(execute) → format →
              sanitize → log → return JSON.

        Any exception is caught and returned as ``{"isError": true, ...}``
        JSON so that MCP protocol framing is never broken.

        Args:
            tool_name: MCP tool name.
            arguments: Caller-supplied arguments (may include ``workspace_id``).

        Returns:
            JSON string of the sanitised ``MCPToolResponse`` or an error dict
            with ``isError=true`` on failure.
        """
        session_id = str(arguments.pop("_session_id", "default"))
        workspace_id_arg: str | None = arguments.pop("workspace_id", None)
        workspace_id_used = workspace_id_arg or self._config.default_workspace_id

        # Create root span and set trace context
        root_span = create_root_span(
            tool_name=tool_name,
            session_id=session_id,
            workspace_id=workspace_id_used,
        )
        set_mcp_request_id(root_span.trace_id)

        log_tool_started(
            root_span,
            tool_name,
            session_id=session_id,
            workspace_id=workspace_id_used,
        )

        try:
            # 1. Rate-limit
            if self._rate_limiter is not None:
                try:
                    self._rate_limiter.check(session_id)
                except RateLimitError:
                    log_rate_limited(
                        root_span,
                        session_id=session_id,
                        workspace_id=workspace_id_used,
                    )
                    raise

            # 2. Validate tool name
            allowed = resolve_allowed_tools(
                safe_mode=self._config.safe_mode,
                tool_scope=self._config.tool_scope,
            )

            if tool_name not in allowed:
                code = (
                    "EXEC_SAFE_MODE_RESTRICTED"
                    if self._config.safe_mode
                    else "EXEC_UNKNOWN_TOOL"
                )
                raise ExecutionError(f"Tool {tool_name!r} is not available.", code=code)

            # 3. Validate tool inputs against inputSchema
            validation_error = self._validate_tool_inputs(tool_name, arguments)
            if validation_error is not None:
                root_span.close(status="error", error_code="EXEC_INVALID_INPUT")
                return json.dumps(
                    {
                        "isError": True,
                        "code": "EXEC_INVALID_INPUT",
                        "message": validation_error,
                    }
                )

            # 4. Resolve workspace
            profile = None
            if self._workspace_resolver is not None:
                resolve_span = root_span.child("mcp.workspace.resolve")
                profile = self._workspace_resolver.resolve(workspace_id_arg)
                resolve_span.close()

            # 5. Authenticate — fail explicitly if workspace resolver is set
            #    but auth provider is absent (misconfiguration, not silent pass-through)
            credentials = None
            if profile is not None:
                if self._auth_provider is None:
                    log_auth_failed(
                        root_span,
                        session_id=session_id,
                        workspace_id=workspace_id_used,
                    )
                    raise AuthenticationError(
                        "Workspace resolved but no auth_provider is configured. "
                        "Cannot obtain credentials for workspace "
                        f"{workspace_id_used!r}.",
                        code="AUTH_NO_PROVIDER",
                    )
                auth_span = root_span.child("mcp.auth.credentials")
                try:
                    credentials = self._auth_provider.get_credentials(profile)
                    auth_span.close()
                except AuthenticationError:
                    auth_span.close(status="error")
                    log_auth_failed(
                        root_span,
                        session_id=session_id,
                        workspace_id=workspace_id_used,
                    )
                    raise

            # 6. Execute via ToolRegistry through circuit breaker
            if self._tool_registry is None:
                raise ExecutionError(
                    "Tool registry not configured.", code="EXEC_NO_REGISTRY"
                )

            agent_context: dict[str, Any] = {"workspace_id": workspace_id_used}
            if credentials is not None:
                agent_context["databricks_host"] = credentials.host
                agent_context["databricks_token"] = credentials.token

            exec_span = root_span.child(f"tool.{tool_name}")

            breaker = (
                self._circuit_breakers.get(workspace_id_used)
                if self._circuit_breakers is not None
                else None
            )

            try:
                if breaker is not None:
                    result = await breaker.call(
                        self._tool_registry.execute_tool,
                        tool_name,
                        agent_context=agent_context,
                        **arguments,
                    )
                else:
                    result = await self._tool_registry.execute_tool(
                        tool_name, agent_context=agent_context, **arguments
                    )
                exec_span.close()
            except Exception:  # noqa: BLE001 - MCP error boundary
                exec_span.close(status="error")
                if breaker is not None:
                    log_circuit_open(
                        root_span,
                        session_id=session_id,
                        workspace_id=workspace_id_used,
                    )
                raise

            # 7. Format result
            format_span = root_span.child("mcp.format.response")
            mcp_response = format_tool_result(
                result,
                workspace_id_used=workspace_id_used,
                max_response_size_bytes=self._config.max_response_size_bytes,
                trace_id=root_span.trace_id,
                duration_ms=root_span.duration_ms,
            )
            format_span.close()

            if mcp_response.truncated:
                log_tool_truncated(
                    root_span,
                    tool_name,
                    session_id=session_id,
                    workspace_id=workspace_id_used,
                )

            # 8. Sanitize
            sanitize_span = root_span.child("mcp.sanitize.output")
            response_dict = mcp_response.model_dump()
            if self._sanitizer is not None:
                response_dict = self._sanitizer.redact_output(response_dict)
            sanitize_span.close()

            # Close root span and log completion
            root_span.close()
            log_tool_completed(
                root_span,
                tool_name,
                session_id=session_id,
                workspace_id=workspace_id_used,
                duration_ms=root_span.duration_ms,
                truncated=mcp_response.truncated,
            )

            return json.dumps(response_dict)

        except (RateLimitError, ExecutionError):
            # Let validation/rate-limit errors propagate — callers expect them.
            raise
        except Exception as exc:  # noqa: BLE001 - MCP error boundary
            error_code = getattr(exc, "code", "UNKNOWN")
            root_span.close(status="error", error_code=error_code)
            log_tool_error(
                root_span,
                tool_name,
                error_code=error_code,
                error_message=str(exc),
                session_id=session_id,
                workspace_id=workspace_id_used,
                duration_ms=root_span.duration_ms,
            )
            # Return structured error JSON for unexpected exceptions.
            # This preserves MCP protocol framing for runtime errors.
            return json.dumps(
                {
                    "isError": True,
                    "code": error_code,
                    "message": str(exc),
                }
            )

    def _validate_tool_inputs(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> str | None:
        """Validate tool arguments against the tool's inputSchema.

        Args:
            tool_name: Registered MCP tool name.
            arguments: Caller-supplied arguments (``workspace_id`` already popped).

        Returns:
            Human-readable error string if validation fails, ``None`` if valid.
        """
        from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

        meta = ALL_TOOL_METADATA.get(tool_name)
        if meta is None:
            # Unknown tool — validation skipped, handled by name check upstream
            return None

        params = meta.get("parameters", {})
        required_fields: list[str] = params.get("required", [])
        missing = [f for f in required_fields if f not in arguments]
        if missing:
            return f"Tool {tool_name!r} missing required parameter(s): " + ", ".join(
                repr(f) for f in missing
            )
        return None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def call_tool_not_implemented(self, tool_name: str) -> MCPError:
        """Return a structured not-implemented error for a tool call.

        Args:
            tool_name: Name of the tool that was called.

        Returns:
            Structured ``MCPError`` with code ``EXEC_NOT_IMPLEMENTED``.
        """
        return MCPError(
            code="EXEC_NOT_IMPLEMENTED",
            message=f"Tool {tool_name!r} is not yet implemented.",
        )
