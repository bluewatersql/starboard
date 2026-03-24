"""Configuration and health endpoints.

Provides server configuration and health check endpoints:
- GET /config - Get server configuration
- GET /health - Health check
- GET /me - Get current user information
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get(
    "/config",
    summary="Get Server Configuration",
    description="Get current server configuration including domain model defaults",
    responses={
        200: {"description": "Server configuration"},
    },
)
async def get_server_config() -> dict[str, Any]:
    """Get server configuration including domain model overrides."""
    from starboard_server.infra.core.config import get_config

    config = get_config()

    return {
        "default_model": config.llm_model,
        "default_temperature": config.llm_temperature,
        "default_max_tokens": config.llm_max_tokens,
        "domain_model_overrides": config.domain_model_overrides or {},
        "domain_temperature_overrides": config.domain_temperature_overrides or {},
    }


@router.get(
    "/health",
    summary="Chat API Health Check",
    description="Check if the chat API is operational",
    responses={
        200: {"description": "API is healthy"},
    },
)
async def health_check() -> JSONResponse:
    """
    Health check for the chat API.

    Returns basic status information. Can be extended to check
    dependencies like ConversationManager initialization.

    Example:
        ```bash
        curl http://localhost:8000/api/v2/chat/health
        ```

        Response:
        ```json
        {
          "status": "healthy",
          "service": "chat_api",
          "version": "2.0"
        }
        ```
    """
    return JSONResponse(
        {
            "status": "healthy",
            "service": "chat_api",
            "version": "2.0",
        }
    )


@router.get(
    "/me",
    summary="Get Current User",
    description="Get information about the authenticated user",
    responses={
        200: {
            "description": "User information",
            "content": {
                "application/json": {
                    "example": {
                        "user_id": "b822cc87-fae3-4192-abd4-89ce0ea19c87",
                        "username": "c.price@databricks.com",
                        "display_name": "Chris Price",
                    }
                }
            },
        },
        401: {"description": "Not authenticated"},
    },
)
async def get_current_user(request: Request) -> dict[str, Any]:
    """
    Get current authenticated user information.

    Returns user ID, username, and display name extracted from authentication middleware.
    The display_name is sourced from Databricks API current_user.me().displayName.

    Args:
        request: FastAPI Request object (contains authenticated user)

    Returns:
        Dict with user_id, username, and display_name

    Example:
        ```bash
        curl http://localhost:8000/api/chat/me
        ```

        Response:
        ```json
        {
          "user_id": "b822cc87-fae3-4192-abd4-89ce0ea19c87",
          "username": "c.price@databricks.com",
          "display_name": "Chris Price"
        }
        ```
    """
    user = request.state.user
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }
