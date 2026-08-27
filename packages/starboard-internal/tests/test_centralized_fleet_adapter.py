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
from starboard_internal._namespace_rewrite import (
    CENTRALIZED_SCHEMA,
    rewrite_system_namespace,
)
from starboard_internal.centralized_fleet_adapter import (
    CentralizedFleetSqlAdapter,
    _DefaultExecutor,
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

    async def test_default_executor_raises_until_wired(self) -> None:
        adapter = CentralizedFleetSqlAdapter()
        with pytest.raises(RuntimeError, match="centralized-tables"):
            await adapter.execute(FleetQuery(sql="SELECT 1"))

    def test_default_executor_type_is_placeholder(self) -> None:
        assert isinstance(CentralizedFleetSqlAdapter()._executor, _DefaultExecutor)
