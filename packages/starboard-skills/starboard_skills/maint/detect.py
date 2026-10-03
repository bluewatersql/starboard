"""OS and scope detection for starboard-maint."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

OS = Literal["darwin", "linux", "wsl"]
Scope = Literal["user", "project"]

_PROC_VERSION = "/proc/version"


def detect_os() -> OS:
    """Return 'darwin', 'wsl', or 'linux'."""
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        try:
            with open(_PROC_VERSION) as fh:
                content = fh.read().lower()
            if "microsoft" in content or "wsl" in content:
                return "wsl"
        except OSError:
            pass
        return "linux"
    raise RuntimeError(f"Unsupported platform: {sys.platform!r}")  # pragma: no cover


def detect_scope(explicit: str | None = None, cwd: Path | None = None) -> Scope:
    """Return 'user' or 'project'.

    If *explicit* is given it is validated and returned directly.  Otherwise
    auto-detect: project scope when ``.claude`` or ``.isaac`` exists under
    *cwd* (defaults to ``Path.cwd()``).
    """
    if explicit is not None:
        if explicit not in ("user", "project"):
            raise ValueError(f"scope must be 'user' or 'project', got {explicit!r}")
        return explicit  # type: ignore[return-value]
    base = cwd or Path.cwd()
    if (base / ".claude").is_dir() or (base / ".isaac").is_dir():
        return "project"
    return "user"


def install_paths(
    scope: Scope,
    os_name: OS | None = None,
    cwd: Path | None = None,
) -> dict[str, Path]:
    """Return a mapping of logical names to absolute ``Path`` objects.

    Keys:
        ``claude_skills``  — skills install directory
        ``claude_base``    — ``~/.claude`` or ``./.claude``
        ``mcp_config``     — path for the MCP JSON config file
        ``isaac_base``     — ``~/.isaac`` or ``./.isaac``
        ``isaac_rules``    — rules directory under isaac_base
        ``maint_json``     — state file (``~/.starboard/maint.json`` or
                             ``.starboard/maint.json``)
    """
    if os_name is None:
        os_name = detect_os()

    if scope == "project":
        base = cwd or Path.cwd()
        return {
            "claude_skills": base / ".claude" / "skills" / "starboard",
            "claude_base": base / ".claude",
            "mcp_config": base / ".mcp.json",
            "isaac_base": base / ".isaac",
            "isaac_rules": base / ".isaac" / "rules",
            "maint_json": base / ".starboard" / "maint.json",
        }

    home = Path.home()
    return {
        "claude_skills": home / ".claude" / "skills" / "starboard",
        "claude_base": home / ".claude",
        "mcp_config": home / ".claude" / "mcp.json",
        "isaac_base": home / ".isaac",
        "isaac_rules": home / ".isaac" / "rules",
        "maint_json": home / ".starboard" / "maint.json",
    }
