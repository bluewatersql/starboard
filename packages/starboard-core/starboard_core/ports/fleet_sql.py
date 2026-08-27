# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Fleet-SQL port (Phase-2 C5, D-2.10).

A kernel-tier, SDK-free Protocol for executing a system-tables query.

The PUBLIC adapter executes single-workspace ``system.*`` queries (the existing
pack path). A gated internal adapter (cross-account fleet view via a
namespace-rewrite) is Phase 3 and does not ship here — so this module names no
internal namespace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class FleetQuery:
    """A system-tables query request.

    Attributes:
        sql: The SQL template/text to execute.
        params: Named parameters to bind.
        workspace_id: Optional target workspace id (public path = single workspace).
        lookback_days: Optional look-back bound.
    """

    sql: str
    params: dict[str, Any] = field(default_factory=dict)
    workspace_id: str | None = None
    lookback_days: int | None = None


@dataclass(frozen=True)
class FleetResult:
    """A tabular query result.

    Attributes:
        columns: Column names.
        rows: Row tuples aligned to ``columns``.
        row_count: Number of rows.
        metadata: Optional adapter metadata.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class FleetSqlPort(Protocol):
    """Execute a :class:`FleetQuery` and return a :class:`FleetResult`."""

    async def execute(self, query: FleetQuery) -> FleetResult:
        """Execute ``query`` and return its result."""
        ...
