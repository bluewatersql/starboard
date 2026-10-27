# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure functions for extracting and resolving Databricks notebook %run directives.

Stdlib-only (re + posixpath).  No I/O, no SDK imports.
"""

from __future__ import annotations

import posixpath
import re

# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------
# Matches per line:
#   - optional leading whitespace
#   - optional Databricks magic-comment prefix  (# / -- / //) + MAGIC + space
#   - %run keyword + at least one space
#   - first whitespace-delimited token = the target (may be quoted)
#
# Examples matched:
#   %run ./setup
#   # MAGIC %run /Shared/utils
#   -- MAGIC %run "./helpers"
#   // MAGIC %run '../common'  $key=value
#   %run ./path $arg=1         (trailing args ignored)

_RUN_RE = re.compile(
    r"^\s*"                         # optional leading whitespace
    r"(?:(?:#|--|//)\s+MAGIC\s+)?"  # optional magic-comment prefix
    r"%run\s+"                      # %run keyword + whitespace
    r"(\"[^\"]*\"|'[^']*'|\S+)"     # quoted string (with spaces) OR bare token
)


def _strip_quotes(token: str) -> str:
    """Strip surrounding single or double quotes from a token."""
    if len(token) >= 2 and (
        (token[0] == '"' and token[-1] == '"')
        or (token[0] == "'" and token[-1] == "'")
    ):
        return token[1:-1]
    return token


def extract_run_targets(notebook_source: str) -> list[str]:
    """Return workspace targets referenced by ``%run`` directives in order.

    Scans exported-notebook source text line by line.  Handles bare
    ``%run`` and the Databricks cell-magic comment prefixes (Python ``#``,
    SQL ``--``, Scala ``//``).

    The target is the first whitespace-delimited token after ``%run``;
    surrounding quotes are stripped.  Trailing arguments (e.g.
    ``$env=prod``) are ignored.

    Does **not** deduplicate — the caller's visited-set handles cycles.

    Args:
        notebook_source: Raw exported notebook source text.

    Returns:
        List of target path strings in document order.  Empty list if none.
    """
    targets: list[str] = []
    for line in notebook_source.splitlines():
        m = _RUN_RE.match(line)
        if m:
            targets.append(_strip_quotes(m.group(1)))
    return targets


def resolve_run_path(current_notebook_path: str, target: str) -> str:
    """Resolve a ``%run`` target to an absolute workspace path.

    Pure workspace-path resolution using ``posixpath`` only.  No I/O.

    Rules:
    - Strips surrounding quotes from *target* first.
    - If target starts with ``/``: treat as absolute; normalise and return.
    - Otherwise: join ``dirname(current_notebook_path)`` with target, then
      normalise (resolves ``./`` and ``../``).
    - Workspace notebook paths carry **no** file extension; none is added.

    Args:
        current_notebook_path: Absolute workspace path of the calling notebook.
        target: Raw target string from a ``%run`` directive.

    Returns:
        Normalised absolute workspace path string.
    """
    target = _strip_quotes(target)
    if target.startswith("/"):
        return posixpath.normpath(target)
    base_dir = posixpath.dirname(current_notebook_path)
    return posixpath.normpath(posixpath.join(base_dir, target))
