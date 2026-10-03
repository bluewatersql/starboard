# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared base utilities and protocols for UC sub-services.

Contains provider protocols, helper functions, and the common base class
that all UC sub-services inherit from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from starboard.infra.observability.logging import get_logger
from starboard.tools.domain.utils import safe_int as _utils_safe_int
from starboard.tools.services.query_workload_service import (
    QueryWorkloadService,
)

logger = get_logger(__name__)


# =============================================================================
# Provider Protocols
# =============================================================================


class UCCatalogProvider(Protocol):
    """Protocol for Unity Catalog API access (async)."""

    async def list_catalogs(self, limit: int = 100) -> list[dict[str, Any]]:
        """List catalogs."""
        ...

    async def list_schemas(
        self, catalog_name: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List schemas in a catalog."""
        ...

    async def list_tables(
        self, catalog_name: str, schema_name: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List tables in a schema."""
        ...

    async def list_volumes(
        self, catalog_name: str, schema_name: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List volumes in a schema."""
        ...

    async def list_functions(
        self, catalog_name: str, schema_name: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List functions in a schema."""
        ...

    async def get_table(
        self, full_name: str, include_delta_metadata: bool = True
    ) -> dict[str, Any] | None:
        """Get table metadata."""
        ...

    async def get_grants(
        self, securable_type: Any, full_name: str
    ) -> dict[str, Any] | None:
        """Get grants for a securable."""
        ...

    async def get_effective_grants(
        self, securable_type: Any, full_name: str
    ) -> dict[str, Any] | None:
        """Get effective grants for a securable."""
        ...


class LineageProvider(Protocol):
    """Protocol for lineage API access (async)."""

    async def get_table_lineage(
        self, table_name: str, include_entity_lineage: bool = True
    ) -> dict[str, Any] | None:
        """Get table lineage."""
        ...


class SQLQueryProvider(Protocol):
    """Protocol for SQL query execution (system tables)."""

    async def execute_query(self, query: str) -> list[dict[str, Any]]:
        """Execute SQL query and return results."""
        ...


class TableDiscoveryProvider(Protocol):
    """Protocol for table discovery from source code (LLM-based)."""

    async def extract_tables(
        self, source_text: str, budget: dict[str, Any] | None = None
    ) -> list[Any]:
        """Extract table references from source code."""
        ...


class TableEnricherProvider(Protocol):
    """Protocol for enriching table references with metadata."""

    async def enrich_tables(self, table_references: list[Any]) -> None:
        """Enrich table references in-place with metadata."""
        ...


# =============================================================================
# Helper Functions
# =============================================================================


def parse_timestamp(value: Any) -> datetime | None:
    """Parse timestamp from various formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Assume milliseconds
        return datetime.fromtimestamp(value / 1000)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return None
    return None


def safe_int(value: Any) -> int | None:
    """Safely convert to int, returning None on failure.

    Delegates to the canonical implementation in tools.domain.utils with
    default=None to preserve the original None-on-failure semantics that
    UC sub-service callers rely on.

    Args:
        value: Value to convert to int.

    Returns:
        Integer value or None if conversion fails.
    """
    return _utils_safe_int(value, default=None)


def classify_table_type(table_dict: dict[str, Any]) -> str:
    """Classify table type from raw dict."""
    table_type = table_dict.get("table_type", "")
    if table_type == "VIEW":
        return "view"
    return "table"


def detect_principal_type(principal: str) -> str:
    """Detect principal type from name."""
    if "@" in principal:
        return "USER"
    if principal.startswith("group:") or "group" in principal.lower():
        return "GROUP"
    if "service" in principal.lower() or "principal" in principal.lower():
        return "SERVICE_PRINCIPAL"
    return "USER"  # Default assumption


class UCServiceBase:
    """Base class for UC sub-services with shared provider references.

    Sub-services receive provider references from the facade UCService
    and share common utility methods.
    """

    def __init__(
        self,
        uc_provider: UCCatalogProvider,
        lineage_provider: LineageProvider | None = None,
        sql_provider: SQLQueryProvider | None = None,
        discovery_provider: TableDiscoveryProvider | None = None,
        enricher_provider: TableEnricherProvider | None = None,
        workload_service: QueryWorkloadService | None = None,
    ) -> None:
        """Initialize with shared provider references.

        Args:
            uc_provider: UC catalog provider
            lineage_provider: Optional lineage provider
            sql_provider: Optional SQL provider for system tables
            discovery_provider: Optional LLM-based table discovery provider
            enricher_provider: Optional table enricher for UC metadata
            workload_service: Optional query workload service for fingerprint/impact
        """
        self.uc_provider = uc_provider
        self.lineage_provider = lineage_provider
        self.sql_provider = sql_provider
        self.discovery_provider = discovery_provider
        self.enricher_provider = enricher_provider
        self.workload_service = workload_service
