# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""QuerySource seam — where a discovery query's SQL actually runs.

The public default (:class:`SystemTablesSource`) is today's identity
behavior: render ``system.*`` SQL and hand it to the customer-workspace
executor, unchanged. A gated internal source (``starboard-internal``) may
rewrite the SQL to run against an internal mirror instead — but that
rewrite never lives in this public package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from starboard_core.domain.models.discovery.query import SystemQuery

    from starboard.discovery.executor import SQLExecutor

#: Renders a SQL template's ``{lookback_days}`` / ``{result_limit}`` placeholders
#: with the same parameters the executor used for the query's own template. A
#: source that swaps in an *alternative* template (e.g. an internal override)
#: must run it through this so the placeholders are substituted consistently —
#: never shipped raw to the warehouse.
RenderFn = Callable[[str], str]


@dataclass(frozen=True)
class PreparedQuery:
    """SQL + the executor it should run on, resolved by a ``QuerySource``.

    ``lookback_days`` is set only when the source served a *shorter* window than
    the executor requested (e.g. a cheaper internal-mirror shape); the executor
    then reports that effective window in the query's metadata so it stays honest.
    """

    sql: str
    executor: SQLExecutor
    lookback_days: int | None = None


@dataclass(frozen=True)
class Unavailable:
    """Signals that a source cannot serve this query (e.g., unmirrored table)."""

    reason: str


@runtime_checkable
class QuerySource(Protocol):
    """Resolves where and how a discovery query's SQL executes.

    ``render`` applies the executor's placeholder substitution
    (``{lookback_days}`` / ``{result_limit}``) to an arbitrary template, so a
    source that substitutes a different SQL body renders it with the same
    parameters as the query's own template.
    """

    def prepare(
        self,
        query: SystemQuery,
        rendered_sql: str,
        render: RenderFn | None = None,
    ) -> PreparedQuery | Unavailable: ...


class SystemTablesSource:
    """Public default: identity — run the rendered system.* SQL on the customer executor.

    ``coverage_caveats`` is an empty tuple on the public path — there are no
    known coverage gaps against a customer's own system tables.  The gated
    internal ``MirrorSource`` overrides this attribute with workspace-level
    caveats (e.g. columns that are null in the mirror) so callers can surface
    them in the envelope without hard-coding internal table names here.
    """

    coverage_caveats: tuple[str, ...] = ()
    #: Query ids the executor should start first (known long poles on this
    #: source). None on the public path; a gated source may set its own.
    schedule_first: tuple[str, ...] = ()

    def __init__(self, executor: SQLExecutor) -> None:
        self._executor = executor

    def prepare(
        self,
        query: SystemQuery,  # noqa: ARG002 - identity source ignores query
        rendered_sql: str,
        render: RenderFn | None = None,  # noqa: ARG002 - identity uses rendered_sql as-is
    ) -> PreparedQuery:
        return PreparedQuery(sql=rendered_sql, executor=self._executor)
