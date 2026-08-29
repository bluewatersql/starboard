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

The zero-arg factory builds the **real** executor (Databricks SQL statement
execution against the governed centralized-tables warehouse) when the internal
deployment env is present (:class:`FleetSqlConfig`); when it is absent it builds
an *unwired* executor that raises a clean, actionable
:class:`MissingInternalConfigError` (never a silent stub). Tests inject an executor.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from starboard_core.ports.fleet_sql import FleetQuery, FleetResult, FleetSqlPort

from starboard_internal._config import (
    FleetSqlConfig,
    MissingInternalConfigError,
    missing_config_message,
)
from starboard_internal._namespace_rewrite import rewrite_system_namespace

#: Stable backend tag (internal-index-only identifier).
_BACKEND_SOURCE = "centralized_system_tables"

#: SQL statement states that mean "keep polling".
_NON_TERMINAL_STATES = frozenset({"PENDING", "RUNNING"})
#: The only terminal state that yields a result set; all others are failures.
_SUCCESS_STATE = "SUCCEEDED"


class _SqlExecutor(Protocol):
    """Async SQL executor (same shape the public adapter accepts)."""

    async def __call__(self, sql: str, params: dict[str, Any]) -> dict[str, Any]: ...


class _UnwiredExecutor:
    """Executor used when the internal deployment env is absent.

    Not a silent stub: raises with the exact env vars to set. The message keeps
    the ``centralized-tables`` phrasing callers/tests match on.
    """

    async def __call__(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        raise MissingInternalConfigError(
            missing_config_message(
                "CentralizedFleetSqlAdapter",
                "centralized-tables",
                FleetSqlConfig.REQUIRED,
                "SQL executor",
            )
        )


class _SdkStatementExecutor:
    """Real executor: runs SQL on the centralized-tables warehouse via the SDK.

    Uses the Databricks SDK statement-execution API against the governed
    warehouse. The blocking SDK call is off-loaded to a worker thread so the
    port's async contract holds; the ``WorkspaceClient`` is created per call.
    """

    def __init__(self, config: FleetSqlConfig) -> None:
        self._config = config

    async def __call__(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._run, sql, params)

    def _client(self) -> Any:
        from databricks.sdk import WorkspaceClient

        kwargs: dict[str, Any] = {}
        if self._config.host:
            kwargs["host"] = self._config.host
        if self._config.token:
            kwargs["token"] = self._config.token
        return WorkspaceClient(**kwargs)

    def _run(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:
        from databricks.sdk.service.sql import StatementParameterListItem

        client = self._client()
        stmt_params = [
            StatementParameterListItem(
                name=str(name), value=None if value is None else str(value)
            )
            for name, value in params.items()
        ] or None
        resp = client.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=self._config.warehouse_id,
            catalog=self._config.catalog,
            parameters=stmt_params,
            wait_timeout=self._config.wait_timeout,
        )
        resp = self._await_terminal(client, resp)
        return self._to_dict(client, resp)

    @staticmethod
    def _state_of(resp: Any) -> str | None:
        status = getattr(resp, "status", None)
        return getattr(getattr(status, "state", None), "value", None)

    def _await_terminal(self, client: Any, resp: Any) -> Any:
        """Poll to a terminal state with a sleep between polls and a hard cap.

        Bounded so a hung/long-running statement cannot busy-spin or storm the
        SQL API: sleeps ``poll_interval`` between checks and raises once
        ``max_poll_seconds`` elapses. A missing/unknown terminal state or any
        non-``SUCCEEDED`` state is an error (never a silent empty result).
        """
        deadline = time.monotonic() + self._config.max_poll_seconds
        state = self._state_of(resp)
        while state in _NON_TERMINAL_STATES:
            if time.monotonic() >= deadline:
                statement_id = getattr(resp, "statement_id", "")
                raise TimeoutError(
                    "centralized-tables statement did not finish within "
                    f"{self._config.max_poll_seconds:g}s "
                    f"(statement_id={statement_id!r}, last state={state})"
                )
            time.sleep(self._config.poll_interval)
            resp = client.statement_execution.get_statement(resp.statement_id)
            state = self._state_of(resp)
        if state != _SUCCESS_STATE:
            status = getattr(resp, "status", None)
            error = getattr(status, "error", None)
            message = getattr(error, "message", None) or state or "unknown state"
            raise RuntimeError(
                f"centralized-tables statement did not succeed: {message}"
            )
        return resp

    @staticmethod
    def _to_dict(client: Any, resp: Any) -> dict[str, Any]:
        manifest = getattr(resp, "manifest", None)
        schema = getattr(manifest, "schema", None)
        columns = [col.name for col in (getattr(schema, "columns", None) or [])]

        # Page through every result chunk (not just the first) so large result
        # sets are returned whole with an accurate row_count.
        rows: list[Any] = []
        statement_id = getattr(resp, "statement_id", None)
        chunk = getattr(resp, "result", None)
        while chunk is not None:
            rows.extend(getattr(chunk, "data_array", None) or [])
            next_index = getattr(chunk, "next_chunk_index", None)
            if next_index is None or statement_id is None:
                break
            chunk = client.statement_execution.get_statement_result_chunk_n(
                statement_id, next_index
            )
        return {"columns": columns, "rows": rows}


def _default_executor() -> _SqlExecutor:
    """Build the real executor from the internal env, else an unwired executor."""
    config = FleetSqlConfig.from_env()
    if config is None:
        return _UnwiredExecutor()
    return _SdkStatementExecutor(config)


class CentralizedFleetSqlAdapter(FleetSqlPort):
    """Execute ``system.*`` SQL against the centralized cross-account tables.

    Args:
        executor: Async ``(sql, params) -> {"columns": [...], "rows": [...]}``.
            When omitted, the real SDK executor is built from the internal
            deployment env when present, else an unwired executor that raises an
            actionable error on use.
    """

    def __init__(self, executor: _SqlExecutor | None = None) -> None:
        self._executor: _SqlExecutor = executor or _default_executor()

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
