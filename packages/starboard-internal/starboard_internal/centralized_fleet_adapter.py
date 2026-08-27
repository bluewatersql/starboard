# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Gated internal ``FleetSqlPort`` adapter — centralized fleet (Phase-3 D7 / D-3.4).

Where the PUBLIC adapter (``SingleWorkspaceFleetAdapter``) runs single-workspace
``system.*`` SQL, this internal adapter rewrites ``system.<schema>.<table>`` ->
``main.centralized_system_tables.<schema>_<table>`` at query-build time to give a
cross-account fleet view, then executes the rewritten SQL via the same injected
async executor protocol. The **public query packs are never edited** (near-zero
pack edits, D-3.4): the rewrite is entirely inside this adapter.

Strict SUPERSET (UNIFIED_PLAN §3.5): the returned :class:`FleetResult` has the
same columns/rows/row_count the public adapter would produce for the same
executor, plus additive ``metadata`` describing the rewrite. When a query names
no ``system.*`` table, the SQL passes through unchanged — behavior is identical
to the public path.
"""

from __future__ import annotations

from typing import Any, Protocol

from starboard_core.ports.fleet_sql import FleetQuery, FleetResult, FleetSqlPort

from starboard_internal._namespace_rewrite import rewrite_system_namespace

#: Stable backend tag (internal-index-only identifier).
_BACKEND_SOURCE = "centralized_system_tables"


class _SqlExecutor(Protocol):
    """Async SQL executor (same shape the public adapter accepts)."""

    async def __call__(self, sql: str, params: dict[str, Any]) -> dict[str, Any]: ...


class _DefaultExecutor:
    """Placeholder executor: real centralized-tables access is external here."""

    async def __call__(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        raise RuntimeError(
            "CentralizedFleetSqlAdapter requires internal centralized-tables "
            "runtime access; inject an executor to use this adapter."
        )


class CentralizedFleetSqlAdapter(FleetSqlPort):
    """Execute ``system.*`` SQL against the centralized cross-account tables.

    Args:
        executor: Async ``(sql, params) -> {"columns": [...], "rows": [...]}``.
            When omitted, a default executor is used that raises on use (real
            internal access is wired at deploy time).
    """

    def __init__(self, executor: _SqlExecutor | None = None) -> None:
        self._executor: _SqlExecutor = executor or _DefaultExecutor()

    async def execute(self, query: FleetQuery) -> FleetResult:
        rewrite = rewrite_system_namespace(query.sql)
        raw = await self._executor(rewrite.rewritten_sql, query.params)
        columns = tuple(raw.get("columns", ()))
        rows = tuple(tuple(row) for row in raw.get("rows", ()))
        metadata: dict[str, Any] = {
            # Public-parity field (SingleWorkspaceFleetAdapter also records this).
            "workspace_id": query.workspace_id or "",
            # --- additive enrichment (superset) ---
            "backend": _BACKEND_SOURCE,
            "cross_account": "true",
            "rewritten": str(rewrite.did_rewrite).lower(),
            "rewrites": "; ".join(f"{src}->{dst}" for src, dst in rewrite.mappings),
            "unmapped": ", ".join(rewrite.unmapped),
        }
        return FleetResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            metadata=metadata,
        )
