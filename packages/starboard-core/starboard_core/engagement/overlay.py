# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Internal-overlay detection for the engagement storage policy.

The overlay marks a Databricks-operated install. When it is enabled, direct
customer-workspace collection must go to Drive, never to local disk (design root
invariant). The signal therefore fails **closed**: the overlay counts as enabled
when *either* the gated internal package is importable *or* the overlay skill is
installed in a known host skill location, and also when the skill scan itself
errors. An environment variable may force it on; nothing can force it off. The
default scan covers both ``$HOME`` and the account's home directory from the
password database, so redirecting ``HOME`` cannot hide an installed skill.

The copy the host loaded is preferred over any plugin cache, so a stale snapshot
of another host never names the overlay: ``STARBOARD_OVERLAY_DIR`` (the overlay
skill dir), then ``$CLAUDE_PLUGIN_ROOT/skills/<skill>``, then the enabled plugin
paths of the dev-mode file ``~/.config/llm-cli/plugin-dev-mode.json`` (read only),
then the direct skill roots, then the plugin caches (``.claude`` before ``.codex``).

This module uses only the standard library and never imports the internal
package (``importlib.util.find_spec`` locates without executing), so the
"public packages import no internal package" contract stays kept.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

INTERNAL_PACKAGE = "starboard_internal"
OVERLAY_SKILL_NAME = "starboard-internal-overlay"
FORCE_ENV = "STARBOARD_OVERLAY"
#: An explicit overlay skill directory (the one holding ``SKILL.md``); checked first.
OVERLAY_DIR_ENV = "STARBOARD_OVERLAY_DIR"
#: The plugin root a Claude Code host exports to the plugin it runs.
PLUGIN_ROOT_ENV = "CLAUDE_PLUGIN_ROOT"
#: The dev-mode plugin file (``{"plugins": {name: {"path", "enabled"}}}``), home-relative.
_DEV_MODE_FILE = ".config/llm-cli/plugin-dev-mode.json"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Host skill locations, relative to the home directory. Plugin caches nest the
# skill a few levels down (<cache>/<marketplace>/<plugin>/<version>/skills/<name>).
_DIRECT_ROOTS = (
    ".claude/skills",
    ".codex/skills",
    ".config/opencode/skills",
    ".agents/skills",
)
_PLUGIN_ROOTS = (
    ".claude/plugins",
    ".codex/plugins",
)
_PLUGIN_MAX_DEPTH = 6


@dataclass(frozen=True)
class OverlaySignal:
    """Result of overlay detection.

    Attributes:
        enabled: True when the no-local rule applies to customer-workspace runs.
        reasons: Why it is enabled (``forced_by_env``, ``internal_package``,
            ``overlay_skill:~/<path>``, ``skill_scan_error:<error>``); empty when
            disabled.
    """

    enabled: bool
    reasons: tuple[str, ...] = ()


def internal_package_installed() -> bool:
    """Whether the gated internal package is importable (located, not imported)."""
    try:
        return importlib.util.find_spec(INTERNAL_PACKAGE) is not None
    except (ImportError, ValueError):
        return False


def _walk_for_skill(root: Path, depth: int) -> Iterator[Path]:
    """Yield ``<dir>/skills/<OVERLAY_SKILL_NAME>`` matches under ``root``, bounded."""
    if depth < 0 or not root.is_dir():
        return
    candidate = root / "skills" / OVERLAY_SKILL_NAME
    if (candidate / "SKILL.md").is_file():
        yield candidate
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.is_symlink() and not child.name.startswith("."):
            yield from _walk_for_skill(child, depth - 1)


def _dev_mode_roots(home: Path) -> list[Path]:
    """The enabled plugin paths of the dev-mode file; none when it is absent,
    unreadable or not the expected shape (it is never written)."""
    try:
        raw = json.loads((home / _DEV_MODE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plugins = raw.get("plugins") if isinstance(raw, dict) else None
    if not isinstance(plugins, dict):
        return []
    return [
        Path(entry["path"])
        for entry in plugins.values()
        if isinstance(entry, dict)
        and entry.get("enabled") is True
        and isinstance(entry.get("path"), str)
        and Path(entry["path"]).is_absolute()
    ]


def _loaded_skill(home: Path, env: Mapping[str, str]) -> Path | None:
    """The overlay skill copy the host loaded (env pin, plugin root, dev mode)."""
    candidates: list[Path] = []
    if pinned := env.get(OVERLAY_DIR_ENV, "").strip():
        candidates.append(Path(pinned))
    roots = [Path(r)] if (r := env.get(PLUGIN_ROOT_ENV, "").strip()) else []
    roots.extend(_dev_mode_roots(home))
    candidates.extend(root / "skills" / OVERLAY_SKILL_NAME for root in roots)
    for candidate in candidates:
        if candidate.is_absolute() and (candidate / "SKILL.md").is_file():
            return candidate
    return None


def find_overlay_skill(home: Path, env: Mapping[str, str] | None = None) -> Path | None:
    """Return the overlay skill directory for ``home``, if any: the copy the host
    loaded first (see the module docstring), then the first installed one.

    Args:
        home: Home directory to scan.
        env: Environment mapping (default: ``os.environ``).

    Raises:
        OSError: when a location exists but cannot be scanned; callers treat
            that as "enabled" (fail closed).
    """
    loaded = _loaded_skill(home, os.environ if env is None else env)
    if loaded is not None:
        return loaded
    for rel in _DIRECT_ROOTS:
        candidate = home / rel / OVERLAY_SKILL_NAME
        if (candidate / "SKILL.md").is_file():
            return candidate
    for rel in _PLUGIN_ROOTS:
        for match in _walk_for_skill(home / rel, _PLUGIN_MAX_DEPTH):
            return match
    return None


def _account_home() -> Path | None:
    """The OS account's home directory, independent of ``$HOME`` (POSIX only)."""
    try:
        import pwd
    except ImportError:  # pragma: no cover - non-POSIX
        return None
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        return None


def _default_homes() -> list[Path]:
    homes: list[Path] = []
    for home in (_account_home(), Path.home()):
        if home is not None and home not in homes:
            homes.append(home)
    return homes


def _display(skill: Path, homes: list[Path]) -> str:
    """``~/``-relative path, so the recorded reason names no account."""
    for home in homes:
        if skill.is_relative_to(home):
            return f"~/{skill.relative_to(home)}"
    return str(skill)


def detect_overlay(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    package_installed: Callable[[], bool] = internal_package_installed,
) -> OverlaySignal:
    """Detect whether the internal overlay is enabled on this install.

    Args:
        home: Home directory to scan (default: the account's home and ``$HOME``).
        env: Environment mapping (default: ``os.environ``).
        package_installed: Injectable internal-package check, for tests.
    """
    env = os.environ if env is None else env
    reasons: list[str] = []
    if env.get(FORCE_ENV, "").strip().lower() in _TRUTHY:
        reasons.append("forced_by_env")
    if package_installed():
        reasons.append("internal_package")
    try:
        homes = _default_homes() if home is None else [home]
        skill = next(
            (found for h in homes if (found := find_overlay_skill(h, env)) is not None),
            None,
        )
    except (OSError, RuntimeError) as exc:
        reasons.append(f"skill_scan_error:{type(exc).__name__}")
    else:
        if skill is not None:
            reasons.append(f"overlay_skill:{_display(skill, homes)}")
    return OverlaySignal(enabled=bool(reasons), reasons=tuple(reasons))
