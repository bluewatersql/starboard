"""Architecture fitness test — GUIDELINE-006: MCP tool input-schema contract.

Every tool schema defined in ``starboard_server/agents/tools/schemas/``
must declare a ``"parameters"`` key with a non-empty JSON-Schema object
(i.e. ``{"type": "object", "properties": {...}}``).  Missing or empty
``parameters`` blocks mean the MCP layer cannot validate caller payloads.

This test uses AST to scan every schema file, finds all module-level dict
assignments (tool schema constants), and asserts each has a ``"parameters"``
key whose value is a non-empty dict literal.

STATUS: Expected to FAIL if any schema constant is missing a parameters block
or has an empty properties dict.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _dict_has_key(node: ast.Dict, key: str) -> bool:
    """Return True if dict literal *node* has string literal key *key*."""
    return any(isinstance(k, ast.Constant) and k.value == key for k in node.keys)


def _get_dict_value(node: ast.Dict, key: str) -> ast.expr | None:
    """Return the value node for string literal *key* in dict *node*, or None."""
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _find_schema_violations(file_path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, constant_name, reason) for schema dicts missing parameters."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        # Only module-level UPPER_CASE assignments that are dict literals
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            continue
        const_name = targets[0].id
        # Skip non-schema names (lowercase, dunder, etc.)
        if not const_name.isupper():
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        # Must have a "name" key to be a tool schema
        if not _dict_has_key(value, "name"):
            continue

        # Check for "parameters" key
        if not _dict_has_key(value, "parameters"):
            hits.append((node.lineno, const_name, "missing 'parameters' key"))
            continue

        # Check parameters value is a non-empty dict with "properties"
        params_node = _get_dict_value(value, "parameters")
        if isinstance(params_node, ast.Dict):
            if not params_node.keys:
                hits.append((node.lineno, const_name, "'parameters' is an empty dict"))
            elif not _dict_has_key(params_node, "properties"):
                hits.append(
                    (
                        node.lineno,
                        const_name,
                        "'parameters' dict missing 'properties' key",
                    )
                )
            else:
                props_node = _get_dict_value(params_node, "properties")
                if isinstance(props_node, ast.Dict) and not props_node.keys:
                    hits.append(
                        (
                            node.lineno,
                            const_name,
                            "'parameters.properties' is empty",
                        )
                    )
    return hits


@pytest.mark.unit
def test_all_mcp_tool_schemas_have_parameters(project_root: Path) -> None:
    """Every tool schema constant must declare a non-empty parameters/properties block."""
    schemas_root = (
        project_root
        / "packages"
        / "starboard-server"
        / "starboard_server"
        / "agents"
        / "tools"
        / "schemas"
    )
    if not schemas_root.exists():
        pytest.skip(f"Tool schemas directory not found: {schemas_root}")

    violations: list[str] = []
    schema_count = 0
    for py_file in sorted(schemas_root.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        for lineno, const_name, reason in _find_schema_violations(py_file):
            rel = py_file.relative_to(project_root)
            violations.append(f"{rel}:{lineno} {const_name} — {reason}")
            schema_count += 1

    if schema_count == 0 and not violations:
        # Count all uppercase assignments to ensure we scanned something
        total = sum(
            1
            for py_file in schemas_root.rglob("*.py")
            if py_file.name != "__init__.py"
            for _ in py_file.read_text().splitlines()
            if _ and _[0].isupper() and "= {" in _
        )
        if total == 0:
            pytest.fail(
                f"GUIDELINE-006: No tool schema constants found in {schemas_root.relative_to(project_root)}"
            )

    assert not violations, (
        f"GUIDELINE-006: {len(violations)} tool schema(s) with incomplete inputSchema:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
