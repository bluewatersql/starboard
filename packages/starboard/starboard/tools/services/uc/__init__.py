# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""UC sub-services package.

Re-exports all sub-services and protocols for convenient access.
The UCService facade in the parent uc_service.py module delegates
to these focused sub-services.
"""

from starboard.tools.services.uc.base import (
    LineageProvider,
    SQLQueryProvider,
    TableDiscoveryProvider,
    TableEnricherProvider,
    UCCatalogProvider,
    UCServiceBase,
    classify_table_type,
    detect_principal_type,
    parse_timestamp,
    safe_int,
)
from starboard.tools.services.uc.catalog_browser import CatalogBrowserService
from starboard.tools.services.uc.governance import GovernanceService
from starboard.tools.services.uc.lineage import LineageService
from starboard.tools.services.uc.schema_operations import (
    SchemaOperationsService,
)
from starboard.tools.services.uc.storage_analysis import StorageAnalysisService
from starboard.tools.services.uc.table_metadata import TableMetadataService

__all__ = [
    # Protocols
    "LineageProvider",
    "SQLQueryProvider",
    "TableDiscoveryProvider",
    "TableEnricherProvider",
    "UCCatalogProvider",
    # Base
    "UCServiceBase",
    # Sub-services
    "CatalogBrowserService",
    "GovernanceService",
    "LineageService",
    "SchemaOperationsService",
    "StorageAnalysisService",
    "TableMetadataService",
    # Helpers
    "classify_table_type",
    "detect_principal_type",
    "parse_timestamp",
    "safe_int",
]
