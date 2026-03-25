"""Architecture fitness test — GUIDELINE-009: Safe prompt construction.

Prompt files must not interpolate runtime/user-supplied variables directly via
f-strings or ``.format()`` calls, as this can enable prompt-injection attacks.
Only constant expressions (string literals, module-level constants defined
within the same file) are acceptable.

This test scans every ``.py`` file under ``starboard_server/prompts/`` and:
  1. Flags f-strings that embed a ``Name`` node (variable reference), which
     indicates runtime interpolation.
  2. Flags ``.format()`` method calls on string literals or names.

Note: f-strings referencing names that resolve to *other constants defined in
the same file* are technically safe, but detecting that requires full
evaluation.  For a conservative fitness gate we fail on any f-string variable
interpolation to force explicit review.

STATUS: Expected to FAIL because prompt modules use f-strings with variable
interpolation (e.g. ``f"... {_HANDOFF_SECTION} ..."``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _fstring_has_variable_interpolation(node: ast.JoinedStr) -> bool:
    """Return True if the f-string contains at least one Name/Attribute expression."""
    for value in ast.walk(node):
        if value is node:
            continue
        if isinstance(value, ast.FormattedValue):
            inner = value.value
            # Any non-constant expression inside {} is a variable reference
            if not isinstance(inner, ast.Constant):
                return True
    return False


def _find_prompt_construction_violations(
    file_path: Path,
) -> list[tuple[int, str]]:
    """Return (lineno, description) for risky prompt-construction patterns."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # f-strings with variable interpolation
        if isinstance(node, ast.JoinedStr):
            if _fstring_has_variable_interpolation(node):
                hits.append((node.lineno, "f-string with variable interpolation"))
        # .format() calls: "...".format(...) or var.format(...)
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "format"
                and node.args  # has positional args, i.e. not an empty .format()
            ):
                hits.append((node.lineno, ".format() call with arguments"))
    return hits


@pytest.mark.unit
def test_prompts_do_not_use_variable_interpolation(project_root: Path) -> None:
    """Prompt files must not use f-strings or .format() with variable interpolation."""
    prompts_root = (
        project_root
        / "packages"
        / "starboard-server"
        / "starboard_server"
        / "prompts"
    )
    if not prompts_root.exists():
        pytest.skip(f"Prompts directory not found: {prompts_root}")

    violations: list[str] = []
    for py_file in sorted(prompts_root.rglob("*.py")):
        for lineno, desc in _find_prompt_construction_violations(py_file):
            rel = py_file.relative_to(project_root)
            violations.append(f"{rel}:{lineno}: {desc}")

    assert not violations, (
        f"GUIDELINE-009: {len(violations)} risky prompt-construction pattern(s) found "
        f"— use only constant concatenation or template strings reviewed for injection:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
