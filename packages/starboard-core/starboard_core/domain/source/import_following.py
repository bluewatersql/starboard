# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure functions for extracting and resolving Python import statements.

Stdlib-only (ast + posixpath).  No I/O, no SDK imports.
"""

from __future__ import annotations

import ast
import posixpath
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ImportRef:
    """Represents a single Python import statement.

    Attributes:
        module: Dotted module name (e.g. ``"pkg.sub"``).  Empty string only
                for bare-dot relative imports (``from . import x``).
        level:  0 = absolute import; N = number of leading dots in relative import.
        names:  Names imported via ``from mod import a, b``; empty tuple for
                plain ``import x`` statements.
    """

    module: str
    level: int
    names: tuple[str, ...]


def extract_imports(source: str) -> list[ImportRef]:
    """Extract all import references from Python source.

    Uses ``ast.walk`` so imports inside functions and classes are captured.
    On ``SyntaxError`` returns an empty list (never raises).

    Args:
        source: Python source code string.

    Returns:
        List of :class:`ImportRef` in ascending ``lineno`` order.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    refs: list[tuple[int, ImportRef]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.append((node.lineno, ImportRef(alias.name, 0, ())))
        elif isinstance(node, ast.ImportFrom):
            refs.append((
                node.lineno,
                ImportRef(
                    node.module or "",
                    node.level,
                    tuple(a.name for a in node.names),
                ),
            ))

    refs.sort(key=lambda x: x[0])
    return [r for _, r in refs]


def resolve_candidates(
    ref: ImportRef,
    current_file_path: str,
    roots: Sequence[str],
) -> list[str]:
    """Resolve an ImportRef to an ordered list of candidate workspace ``.py`` paths.

    Pure (``posixpath`` only).  No I/O.  Most-specific candidates first.

    For **absolute** imports (``level == 0``): for each root *R* (in order),
    emits per-name submodule candidates first (``R/<parts>/<name>.py``,
    ``R/<parts>/<name>/__init__.py``), then the module itself
    (``R/<parts>.py``, ``R/<parts>/__init__.py``).

    For **relative** imports (``level > 0``): computes *base* as
    ``dirname(current_file_path)`` going up ``level - 1`` additional directories,
    optionally extended by the module path.  Emits per-name candidates first,
    then the package itself (when ``module`` is non-empty).  Relative candidates
    do not use *roots*.

    All returned paths are ``posixpath.normpath``-normalised; duplicates are
    suppressed (first occurrence wins).

    Args:
        ref:               Import reference to resolve.
        current_file_path: Absolute workspace path of the file containing the import.
        roots:             Ordered workspace root paths for absolute-import probing.

    Returns:
        Ordered, deduplicated list of candidate ``.py`` workspace paths.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(path: str) -> None:
        normed = posixpath.normpath(path)
        if normed not in seen:
            seen.add(normed)
            result.append(normed)

    if ref.level == 0:
        # Absolute import — probe under every root
        parts = ref.module.split(".")
        parts_path = posixpath.join(*parts)

        for root in roots:
            # Per-name candidates (submodule resolution — most specific)
            for name in ref.names:
                _add(posixpath.join(root, parts_path, name + ".py"))
                _add(posixpath.join(root, parts_path, name, "__init__.py"))
            # Module itself
            _add(posixpath.join(root, parts_path + ".py"))
            _add(posixpath.join(root, parts_path, "__init__.py"))
    else:
        # Relative import — resolve against current file's directory
        base = posixpath.dirname(current_file_path)
        for _ in range(ref.level - 1):
            base = posixpath.dirname(base)

        # Extend base by module path when a module is specified
        if ref.module:
            parts = ref.module.split(".")
            base = posixpath.join(base, *parts)

        # Per-name candidates
        if ref.names:
            for name in ref.names:
                _add(posixpath.join(base, name + ".py"))
                _add(posixpath.join(base, name, "__init__.py"))

        # Package itself — only when a module path was specified
        if ref.module:
            _add(base + ".py")
            _add(posixpath.join(base, "__init__.py"))

    return result
