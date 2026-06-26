# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Databricks service layer.

Provides async services for Databricks SDK operations.

Services:
    - BaseService: Base class with async patterns
    - JobService: Job management and execution
    - SQLService: SQL query execution
    - ClusterService: Cluster management
    - WarehouseService: SQL warehouse management
    - CatalogService: Unity Catalog operations
    - WorkspaceService: Workspace and DBFS operations
    - UsersService: User authentication and identity
"""

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.adapters.databricks.services.catalog import CatalogService
from starboard_server.adapters.databricks.services.clusters import ClusterService
from starboard_server.adapters.databricks.services.jobs import JobService
from starboard_server.adapters.databricks.services.sql import (
    DEFAULT_MAX_ROWS,
    RowLimitExceededError,
    SQLService,
)
from starboard_server.adapters.databricks.services.users import UsersService
from starboard_server.adapters.databricks.services.warehouses import WarehouseService
from starboard_server.adapters.databricks.services.workspace import WorkspaceService

__all__ = [
    "BaseService",
    "CatalogService",
    "ClusterService",
    "DEFAULT_MAX_ROWS",
    "JobService",
    "RowLimitExceededError",
    "SQLService",
    "UsersService",
    "WarehouseService",
    "WorkspaceService",
]
