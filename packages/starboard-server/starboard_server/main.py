# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Starboard Server - FastAPI Application.

Main entry point for the Starboard AI Agent FastAPI backend.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from starboard_server.infra.core.config import get_config
from starboard_server.infra.core.container import Container
from starboard_server.infra.observability.logging import setup_structured_logging
from starboard_server.infra.observability.tracing import init_tracing

if TYPE_CHECKING:
    from starboard_server.infra.auth.service import AuthenticationService

logger = structlog.get_logger(__name__)

# Global container instance
_container: Container | None = None
_auth_service: "AuthenticationService | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Lifespan context manager for FastAPI application.

    Handles startup and shutdown tasks.
    """
    global _container, _auth_service

    # Startup
    logger.info("server_starting", version=app.version)

    # Validate event coverage (ensure all events have type mappings)
    from starboard_server.api.event_converter import validate_event_coverage

    is_valid, missing = validate_event_coverage()
    if not is_valid:
        logger.error(
            "event_coverage_validation_failed",
            missing_events=missing,
            message="Some StreamingEvent types are not registered in EVENT_TYPE_MAPPING",
        )
        raise RuntimeError(
            f"Event coverage validation failed. Missing event mappings: {missing}. "
            f"Add these events to EVENT_TYPE_MAPPING in event_converter.py"
        )

    logger.debug(
        "event_coverage_validated", total_events=len(missing) if missing else "all"
    )

    # Initialize OpenTelemetry tracing
    env_config = get_config()
    init_tracing(
        service_name="starboard-server",
        otlp_endpoint=getattr(env_config, "otlp_endpoint", None),
    )
    logger.debug("tracing_initialized")

    # Initialize state management container
    try:
        logger.debug("initializing_state_container")
        env_config.validate_config()

        _container = Container(env_config)
        await _container.initialize()

        logger.info(
            "state_container_initialized",
            environment=env_config.environment,
            database_backend=env_config.database_backend,
        )

        # Initialize authentication service
        logger.debug("initializing_auth_service")
        from starboard_server.adapters.databricks import AsyncDatabricksClient
        from starboard_server.infra.auth.providers.databricks import (
            DatabricksAuthProvider,
        )

        # Use AsyncDatabricksClient for authentication
        # warehouse_id not required for user authentication
        databricks_client = AsyncDatabricksClient()
        await databricks_client._initialize()  # Must initialize before use
        _auth_service = DatabricksAuthProvider(
            databricks_api=databricks_client,
            user_repository=_container.user_store,
        )

        logger.debug("auth_service_initialized", provider="databricks")

    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "state_container_initialization_failed",
            error=str(e),
            exc_info=True,
        )
        raise

    yield

    # Shutdown
    logger.info("server_shutting_down")

    # Cleanup state container
    if _container:
        logger.debug("shutting_down_state_container")
        await _container.shutdown()
        logger.info("server_shutdown_complete")



def _get_log_level(level_name: str) -> int:
    """Convert log level name string to integer level.

    Maps level name strings to their integer values without importing
    the stdlib logging module (which is replaced by structlog project-wide).
    """
    _level_map: dict[str, int] = {
        "CRITICAL": 50,
        "FATAL": 50,
        "ERROR": 40,
        "WARNING": 30,
        "WARN": 30,
        "INFO": 20,
        "DEBUG": 10,
        "NOTSET": 0,
    }
    return _level_map.get(level_name.upper(), 20)  # default INFO

def get_container() -> Container:
    """
    Get the global Container instance.

    Returns:
        Container instance

    Raises:
        RuntimeError: If container not initialized
    """
    if _container is None:
        raise RuntimeError(
            "Container not initialized. Server may not have started properly."
        )
    return _container


def get_auth_service() -> "AuthenticationService":
    """
    Get the global AuthenticationService instance.

    Returns:
        AuthenticationService instance

    Raises:
        RuntimeError: If auth service not initialized
    """
    if _auth_service is None:
        raise RuntimeError(
            "Auth service not initialized. Server may not have started properly."
        )
    return _auth_service


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance
    """
    # Setup logging
    config = get_config()
    setup_structured_logging(
        level=_get_log_level(config.log_level),
        json_output=config.log_json,
        enable_pii_redaction=config.enable_pii_redaction,
    )

    # Create FastAPI app
    # Gate OpenAPI/docs endpoints: disabled in production to prevent schema leakage
    is_production = config.environment == "production"
    app = FastAPI(
        title="Starboard AI Agent API",
        description="AI-powered Databricks workload analysis and optimization",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    # Configure CORS for Next.js frontend
    # Allow both development and production origins
    allowed_origins = [
        "http://localhost:3000",  # Next.js development
        "http://localhost:3001",  # Alternative dev port
        "http://127.0.0.1:3000",  # Alternative localhost
        "http://127.0.0.1:8000",  # Backend itself
    ]

    # Add production frontend URL if configured
    frontend_url = os.getenv("FRONTEND_URL")
    if frontend_url:
        allowed_origins.append(frontend_url)

    # Note: Cannot use "*" wildcard when allow_credentials=True
    # For development, we explicitly list common local origins above

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,  # Required for auth passthrough
        allow_methods=["GET", "POST", "OPTIONS"],  # Only required methods
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-Conversation-ID",
            "Accept",
            "Cache-Control",
        ],
        expose_headers=[
            "Content-Length",
            "Content-Type",
            "X-Request-ID",
            "X-Conversation-ID",
        ],
        max_age=600,  # Cache preflight requests for 10 minutes
    )

    # Add authentication middleware (lazy-loads auth service from lifespan)
    from starboard_server.infra.auth.middleware import AuthMiddleware

    app.add_middleware(
        AuthMiddleware,
        exclude_paths=[
            "/health/live",
            "/health/ready",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/favicon.ico",
        ],
    )

    # Load config (needed for middleware configuration)
    env_config = get_config()

    # Request size limits
    from starboard_server.infra.middleware.request_size import (
        RequestSizeLimitMiddleware,
    )

    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_size=env_config.max_request_size,
    )

    logger.debug(
        "request_size_limit_enabled",
        max_size_mb=env_config.max_request_size / (1024 * 1024),
    )

    # Rate limiting
    from slowapi import Limiter

    if env_config.rate_limit_enabled:
        # Key function: prefer user_id from request.state, fallback to IP
        def get_rate_limit_key(request: Request) -> str:
            """Get rate limit key from user_id or IP address."""
            # Try to get user_id from request.state (set by auth middleware)
            if hasattr(request.state, "user_id") and request.state.user_id:
                return f"user:{request.state.user_id}"
            # Fallback to IP address
            from slowapi.util import get_remote_address

            return get_remote_address(request)

        # Initialize rate limiter
        limiter = Limiter(
            key_func=get_rate_limit_key,
            storage_uri=env_config.rate_limit_storage,
            default_limits=[env_config.rate_limit_default],
        )
        app.state.limiter = limiter
        # Use slowapi's default exception handler
        from slowapi.errors import RateLimitExceeded as SlowAPIRateLimitExceeded

        def rate_limit_handler(_request: Request, _exc: Exception) -> JSONResponse:
            """Handle rate limit exceeded exceptions."""
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )

        app.add_exception_handler(SlowAPIRateLimitExceeded, rate_limit_handler)

        logger.debug(
            "rate_limiting_enabled",
            storage=env_config.rate_limit_storage,
            default_limit=env_config.rate_limit_default,
        )
    else:
        logger.debug("rate_limiting_disabled")

    # Error sanitization middleware — MUST be last add_middleware() call
    # so it is the outermost middleware (LIFO order) and catches all unhandled exceptions.
    from starboard_server.infra.middleware.error_sanitizer import (
        ErrorSanitizationMiddleware,
    )

    app.add_middleware(
        ErrorSanitizationMiddleware,
        environment=env_config.environment,
    )

    # Register API routes
    from starboard_server.api import (
        chat_router,
        clarification_router,
        feedback_router,
        streaming_router,
    )
    from starboard_server.api.data import router as data_router
    from starboard_server.api.visualization import router as visualization_router

    app.include_router(chat_router)
    app.include_router(streaming_router)
    app.include_router(feedback_router)
    app.include_router(clarification_router)
    app.include_router(visualization_router)
    app.include_router(data_router)

    # ========================================================================
    # Conditional MCP mount (Streamable HTTP at /mcp)
    # ========================================================================
    try:
        from starboard_server.mcp.config import load_mcp_config
        from starboard_server.mcp.transports import create_mcp_app

        mcp_config = load_mcp_config()
        if mcp_config:
            mcp_app = create_mcp_app(config=mcp_config)
            app.mount("/mcp", mcp_app)
            logger.info(
                "mcp_server_mounted",
                path="/mcp",
                default_workspace=mcp_config.default_workspace_id,
            )
        else:
            logger.debug("mcp_server_not_configured")
    except Exception as exc:  # noqa: BLE001 - API error boundary
        logger.warning(
            "mcp_server_mount_failed",
            error=str(exc),
            message="MCP server will not be available. Continuing without it.",
        )

    # Health check endpoints
    @app.get("/health/live")
    async def health_live() -> JSONResponse:
        """Liveness probe - is the service running?"""
        return JSONResponse({"status": "ok"})

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        """Readiness probe - is the service ready to accept traffic?"""
        from starboard_server.infra.health.probes import HealthCheckRunner

        try:
            container = get_container()
            probes = _build_health_probes(container)
            runner = HealthCheckRunner(probes)
            result = await runner.run()
            return JSONResponse(result, status_code=200)
        except RuntimeError as e:
            return JSONResponse(
                {"status": "not_ready", "error": str(e)},
                status_code=503,
            )

    def _build_health_probes(container: Any) -> list:
        """Build health probes from container dependencies."""
        from starboard_server.infra.health.probes import (
            DatabaseProbe,
            HealthProbe,
            RedisProbe,
        )

        probes: list[HealthProbe] = []

        # Database probe — check if state store has a pool (Postgres) or connection (SQLite)
        state_store = container.state_store
        if hasattr(state_store, "pool") and state_store.pool is not None:
            probes.append(DatabaseProbe(state_store.pool))
        elif hasattr(state_store, "conn") and state_store.conn is not None:

            class _SQLitePoolAdapter:
                def __init__(self, conn: Any) -> None:
                    self._conn = conn

                async def acquire(self) -> Any:
                    return self._conn

                async def release(self, conn: Any) -> None:
                    pass

            probes.append(DatabaseProbe(_SQLitePoolAdapter(state_store.conn)))

        # Cache/Redis probe
        cache_store = getattr(container, "cache_store", None)
        if cache_store is not None and hasattr(cache_store, "ping"):
            probes.append(RedisProbe(cache_store))

        return probes

    # ========================================================================
    # Serve Static Frontend (Next.js)
    # ========================================================================
    # This allows FastAPI to serve the built Next.js frontend
    # Only active when frontend/out directory exists (Databricks deployment)

    # Determine frontend build path
    # In Databricks container: /app/frontend/out
    # In local dev: relative to this file
    frontend_out = Path(__file__).parent.parent.parent / "frontend" / "out"

    if frontend_out.exists():
        logger.debug(
            "frontend_static_serving_enabled",
            path=str(frontend_out),
            message="Serving Next.js static frontend via FastAPI",
        )

        # Serve Next.js static assets (_next/static/*)
        if (frontend_out / "_next").exists():
            app.mount(
                "/_next",
                StaticFiles(directory=str(frontend_out / "_next")),
                name="nextjs_static",
            )

        # Serve other static files (images, fonts, etc.)
        # Note: Be careful not to conflict with API routes
        @app.get("/favicon.ico")
        async def favicon():
            """Serve favicon."""
            favicon_path = frontend_out / "favicon.ico"
            if favicon_path.exists():
                return FileResponse(favicon_path)
            return JSONResponse({"error": "Not found"}, status_code=404)

        # Serve frontend routes (must be last to not override API routes)
        @app.get("/")
        @app.get("/chat")
        @app.get("/config")
        async def serve_frontend():
            """
            Serve the Next.js frontend for all non-API routes.

            This enables client-side routing in the Next.js app.
            """
            index_path = frontend_out / "index.html"
            if index_path.exists():
                return FileResponse(index_path)

            # If frontend not built, show helpful message
            return JSONResponse(
                {
                    "error": "Frontend not built",
                    "message": "Run 'cd frontend && npm run build' to build the frontend",
                    "api_docs": "/docs",
                },
                status_code=404,
            )

    else:
        logger.debug(
            "frontend_static_serving_disabled",
            path=str(frontend_out),
            message="Frontend build not found. Run 'cd frontend && npm run build' to enable frontend serving.",
        )

        # Provide helpful message at root
        @app.get("/")
        async def root():
            """Root endpoint when frontend is not built."""
            return JSONResponse(
                {
                    "name": "Starboard AI Agent API",
                    "version": "0.1.0",
                    "status": "running",
                    "frontend": "not_built",
                    "message": "Frontend not available. This is API-only mode.",
                    "docs": f"{config.host}:{config.port}/docs",
                    "health": {
                        "live": f"{config.host}:{config.port}/health/live",
                        "ready": f"{config.host}:{config.port}/health/ready",
                    },
                }
            )

    return app


def run() -> None:
    """
    Run the FastAPI server with Uvicorn.

    Used as entry point for `starboard-server` CLI command.
    """
    import uvicorn

    config = get_config()

    uvicorn.run(
        "starboard_server.main:create_app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        factory=True,
        log_level=config.log_level.lower(),
    )


# Create app instance for direct import
app = create_app()


if __name__ == "__main__":
    run()
