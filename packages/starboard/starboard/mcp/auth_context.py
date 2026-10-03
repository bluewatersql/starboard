# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Environment-based token authentication provider.

Reads Databricks API tokens from environment variables. Token values
are NEVER included in logs or error messages.
"""

from __future__ import annotations

import os

from starboard.infra.observability.logging import get_logger
from starboard.mcp.config import WorkspaceProfile
from starboard.mcp.exceptions import AuthenticationError
from starboard.mcp.protocols import DatabricksCredentials

logger = get_logger(__name__)


class EnvTokenAuthProvider:
    """Read credentials from environment variables.

    Conforms to the ``MCPAuthProvider`` protocol.
    """

    def get_credentials(self, profile: WorkspaceProfile) -> DatabricksCredentials:
        """Read credentials for the given workspace profile.

        Args:
            profile: Workspace connection profile containing the
                ``token_env`` variable name.

        Returns:
            Resolved ``DatabricksCredentials``.

        Raises:
            AuthenticationError: If the token env var is missing or empty.
        """
        token = os.environ.get(profile.token_env)
        if not token:
            logger.warning(
                "auth_token_missing",
                token_env=profile.token_env,
                host=profile.host,
            )
            raise AuthenticationError(
                f"Environment variable {profile.token_env!r} is not set or empty. "
                f"Cannot authenticate to workspace at {profile.host}.",
                code="AUTH_MISSING_TOKEN",
            )
        return DatabricksCredentials(host=profile.host, token=token)
