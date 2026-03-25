"""Public entry point for creating Starboard server instances.

This module provides the canonical way to create and configure the Starboard
application. CLI, SDK, and test code should use this facade instead of
importing internal server modules directly.

Usage:
    from starboard_server.bootstrap import create_application

    app = create_application()
"""

from starboard_server.main import create_app


def create_application(**kwargs):
    """Create and configure the Starboard FastAPI application.

    This is the public API for bootstrapping the server. All internal wiring
    (DI container, middleware, routes, agents) is handled by create_app.

    Args:
        **kwargs: Forwarded to create_app (e.g., config overrides).

    Returns:
        FastAPI application instance, fully configured and ready to serve.
    """
    return create_app(**kwargs)


__all__ = ["create_application"]
