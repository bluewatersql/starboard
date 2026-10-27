# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Table definition registry for UC storage.

This module provides data structures for defining Unity Catalog tables
and a registry for managing table definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnDef:
    """Column definition for UC table.

    Attributes:
        name: Column name.
        data_type: SQL data type (STRING, INT, DOUBLE, TIMESTAMP, etc.).
        nullable: Whether the column allows NULL values.
        comment: Optional column description.

    Example:
        ```python
        col = ColumnDef(
            name="warehouse_id",
            data_type="STRING",
            nullable=False,
            comment="Unique warehouse identifier",
        )
        ```
    """

    name: str
    data_type: str
    nullable: bool = True
    comment: str | None = None

    def to_sql(self) -> str:
        """Generate column DDL fragment.

        Returns:
            SQL column definition string.

        Example:
            >>> col = ColumnDef("id", "STRING", nullable=False)
            >>> col.to_sql()
            'id STRING NOT NULL'
        """
        parts = [self.name, self.data_type]

        if not self.nullable:
            parts.append("NOT NULL")

        if self.comment:
            # Escape single quotes in comment
            escaped_comment = self.comment.replace("'", "''")
            parts.append(f"COMMENT '{escaped_comment}'")

        return " ".join(parts)


@dataclass(frozen=True)
class TableDef:
    """Table definition for UC storage.

    Defines the schema and properties for a Unity Catalog table.

    Attributes:
        table_id: Unique identifier for this table type (for registry lookup).
        table_name: Actual table name (without catalog/schema).
        columns: Tuple of column definitions.
        primary_key: Column names that form the primary key (for upserts).
        partition_by: Optional columns to partition by.
        cluster_by: Optional columns to cluster by.
        comment: Optional table description.
        properties: Optional table properties.

    Example:
        ```python
        table = TableDef(
            table_id="warehouse_slo",
            table_name="warehouse_slo_config",
            columns=(
                ColumnDef("warehouse_id", "STRING", nullable=False),
                ColumnDef("p95_target", "DOUBLE"),
            ),
            primary_key=("warehouse_id",),
            comment="SLO configurations for warehouses",
        )
        ```
    """

    table_id: str
    table_name: str
    columns: tuple[ColumnDef, ...]
    primary_key: tuple[str, ...]

    # Optional
    partition_by: tuple[str, ...] = ()
    cluster_by: tuple[str, ...] = ()
    comment: str | None = None
    properties: dict[str, str] = field(default_factory=dict)

    def get_full_name(self, catalog: str, schema: str) -> str:
        """Get fully qualified table name.

        Args:
            catalog: Catalog name.
            schema: Schema name.

        Returns:
            Fully qualified table name (catalog.schema.table).
        """
        return f"{catalog}.{schema}.{self.table_name}"

    def to_create_ddl(self, catalog: str, schema: str) -> str:
        """Generate CREATE TABLE DDL statement.

        Args:
            catalog: Catalog name.
            schema: Schema name.

        Returns:
            CREATE TABLE IF NOT EXISTS DDL statement.
        """
        full_name = self.get_full_name(catalog, schema)

        # Build column definitions
        columns_sql = ",\n  ".join(col.to_sql() for col in self.columns)

        ddl = f"CREATE TABLE IF NOT EXISTS {full_name} (\n  {columns_sql}\n)"

        # Add partitioning
        if self.partition_by:
            ddl += f"\nPARTITIONED BY ({', '.join(self.partition_by)})"

        # Add clustering
        if self.cluster_by:
            ddl += f"\nCLUSTER BY ({', '.join(self.cluster_by)})"

        # Add comment
        if self.comment:
            escaped_comment = self.comment.replace("'", "''")
            ddl += f"\nCOMMENT '{escaped_comment}'"

        # Add table properties
        if self.properties:
            props = ", ".join(f"'{k}' = '{v}'" for k, v in self.properties.items())
            ddl += f"\nTBLPROPERTIES ({props})"

        return ddl


class TableRegistry:
    """Registry for table definitions.

    Manages table definitions and provides lookup by table_id.
    Each registry instance is isolated - useful for testing.

    Example:
        ```python
        registry = TableRegistry()
        registry.register(my_table_def)

        table = registry.get("my_table")
        if table:
            ddl = table.to_create_ddl("catalog", "schema")
        ```
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._tables: dict[str, TableDef] = {}

    def register(self, table_def: TableDef) -> None:
        """Register a table definition.

        Args:
            table_def: Table definition to register.
        """
        self._tables[table_def.table_id] = table_def

    def get(self, table_id: str) -> TableDef | None:
        """Get table definition by ID.

        Args:
            table_id: Unique table identifier.

        Returns:
            Table definition if found, None otherwise.
        """
        return self._tables.get(table_id)

    def list_all(self) -> dict[str, TableDef]:
        """List all registered tables.

        Returns:
            Dictionary of table_id -> TableDef.
        """
        return dict(self._tables)
