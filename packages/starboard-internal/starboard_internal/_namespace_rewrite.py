# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure ``system.*`` -> centralized-tables namespace rewrite (Phase-3 D7 / D-3.4).

The fleet-mode internal adapter rewrites single-workspace ``system.<schema>.<table>``
references into their centralized multi-account equivalents at query-build time,
so the **public query packs stay byte-for-byte unchanged** (near-zero pack edits,
D-3.4). This module is the pure, SDK-free rewrite core — internal-index-only, and
the only place the centralized namespace is named.

Rule (paraphrased internal methodology): ``system.{schema}.{table}`` becomes
``main.centralized_system_tables.{schema}_{table}``. Tables with no centralized
equivalent are left untouched and reported in :attr:`NamespaceRewrite.unmapped`
so a caller can flag or drop them rather than silently query a missing table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The centralized multi-account catalog + schema the rewrite targets.
CENTRALIZED_CATALOG = "main"
CENTRALIZED_SCHEMA = "centralized_system_tables"

#: ``system.<schema>.<table>`` references with no centralized equivalent. Left
#: as-is and reported so the caller can decide (omit / stub / flag).
_NO_CENTRALIZED_EQUIVALENT: frozenset[str] = frozenset(
    {
        "system.access.table_lineage",
        "system.access.column_lineage",
    }
)

#: Matches a three-part ``system.<schema>.<table>`` identifier.
_SYSTEM_REF = re.compile(
    r"\bsystem\.([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NamespaceRewrite:
    """Result of rewriting ``system.*`` references in a SQL string.

    Attributes:
        original_sql: The input SQL, unchanged.
        rewritten_sql: The SQL with every mappable ``system.*`` reference rewritten
            to its centralized equivalent (identical to ``original_sql`` when there
            was nothing to rewrite).
        mappings: ``(original_ref, centralized_ref)`` pairs actually rewritten, in
            first-seen order, de-duplicated.
        unmapped: ``system.*`` references left untouched because they have no
            centralized equivalent, in first-seen order, de-duplicated.
    """

    original_sql: str
    rewritten_sql: str
    mappings: tuple[tuple[str, str], ...]
    unmapped: tuple[str, ...]

    @property
    def did_rewrite(self) -> bool:
        """Whether any reference was rewritten."""
        return bool(self.mappings)


def centralized_table(schema: str, table: str) -> str:
    """Return the centralized-tables name for ``system.<schema>.<table>``."""
    return f"{CENTRALIZED_CATALOG}.{CENTRALIZED_SCHEMA}.{schema}_{table}"


def rewrite_system_namespace(sql: str) -> NamespaceRewrite:
    """Rewrite ``system.<schema>.<table>`` references to centralized equivalents.

    Pure and deterministic: the same input always yields the same output; nothing
    is executed. Unmapped references (no centralized equivalent) are preserved and
    reported rather than dropped.
    """
    mappings: list[tuple[str, str]] = []
    unmapped: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        schema = match.group(1)
        table = match.group(2)
        ref = f"system.{schema}.{table}"
        if ref.lower() in _NO_CENTRALIZED_EQUIVALENT:
            unmapped.append(ref)
            return match.group(0)
        target = centralized_table(schema, table)
        mappings.append((ref, target))
        return target

    rewritten = _SYSTEM_REF.sub(_replace, sql)
    return NamespaceRewrite(
        original_sql=sql,
        rewritten_sql=rewritten,
        mappings=tuple(dict.fromkeys(mappings)),
        unmapped=tuple(dict.fromkeys(unmapped)),
    )
