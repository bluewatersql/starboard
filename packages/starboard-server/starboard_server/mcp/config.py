# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""MCP server configuration models and loading logic.

Configuration priority (highest to lowest):
1. ``--config`` CLI flag (path to JSON file)
2. ``STARBOARD_MCP_CONFIG`` env var (JSON string)
3. ``~/.starboard/config.json`` user config file
4. Fallback: ``DATABRICKS_HOST`` + ``DATABRICKS_TOKEN`` → single workspace ``"default"``
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, model_validator

from starboard_server.mcp.exceptions import ConfigurationError


class CostAttribution(BaseModel):
    """Cost attribution metadata for a workspace.

    Attributes:
        tenant_id: Tenant identifier for multi-tenant attribution.
        user_id: User identifier.
        team: Team name.
        environment: Environment label (production/staging/dev).
    """

    model_config = ConfigDict(frozen=True)

    tenant_id: str | None = None
    user_id: str | None = None
    team: str | None = None
    environment: str | None = None


class WorkspaceProfile(BaseModel):
    """Connection profile for a single Databricks workspace.

    Attributes:
        host: Databricks workspace URL (must be a valid URL).
        token_env: Name of the environment variable holding the API token.
        warehouse_id: Optional default SQL warehouse ID.
        default_catalog: Optional default Unity Catalog name.
        default_schema: Optional default schema name.
        token_budget: Per-workspace token budget (overrides server default).
        cost_attribution: Optional cost attribution metadata.
    """

    model_config = ConfigDict(frozen=True)

    host: str
    token_env: str
    warehouse_id: str | None = None
    default_catalog: str | None = None
    default_schema: str | None = None
    token_budget: int | None = None
    cost_attribution: CostAttribution | None = None

    @model_validator(mode="after")
    def _validate_host_url(self) -> WorkspaceProfile:
        """Validate that host is a valid URL."""
        parsed = urlparse(self.host)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(
                f"Invalid workspace host URL: {self.host!r}. "
                f"Must include scheme and netloc (e.g. https://my-workspace.cloud.databricks.com)."
            )
        return self


class MCPServerConfig(BaseModel):
    """Top-level MCP server configuration.

    Attributes:
        default_workspace_id: Key into ``workspaces`` used when callers
            omit ``workspace_id``.
        workspaces: Mapping of workspace ID → connection profile.
        rate_limit_per_minute: Maximum MCP calls per minute per session.
        max_response_size_bytes: Truncation threshold for tool responses.
        safe_mode: When ``True``, only offline tools are exposed.
        tool_scope: Tool exposure scope — ``"phase_a"`` (quick-lookup only),
            ``"phase_b"`` (adds deep-analysis and discovery tools), or
            ``"full"`` (all non-internal tools).
        schema_version: Configuration schema version for forward compat.
        agent_timeout: Default timeout in seconds for agent executions.
    """

    model_config = ConfigDict(frozen=True)

    default_workspace_id: str
    workspaces: dict[str, WorkspaceProfile]
    rate_limit_per_minute: int = 60
    max_response_size_bytes: int = 32_768
    safe_mode: bool = False
    tool_scope: Literal["phase_a", "phase_b", "full"] = "phase_b"
    schema_version: str = "1.0.0"
    agent_timeout: int = 900
    token_budget: int | None = None

    @model_validator(mode="after")
    def _validate_config(self) -> MCPServerConfig:
        """Validate cross-field constraints."""
        if not self.workspaces:
            raise ValueError("At least one workspace must be configured.")
        if self.default_workspace_id not in self.workspaces:
            raise ValueError(
                f"default_workspace_id {self.default_workspace_id!r} "
                f"not found in workspaces: {list(self.workspaces.keys())}."
            )
        return self


def load_mcp_config(
    config_path: str | Path | None = None,
) -> MCPServerConfig | None:
    """Load MCP configuration from available sources.

    Args:
        config_path: Explicit path to a JSON config file (highest priority).

    Returns:
        Parsed ``MCPServerConfig``, or ``None`` if no MCP configuration
        is available (MCP should not be mounted).

    Raises:
        ConfigurationError: If configuration is present but invalid.
    """
    raw: dict[str, Any] | None = None

    # Priority 1: Explicit config file
    if config_path is not None:
        path = Path(config_path)
        if not path.is_file():
            raise ConfigurationError(f"Config file not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigurationError(
                f"Failed to read config file {path}: {exc}"
            ) from exc

    # Priority 2: Environment variable (JSON string)
    if raw is None:
        env_json = os.environ.get("STARBOARD_MCP_CONFIG")
        if env_json:
            try:
                raw = json.loads(env_json)
            except json.JSONDecodeError as exc:
                raise ConfigurationError(
                    f"Invalid JSON in STARBOARD_MCP_CONFIG: {exc}"
                ) from exc

    # Priority 3: User config file (~/.starboard/config.json)
    if raw is None:
        user_config_path = Path.home() / ".starboard" / "config.json"
        if user_config_path.is_file():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                raw = json.loads(user_config_path.read_text(encoding="utf-8"))

    # Priority 4: Fallback from DATABRICKS_HOST + DATABRICKS_TOKEN
    if raw is None:
        host = os.environ.get("DATABRICKS_HOST")
        token_env = "DATABRICKS_TOKEN"
        if host and os.environ.get(token_env):
            raw = {
                "default_workspace_id": "default",
                "workspaces": {
                    "default": {
                        "host": host,
                        "token_env": token_env,
                    }
                },
            }

    if raw is None:
        return None

    try:
        return MCPServerConfig.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - MCP error boundary
        raise ConfigurationError(f"Invalid MCP server configuration: {exc}") from exc
