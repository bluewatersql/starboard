"""Architecture fitness test — GUIDELINE-008: Function length limit.

No function or method in the server package may exceed **80 significant lines**
(i.e. lines that are neither blank nor pure-comment lines).  Long functions are
a proxy for excessive complexity and hidden coupling.

This test uses AST to find every function/method definition, then counts its
significant lines from the raw source.

STATUS: Expected to FAIL because there are known long functions in the codebase.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

MAX_LINES = 80


def _count_significant_lines(source_lines: list[str], start: int, end: int) -> int:
    """Count non-blank, non-comment lines in source_lines[start-1 : end]."""
    count = 0
    for line in source_lines[start - 1 : end]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def _find_long_functions(
    file_path: Path,
    max_lines: int,
) -> list[tuple[int, str, int]]:
    """Return (lineno, qualname, sig_line_count) for functions exceeding max_lines."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    source_lines = source.splitlines()
    results: list[tuple[int, str, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end_line = getattr(node, "end_lineno", None)
        if end_line is None:
            continue
        sig_lines = _count_significant_lines(source_lines, node.lineno, end_line)
        if sig_lines > max_lines:
            results.append((node.lineno, node.name, sig_lines))
    return results


@pytest.mark.unit
def test_no_function_exceeds_max_lines(project_root: Path) -> None:
    """No function/method in starboard_server may exceed 80 significant lines."""
    server_root = (
        project_root
        / "packages"
        / "starboard-server"
        / "starboard_server"
    )
    if not server_root.exists():
        pytest.skip(f"Server package not found: {server_root}")

    violations: list[str] = []
    for py_file in sorted(server_root.rglob("*.py")):
        for lineno, func_name, line_count in _find_long_functions(py_file, MAX_LINES):
            rel = py_file.relative_to(project_root)
            violations.append(
                f"{rel}:{lineno} {func_name}() — {line_count} significant lines"
                f" (limit {MAX_LINES})"
            )

    assert not violations, (
        f"GUIDELINE-008: {len(violations)} function(s) exceed the {MAX_LINES}-line "
        f"limit:\n" + "\n".join(f"  - {v}" for v in violations)
    )
