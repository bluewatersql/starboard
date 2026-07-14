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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from starboard_server.infra.core.config import get_config
from starboard_server.infra.observability.logging import setup_structured_logging
from starboard_server.infra.observability.tracing import init_tracing

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
            from starboard_server.bootstrap import (
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
        from starboard_server.mcp.config import load_mcp_config
        from starboard_server.mcp.transports import create_starboard_mcp_server

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
        "starboard_server.main:create_app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        factory=True,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    run()
