# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the D7 internal ``FleetSqlPort`` adapter (centralized namespace rewrite).

Covers the pure rewrite core and the adapter (driven by a stub executor). Asserts
``system.<schema>.<table>`` maps to its centralized equivalent, non-``system``
SQL passes through unchanged (public parity), and the result carries the public
columns/rows plus additive rewrite metadata.
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.ports.fleet_sql import FleetQuery, FleetResult
from starboard_internal._config import FleetSqlConfig
from starboard_internal._namespace_rewrite import (
    CENTRALIZED_SCHEMA,
    rewrite_system_namespace,
)
from starboard_internal.centralized_fleet_adapter import (
    CentralizedFleetSqlAdapter,
    _SdkStatementExecutor,
    _UnwiredExecutor,
)


class _StubExecutor:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.executed_sql: str | None = None

    async def __call__(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:
        self.executed_sql = sql
        return self._result


@pytest.mark.unit
class TestNamespaceRewrite:
    def test_maps_system_refs_to_centralized(self) -> None:
        rw = rewrite_system_namespace(
            "SELECT * FROM system.billing.usage u "
            "JOIN system.lakeflow.jobs j ON u.workspace_id = j.workspace_id"
        )
        assert f"main.{CENTRALIZED_SCHEMA}.billing_usage" in rw.rewritten_sql
        assert f"main.{CENTRALIZED_SCHEMA}.lakeflow_jobs" in rw.rewritten_sql
        assert "system.billing.usage" not in rw.rewritten_sql
        assert rw.did_rewrite is True
        assert (
            "system.billing.usage",
            f"main.{CENTRALIZED_SCHEMA}.billing_usage",
        ) in rw.mappings

    def test_non_system_sql_passes_through_unchanged(self) -> None:
        sql = "SELECT 1 FROM main.foo.bar WHERE x = :p"
        rw = rewrite_system_namespace(sql)
        assert rw.rewritten_sql == sql
        assert rw.did_rewrite is False
        assert rw.mappings == ()

    def test_unmapped_tables_preserved_and_reported(self) -> None:
        rw = rewrite_system_namespace("SELECT * FROM system.access.table_lineage")
        assert "system.access.table_lineage" in rw.rewritten_sql
        assert rw.unmapped == ("system.access.table_lineage",)
        assert rw.mappings == ()

    def test_rewrite_is_deterministic_and_dedups(self) -> None:
        sql = "system.billing.usage system.billing.usage"
        rw = rewrite_system_namespace(sql)
        assert len(rw.mappings) == 1


@pytest.mark.unit
class TestCentralizedFleetSqlAdapter:
    async def test_executes_rewritten_sql_and_enriches(self) -> None:
        executor = _StubExecutor({"columns": ["c"], "rows": [(1,), (2,)]})
        adapter = CentralizedFleetSqlAdapter(executor)
        result = await adapter.execute(
            FleetQuery(sql="SELECT c FROM system.billing.usage", workspace_id="ws1")
        )

        assert isinstance(result, FleetResult)
        assert executor.executed_sql is not None
        assert f"main.{CENTRALIZED_SCHEMA}.billing_usage" in executor.executed_sql
        # Public capability whole: columns/rows shape preserved.
        assert result.columns == ("c",)
        assert result.rows == ((1,), (2,))
        assert result.row_count == 2
        # Public-parity metadata key present.
        assert result.metadata["workspace_id"] == "ws1"
        # Additive enrichment.
        assert result.metadata["cross_account"] == "true"
        assert result.metadata["rewritten"] == "true"
        assert "system.billing.usage->" in result.metadata["rewrites"]

    async def test_non_system_query_behaves_like_single_workspace(self) -> None:
        executor = _StubExecutor({"columns": ["c"], "rows": [(9,)]})
        adapter = CentralizedFleetSqlAdapter(executor)
        result = await adapter.execute(FleetQuery(sql="SELECT c FROM main.foo.bar"))
        assert executor.executed_sql == "SELECT c FROM main.foo.bar"
        assert result.metadata["rewritten"] == "false"

    async def test_default_executor_raises_until_wired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID", raising=False)
        adapter = CentralizedFleetSqlAdapter()
        with pytest.raises(RuntimeError, match="centralized-tables") as exc:
            await adapter.execute(FleetQuery(sql="SELECT 1"))
        assert "STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID" in str(exc.value)

    def test_default_executor_is_unwired_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID", raising=False)
        assert isinstance(CentralizedFleetSqlAdapter()._executor, _UnwiredExecutor)

    def test_real_executor_selected_when_env_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID", "wh-1")
        assert isinstance(
            CentralizedFleetSqlAdapter()._executor, _SdkStatementExecutor
        )

    async def test_sdk_executor_maps_statement_response(self) -> None:
        # Fake SDK response objects (no network): manifest.schema.columns + rows.
        class _Col:
            def __init__(self, name: str) -> None:
                self.name = name

        class _State:
            value = "SUCCEEDED"

        class _Status:
            state = _State()

        class _Schema:
            columns = [_Col("a"), _Col("b")]

        class _Manifest:
            schema = _Schema()

        class _Result:
            data_array = [["1", "2"], ["3", "4"]]

        class _Resp:
            status = _Status()
            manifest = _Manifest()
            result = _Result()
            statement_id = "s1"

        class _StmtExec:
            def execute_statement(self, **kwargs: Any) -> _Resp:
                self.kwargs = kwargs
                return _Resp()

        class _FakeClient:
            statement_execution = _StmtExec()

        executor = _SdkStatementExecutor(FleetSqlConfig(warehouse_id="wh-1"))
        executor._client = lambda: _FakeClient()  # type: ignore[method-assign]
        out = await executor("SELECT a, b FROM system.billing.usage", {})
        assert out["columns"] == ["a", "b"]
        assert out["rows"] == [["1", "2"], ["3", "4"]]


class _State:
    def __init__(self, value: str | None) -> None:
        self.value = value


class _Status:
    def __init__(self, value: str | None, error: Any = None) -> None:
        self.state = _State(value)
        self.error = error


class _Chunk:
    def __init__(self, data_array: list, next_chunk_index: int | None) -> None:
        self.data_array = data_array
        self.next_chunk_index = next_chunk_index


class _Col:
    def __init__(self, name: str) -> None:
        self.name = name


class _Schema:
    def __init__(self, names: list[str]) -> None:
        self.columns = [_Col(n) for n in names]


class _Manifest:
    def __init__(self, names: list[str]) -> None:
        self.schema = _Schema(names)


class _Resp:
    def __init__(
        self,
        state: str | None,
        *,
        columns: list[str] | None = None,
        result: Any = None,
        error: Any = None,
        statement_id: str = "s1",
    ) -> None:
        self.status = _Status(state, error)
        self.manifest = _Manifest(columns or [])
        self.result = result
        self.statement_id = statement_id


@pytest.mark.unit
class TestSdkExecutorRobustness:
    async def test_hung_statement_hits_cap_and_raises(self) -> None:
        # Never leaves RUNNING; the deadline cap must abandon it (not spin).
        class _StmtExec:
            def execute_statement(self, **kwargs: Any) -> _Resp:
                return _Resp("RUNNING")

            def get_statement(self, statement_id: str) -> _Resp:
                return _Resp("RUNNING")

        class _FakeClient:
            statement_execution = _StmtExec()

        # max_poll_seconds=0 => the first deadline check trips immediately (no sleep).
        executor = _SdkStatementExecutor(
            FleetSqlConfig(warehouse_id="wh-1", poll_interval=0.0, max_poll_seconds=0.0)
        )
        executor._client = lambda: _FakeClient()  # type: ignore[method-assign]
        with pytest.raises(TimeoutError, match="did not finish"):
            await executor("SELECT 1", {})

    async def test_none_state_is_treated_as_error(self) -> None:
        # A missing/unknown terminal state must NOT masquerade as empty success.
        class _StmtExec:
            def execute_statement(self, **kwargs: Any) -> _Resp:
                return _Resp(None)

        class _FakeClient:
            statement_execution = _StmtExec()

        executor = _SdkStatementExecutor(FleetSqlConfig(warehouse_id="wh-1"))
        executor._client = lambda: _FakeClient()  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="did not succeed"):
            await executor("SELECT 1", {})

    async def test_failed_state_raises_with_error_message(self) -> None:
        class _Err:
            message = "table not found"

        class _StmtExec:
            def execute_statement(self, **kwargs: Any) -> _Resp:
                return _Resp("FAILED", error=_Err())

        class _FakeClient:
            statement_execution = _StmtExec()

        executor = _SdkStatementExecutor(FleetSqlConfig(warehouse_id="wh-1"))
        executor._client = lambda: _FakeClient()  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="table not found"):
            await executor("SELECT 1", {})

    async def test_multi_chunk_result_returns_all_rows(self) -> None:
        # Three chunks paged via next_chunk_index -> get_statement_result_chunk_n.
        chunks = {
            1: _Chunk([["r2"]], 2),
            2: _Chunk([["r3"]], None),
        }

        class _StmtExec:
            def execute_statement(self, **kwargs: Any) -> _Resp:
                return _Resp(
                    "SUCCEEDED",
                    columns=["c"],
                    result=_Chunk([["r1"]], 1),
                )

            def get_statement_result_chunk_n(
                self, statement_id: str, chunk_index: int
            ) -> _Chunk:
                return chunks[chunk_index]

        class _FakeClient:
            statement_execution = _StmtExec()

        executor = _SdkStatementExecutor(FleetSqlConfig(warehouse_id="wh-1"))
        executor._client = lambda: _FakeClient()  # type: ignore[method-assign]
        out = await executor("SELECT c FROM system.billing.usage", {})
        assert out["columns"] == ["c"]
        assert out["rows"] == [["r1"], ["r2"], ["r3"]]

    async def test_multi_chunk_row_count_is_accurate_through_adapter(self) -> None:
        chunks = {1: _Chunk([["r2"], ["r3"]], None)}

        class _StmtExec:
            def execute_statement(self, **kwargs: Any) -> _Resp:
                return _Resp("SUCCEEDED", columns=["c"], result=_Chunk([["r1"]], 1))

            def get_statement_result_chunk_n(
                self, statement_id: str, chunk_index: int
            ) -> _Chunk:
                return chunks[chunk_index]

        class _FakeClient:
            statement_execution = _StmtExec()

        executor = _SdkStatementExecutor(FleetSqlConfig(warehouse_id="wh-1"))
        executor._client = lambda: _FakeClient()  # type: ignore[method-assign]
        adapter = CentralizedFleetSqlAdapter(executor)
        result = await adapter.execute(
            FleetQuery(sql="SELECT c FROM system.billing.usage")
        )
        assert result.row_count == 3
        assert result.rows == (("r1",), ("r2",), ("r3",))
