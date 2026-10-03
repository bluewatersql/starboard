# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public ``FleetSqlPort`` adapter — single-workspace ``system.*`` executor (C5).

Executes system-tables SQL against the current single workspace via an injected
executor. There is intentionally NO cross-account/namespace rewrite here — that
is a gated internal-adapter capability and is Phase 3.
"""

from __future__ import annotations

from typing import Any, Protocol

from starboard_core.ports.fleet_sql import FleetQuery, FleetResult, FleetSqlPort


class _SqlExecutor(Protocol):
    """Structural type for an async SQL executor.

    Returns a mapping with ``columns`` (sequence of names) and ``rows``
    (sequence of row sequences).
    """

    async def __call__(
        self, sql: str, params: dict[str, Any]
    ) -> dict[str, Any]: ...


class SingleWorkspaceFleetAdapter(FleetSqlPort):
    """Execute single-workspace ``system.*`` queries.

    Args:
        executor: Async callable ``(sql, params) -> {"columns": [...], "rows": [...]}``.
    """

    def __init__(self, executor: _SqlExecutor) -> None:
        self._executor = executor

    async def execute(self, query: FleetQuery) -> FleetResult:
        raw = await self._executor(query.sql, query.params)
        columns = tuple(raw.get("columns", ()))
        rows = tuple(tuple(row) for row in raw.get("rows", ()))
        return FleetResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            metadata={"workspace_id": query.workspace_id or ""},
        )
