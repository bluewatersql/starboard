"""Container integration utilities for FastAPI."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from starboard_server.infra import EnvConfig
from starboard_server.infra.core.container import Container
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Global container instance
_container: Container | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """
    Manage application lifecycle.

    - Startup: Initialize container and connect to databases
    - Shutdown: Close connections and cleanup resources

    Args:
        app: FastAPI application instance

    Yields:
        None during application lifetime
    """
    global _container

    try:
        # Startup
        logger.debug("initializing_container")
        config = get_config()
        config.validate_config()

        _container = Container(config)
        await _container.initialize()

        logger.debug(
            "container_initialized",
            environment=config.environment,
            database_url=bool(config.database_url),
            redis_url=bool(config.redis_url),
            memory_consolidation=config.memory_consolidation_enabled,
        )

        yield

    finally:
        # Shutdown
        logger.debug("shutting_down_container")
        if _container:
            await _container.shutdown()
        logger.debug("container_shutdown_complete")


def get_container() -> Container:
    """
    Dependency injection for container.

    Returns:
        Container instance

    Raises:
        HTTPException: If container not initialized (500 error)

    Example:
        @app.post("/conversations/{conversation_id}/messages")
        async def add_message(
            conversation_id: str,
            container: Container = Depends(get_container),
        ):
            conv_repo = container.conversation_repo
            # ... use repository ...
    """
    if _container is None:
        logger.error("container_not_initialized")
        raise HTTPException(
            status_code=500,
            detail="Container not initialized. Check application startup.",
        )
    return _container


def create_app_with_container() -> FastAPI:
    """
    Create FastAPI app with container lifecycle management.

    Returns:
        FastAPI application with container integration

    Example:
        app = create_app_with_container()

        @app.post("/test")
        async def test(container: Container = Depends(get_container)):
            # Use container
            pass
    """
    app = FastAPI(
        title="Job Agent API",
        version="2.0.0",
        lifespan=lifespan,
    )

    return app
