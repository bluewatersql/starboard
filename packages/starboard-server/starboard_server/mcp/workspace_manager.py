# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Interactive workspace profile manager for ~/.starboard/.

Provides CLI-driven management of Databricks workspace profiles
without exposing credentials to AI assistants. Writes:

- ``~/.starboard/config.json`` — MCPServerConfig (token_env refs, no secrets)
- ``~/.starboard/.env`` — actual token values (gitignored, never read by Claude)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STARBOARD_DIR = Path.home() / ".starboard"
CONFIG_PATH = STARBOARD_DIR / "config.json"
ENV_PATH = STARBOARD_DIR / ".env"


def _ensure_dir() -> None:
    STARBOARD_DIR.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.is_file():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"default_workspace_id": "", "workspaces": {}}


def _save_config(config: dict[str, Any]) -> None:
    _ensure_dir()
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _load_env_vars() -> dict[str, str]:
    """Parse ~/.starboard/.env into a dict (KEY=VALUE lines)."""
    result: dict[str, str] = {}
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip().strip("\"'")
    return result


def _save_env_vars(env_vars: dict[str, str]) -> None:
    _ensure_dir()
    lines = [
        "# Starboard workspace credentials (auto-generated)",
        "# Do NOT commit this file or share it with AI assistants.",
        "",
    ]
    for key, value in sorted(env_vars.items()):
        lines.append(f"{key}={value}")
    lines.append("")
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)


def _token_env_name(workspace_id: str) -> str:
    return f"STARBOARD_TOKEN_{workspace_id.upper().replace('-', '_')}"


def add_workspace(
    workspace_id: str,
    host: str,
    token: str,
    *,
    set_default: bool = False,
    warehouse_id: str | None = None,
    default_catalog: str | None = None,
) -> None:
    """Add or update a workspace profile.

    Args:
        workspace_id: Short identifier (e.g. "production", "staging").
        host: Databricks workspace URL.
        token: Databricks personal access token.
        set_default: Whether to make this the default workspace.
        warehouse_id: Optional default SQL warehouse ID.
        default_catalog: Optional default Unity Catalog name.
    """
    if not host.startswith("https://"):
        host = f"https://{host}"

    config = _load_config()
    env_vars = _load_env_vars()

    token_env = _token_env_name(workspace_id)

    profile: dict[str, Any] = {
        "host": host,
        "token_env": token_env,
    }
    if warehouse_id:
        profile["warehouse_id"] = warehouse_id
    if default_catalog:
        profile["default_catalog"] = default_catalog

    config["workspaces"][workspace_id] = profile

    if set_default or not config.get("default_workspace_id"):
        config["default_workspace_id"] = workspace_id

    env_vars[token_env] = token

    _save_config(config)
    _save_env_vars(env_vars)


def remove_workspace(workspace_id: str) -> bool:
    """Remove a workspace profile. Returns True if it existed."""
    config = _load_config()
    env_vars = _load_env_vars()

    if workspace_id not in config.get("workspaces", {}):
        return False

    token_env = config["workspaces"][workspace_id].get("token_env", "")
    del config["workspaces"][workspace_id]
    env_vars.pop(token_env, None)

    if config.get("default_workspace_id") == workspace_id:
        remaining = list(config.get("workspaces", {}).keys())
        config["default_workspace_id"] = remaining[0] if remaining else ""

    _save_config(config)
    _save_env_vars(env_vars)
    return True


def list_workspaces() -> list[dict[str, Any]]:
    """List configured workspaces (no token values)."""
    config = _load_config()
    default_id = config.get("default_workspace_id", "")
    result: list[dict[str, Any]] = []
    for ws_id, profile in config.get("workspaces", {}).items():
        token_env = profile.get("token_env", "")
        has_token = bool(os.environ.get(token_env) or _load_env_vars().get(token_env))
        result.append(
            {
                "workspace_id": ws_id,
                "host": profile.get("host", ""),
                "is_default": ws_id == default_id,
                "warehouse_id": profile.get("warehouse_id"),
                "default_catalog": profile.get("default_catalog"),
                "token_configured": has_token,
            }
        )
    return result


def set_default(workspace_id: str) -> bool:
    """Set the default workspace. Returns True if workspace exists."""
    config = _load_config()
    if workspace_id not in config.get("workspaces", {}):
        return False
    config["default_workspace_id"] = workspace_id
    _save_config(config)
    return True
