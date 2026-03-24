# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Protocol definitions for MCP server extensibility.

These protocols define the contracts that concrete implementations must
satisfy. They enable dependency injection for workspace resolution and
authentication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from starboard_server.mcp.config import WorkspaceProfile


@dataclass(frozen=True)
class DatabricksCredentials:
    """Resolved credentials for a Databricks workspace.

    Attributes:
        host: Workspace URL.
        token: API token value (never log this).
    """

    host: str
    token: str


class WorkspaceResolver(Protocol):
    """Resolve a workspace ID to its connection profile."""

    def resolve(self, workspace_id: str | None) -> WorkspaceProfile:
        """Resolve a workspace ID to its profile.

        Args:
            workspace_id: Explicit workspace ID, or ``None`` to use the
                configured default.

        Returns:
            The resolved ``WorkspaceProfile``.

        Raises:
            ConfigurationError: If the workspace ID is unknown.
        """
        ...

    def list_workspaces(self) -> list[str]:
        """List all configured workspace IDs.

        Returns:
            List of workspace identifier strings.
        """
        ...


class MCPAuthProvider(Protocol):
    """Provide credentials for a Databricks workspace."""

    def get_credentials(self, profile: WorkspaceProfile) -> DatabricksCredentials:
        """Read credentials for the given workspace profile.

        Args:
            profile: Workspace connection profile containing the
                ``token_env`` variable name.

        Returns:
            Resolved ``DatabricksCredentials``.

        Raises:
            AuthenticationError: If credentials cannot be resolved.
        """
        ...
