# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog table storage adapter.

This module provides a standardized interface for agents to read/write
Delta Lake tables stored in Unity Catalog. Features include:

- Abstract agent interaction with UC tables (read/write)
- Automatic catalog, schema & table creation
- SQL-based CRUD operations via Databricks SQL warehouse
- Typed repository pattern for domain models

Example:
    ```python
    from starboard_server.infra.storage import (
        UCStorageAdapter,
        UCStorageConfig,
        UCRepository,
        TableDef,
        ColumnDef,
        TableRegistry,
    )

    # Define a table
    registry = TableRegistry()
    registry.register(
        TableDef(
            table_id="warehouse_slo",
            table_name="warehouse_slo_config",
            columns=(
                ColumnDef("warehouse_id", "STRING", nullable=False),
                ColumnDef("p95_target", "DOUBLE"),
            ),
            primary_key=("warehouse_id",),
        )
    )

    # Create adapter
    config = UCStorageConfig.from_env()
    adapter = UCStorageAdapter(workspace_client, config, registry)

    # Use typed repository
    repo = UCRepository(adapter, "warehouse_slo", WarehouseSLOConfig)
    slo = await repo.get(warehouse_id="wh-123")
    ```
"""

from starboard_server.infra.storage.repository import UCRepository
from starboard_server.infra.storage.table_registry import (
    ColumnDef,
    TableDef,
    TableRegistry,
)
from starboard_server.infra.storage.uc_adapter import (
    UCStorageAdapter,
    UCStorageConfig,
)

__all__ = [
    # Config
    "UCStorageConfig",
    # Adapter
    "UCStorageAdapter",
    # Registry
    "ColumnDef",
    "TableDef",
    "TableRegistry",
    # Repository
    "UCRepository",
]
