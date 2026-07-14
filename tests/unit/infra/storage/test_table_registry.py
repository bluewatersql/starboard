# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for table definition registry.

Tests cover:
- ColumnDef creation and SQL generation
- TableDef creation and DDL generation
- Table registration and lookup
"""

from __future__ import annotations

from starboard.infra.storage.table_registry import (
    ColumnDef,
    TableDef,
    TableRegistry,
)


class TestColumnDef:
    """Tests for ColumnDef model."""

    def test_create_basic_column(self) -> None:
        """Test creating a basic column definition."""
        col = ColumnDef(
            name="warehouse_id",
            data_type="STRING",
        )

        assert col.name == "warehouse_id"
        assert col.data_type == "STRING"
        assert col.nullable is True
        assert col.comment is None

    def test_create_column_with_all_options(self) -> None:
        """Test creating a column with all options."""
        col = ColumnDef(
            name="total_cost",
            data_type="DOUBLE",
            nullable=False,
            comment="Total cost in USD",
        )

        assert col.name == "total_cost"
        assert col.data_type == "DOUBLE"
        assert col.nullable is False
        assert col.comment == "Total cost in USD"

    def test_to_sql_nullable(self) -> None:
        """Test SQL generation for nullable column."""
        col = ColumnDef(
            name="description",
            data_type="STRING",
            nullable=True,
        )

        sql = col.to_sql()
        assert sql == "description STRING"

    def test_to_sql_not_null(self) -> None:
        """Test SQL generation for NOT NULL column."""
        col = ColumnDef(
            name="warehouse_id",
            data_type="STRING",
            nullable=False,
        )

        sql = col.to_sql()
        assert sql == "warehouse_id STRING NOT NULL"

    def test_to_sql_with_comment(self) -> None:
        """Test SQL generation with comment."""
        col = ColumnDef(
            name="created_at",
            data_type="TIMESTAMP",
            nullable=False,
            comment="Creation timestamp",
        )

        sql = col.to_sql()
        assert sql == "created_at TIMESTAMP NOT NULL COMMENT 'Creation timestamp'"


class TestTableDef:
    """Tests for TableDef model."""

    def test_create_simple_table(self) -> None:
        """Test creating a simple table definition."""
        table = TableDef(
            table_id="test_table",
            table_name="test_data",
            columns=(
                ColumnDef("id", "STRING", nullable=False),
                ColumnDef("value", "INT"),
            ),
            primary_key=("id",),
        )

        assert table.table_id == "test_table"
        assert table.table_name == "test_data"
        assert len(table.columns) == 2
        assert table.primary_key == ("id",)

    def test_get_full_name(self) -> None:
        """Test getting fully qualified table name."""
        table = TableDef(
            table_id="test",
            table_name="my_table",
            columns=(),
            primary_key=(),
        )

        full_name = table.get_full_name("my_catalog", "my_schema")
        assert full_name == "my_catalog.my_schema.my_table"

    def test_to_create_ddl_simple(self) -> None:
        """Test DDL generation for simple table."""
        table = TableDef(
            table_id="test",
            table_name="test_table",
            columns=(
                ColumnDef("id", "STRING", nullable=False),
                ColumnDef("value", "INT"),
            ),
            primary_key=("id",),
        )

        ddl = table.to_create_ddl("cat", "sch")

        assert "CREATE TABLE IF NOT EXISTS cat.sch.test_table" in ddl
        assert "id STRING NOT NULL" in ddl
        assert "value INT" in ddl

    def test_to_create_ddl_with_partitioning(self) -> None:
        """Test DDL generation with partitioning."""
        table = TableDef(
            table_id="test",
            table_name="partitioned_table",
            columns=(
                ColumnDef("id", "STRING", nullable=False),
                ColumnDef("date_key", "DATE"),
            ),
            primary_key=("id",),
            partition_by=("date_key",),
        )

        ddl = table.to_create_ddl("cat", "sch")

        assert "PARTITIONED BY (date_key)" in ddl

    def test_to_create_ddl_with_clustering(self) -> None:
        """Test DDL generation with clustering."""
        table = TableDef(
            table_id="test",
            table_name="clustered_table",
            columns=(
                ColumnDef("id", "STRING", nullable=False),
                ColumnDef("warehouse_id", "STRING"),
            ),
            primary_key=("id",),
            cluster_by=("warehouse_id",),
        )

        ddl = table.to_create_ddl("cat", "sch")

        assert "CLUSTER BY (warehouse_id)" in ddl

    def test_to_create_ddl_with_comment(self) -> None:
        """Test DDL generation with table comment."""
        table = TableDef(
            table_id="test",
            table_name="documented_table",
            columns=(ColumnDef("id", "STRING", nullable=False),),
            primary_key=("id",),
            comment="This is a test table",
        )

        ddl = table.to_create_ddl("cat", "sch")

        assert "COMMENT 'This is a test table'" in ddl

    def test_to_create_ddl_with_properties(self) -> None:
        """Test DDL generation with table properties."""
        table = TableDef(
            table_id="test",
            table_name="props_table",
            columns=(ColumnDef("id", "STRING", nullable=False),),
            primary_key=("id",),
            properties={"delta.autoOptimize.optimizeWrite": "true"},
        )

        ddl = table.to_create_ddl("cat", "sch")

        assert "TBLPROPERTIES" in ddl
        assert "delta.autoOptimize.optimizeWrite" in ddl


class TestTableRegistry:
    """Tests for TableRegistry."""

    def test_register_and_get_table(self) -> None:
        """Test registering and retrieving a table definition."""
        registry = TableRegistry()

        table = TableDef(
            table_id="my_table",
            table_name="actual_table_name",
            columns=(ColumnDef("id", "STRING"),),
            primary_key=("id",),
        )

        registry.register(table)

        retrieved = registry.get("my_table")
        assert retrieved is not None
        assert retrieved.table_name == "actual_table_name"

    def test_get_nonexistent_table(self) -> None:
        """Test getting a table that doesn't exist."""
        registry = TableRegistry()

        retrieved = registry.get("nonexistent")
        assert retrieved is None

    def test_register_multiple_tables(self) -> None:
        """Test registering multiple tables."""
        registry = TableRegistry()

        table1 = TableDef(
            table_id="table1",
            table_name="table_one",
            columns=(),
            primary_key=(),
        )
        table2 = TableDef(
            table_id="table2",
            table_name="table_two",
            columns=(),
            primary_key=(),
        )

        registry.register(table1)
        registry.register(table2)

        assert registry.get("table1") is not None
        assert registry.get("table2") is not None

    def test_list_all_tables(self) -> None:
        """Test listing all registered tables."""
        registry = TableRegistry()

        registry.register(
            TableDef(table_id="a", table_name="a", columns=(), primary_key=())
        )
        registry.register(
            TableDef(table_id="b", table_name="b", columns=(), primary_key=())
        )

        all_tables = registry.list_all()
        assert len(all_tables) == 2
        assert set(all_tables.keys()) == {"a", "b"}

    def test_registry_is_isolated(self) -> None:
        """Test that registry instances are isolated."""
        registry1 = TableRegistry()
        registry2 = TableRegistry()

        registry1.register(
            TableDef(table_id="only_in_1", table_name="t", columns=(), primary_key=())
        )

        assert registry1.get("only_in_1") is not None
        assert registry2.get("only_in_1") is None
