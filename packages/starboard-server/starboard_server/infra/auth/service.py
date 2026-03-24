"""
Authentication service protocol.

Defines the interface for authentication services following the Protocol pattern
for dependency injection.
"""

from typing import Protocol

from fastapi import Request
from starboard_core.domain.models.auth import User


class AuthenticationService(Protocol):
    """
    Protocol defining authentication service interface.

    This enables provider-agnostic authentication across the application.
    Implementations can use any auth provider (Databricks, OAuth, SAML, etc.).

    Examples:
        >>> auth_service: AuthenticationService = DatabricksAuthProvider(...)
        >>> user = await auth_service.get_current_user(request)
        >>> user.username
        'user@example.com'
    """

    async def get_current_user(self, request: Request) -> User:
        """
        Get currently authenticated user from request.

        Args:
            request: FastAPI Request object containing auth headers/context

        Returns:
            Authenticated User object

        Raises:
            AuthenticationError: If authentication fails
            UserNotFoundError: If user not found in system
        """
        ...

    async def validate_session(self, session_id: str) -> bool:
        """
        Validate if a session is active and valid.

        Args:
            session_id: Session identifier to validate

        Returns:
            True if session is valid and active, False otherwise
        """
        ...
