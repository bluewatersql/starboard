"""Isaac plugin backend for starboard-maint."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

_DEFAULT_ALIAS = "starboard-dev"


def install(plugin_dir: Path, alias: str = _DEFAULT_ALIAS) -> dict[str, Any]:
    """Register and enable the local plugin with Isaac.

    Registers the local ``./plugin`` bundle for Isaac (Claude Code plugin format).
    Returns extra fields to record in maint.json.
    """
    plugin_dir = plugin_dir.resolve()
    if not plugin_dir.is_dir():
        raise FileNotFoundError(f"Plugin directory not found: {plugin_dir}")

    subprocess.run(
        ["isaac", "plugin", "dev", "add", alias, str(plugin_dir)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["isaac", "plugin", "dev", "on", alias],
        check=True,
        capture_output=True,
    )
    return {"plugin_alias": alias, "plugin_dir": str(plugin_dir), "enabled": True}


def remove(alias: str = _DEFAULT_ALIAS) -> None:
    """Remove the Isaac dev plugin entry."""
    subprocess.run(
        ["isaac", "plugin", "dev", "remove", alias],
        check=True,
        capture_output=True,
    )


def verify(alias: str = _DEFAULT_ALIAS) -> tuple[bool, str]:
    """Check that the plugin is registered and enabled in Isaac.

    Returns ``(ok, message)``.
    """
    result = subprocess.run(
        ["isaac", "plugin", "dev", "list"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"'isaac plugin dev list' failed: {result.stderr.strip()}"
    if alias not in result.stdout:
        return False, f"Plugin alias {alias!r} not found in Isaac dev plugin list"
    return True, f"OK: Isaac plugin {alias!r} registered"
