"""
FastAPI authentication middleware.

Extracts authenticated user from requests and makes it available throughout the request lifecycle.
"""

from fastapi import Request, Response
from starboard_core.domain.models.auth import User
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from starboard_server.domain.auth.exceptions import AuthenticationError
from starboard_server.infra.auth.service import AuthenticationService
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware for FastAPI.

    Intercepts all requests to authenticate users before reaching endpoints.
    Adds authenticated user to request.state for downstream access.

    Flow:
    1. Request arrives
    2. Middleware calls authentication service
    3. User object stored in request.state.user
    4. Request proceeds to endpoint
    5. Endpoint can access request.state.user

    Error Handling:
    - Authentication failures return 401 Unauthorized
    - Unexpected errors return 500 Internal Server Error

    Examples:
        ```python
        from starboard_server.infra.auth.middleware import AuthMiddleware
        from starboard_server.infra.auth.providers.databricks import DatabricksAuthProvider

        # In main.py:
        auth_service = DatabricksAuthProvider(databricks_api, user_repo)
        app.add_middleware(AuthMiddleware, auth_service=auth_service)

        # In endpoint:
        @app.get("/conversations")
        async def list_conversations(request: Request):
            user: User = request.state.user
            return await conversation_service.list_for_user(user.id)
        ```
    """

    def __init__(
        self,
        app: ASGIApp,
        auth_service: AuthenticationService | None = None,
        exclude_paths: list[str] | None = None,
    ) -> None:
        """
        Initialize authentication middleware.

        Args:
            app: ASGI application
            auth_service: Authentication service for user lookup (lazy-loaded if None)
            exclude_paths: Optional list of paths to exclude from auth (e.g., /health)
        """
        super().__init__(app)
        self._auth_service = auth_service
        self.exclude_paths = set(
            exclude_paths or ["/health", "/health/live", "/health/ready"]
        )

    def _get_auth_service(self) -> AuthenticationService:
        """Get auth service, lazy-loading from main module if needed."""
        if self._auth_service is None:
            from starboard_server.main import get_auth_service

            self._auth_service = get_auth_service()
        return self._auth_service

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        """
        Process request through authentication.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/endpoint in chain

        Returns:
            HTTP response from endpoint or error response
        """
        # Skip authentication for excluded paths — use prefix match so that
        # sub-paths (e.g. /health/live/detail) are also excluded.
        path = request.url.path
        if any(
            path == excluded or path.startswith(excluded + "/")
            for excluded in self.exclude_paths
        ):
            logger.debug(
                "auth_skipped_excluded_path",
                path=path,
            )
            return await call_next(request)

        try:
            # Authenticate user
            user: User = await self._get_auth_service().get_current_user(request)

            # Store user in request state for downstream access
            request.state.user = user

            logger.debug(
                "auth_success",
                user_id=user.id,
                username=user.username,
                path=request.url.path,
            )

            # Continue to endpoint
            response = await call_next(request)
            return response

        except AuthenticationError as e:
            # Authentication failed - return 401
            logger.warning(
                "auth_failed",
                error=str(e),
                provider=e.provider,
                path=request.url.path,
                method=request.method,
            )

            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": "Authentication failed",
                },
            )

        except Exception as e:  # noqa: BLE001 - auth middleware boundary
            # Unexpected error - return 500
            logger.error(
                "auth_middleware_error",
                error=str(e),
                error_type=type(e).__name__,
                path=request.url.path,
                method=request.method,
            )

            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred during authentication",
                },
            )


def get_current_user(request: Request) -> User:
    """
    Get authenticated user from request.

    Helper function for endpoints to easily access the authenticated user.

    Args:
        request: FastAPI Request object

    Returns:
        Authenticated User object

    Raises:
        AttributeError: If no user found in request.state (middleware not configured)

    Examples:
        ```python
        from starboard_server.infra.auth.middleware import get_current_user

        @app.get("/me")
        async def get_me(request: Request):
            user = get_current_user(request)
            return {"user_id": user.id, "username": user.username}
        ```
    """
    return request.state.user
