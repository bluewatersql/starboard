# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared fakes for the UC-native state adapter tests.

``FakeUCAdapter`` simulates :class:`UCStorageAdapter` in-memory. Crucially, on
read it returns **stringified** values, mimicking the Statement Execution API
(every ``result.data_array`` cell is a string), so the adapters' JSON/timestamp
(de)serialization is genuinely exercised on the round trip.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _stringify(value: Any) -> Any:
    """Mimic how the SQL warehouse renders a value in ``data_array``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float, str)):
        return str(value) if not isinstance(value, str) else value
    return str(value)


class FakeUCAdapter:
    """In-memory stand-in for ``UCStorageAdapter`` (records MERGE upserts)."""

    def __init__(self) -> None:
        # table_id -> list[stringified row]
        self.tables: dict[str, list[dict[str, Any]]] = {}
        # capture of (table_id, raw_row) for every upsert (asserts MERGE path)
        self.upserts: list[tuple[str, dict[str, Any]]] = []
        self.deletes: list[tuple[str, dict[str, Any]]] = []
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    async def upsert(self, table_id: str, row: dict[str, Any]) -> None:
        self.upserts.append((table_id, dict(row)))
        srow = {k: _stringify(v) for k, v in row.items()}
        rows = self.tables.setdefault(table_id, [])
        # Replace an existing row with the same first-column value (PK-ish).
        pk = next(iter(row))
        for i, existing in enumerate(rows):
            if existing.get(pk) == srow.get(pk):
                rows[i] = srow
                return
        rows.append(srow)

    def _match(self, row: dict[str, Any], filters: dict[str, Any]) -> bool:
        return all(row.get(k) == _stringify(v) for k, v in filters.items())

    async def read_one(
        self, table_id: str, filters: dict[str, Any]
    ) -> dict[str, Any] | None:
        for r in self.tables.get(table_id, []):
            if self._match(r, filters):
                return dict(r)
        return None

    async def read(
        self,
        table_id: str,
        filters: dict[str, Any] | None = None,
        columns: list[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self.tables.get(table_id, []))
        if filters:
            rows = [r for r in rows if self._match(r, filters)]
        if order_by:
            col = order_by.split()[0]
            reverse = order_by.upper().endswith("DESC")
            rows.sort(key=lambda r: r.get(col) or "", reverse=reverse)
        if limit is not None:
            rows = rows[:limit]
        return [dict(r) for r in rows]

    async def delete(self, table_id: str, filters: dict[str, Any]) -> int:
        self.deletes.append((table_id, dict(filters)))
        rows = self.tables.get(table_id, [])
        kept = [r for r in rows if not self._match(r, filters)]
        removed = len(rows) - len(kept)
        self.tables[table_id] = kept
        return removed
