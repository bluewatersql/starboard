"""Architecture fitness test — GUIDELINE-001: StateStore Protocol compliance.

All classes whose name ends in ``Store`` must implement a common ``StateStore``
Protocol exposing ``connect()``, ``close()``, ``get()``, ``set()``, and
``delete()``.  The test scans the codebase with AST, collects every ``Store``
class, and verifies that each one defines all five methods.

STATUS: Expected to FAIL until all store implementations are aligned.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest


@runtime_checkable
class StateStore(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def get(self, key: str): ...
    async def set(self, key: str, value: object) -> None: ...
    async def delete(self, key: str) -> None: ...


REQUIRED_METHODS = {"connect", "close", "get", "set", "delete"}


def _collect_store_classes(root: Path) -> list[tuple[Path, str, set[str]]]:
    """Return (file, class_name, defined_methods) for every *Store class."""
    results: list[tuple[Path, str, set[str]]] = []
    for py_file in root.rglob("*.py"):
        if "test_" in py_file.name or py_file.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.endswith("Store"):
                continue
            methods: set[str] = set()
            for item in ast.walk(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(item.name)
            results.append((py_file, node.name, methods))
    return results


@pytest.mark.unit
def test_all_stores_implement_state_store_protocol(project_root: Path) -> None:
    """Every *Store class must define all StateStore protocol methods."""
    packages_root = project_root / "packages"
    if not packages_root.exists():
        pytest.skip("packages directory not found")

    store_classes = _collect_store_classes(packages_root)
    assert store_classes, "No Store classes found — check scan path"

    violations: list[str] = []
    for file_path, class_name, defined_methods in store_classes:
        missing = REQUIRED_METHODS - defined_methods
        if missing:
            rel = file_path.relative_to(project_root)
            violations.append(f"{rel}::{class_name} missing methods: {sorted(missing)}")

    assert not violations, (
        f"GUIDELINE-001: {len(violations)} Store class(es) do not implement the "
        f"full StateStore Protocol ({sorted(REQUIRED_METHODS)}):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
