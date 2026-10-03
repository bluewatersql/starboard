# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Databricks authentication provider.

Implements transparent Databricks platform authentication by extracting
user identity from the Databricks API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request
from starboard_core.domain.models.auth import User

from starboard.domain.auth.exceptions import (
    AuthenticationError,
    UserNotFoundError,
)
from starboard.domain.repositories.user_repository import UserRepository
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.adapters.databricks import AsyncDatabricksClient

logger = get_logger(__name__)


class DatabricksAuthProvider:
    """
    Databricks platform authentication provider.

    Leverages Databricks workspace authentication to identify users.
    Users are automatically provisioned on first access (find_or_create pattern).

    This provider implements the AuthenticationService protocol.
    """

    def __init__(
        self,
        databricks_api: AsyncDatabricksClient,
        user_repository: UserRepository,
    ) -> None:
        """
        Initialize Databricks auth provider.

        Args:
            databricks_api: Async Databricks client for user lookups
            user_repository: Repository for user persistence
        """
        self.databricks = databricks_api
        self.users = user_repository

    async def get_current_user(self, request: Request) -> User:  # noqa: ARG002
        """
        Extract user from Databricks API and auto-provision if needed.

        Flow:
        1. Call Databricks API current_user.me()
        2. Extract user ID, name, username (email)
        3. Find or create user in our database
        4. Update last_login timestamp
        5. Return User object

        Args:
            request: FastAPI Request (not used for Databricks, auth is platform-level)

        Returns:
            Authenticated User object

        Raises:
            AuthenticationError: If Databricks authentication fails
            UserNotFoundError: If user data is invalid

        Examples:
            >>> provider = DatabricksAuthProvider(databricks_api, user_repo)
            >>> user = await provider.get_current_user(request)
            >>> user.username
            'user@company.com'
        """
        try:
            # Get user from Databricks API (async)
            db_user = await self.databricks.users.get_current_user()

            if not db_user:
                raise AuthenticationError(
                    "No authenticated Databricks user found",
                    provider="databricks",
                )

            # Extract user data
            # Note: as_dict() returns camelCase keys, not snake_case
            external_id = db_user.get("id")
            username = db_user.get("userName")  # Email (camelCase from SDK)
            display_name = db_user.get("displayName") or username

            if not external_id or not username:
                raise AuthenticationError(
                    "Invalid user data from Databricks API",
                    provider="databricks",
                    details={"user_data_keys": list(db_user.keys())},
                )

            # Find or create user in our system (auto-provisioning)
            user = await self.users.find_or_create(
                external_id=str(external_id),
                username=username,
                display_name=display_name,  # type: ignore[arg-type]
                provider="databricks",
                metadata=db_user,
            )

            # Update last login
            await self.users.track_login(user.id)

            logger.debug(
                "databricks_auth_success",
                user_id=user.id,
                username=user.username,
                external_id=external_id,
            )

            return user

        except (AuthenticationError, UserNotFoundError):
            # Re-raise auth-specific errors
            raise
        except Exception as e:  # noqa: BLE001 - auth provider boundary
            logger.error(
                "databricks_auth_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise AuthenticationError(
                "Failed to authenticate with Databricks",
                provider="databricks",
                details={"original_error": str(e)},
            ) from e

    async def validate_session(self, session_id: str) -> bool:  # noqa: ARG002
        """
        Validate session — always returns True for Databricks platform auth.

        Design Decision (ADR-001):
            Databricks Apps run inside the Databricks workspace and inherit the
            platform's own session management. Every inbound HTTP request has
            already been authenticated by the Databricks reverse proxy before it
            reaches this application. Re-validating the session here would be
            redundant and would require storing session state that the platform
            already manages.

            Therefore this method is intentionally a no-op that returns True.
            If the application is ever deployed outside the Databricks platform,
            this method MUST be replaced with real session validation.

        See Also:
            changes/fix/phase-01-security-hardening/ADR-001-databricks-auth-session-validation.md

        Args:
            session_id: Session identifier (unused — platform manages sessions)

        Returns:
            Always True for Databricks platform auth
        """
        return True
