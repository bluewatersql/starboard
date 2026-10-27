# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the authorized-row-scope SQL wrapper (engagement spec G3)."""

from __future__ import annotations

import pytest
from starboard_core.engagement.row_scope import (
    NON_WORKSPACE_TABLES,
    RowScopeError,
    scope_system_sql,
)

W = ("1234567890",)
SCOPE = "WHERE workspace_id IN ('1234567890'))"


def _wrapped(table: str) -> str:
    return f"(SELECT * FROM {table} {SCOPE}"


@pytest.mark.unit
class TestWrapping:
    def test_bare_reference_gets_table_name_alias(self) -> None:
        out = scope_system_sql("SELECT usage.sku_name FROM system.billing.usage", W)
        assert out == (
            "SELECT usage.sku_name FROM "
            + _wrapped("system.billing.usage")
            + " `usage`"
        )

    def test_alias_is_preserved(self) -> None:
        out = scope_system_sql(
            "SELECT u.x FROM system.billing.usage u WHERE u.x > 1", W
        )
        assert out == (
            "SELECT u.x FROM " + _wrapped("system.billing.usage") + " u WHERE u.x > 1"
        )

    def test_as_alias_is_preserved(self) -> None:
        out = scope_system_sql("SELECT 1 FROM system.query.history AS qh", W)
        assert out == "SELECT 1 FROM " + _wrapped("system.query.history") + " AS qh"

    @pytest.mark.parametrize(
        "keyword",
        ["WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "LEFT", "ON", "UNION", "QUALIFY"],
    )
    def test_following_keyword_is_not_an_alias(self, keyword: str) -> None:
        out = scope_system_sql(f"SELECT 1 FROM system.billing.usage\n{keyword} x", W)
        assert out == (
            "SELECT 1 FROM "
            + _wrapped("system.billing.usage")
            + f" `usage`\n{keyword} x"
        )

    def test_join_is_wrapped(self) -> None:
        sql = (
            "SELECT 1 FROM system.lakeflow.jobs j "
            "LEFT JOIN system.lakeflow.job_run_timeline t ON j.job_id = t.job_id"
        )
        out = scope_system_sql(sql, W)
        assert _wrapped("system.lakeflow.jobs") + " j" in out
        assert (
            "LEFT JOIN " + _wrapped("system.lakeflow.job_run_timeline") + " t ON" in out
        )

    def test_backtick_parts_are_wrapped_and_canonicalised(self) -> None:
        out = scope_system_sql("SELECT 1 FROM `system`.`billing`.`usage` u", W)
        assert out == "SELECT 1 FROM " + _wrapped("system.billing.usage") + " u"

    def test_whole_backtick_identifier_is_wrapped(self) -> None:
        out = scope_system_sql("SELECT 1 FROM `system.billing.usage`", W)
        assert out == "SELECT 1 FROM " + _wrapped("system.billing.usage") + " `usage`"

    def test_case_insensitive(self) -> None:
        out = scope_system_sql("select 1 from SYSTEM.Billing.USAGE u", W)
        assert out == "select 1 from " + _wrapped("system.billing.usage") + " u"

    def test_multiple_ids_and_dedupe(self) -> None:
        out = scope_system_sql("SELECT 1 FROM system.billing.usage u", ("1", "2", "1"))
        assert "WHERE workspace_id IN ('1','2'))" in out

    def test_cte_and_subquery_references_are_wrapped(self) -> None:
        sql = (
            "WITH a AS (SELECT * FROM system.billing.usage WHERE x = 1) "
            "SELECT * FROM a WHERE a.y IN (SELECT y FROM system.query.history)"
        )
        out = scope_system_sql(sql, W)
        assert _wrapped("system.billing.usage") + " `usage` WHERE x = 1" in out
        assert _wrapped("system.query.history") + " `history`)" in out

    def test_unknown_system_table_is_wrapped_fail_closed(self) -> None:
        out = scope_system_sql("SELECT 1 FROM system.brand_new.thing", W)
        assert out == "SELECT 1 FROM " + _wrapped("system.brand_new.thing") + " `thing`"

    def test_non_system_tables_untouched(self) -> None:
        sql = "SELECT 1 FROM main.default.t JOIN a ON a.x = t.x"
        assert scope_system_sql(sql, W) == sql


@pytest.mark.unit
class TestExemptions:
    @pytest.mark.parametrize("table", sorted(NON_WORKSPACE_TABLES))
    def test_non_workspace_tables_pass(self, table: str) -> None:
        sql = f"SELECT 1 FROM {table} lp"
        assert scope_system_sql(sql, W) == sql

    def test_information_schema_passes(self) -> None:
        sql = "SELECT 1 FROM system.information_schema.tables"
        assert scope_system_sql(sql, W) == sql

    def test_metastore_grained_dq_dcl_tables_are_exempt(self) -> None:
        for t in (
            "system.data_classification.results",
            "system.data_quality_monitoring.table_results",
        ):
            assert t in NON_WORKSPACE_TABLES
            assert scope_system_sql(f"SELECT 1 FROM {t} r", W) == f"SELECT 1 FROM {t} r"

    def test_known_dims_are_exempt(self) -> None:
        assert "system.billing.list_prices" in NON_WORKSPACE_TABLES
        assert "system.compute.node_types" in NON_WORKSPACE_TABLES
        assert "system.billing.usage" not in NON_WORKSPACE_TABLES

    def test_mixed_join_wraps_only_workspace_grained(self) -> None:
        sql = (
            "SELECT 1 FROM system.billing.usage u "
            "JOIN system.billing.list_prices lp ON u.sku_name = lp.sku_name"
        )
        out = scope_system_sql(sql, W)
        assert _wrapped("system.billing.usage") + " u" in out
        assert "JOIN system.billing.list_prices lp ON" in out


@pytest.mark.unit
class TestFailClosed:
    def test_empty_ids_raise(self) -> None:
        with pytest.raises(RowScopeError):
            scope_system_sql("SELECT 1 FROM system.billing.usage", ())

    @pytest.mark.parametrize("bad", ["", "12a", "1' OR '1'='1", " 1", "-1"])
    def test_non_digit_ids_raise(self, bad: str) -> None:
        with pytest.raises(RowScopeError):
            scope_system_sql("SELECT 1 FROM system.billing.usage", (bad,))

    def test_is_value_error(self) -> None:
        assert issubclass(RowScopeError, ValueError)

    def test_comma_join_reference_raises(self) -> None:
        with pytest.raises(RowScopeError, match="system.query.history"):
            scope_system_sql(
                "SELECT 1 FROM system.billing.usage u, system.query.history h", W
            )

    def test_reference_in_string_literal_raises(self) -> None:
        with pytest.raises(RowScopeError):
            scope_system_sql("SELECT 'system.billing.usage' AS t FROM range(1)", W)

    def test_fully_qualified_column_ref_raises(self) -> None:
        with pytest.raises(RowScopeError):
            scope_system_sql(
                "SELECT system.billing.usage.sku_name FROM system.billing.usage", W
            )

    def test_reference_in_comment_is_ignored(self) -> None:
        sql = "-- reads system.query.history\nSELECT 1 FROM system.billing.usage u"
        out = scope_system_sql(sql, W)
        assert _wrapped("system.billing.usage") + " u" in out

    def test_exempt_table_outside_from_is_allowed(self) -> None:
        sql = "SELECT 1 FROM main.x.y, system.billing.list_prices"
        assert scope_system_sql(sql, W) == sql


@pytest.mark.unit
class TestLexicalBypasses:
    """Quotes and comments are tokenized, so neither can hide a reference."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT '--' AS x, * FROM system.billing.usage u, system.access.audit a",
            "SELECT '/*' AS x, * FROM system.billing.usage u, system.access.audit a, "
            "'*/' AS y",
            "SELECT 1 AS `x--`, * FROM system.billing.usage u, system.access.audit a",
            'SELECT "--" AS x, * FROM system.billing.usage u, system.access.audit a',
            "SELECT 'it\\'s --' AS x, * FROM system.billing.usage u, "
            "system.access.audit a",
            "SELECT 1 AS `a``--`, * FROM system.billing.usage u, system.access.audit a",
        ],
    )
    def test_quoted_comment_marker_cannot_hide_a_comma_join(self, sql: str) -> None:
        with pytest.raises(RowScopeError, match="system.access.audit"):
            scope_system_sql(sql, W)

    def test_quoted_comment_marker_does_not_break_from_rewrite(self) -> None:
        out = scope_system_sql("SELECT '--' AS x FROM system.billing.usage u", W)
        assert out == "SELECT '--' AS x FROM " + _wrapped("system.billing.usage") + " u"

    def test_comment_marker_in_quoted_alias_keeps_alias(self) -> None:
        out = scope_system_sql("SELECT 1 FROM system.billing.usage `u--x`", W)
        assert out == "SELECT 1 FROM " + _wrapped("system.billing.usage") + " `u--x`"

    def test_nested_block_comment_is_ignored(self) -> None:
        sql = (
            "/* outer /* system.query.history */ still comment system.access.audit */"
            "SELECT 1 FROM system.billing.usage u"
        )
        out = scope_system_sql(sql, W)
        assert out.endswith(_wrapped("system.billing.usage") + " u")

    def test_comment_between_from_and_table_is_still_scoped(self) -> None:
        out = scope_system_sql("SELECT 1 FROM/* c */system.billing.usage u", W)
        assert _wrapped("system.billing.usage") + " u" in out
        assert "FROM system.billing.usage u" not in out

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 'unterminated FROM system.billing.usage",
            "SELECT 1 FROM system.billing.usage /* unterminated",
            "SELECT 1 FROM `unterminated",
        ],
    )
    def test_unterminated_token_raises(self, sql: str) -> None:
        with pytest.raises(RowScopeError):
            scope_system_sql(sql, W)

    def test_double_quoted_reference_raises(self) -> None:
        with pytest.raises(RowScopeError):
            scope_system_sql('SELECT 1 FROM "system"."billing"."usage"', W)

    def test_string_literal_mention_still_raises(self) -> None:
        with pytest.raises(RowScopeError):
            scope_system_sql("SELECT 'a -- system.query.history' FROM range(1)", W)


@pytest.mark.unit
class TestIndirectReferences:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM IDENTIFIER('system.billing.usage')",
            "SELECT * FROM identifier ('system' || '.billing.usage')",
            "SELECT * FROM `IDENTIFIER`(:t)",
            "SELECT * FROM IDENTIFIER/* c */(:t)",
        ],
    )
    def test_identifier_clause_raises(self, sql: str) -> None:
        with pytest.raises(RowScopeError, match="IDENTIFIER"):
            scope_system_sql(sql, W)

    def test_identifier_word_in_string_or_column_is_fine(self) -> None:
        sql = "SELECT 'IDENTIFIER(x)' AS s, identifier_id FROM main.x.y"
        assert scope_system_sql(sql, W) == sql

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM billing.usage",
            "SELECT * FROM main.x.y m JOIN access.audit a ON m.id = a.id",
            "SELECT * FROM `query`.`history`",
            "SELECT * FROM Lakeflow . job_run_timeline",
        ],
    )
    def test_two_part_system_schema_reference_raises(self, sql: str) -> None:
        with pytest.raises(RowScopeError, match="system schema"):
            scope_system_sql(sql, W)

    def test_two_part_non_system_schema_is_fine(self) -> None:
        sql = "SELECT * FROM sales.orders o JOIN main.billing.usage u ON o.id = u.id"
        assert scope_system_sql(sql, W) == sql


class TestSessionAndLineEndBypasses:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1 -- x\rFROM system.billing.usage",
            "SELECT 1 FROM main.a.b -- x\rJOIN system.billing.usage u ON 1=1",
        ],
    )
    def test_carriage_return_ends_a_line_comment(self, sql: str) -> None:
        assert _wrapped("system.billing.usage") in scope_system_sql(sql, W)

    def test_line_comment_continuation_still_hides_the_next_line(self) -> None:
        sql = "SELECT 1 FROM main.a.b -- x\\\nsystem.billing.usage"
        assert scope_system_sql(sql, W) == sql

    @pytest.mark.parametrize(
        "sql",
        [
            "USE CATALOG system; USE SCHEMA billing; SELECT * FROM usage",
            "USE system.billing",
            "SET CATALOG system",
            "set schema billing",
            "SELECT 1; USE `system`",
        ],
    )
    def test_default_catalog_or_schema_change_raises(self, sql: str) -> None:
        with pytest.raises(RowScopeError, match="catalog or schema"):
            scope_system_sql(sql, W)

    def test_use_word_in_string_or_column_is_fine(self) -> None:
        sql = "SELECT 'USE CATALOG system' AS s, use_count FROM main.x.y"
        assert scope_system_sql(sql, W) == sql
