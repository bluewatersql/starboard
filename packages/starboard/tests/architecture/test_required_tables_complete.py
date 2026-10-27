# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Completeness guard: ``SystemQuery.required_tables`` must match the SQL.

The internal-mirror availability gate (``starboard_internal.mirror_source.MirrorSource``)
and the future ``QuerySource`` seam both decide whether a query can run against a
non-``system.*`` source purely from ``SystemQuery.required_tables`` — they never
parse ``sql_template`` themselves. If a query's declared ``required_tables`` is
missing a table the SQL actually reads (or lists one it doesn't), that gate makes
the wrong call silently. This test parses every ``sql_template`` in the default
registry for ``system.<schema>.<table>`` references and asserts the discovered
set is exactly ``set(required_tables)``.
"""

from __future__ import annotations

import re

from starboard.discovery.query_packs.registry import create_default_registry

_SYSTEM_TABLE_REF = re.compile(r"\bsystem\.[a-z0-9_]+\.[a-z0-9_]+\b", re.IGNORECASE)


def _referenced_tables(sql_template: str) -> set[str]:
    return {ref.lower() for ref in _SYSTEM_TABLE_REF.findall(sql_template)}


def test_registry_is_non_empty() -> None:
    registry = create_default_registry()
    assert registry.pack_count > 0
    assert any(pack.queries for pack in registry.all_packs)


def test_every_query_required_tables_matches_its_sql() -> None:
    registry = create_default_registry()

    mismatches: list[str] = []
    total_queries = 0
    for pack in registry.all_packs:
        for query in pack.queries:
            total_queries += 1
            referenced = _referenced_tables(query.sql_template)
            declared = {t.lower() for t in query.required_tables}
            if referenced != declared:
                missing_from_declared = sorted(referenced - declared)
                missing_from_sql = sorted(declared - referenced)
                mismatches.append(
                    f"[{pack.pack_id}/{query.query_id}] "
                    f"in SQL but not required_tables: {missing_from_declared}; "
                    f"in required_tables but not in SQL: {missing_from_sql}"
                )

    assert total_queries > 0
    assert not mismatches, (
        "required_tables must exactly equal the system.<schema>.<table> "
        "references found in sql_template (the internal-source availability "
        "gate relies on this). Mismatches:\n" + "\n".join(mismatches)
    )
