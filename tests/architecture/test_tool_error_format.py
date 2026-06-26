# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Architecture fitness test — GUIDELINE-003: Uniform tool error format.

Every tool adapter that returns an error dict must use the standard shape::

    {"error": str, "error_code": str, "details": dict | None}

This test uses AST to find dict-literal returns inside tool adapter files
that contain an ``"error"`` key, then checks whether ``"error_code"`` is also
present.  Missing ``error_code`` keys are reported as violations.

STATUS: Expected to FAIL because tool adapters use inconsistent error shapes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REQUIRED_ERROR_KEYS = {"error", "error_code"}


def _dict_keys(node: ast.Dict) -> set[str]:
    """Return string literal keys of a dict node."""
    keys: set[str] = set()
    for k in node.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
    return keys


def _find_error_returns(file_path: Path) -> list[tuple[int, set[str]]]:
    """Return (line, keys) for every dict-return that has an 'error' key."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    hits: list[tuple[int, set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return):
            continue
        val = node.value
        if isinstance(val, ast.Dict):
            keys = _dict_keys(val)
            if "error" in keys:
                hits.append((node.lineno, keys))
    return hits


@pytest.mark.unit
def test_tool_adapters_use_standard_error_format(project_root: Path) -> None:
    """Tool adapters must return error dicts with both 'error' and 'error_code'."""
    adapters_root = (
        project_root
        / "packages"
        / "starboard-server"
        / "starboard_server"
        / "tools"
        / "adapters"
    )
    if not adapters_root.exists():
        pytest.skip(f"tools/adapters directory not found: {adapters_root}")

    violations: list[str] = []
    for py_file in sorted(adapters_root.rglob("*.py")):
        for lineno, keys in _find_error_returns(py_file):
            missing = REQUIRED_ERROR_KEYS - keys
            if missing:
                rel = py_file.relative_to(project_root)
                violations.append(
                    f"{rel}:{lineno}: error dict missing keys {sorted(missing)} "
                    f"(found: {sorted(keys)})"
                )

    assert not violations, (
        f"GUIDELINE-003: {len(violations)} tool adapter error return(s) lack "
        f"required keys {sorted(REQUIRED_ERROR_KEYS)}:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
