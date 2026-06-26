# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Architecture fitness test — GUIDELINE-007: No ``Any`` in SDK public API.

Public function and method signatures in ``starboard_sdk`` must not use
``typing.Any`` as a parameter or return annotation.  ``Any`` erases type
safety for downstream consumers.  This test scans ``starboard_sdk`` source
files with AST and fails if any public (non-underscore-prefixed) function or
method has an annotation node that resolves to ``Any``.

STATUS: Expected to FAIL because the SDK client currently uses ``Any``
annotations (e.g. ``manager: Any``, ``list[Any]``, ``tuple[Any, ...]``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _annotation_contains_any(node: ast.expr | None) -> bool:
    """Return True if an annotation AST node references ``Any``."""
    if node is None:
        return False
    if isinstance(node, ast.Name) and node.id == "Any":
        return True
    if isinstance(node, ast.Attribute) and node.attr == "Any":
        return True
    # Recurse into subscripts: list[Any], dict[str, Any], Optional[Any], …
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, ast.Name) and child.id == "Any":
            return True
        if isinstance(child, ast.Attribute) and child.attr == "Any":
            return True
    return False


def _find_any_in_public_signatures(
    file_path: Path,
) -> list[tuple[int, str, str]]:
    """Return (lineno, func_name, description) for each Any-annotated public sig."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        # Skip private/dunder
        if node.name.startswith("_"):
            continue
        args = node.args
        all_args = (
            args.posonlyargs
            + args.args
            + args.kwonlyargs
            + ([args.vararg] if args.vararg else [])
            + ([args.kwarg] if args.kwarg else [])
        )
        for arg in all_args:
            if arg.arg == "self":
                continue
            if _annotation_contains_any(arg.annotation):
                hits.append(
                    (node.lineno, node.name, f"param '{arg.arg}' annotated Any")
                )
        if _annotation_contains_any(node.returns):
            hits.append((node.lineno, node.name, "return type annotated Any"))
    return hits


@pytest.mark.unit
def test_sdk_public_api_has_no_any_annotations(project_root: Path) -> None:
    """Public SDK functions must not use Any in their signatures."""
    sdk_dir = project_root / "packages" / "starboard-sdk" / "starboard_sdk"
    if not sdk_dir.exists():
        pytest.skip(f"SDK package not found: {sdk_dir}")

    violations: list[str] = []
    for py_file in sorted(sdk_dir.rglob("*.py")):
        for lineno, func_name, desc in _find_any_in_public_signatures(py_file):
            rel = py_file.relative_to(project_root)
            violations.append(f"{rel}:{lineno} {func_name}() — {desc}")

    assert not violations, (
        f"GUIDELINE-007: {len(violations)} Any annotation(s) in SDK public API:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
