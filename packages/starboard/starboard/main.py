# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Starboard Server — FastAPI application.

Provides:
  - /health/live and /health/ready probes
  - /mcp  Streamable HTTP MCP transport (when MCP config is present)

The primary consumption paths are:
  - starboard-mcp  (stdio MCP server, no FastAPI)
  - starboard       (CLI, direct in-process agent execution)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from starboard.infra.core.config import get_config
from starboard.infra.observability.logging import setup_structured_logging
from starboard.infra.observability.tracing import init_tracing

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan: bootstrap MCP server deps on startup, nothing on shutdown."""
    config = get_config()
    init_tracing(
        service_name="starboard-server",
        otlp_endpoint=getattr(config, "otlp_endpoint", None),
    )

    # Inject runtime deps into MCP server if it was mounted
    mcp_server = getattr(app.state, "mcp_server", None)
    if mcp_server is not None:
        try:
            from starboard.bootstrap import (
                AgentConfig,
                AgentFactory,
                AsyncDatabricksClient,
                IntentRouter,
                SharedContextProvider,
                create_llm_client,
                create_tool_registry,
            )

            cfg = get_config()
            llm_client = create_llm_client(cfg=cfg)
            api = AsyncDatabricksClient(cfg=cfg)
            await api._initialize()
            provider = SharedContextProvider(api)
            tool_registry, _ = create_tool_registry(
                api=api,
                provider=provider,
                events=None,
                input_callback=None,
                llm_client=llm_client,
                vector_store=None,
                embedding_service=None,
            )
            agent_factory = AgentFactory(
                llm_client=llm_client,
                tool_registry=tool_registry,
                base_config=AgentConfig(
                    model=cfg.llm_model,
                    max_tokens=cfg.llm_max_tokens,
                    temperature=cfg.llm_temperature,
                    domain_model_overrides=cfg.domain_model_overrides or {},
                    domain_temperature_overrides=cfg.domain_temperature_overrides or {},
                ),
                events=None,
            )
            intent_router = IntentRouter(
                llm_client=llm_client,
                disabled_domains=cfg.disabled_agent_domains or [],
            )
            mcp_server.inject_runtime_deps(
                tool_registry=tool_registry,
                agent_factory=agent_factory,
                intent_router=intent_router,
            )
            logger.info("mcp_runtime_deps_injected")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mcp_dep_injection_failed",
                error=str(exc),
                message="MCP server will serve tool listings but call_tool may fail.",
            )

    yield

    logger.info("server_shutdown_complete")


# ---------------------------------------------------------------------------
# Databricks Apps — OBO (on-behalf-of) per-request client dependency (O4)
# ---------------------------------------------------------------------------
# When Starboard runs as a Databricks App the platform forwards the end-user's
# OAuth token in the X-Forwarded-Access-Token header.  ``get_obo_client``
# detects that header and resolves a per-request ``WorkspaceClient`` via the
# existing ``resolve_user_client()`` seam in ``infra/auth/resolver.py``.
# Identity is logged via ``describe_auth()`` — never the token.
#
# Without the header (CLI / MCP stdio / any non-App path) the dependency returns
# ``None`` and the default resolver path is wholly unchanged — OBO is strictly
# additive and opt-in per request/deployment.

_APPS_FORWARDED_HEADER = "x-forwarded-access-token"
"""Lower-cased name of the Databricks Apps forwarded-user OAuth header.

Starlette's ``Headers`` object is case-insensitive so the lower-case form is
used for membership testing across all header capitalizations.
"""


async def get_obo_client(request: Request) -> Any:
    """FastAPI dependency — per-request OBO ``WorkspaceClient`` for Databricks Apps.

    When the Databricks Apps runtime forwards the end-user's token (the
    ``X-Forwarded-Access-Token`` header is present), this dependency resolves a
    per-request ``WorkspaceClient`` via :func:`resolve_user_client` so every SDK
    call in that request executes on behalf of the authenticated user — enabling
    per-user Unity Catalog and Genie access.

    User identity is logged via :func:`describe_auth` (which redacts all secrets).
    If the identity log call fails (e.g. a transient network error on
    ``/api/2.0/preview/scim/v2/Me``), the error is swallowed and the client is
    still returned — a logging failure must not disrupt the request.

    Outside Databricks Apps (no forwarded-user header) the dependency returns
    ``None`` so callers can fall back to the ambient resolver.  The non-App path
    is byte-for-byte unchanged.

    Returns:
        A per-request ``WorkspaceClient`` (OBO strategy) when in App context,
        or ``None`` on the non-App path.
    """
    user_token = request.headers.get(_APPS_FORWARDED_HEADER)
    if not user_token:
        return None

    # Lazy import: keeps module load clean of SDK for the non-App path.
    from starboard.infra.auth.resolver import (  # noqa: PLC0415
        describe_auth,
        resolve_user_client,
    )

    # Authenticate as the end user with their forwarded OAuth token (the canonical
    # Databricks Apps OBO flow), not merely detect the header's presence.
    client = resolve_user_client(user_access_token=user_token)
    try:
        # describe_auth() makes a blocking SCIM /Me call — offload it so a single
        # identity-log lookup never serializes concurrent requests on the loop.
        auth_info = await asyncio.to_thread(describe_auth, client)
        logger.info("obo_request_identity", **auth_info)
    except Exception:  # noqa: BLE001
        logger.debug("obo_identity_log_unavailable")
    return client


def _get_log_level(level_name: str) -> int:
    _level_map: dict[str, int] = {
        "CRITICAL": 50, "FATAL": 50, "ERROR": 40,
        "WARNING": 30, "WARN": 30, "INFO": 20, "DEBUG": 10, "NOTSET": 0,
    }
    return _level_map.get(level_name.upper(), 20)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()
    setup_structured_logging(
        level=_get_log_level(config.log_level),
        json_output=config.log_json,
        enable_pii_redaction=config.enable_pii_redaction,
    )

    is_production = config.environment == "production"
    app = FastAPI(
        title="Starboard AI Agent",
        description="AI-powered Databricks workload analysis and optimization",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    # Mount MCP HTTP transport at /mcp (when config present)
    try:
        from starboard.mcp.config import load_mcp_config
        from starboard.mcp.transports import create_starboard_mcp_server

        mcp_config = load_mcp_config()
        if mcp_config:
            mcp_server = create_starboard_mcp_server(mcp_config)
            app.state.mcp_server = mcp_server
            mcp_app = mcp_server.mcp.streamable_http_app()
            app.mount("/mcp", mcp_app)
            logger.info("mcp_server_mounted", path="/mcp")
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_server_mount_failed", error=str(exc))

    @app.get("/health/live")
    async def health_live() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/")
    async def root() -> JSONResponse:
        return JSONResponse({
            "name": "Starboard AI Agent",
            "version": "0.1.0",
            "status": "running",
            "docs": "/docs",
            "health": {"live": "/health/live", "ready": "/health/ready"},
            "mcp": "/mcp",
        })

    return app


def run() -> None:
    """Run the FastAPI server with Uvicorn (entry point: starboard-server)."""
    import uvicorn

    config = get_config()
    uvicorn.run(
        "starboard.main:create_app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        factory=True,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    run()
