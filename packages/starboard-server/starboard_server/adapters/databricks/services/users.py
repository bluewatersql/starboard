"""Async Users service implementation.

This module provides async user operations for Databricks authentication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.exceptions import DatabricksAPIError
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = get_logger(__name__)

class UsersService(BaseService):
    """Async service for Databricks user operations.

    Provides async user authentication and lookup:
    - Get current authenticated user
    - User identity information

    Example:
        >>> service = UsersService(workspace_client)
        >>> user = await service.get_current_user()
        >>> print(user["userName"])
        'user@example.com'
    """

    def __init__(self, client: WorkspaceClient) -> None:
        """Initialize Users service.

        Args:
            client: Authenticated Databricks WorkspaceClient
        """
        super().__init__(client)

    async def get_current_user(self) -> dict[str, Any] | None:
        """Get the current authenticated user.

        Returns:
            User information dictionary or None if not found

        Example:
            >>> user = await service.get_current_user()
            >>> user["userName"]
            'user@example.com'
        """
        try:

            def _get_user() -> dict[str, Any] | None:
                user = self._client.current_user.me()
                if user:
                    return user.as_dict()
                return None

            return await self._run_sync(_get_user)
        except (DatabricksAPIError, OSError) as e:
            logger.error("get_current_user_failed", error=str(e))
            return None
