# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Architecture fitness test — GUIDELINE-005: Package boundary enforcement.

``starboard-cli`` must only import from:
  - its own package (``starboard_cli.*``)
  - ``starboard_core.*``  (the shared pure-domain package)
  - the public API of ``starboard_server`` (symbols exported in
    ``starboard_server/__init__.py``)

Importing internal server sub-modules (e.g. ``starboard_server.infra.*``,
``starboard_server.agents.*``) bypasses the public boundary and creates
tight coupling.

STATUS: Expected to FAIL because CLI imports internal server modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Sub-packages that are considered "internal" (not part of public API)
_INTERNAL_PREFIXES = (
    "starboard_server.infra",
    "starboard_server.agents",
    "starboard_server.adapters",
    "starboard_server.tools",
    "starboard_server.domain",
    "starboard_server.repositories",
    "starboard_server.services",
    "starboard_server.prompts",
    "starboard_server.mcp",
    "starboard_server.discovery",
    "starboard_server.config",
)


def _collect_server_internal_imports(
    package_dir: Path,
    own_prefix: str,
) -> list[tuple[Path, int, str]]:
    """Return (file, lineno, import_str) for every internal-server import."""
    results: list[tuple[Path, int, str]] = []
    for py_file in sorted(package_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name.startswith(p) for p in _INTERNAL_PREFIXES):
                        results.append((py_file, node.lineno, f"import {alias.name}"))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(module.startswith(p) for p in _INTERNAL_PREFIXES):
                    results.append((py_file, node.lineno, f"from {module} import ..."))
    return results


@pytest.mark.unit
def test_cli_does_not_import_internal_server_modules(project_root: Path) -> None:
    """starboard_cli must not import internal starboard_server sub-modules."""
    cli_dir = project_root / "packages" / "starboard-cli" / "starboard_cli"
    if not cli_dir.exists():
        pytest.skip(f"CLI package not found: {cli_dir}")

    violations = _collect_server_internal_imports(cli_dir, "starboard_cli")
    formatted = [
        f"{f.relative_to(project_root)}:{ln}: {imp}" for f, ln, imp in violations
    ]
    assert not formatted, (
        f"GUIDELINE-005: {len(formatted)} internal server import(s) in starboard_cli:\n"
        + "\n".join(f"  - {v}" for v in formatted)
    )


