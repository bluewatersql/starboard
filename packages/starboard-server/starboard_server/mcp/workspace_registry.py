# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Default workspace resolver implementation.

Resolves workspace IDs to ``WorkspaceProfile`` instances using the
static configuration provided at server startup.
"""

from __future__ import annotations

import os

from starboard_server.infra.observability.logging import get_logger

from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.exceptions import ConfigurationError

logger = get_logger(__name__)


class DefaultWorkspaceRegistry:
    """Resolve workspace IDs from ``MCPServerConfig``.

    Conforms to the ``WorkspaceResolver`` protocol.

    Args:
        config: Validated MCP server configuration.

    Raises:
        ConfigurationError: If the default workspace ID is not in workspaces.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        if not config.workspaces:
            raise ConfigurationError(
                "No workspaces configured.",
                code="CONFIG_INVALID_DEFAULT",
            )
        if config.default_workspace_id not in config.workspaces:
            raise ConfigurationError(
                f"Default workspace {config.default_workspace_id!r} "
                f"not found in workspaces: {list(config.workspaces.keys())}.",
                code="CONFIG_INVALID_DEFAULT",
            )
        self._config = config

    def resolve(self, workspace_id: str | None) -> WorkspaceProfile:
        """Resolve a workspace ID to its profile.

        Args:
            workspace_id: Explicit workspace ID, or ``None`` to use default.

        Returns:
            The resolved ``WorkspaceProfile``.

        Raises:
            ConfigurationError: If the workspace ID is unknown.
        """
        effective_id = workspace_id or self._config.default_workspace_id
        profile = self._config.workspaces.get(effective_id)
        if profile is None:
            raise ConfigurationError(
                f"Unknown workspace: {effective_id!r}. "
                f"Available: {list(self._config.workspaces.keys())}.",
                code="CONFIG_UNKNOWN_WORKSPACE",
            )
        return profile

    def list_workspaces(self) -> list[str]:
        """List all configured workspace IDs.

        Returns:
            Sorted list of workspace identifiers.
        """
        return sorted(self._config.workspaces.keys())

    def validate(self) -> list[str]:
        """Validate configuration and return warnings.

        Checks that all ``token_env`` variables are set in the
        environment. Does not raise — returns warnings for missing vars.

        Returns:
            List of warning messages (empty if all OK).
        """
        warnings: list[str] = []
        for ws_id, profile in self._config.workspaces.items():
            if not os.environ.get(profile.token_env):
                warnings.append(
                    f"Workspace {ws_id!r}: environment variable "
                    f"{profile.token_env!r} is not set."
                )
        if warnings:
            logger.warning(
                "workspace_validation_warnings",
                warning_count=len(warnings),
            )
        return warnings
