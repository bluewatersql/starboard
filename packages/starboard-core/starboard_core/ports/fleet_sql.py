# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Fleet-SQL port.

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


class FleetSourceAuthRequired(PermissionError):
    """A fleet-SQL source's sign-in is missing or expired.

    Raised by an adapter when its credential chain rejects the request
    (expired OAuth token, revoked credential). Callers map it to an
    auth-class exit without a traceback. ``hint`` carries the re-login
    step; the adapter that raises it owns the wording (the public base
    names no profile or source).

    Attributes:
        code: Stable error code for envelopes (subclasses override).
        hint: Operator remediation, or ``None``.
    """

    code: str = "SOURCE_AUTH_REQUIRED"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class FleetSourceTimeout(TimeoutError):
    """A fleet-SQL source statement did not finish within its deadline.

    Typically transient (a busy shared warehouse), so callers map it to a
    coded, retryable exit without a traceback; re-running the same command is
    the retry. ``hint`` carries the operator step; the adapter that raises it
    owns the wording.

    Attributes:
        code: Stable error code for envelopes.
        retryable: Always ``True`` -- the same command can be re-run.
        hint: Operator remediation, or ``None``.
    """

    code: str = "SOURCE_TIMEOUT"
    retryable: bool = True

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint
