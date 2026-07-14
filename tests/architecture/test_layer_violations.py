# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Architecture fitness test — GUIDELINE-002: Layer boundary violations.

The architectural dependency rule is:

    api -> agents -> domain  (top-down only)

The ``agents`` layer must not import from the ``api`` layer (HTTP models,
request/response schemas).  Doing so creates an upward dependency: the
business-logic layer couples itself to the HTTP transport layer.

This test uses AST to scan every ``.py`` file under
``starboard/agents/`` and fails if any file imports from
``starboard.api``.

STATUS: Expected to FAIL — agents currently import api.models (e.g.
multi_agent_manager.py, history_formatter.py, sse_broadcaster.py).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_FORBIDDEN_PREFIX = "starboard.api"


def _imports_api_layer(file_path: Path) -> list[str]:
    """Return import-statement descriptions for any api-layer imports."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _FORBIDDEN_PREFIX or alias.name.startswith(
                    _FORBIDDEN_PREFIX + "."
                ):
                    violations.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == _FORBIDDEN_PREFIX or module.startswith(
                _FORBIDDEN_PREFIX + "."
            ):
                names = ", ".join(a.name for a in node.names)
                violations.append(f"line {node.lineno}: from {module} import {names}")
    return violations


@pytest.mark.unit
def test_agents_layer_does_not_import_api_layer(project_root: Path) -> None:
    """Files under starboard/agents/ must not import from starboard.api.

    The agents layer is business logic; the api layer is HTTP transport.
    Agents importing api models creates an upward dependency that prevents
    reuse of agents outside the HTTP context (e.g. CLI, SDK, tests).
    """
    agents_root = (
        project_root / "packages" / "starboard" / "starboard" / "agents"
    )
    if not agents_root.exists():
        pytest.skip(f"agents directory not found: {agents_root}")

    all_violations: list[str] = []
    for py_file in sorted(agents_root.rglob("*.py")):
        for v in _imports_api_layer(py_file):
            rel = py_file.relative_to(project_root)
            all_violations.append(f"{rel}: {v}")

    assert not all_violations, (
        f"GUIDELINE-002: {len(all_violations)} upward dependency violation(s) — "
        f"agents/ must not import from api/ layer:\n"
        + "\n".join(f"  - {v}" for v in all_violations)
    )
