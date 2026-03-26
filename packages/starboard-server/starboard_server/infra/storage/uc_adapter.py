"""Unity Catalog storage adapter.

This module provides the UCStorageAdapter class for reading and writing
data to Unity Catalog tables via Databricks SQL warehouse.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

from starboard_server.adapters.databricks.services.base import run_databricks_sync
from starboard_server.infra.observability.logging import get_logger
from starboard_server.exceptions import DatabricksAPIError
from starboard_server.infra.storage.table_registry import TableDef, TableRegistry

logger = get_logger(__name__)


class InvalidColumnError(ValueError):
    """Raised when an invalid column name is used in a query.

    This prevents SQL injection through column names by validating
    all column references against the table schema.
    """

    pass


@dataclass
class UCStorageConfig:
    """Configuration for UC storage adapter.

    Attributes:
        catalog: Unity Catalog name.
        schema: Schema name within the catalog.
        warehouse_id: SQL warehouse ID for executing queries.
        auto_create_catalog: Whether to auto-create catalog if missing.
        auto_create_schema: Whether to auto-create schema if missing.
        auto_create_tables: Whether to auto-create tables if missing.
    """

    catalog: str = "starboard"
    schema: str = "agent_state"
    warehouse_id: str | None = None

    # Auto-creation options
    auto_create_catalog: bool = True
    auto_create_schema: bool = True
    auto_create_tables: bool = True

    @classmethod
    def from_env(cls) -> UCStorageConfig:
        """Create configuration from environment variables.

        Environment variables:
            STARBOARD_UC_CATALOG: Catalog name (default: starboard)
            STARBOARD_UC_SCHEMA: Schema name (default: agent_state)
            STARBOARD_WAREHOUSE_ID: SQL warehouse ID

        Returns:
            Configuration instance.
        """
        return cls(
            catalog=os.getenv("STARBOARD_UC_CATALOG", "starboard"),
            schema=os.getenv("STARBOARD_UC_SCHEMA", "agent_state"),
            warehouse_id=os.getenv("STARBOARD_WAREHOUSE_ID"),
        )


class UCStorageAdapter:
    """Unity Catalog table storage adapter.

    Provides abstract read/write access to Delta tables stored in UC.
    All queries execute via SQL warehouse (not direct file access).

    This adapter handles:
    - SQL query building for CRUD operations
    - Value formatting for SQL statements
    - Result parsing from Databricks SQL responses

    Example:
        ```python
        client = WorkspaceClient()
        config = UCStorageConfig.from_env()
        registry = TableRegistry()
        # ... register tables ...

        adapter = UCStorageAdapter(client, config, registry)
        await adapter.initialize()

        # Read rows
        rows = await adapter.read("my_table", filters={"status": "active"})

        # Write row
        await adapter.upsert("my_table", {"id": "123", "status": "active"})
        ```
    """

    def __init__(
        self,
        workspace_client: Any,  # databricks.sdk.WorkspaceClient
        config: UCStorageConfig,
        registry: TableRegistry,
    ) -> None:
        """Initialize the storage adapter.

        Args:
            workspace_client: Databricks workspace client.
            config: Storage configuration.
            registry: Table definition registry.
        """
        self.client = workspace_client
        self.config = config
        self.registry = registry
        self._initialized_tables: set[str] = set()

    async def initialize(self) -> None:
        """Initialize storage - create catalog, schema, and tables if needed.

        Called once at startup or lazily on first access.
        """
        if self.config.auto_create_catalog:
            await self._ensure_catalog_exists()

        if self.config.auto_create_schema:
            await self._ensure_schema_exists()

        if self.config.auto_create_tables:
            await self._ensure_tables_exist()

        logger.debug(
            "uc_storage_initialized",
            catalog=self.config.catalog,
            schema=self.config.schema,
            tables=list(self._initialized_tables),
        )

    async def _ensure_catalog_exists(self) -> None:
        """Create catalog if it doesn't exist.

        Uses the dedicated Databricks thread pool to avoid blocking the
        event loop with synchronous SDK calls.
        """
        try:
            await run_databricks_sync(self.client.catalogs.get, self.config.catalog)
        except DatabricksAPIError:
            # Catalog doesn't exist, create it
            logger.debug("creating_catalog", catalog=self.config.catalog)
            await run_databricks_sync(
                partial(
                    self.client.catalogs.create,
                    name=self.config.catalog,
                    comment="Starboard AI Agent state storage",
                ),
            )

    async def _ensure_schema_exists(self) -> None:
        """Create schema if it doesn't exist.

        Uses the dedicated Databricks thread pool to avoid blocking the
        event loop with synchronous SDK calls.
        """
        full_schema = f"{self.config.catalog}.{self.config.schema}"
        try:
            await run_databricks_sync(self.client.schemas.get, full_schema)
        except DatabricksAPIError:
            # Schema doesn't exist, create it
            logger.debug("creating_schema", schema=full_schema)
            await run_databricks_sync(
                partial(
                    self.client.schemas.create,
                    catalog_name=self.config.catalog,
                    name=self.config.schema,
                    comment="Agent state and configuration storage",
                ),
            )

    async def _ensure_tables_exist(self) -> None:
        """Create all registered tables if they don't exist."""
        for table_id, table_def in self.registry.list_all().items():
            await self._ensure_table_exists(table_def)
            self._initialized_tables.add(table_id)

    async def _ensure_table_exists(self, table_def: TableDef) -> None:
        """Create a single table if it doesn't exist."""
        ddl = table_def.to_create_ddl(self.config.catalog, self.config.schema)
        await self._execute_statement(ddl)
        logger.debug("ensured_table_exists", table_name=table_def.table_name)

    # =========================================================================
    # Read Operations
    # =========================================================================

    async def read(
        self,
        table_id: str,
        filters: dict[str, Any] | None = None,
        columns: list[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read rows from a table.

        Args:
            table_id: Registered table identifier.
            filters: Column filters (equality only).
            columns: Columns to select (default: all).
            order_by: ORDER BY clause.
            limit: Max rows to return.

        Returns:
            List of row dictionaries.

        Raises:
            ValueError: If table_id is not registered.
        """
        query = self._build_read_query(table_id, columns, filters, order_by, limit)
        return await self._execute_query(query)

    async def read_one(
        self,
        table_id: str,
        filters: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Read a single row by filters.

        Args:
            table_id: Registered table identifier.
            filters: Column filters to identify the row.

        Returns:
            Row dictionary if found, None otherwise.
        """
        results = await self.read(table_id, filters=filters, limit=1)
        return results[0] if results else None

    async def exists(
        self,
        table_id: str,
        filters: dict[str, Any],
    ) -> bool:
        """Check if a row exists.

        Args:
            table_id: Registered table identifier.
            filters: Column filters to check.

        Returns:
            True if row exists, False otherwise.
        """
        result = await self.read_one(table_id, filters)
        return result is not None

    # =========================================================================
    # Write Operations
    # =========================================================================

    async def write(
        self,
        table_id: str,
        row: dict[str, Any],
    ) -> None:
        """Insert a single row.

        Args:
            table_id: Registered table identifier.
            row: Row data as dictionary.
        """
        query = self._build_insert_query(table_id, row)
        await self._execute_statement(query)

    async def upsert(
        self,
        table_id: str,
        row: dict[str, Any],
    ) -> None:
        """Insert or update a row based on primary key.

        Uses MERGE INTO for atomic upsert.

        Args:
            table_id: Registered table identifier.
            row: Row data as dictionary.
        """
        query = self._build_upsert_query(table_id, row)
        await self._execute_statement(query)

    async def delete(
        self,
        table_id: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete rows matching filters.

        Args:
            table_id: Registered table identifier.
            filters: Column filters for deletion.

        Returns:
            Number of rows deleted (may be -1 if not available).
        """
        query = self._build_delete_query(table_id, filters)
        await self._execute_statement(query)
        return -1  # Delta doesn't return affected row count easily

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def write_batch(
        self,
        table_id: str,
        rows: list[dict[str, Any]],
    ) -> None:
        """Insert multiple rows efficiently.

        Args:
            table_id: Registered table identifier.
            rows: List of row dictionaries.
        """
        if not rows:
            return

        query = self._build_batch_insert_query(table_id, rows)
        await self._execute_statement(query)

    # =========================================================================
    # Query Building (Internal)
    # =========================================================================

    def _build_read_query(
        self,
        table_id: str,
        columns: list[str] | None,
        filters: dict[str, Any] | None,
        order_by: str | None,
        limit: int | None,
    ) -> str:
        """Build a SELECT query.

        All column names are validated against the table schema to prevent
        SQL injection through column name manipulation.
        """
        table_def = self._get_table_def(table_id)
        full_name = table_def.get_full_name(self.config.catalog, self.config.schema)
        valid_columns = self._get_valid_columns(table_def)

        # Validate SELECT columns
        if columns:
            self._validate_columns(columns, valid_columns, context="SELECT")
            select_cols = ", ".join(columns)
        else:
            select_cols = "*"

        # Build query
        query = f"SELECT {select_cols} FROM {full_name}"

        # Validate and add WHERE clause
        if filters:
            self._validate_columns(
                list(filters.keys()), valid_columns, context="filter"
            )
            conditions = self._build_where_conditions(filters)
            query += " WHERE " + " AND ".join(conditions)

        # Validate and add ORDER BY
        if order_by:
            self._validate_order_by(order_by, valid_columns)
            query += f" ORDER BY {order_by}"

        # Add LIMIT
        if limit:
            query += f" LIMIT {limit}"

        return query

    def _build_insert_query(
        self,
        table_id: str,
        row: dict[str, Any],
    ) -> str:
        """Build an INSERT query.

        Column names are validated against the table schema.
        """
        table_def = self._get_table_def(table_id)
        full_name = table_def.get_full_name(self.config.catalog, self.config.schema)
        valid_columns = self._get_valid_columns(table_def)

        columns = list(row.keys())
        self._validate_columns(columns, valid_columns, context="INSERT")
        values = [self._format_value(v) for v in row.values()]

        return f"""
            INSERT INTO {full_name} ({", ".join(columns)})
            VALUES ({", ".join(values)})
        """

    def _build_upsert_query(
        self,
        table_id: str,
        row: dict[str, Any],
    ) -> str:
        """Build a MERGE (upsert) query."""
        table_def = self._get_table_def(table_id)
        full_name = table_def.get_full_name(self.config.catalog, self.config.schema)

        # Build primary key match condition
        pk_conditions = " AND ".join(
            f"target.{pk} = source.{pk}" for pk in table_def.primary_key
        )

        columns = list(row.keys())
        values = [self._format_value(v) for v in row.values()]

        # Build source select
        source_cols = ", ".join(f"{v} AS {c}" for c, v in zip(columns, values))

        # Build update set (exclude primary key columns)
        update_cols = [c for c in columns if c not in table_def.primary_key]
        update_set = ", ".join(f"target.{col} = source.{col}" for col in update_cols)

        # Build insert columns and values
        insert_cols = ", ".join(columns)
        insert_vals = ", ".join(f"source.{col}" for col in columns)

        return f"""
            MERGE INTO {full_name} AS target
            USING (SELECT {source_cols}) AS source
            ON {pk_conditions}
            WHEN MATCHED THEN UPDATE SET {update_set}
            WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
        """

    def _build_delete_query(
        self,
        table_id: str,
        filters: dict[str, Any],
    ) -> str:
        """Build a DELETE query.

        Filter column names are validated against the table schema.
        """
        table_def = self._get_table_def(table_id)
        full_name = table_def.get_full_name(self.config.catalog, self.config.schema)
        valid_columns = self._get_valid_columns(table_def)

        self._validate_columns(
            list(filters.keys()), valid_columns, context="DELETE filter"
        )
        conditions = self._build_where_conditions(filters)

        return f"DELETE FROM {full_name} WHERE {' AND '.join(conditions)}"

    def _build_batch_insert_query(
        self,
        table_id: str,
        rows: list[dict[str, Any]],
    ) -> str:
        """Build a batch INSERT query."""
        table_def = self._get_table_def(table_id)
        full_name = table_def.get_full_name(self.config.catalog, self.config.schema)

        columns = list(rows[0].keys())

        values_list = []
        for row in rows:
            values = [self._format_value(row.get(col)) for col in columns]
            values_list.append(f"({', '.join(values)})")

        return f"""
            INSERT INTO {full_name} ({", ".join(columns)})
            VALUES {", ".join(values_list)}
        """

    def _build_where_conditions(self, filters: dict[str, Any]) -> list[str]:
        """Build WHERE clause conditions."""
        conditions = []
        for col, val in filters.items():
            if val is None:
                conditions.append(f"{col} IS NULL")
            elif isinstance(val, str):
                escaped = val.replace("'", "''")
                conditions.append(f"{col} = '{escaped}'")
            else:
                conditions.append(f"{col} = {val}")
        return conditions

    # =========================================================================
    # Query Execution (Internal)
    # =========================================================================

    async def _execute_query(self, query: str) -> list[dict[str, Any]]:
        """Execute a SELECT query and return results.

        Uses the dedicated Databricks thread pool to avoid blocking the
        event loop with synchronous SDK calls.
        """
        logger.debug("executing_query", query_preview=query[:200])

        # Execute via SQL warehouse (wrapped for async)
        response = await run_databricks_sync(
            lambda: self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id,
                statement=query,
                wait_timeout="30s",
            )
        )

        if response.status.state != "SUCCEEDED":
            error_msg = (
                response.status.error.message
                if response.status.error
                else "Unknown error"
            )
            raise RuntimeError(f"Query failed: {error_msg}")

        # Convert to list of dicts
        if not response.result or not response.result.data_array:
            return []

        columns = [col.name for col in response.manifest.schema.columns]
        return [dict(zip(columns, row)) for row in response.result.data_array]

    async def _execute_statement(self, statement: str) -> None:
        """Execute a DDL/DML statement.

        Uses the dedicated Databricks thread pool to avoid blocking the
        event loop with synchronous SDK calls.
        """
        logger.debug("executing_statement", statement_preview=statement[:200])

        response = await run_databricks_sync(
            lambda: self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id,
                statement=statement,
                wait_timeout="60s",
            )
        )

        if response.status.state != "SUCCEEDED":
            error_msg = (
                response.status.error.message
                if response.status.error
                else "Unknown error"
            )
            raise RuntimeError(f"Statement failed: {error_msg}")

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_table_def(self, table_id: str) -> TableDef:
        """Get table definition, raising if not found."""
        table_def = self.registry.get(table_id)
        if not table_def:
            raise ValueError(f"Unknown table: {table_id}")
        return table_def

    def _get_valid_columns(self, table_def: TableDef) -> set[str]:
        """Get set of valid column names for a table.

        Args:
            table_def: Table definition.

        Returns:
            Set of valid column names.
        """
        return {col.name for col in table_def.columns}

    def _validate_columns(
        self,
        columns: list[str],
        valid_columns: set[str],
        context: str = "query",
    ) -> None:
        """Validate that all column names exist in the table schema.

        Args:
            columns: List of column names to validate.
            valid_columns: Set of valid column names from schema.
            context: Context for error message (e.g., "filter", "select").

        Raises:
            InvalidColumnError: If any column is not in the schema.
        """
        for col in columns:
            if col not in valid_columns:
                raise InvalidColumnError(
                    f"Invalid column '{col}' in {context}. "
                    f"Valid columns: {sorted(valid_columns)}"
                )

    def _validate_order_by(
        self,
        order_by: str,
        valid_columns: set[str],
    ) -> None:
        """Validate ORDER BY clause columns.

        Parses ORDER BY clause and validates each column name against schema.
        Handles: "col", "col ASC", "col DESC", "col1, col2 DESC"

        Args:
            order_by: ORDER BY clause string.
            valid_columns: Set of valid column names from schema.

        Raises:
            InvalidColumnError: If any column is not in the schema.
        """
        # Split by comma for multiple columns
        parts = [p.strip() for p in order_by.split(",")]

        for part in parts:
            # Extract column name (remove ASC/DESC suffix)
            col_match = re.match(r"^(\w+)(?:\s+(?:ASC|DESC))?$", part.strip(), re.I)
            if col_match:
                col_name = col_match.group(1)
                if col_name not in valid_columns:
                    raise InvalidColumnError(
                        f"Invalid column '{col_name}' in ORDER BY. "
                        f"Valid columns: {sorted(valid_columns)}"
                    )

    def _format_value(self, value: Any) -> str:
        """Format a Python value for SQL.

        Args:
            value: Python value to format.

        Returns:
            SQL-formatted string.
        """
        if value is None:
            return "NULL"
        elif isinstance(value, str):
            # Escape single quotes
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        elif isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        elif isinstance(value, datetime):
            return f"TIMESTAMP'{value.isoformat()}'"
        elif isinstance(value, dict):
            escaped = json.dumps(value).replace("'", "''")
            return f"'{escaped}'"
        else:
            # Escape single quotes in the string representation to prevent injection
            str_val = str(value)
            if "'" in str_val:
                escaped = str_val.replace("'", "''")
                return f"'{escaped}'"
            return str_val
