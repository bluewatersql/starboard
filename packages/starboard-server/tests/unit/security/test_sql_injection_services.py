"""Security tests: SQL injection prevention in tool service layer.

Covers the live high-severity findings for service-layer SQL construction:

- F-3-p2-server-tools-dom-svc-1: warehouse_portfolio_service.py interpolates a
  resolved warehouse id into string-literal filters.
- F-3-p2-server-tools-dom-svc-2: uc/governance.py interpolates a UC table name
  and window_days into table_lineage / query.history queries.
- F-3-p2-server-tools-dom-svc-3: query_workload_service.py interpolates
  window_days into ``INTERVAL <n> DAYS`` and table names into an IN clause.
- F-3-4d-006: infra/storage/uc_adapter.py _build_where_conditions interpolates
  filter values and column names.

Databricks SQL cannot bind identifiers (table/column/warehouse ids) or the day
count of an INTERVAL as parameter markers in these queries, so each value is
strictly validated before interpolation. These tests prove that injection
payloads are rejected (or safely escaped for value literals) rather than
reaching the SQL string.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest

# Representative injection payloads reused across cases.
INJECTION_PAYLOADS = [
    "x'; DROP TABLE users; --",
    "1' OR '1'='1",
    "abc' UNION SELECT * FROM secrets --",
    "id`; DELETE FROM t; --",
    "a b",  # whitespace
]


# =============================================================================
# Shared validators (tools/services/validation.py)
# =============================================================================


class TestValidationHelpers:
    def test_validate_window_days_coerces_numeric_string(self) -> None:
        from starboard_server.tools.services.validation import validate_window_days

        assert validate_window_days("30") == 30
        assert validate_window_days(7) == 7

    @pytest.mark.parametrize(
        "bad",
        ["30 OR 1=1", "7; DROP TABLE x", "-1", "0", "abc", None, True, 10**9],
    )
    def test_validate_window_days_rejects_bad_values(self, bad) -> None:
        from starboard_server.tools.services.validation import validate_window_days

        with pytest.raises(ValueError):
            validate_window_days(bad)

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_validate_warehouse_id_rejects_payloads(self, payload) -> None:
        from starboard_server.tools.services.validation import validate_warehouse_id

        with pytest.raises(ValueError):
            validate_warehouse_id(payload)

    def test_validate_warehouse_id_accepts_alnum(self) -> None:
        from starboard_server.tools.services.validation import validate_warehouse_id

        assert validate_warehouse_id("1234567890abcdef") == "1234567890abcdef"

    def test_qualified_table_name_dotted(self) -> None:
        from starboard_server.tools.services.validation import QualifiedTableName

        assert (
            QualifiedTableName.from_string("main.default.t").to_dotted_name()
            == "main.default.t"
        )

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_qualified_table_name_rejects_payloads(self, payload) -> None:
        from starboard_server.tools.services.validation import QualifiedTableName

        with pytest.raises(ValueError):
            QualifiedTableName.from_string(f"main.default.{payload}")


# =============================================================================
# F-3-p2-server-tools-dom-svc-1: warehouse_portfolio_service
# =============================================================================


def _make_portfolio_service():
    from starboard_server.tools.services.warehouse_portfolio_service import (
        WarehousePortfolioService,
    )

    sql_executor = MagicMock()
    sql_executor.execute_sql = AsyncMock(return_value=pl.DataFrame())
    warehouse_data = MagicMock()
    # _resolve_warehouse: get_warehouse returns the id directly -> resolved_id = input
    warehouse_data.get_warehouse = AsyncMock(
        side_effect=lambda x: {"id": x, "name": x}
    )
    warehouse_data.list_warehouses = AsyncMock(return_value=[])
    return WarehousePortfolioService(
        sql_executor=sql_executor, warehouse_data=warehouse_data
    )


class TestWarehousePortfolioInjection:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    async def test_get_fingerprint_rejects_injection(self, payload) -> None:
        service = _make_portfolio_service()
        with pytest.raises(ValueError):
            await service.get_fingerprint(payload, window_days=7)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    async def test_get_user_activity_rejects_injection(self, payload) -> None:
        service = _make_portfolio_service()
        with pytest.raises(ValueError):
            await service.get_user_activity(warehouse_id=payload, window_days=7)

    @pytest.mark.asyncio
    async def test_fetch_warehouse_cost_rejects_injection(self) -> None:
        service = _make_portfolio_service()
        with pytest.raises(ValueError):
            await service._fetch_warehouse_cost("a' OR '1'='1", window_days=7)

    @pytest.mark.asyncio
    async def test_valid_warehouse_id_passes_and_not_in_sql_raw(self) -> None:
        service = _make_portfolio_service()
        await service.get_fingerprint("abc123def456", window_days=7)
        sql = service._sql_executor.execute_sql.call_args.kwargs["sql"]
        assert "compute.warehouse_id = 'abc123def456'" in sql


# =============================================================================
# F-3-p2-server-tools-dom-svc-2: uc/governance
# =============================================================================


def _make_governance_service():
    from starboard_server.tools.services.uc.governance import GovernanceService

    sql_provider = MagicMock()
    sql_provider.execute_query = AsyncMock(return_value=[])
    uc_provider = MagicMock()
    return GovernanceService(uc_provider=uc_provider, sql_provider=sql_provider)


class TestGovernanceAccessPatternsInjection:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    async def test_table_name_injection_rejected(self, payload) -> None:
        service = _make_governance_service()
        with pytest.raises(ValueError):
            await service.analyze_access_patterns(f"cat.sch.{payload}", window_days=30)

    @pytest.mark.asyncio
    async def test_window_days_injection_rejected(self) -> None:
        service = _make_governance_service()
        with pytest.raises(ValueError):
            await service.analyze_access_patterns(
                "cat.sch.tbl", window_days="30; DROP TABLE x"  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_valid_inputs_produce_safe_sql(self) -> None:
        service = _make_governance_service()
        await service.analyze_access_patterns("cat.sch.tbl", window_days=30)
        # First call is the main query; assert validated literal present, no payload.
        first_query = service.sql_provider.execute_query.call_args_list[0].args[0]
        assert "source_table_full_name = 'cat.sch.tbl'" in first_query
        assert "INTERVAL 30 DAYS" in first_query


# =============================================================================
# F-3-p2-server-tools-dom-svc-3: query_workload_service
# =============================================================================


def _make_workload_service():
    from starboard_server.tools.services.query_workload_service import (
        QueryWorkloadService,
    )

    executor = MagicMock()
    executor.execute_query_polars = AsyncMock(return_value=pl.DataFrame())
    return QueryWorkloadService(sql_executor=executor)


class TestQueryWorkloadInjection:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    async def test_table_name_injection_rejected(self, payload) -> None:
        service = _make_workload_service()
        with pytest.raises(ValueError):
            await service.fetch_workload_data([f"cat.sch.{payload}"], window_days=30)

    @pytest.mark.asyncio
    async def test_window_days_injection_rejected_in_workload(self) -> None:
        service = _make_workload_service()
        with pytest.raises(ValueError):
            await service.fetch_workload_data(
                ["cat.sch.tbl"], window_days="30 OR 1=1"  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_window_days_injection_rejected_in_billing(self) -> None:
        service = _make_workload_service()
        with pytest.raises(ValueError):
            await service.fetch_billing_data(window_days="x; DROP")  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_valid_inputs_produce_safe_sql(self) -> None:
        service = _make_workload_service()
        await service.fetch_workload_data(["cat.sch.tbl"], window_days=30, limit=50)
        query = service.sql_executor.execute_query_polars.call_args.args[0]
        assert "'cat.sch.tbl'" in query
        assert "INTERVAL 30 DAYS" in query
        assert "LIMIT 50" in query


# =============================================================================
# F-3-4d-006: uc_adapter _build_where_conditions
# =============================================================================


def _make_uc_adapter():
    from starboard_server.infra.storage.table_registry import TableRegistry
    from starboard_server.infra.storage.uc_adapter import (
        UCStorageAdapter,
        UCStorageConfig,
    )

    config = UCStorageConfig(catalog="cat", schema="sch", warehouse_id="wh")
    return UCStorageAdapter(
        workspace_client=MagicMock(), config=config, registry=TableRegistry()
    )


class TestUCAdapterWhereConditions:
    def test_string_value_escaped(self) -> None:
        adapter = _make_uc_adapter()
        conditions = adapter._build_where_conditions({"name": "O'Malley"})
        assert conditions == ["name = 'O''Malley'"]

    def test_injection_payload_escaped(self) -> None:
        adapter = _make_uc_adapter()
        conditions = adapter._build_where_conditions(
            {"user_id": "'; DROP TABLE conversations; --"}
        )
        assert "''" in conditions[0]
        # No bare quote terminates the literal early.
        assert conditions[0].count("'") % 2 == 0

    def test_numeric_value_not_raw_when_string_subclass(self) -> None:
        adapter = _make_uc_adapter()
        # Integers remain unquoted (safe) but go through _format_value now.
        assert adapter._build_where_conditions({"count": 5}) == ["count = 5"]

    def test_none_value_is_null(self) -> None:
        adapter = _make_uc_adapter()
        assert adapter._build_where_conditions({"deleted_at": None}) == [
            "deleted_at IS NULL"
        ]

    def test_invalid_column_name_rejected(self) -> None:
        from starboard_server.infra.storage.uc_adapter import InvalidColumnError

        adapter = _make_uc_adapter()
        with pytest.raises(InvalidColumnError):
            adapter._build_where_conditions({"col = 1; DROP TABLE x --": "v"})
