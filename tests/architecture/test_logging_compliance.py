"""Architecture fitness test — GUIDELINE-004: No stdlib logging.

All server-package modules must use ``structlog`` (via the project's
``get_logger`` helper) instead of the Python standard-library ``logging``
module.  This test scans every ``.py`` file under ``starboard_server/`` and
fails if any file contains a bare ``import logging`` or
``from logging import ...`` statement.

The logging infrastructure module itself (``infra/observability/logging.py``)
is excluded because it is the bridge that configures stdlib logging for
structlog interop.  All other modules must use ``get_logger`` instead.

STATUS: Expected to PASS after logging migration is complete.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Files that are legitimately allowed to import stdlib logging because they
# configure or bridge it (the shim/setup layer itself).
_STDLIB_LOGGING_ALLOWLIST = frozenset(
    [
        # The logging setup bridge — configures stdlib logging for structlog interop.
        "infra/observability/logging.py",
        # The tracing bridge — uses logging.Filter/LogRecord to inject trace context
        # into stdlib log records for OpenTelemetry integration.
        "infra/observability/tracing.py",
    ]
)


def _has_stdlib_logging_import(file_path: Path) -> list[str]:
    """Return list of stdlib-logging import lines found in *file_path*."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Match exactly "logging" or "logging.something"
                if alias.name == "logging" or alias.name.startswith("logging."):
                    hits.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "logging" or module.startswith("logging."):
                names = ", ".join(a.name for a in node.names)
                hits.append(f"line {node.lineno}: from {module} import {names}")
    return hits


@pytest.mark.unit
def test_no_stdlib_logging_in_server_package(project_root: Path) -> None:
    """starboard_server must not use stdlib logging — use structlog instead."""
    server_root = (
        project_root
        / "packages"
        / "starboard-server"
        / "starboard_server"
    )
    if not server_root.exists():
        pytest.skip(f"server package not found: {server_root}")

    violations: list[str] = []
    for py_file in sorted(server_root.rglob("*.py")):
        # Skip allowlisted infrastructure files
        rel_to_server = py_file.relative_to(server_root).as_posix()
        if rel_to_server in _STDLIB_LOGGING_ALLOWLIST:
            continue

        hits = _has_stdlib_logging_import(py_file)
        for hit in hits:
            rel = py_file.relative_to(project_root)
            violations.append(f"{rel}: {hit}")

    assert not violations, (
        f"GUIDELINE-004: {len(violations)} stdlib logging import(s) found in "
        f"starboard_server — replace with structlog / get_logger:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
