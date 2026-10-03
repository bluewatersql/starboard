"""Prerequisite enforcement for starboard-maint."""
from __future__ import annotations

import shutil
import sys


class PrereqError(RuntimeError):
    """Raised when a required tool or condition is not met."""


# Maps host → list of (label, check_fn, fix_hint) tuples.
_CHECKS: dict[str, list[tuple[str, object, str]]] = {
    "claude-code": [
        (
            "Python >=3.12",
            lambda: sys.version_info >= (3, 12),
            "Install Python 3.12 or later from https://python.org",
        ),
        (
            "starboard-helper on PATH",
            lambda: shutil.which("starboard-helper") is not None,
            "Run: pip install starboard-skills  (or: uv pip install starboard-skills)",
        ),
    ],
    "isaac": [
        (
            "Python >=3.12",
            lambda: sys.version_info >= (3, 12),
            "Install Python 3.12 or later from https://python.org",
        ),
        (
            "isaac CLI on PATH",
            lambda: shutil.which("isaac") is not None,
            "Install Isaac from https://www.isaaclabs.ai/download",
        ),
        (
            "starboard-helper on PATH",
            lambda: shutil.which("starboard-helper") is not None,
            "Run: pip install starboard-skills  (or: uv pip install starboard-skills)",
        ),
    ],
    "codex": [
        (
            "Python >=3.12",
            lambda: sys.version_info >= (3, 12),
            "Install Python 3.12 or later from https://python.org",
        ),
        (
            "starboard-helper on PATH",
            lambda: shutil.which("starboard-helper") is not None,
            "Run: pip install starboard-skills  (or: uv pip install starboard-skills)",
        ),
    ],
    "opencode": [
        # OpenCode has no package channel — instructions only, minimal prereqs.
        (
            "Python >=3.12",
            lambda: sys.version_info >= (3, 12),
            "Install Python 3.12 or later from https://python.org",
        ),
    ],
    "mcp": [
        (
            "starboard-mcp on PATH",
            lambda: shutil.which("starboard-mcp") is not None,
            "Run: pip install starboard  (or: uv pip install starboard)",
        ),
    ],
}


def check(host: str) -> None:
    """Verify all prerequisites for *host*; raise :class:`PrereqError` on failure.

    The error message contains a human-readable fix hint so the user knows
    exactly what to install.
    """
    failures: list[str] = []
    for label, check_fn, hint in _CHECKS.get(host, []):
        try:
            ok = bool(check_fn())  # type: ignore[operator]
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            failures.append(f"  - {label}\n    Fix: {hint}")

    if failures:
        lines = "\n".join(failures)
        raise PrereqError(
            f"Missing prerequisites for host {host!r}:\n{lines}\n"
            f"Resolve the above, then re-run starboard-maint install."
        )
