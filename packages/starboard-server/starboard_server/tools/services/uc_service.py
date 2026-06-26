# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""UC service facade -- backward-compatible delegation to focused sub-services.

This module preserves the original UCService interface while delegating
to focused sub-services under tools/services/uc/. All existing callers
continue to work without modification.

Sub-services:
    - CatalogBrowserService: asset enumeration, table discovery, enrichment
    - TableMetadataService: table metadata, fingerprints
    - LineageService: lineage queries
    - GovernanceService: grants, access patterns, policy coverage
    - SchemaOperationsService: schema analysis, drift, diff
    - StorageAnalysisService: history, optimization, impact, costs
"""

from __future__ import annotations

from typing import Any

from starboard_core.domain.analyzers import AnomalyThresholds
from starboard_core.domain.models.databricks import TableReference
from starboard_core.domain.models.uc import (
    AccessPatterns,
    CostBreakdown,
    DeltaHistory,
    PolicyCoverageReport,
    QueryImpactAnalysis,
    SchemaAnalysis,
    SchemaDiff,
    SchemaDriftAnalysis,
    StorageOptimizationReport,
    TableDiscoveryResult,
    TableFingerprint,
    TableGrants,
    TableLineage,
    UCAssetList,
    UCTableMetadata,
)

from starboard_server.tools.services.query_workload_service import (
    QueryWorkloadService,
)

# Re-export protocols and helpers for backward compatibility -- callers import
# these from uc_service directly (e.g., uc_tools.py imports SQLQueryProvider etc.)
from starboard_server.tools.services.uc.base import (  # noqa: F401
    LineageProvider,
    SQLQueryProvider,
    TableDiscoveryProvider,
    TableEnricherProvider,
    UCCatalogProvider,
)
from starboard_server.tools.services.uc.catalog_browser import CatalogBrowserService
from starboard_server.tools.services.uc.governance import GovernanceService
from starboard_server.tools.services.uc.lineage import LineageService
from starboard_server.tools.services.uc.schema_operations import (
    SchemaOperationsService,
)
from starboard_server.tools.services.uc.storage_analysis import StorageAnalysisService
from starboard_server.tools.services.uc.table_metadata import TableMetadataService


class UCService:
    """Facade for Unity Catalog operations -- delegates to focused sub-services.

    This class preserves the original UCService interface while internally
    routing each method to the appropriate sub-service. All existing callers
    (uc_tools.py, services/__init__.py, tests) continue to work unchanged.

    Example:
        >>> service = UCService(uc_provider, lineage_provider)
        >>> assets = await service.enumerate_assets("catalog", "schema")
        >>> len(assets.assets) > 0
        True
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
        """Initialize UC service facade with sub-services.

        Args:
            uc_provider: UC catalog provider
            lineage_provider: Optional lineage provider
            sql_provider: Optional SQL provider for system tables
            discovery_provider: Optional LLM-based table discovery provider
            enricher_provider: Optional table enricher for UC metadata
            workload_service: Optional query workload service for fingerprint/impact
        """
        # Store provider references for direct access by callers
        self.uc_provider = uc_provider
        self.lineage_provider = lineage_provider
        self.sql_provider = sql_provider
        self.discovery_provider = discovery_provider
        self.enricher_provider = enricher_provider
        self.workload_service = workload_service

        # Shared kwargs for sub-service construction
        provider_kwargs: dict[str, Any] = {
            "uc_provider": uc_provider,
            "lineage_provider": lineage_provider,
            "sql_provider": sql_provider,
            "discovery_provider": discovery_provider,
            "enricher_provider": enricher_provider,
            "workload_service": workload_service,
        }

        # Initialize sub-services
        self._catalog_browser = CatalogBrowserService(**provider_kwargs)
        self._table_metadata = TableMetadataService(**provider_kwargs)
        self._lineage = LineageService(**provider_kwargs)
        self._governance = GovernanceService(**provider_kwargs)
        self._schema_ops = SchemaOperationsService(**provider_kwargs)
        self._storage = StorageAnalysisService(**provider_kwargs)

    # =========================================================================
    # CatalogBrowserService delegates
    # =========================================================================

    async def enumerate_assets(
        self,
        catalog: str | None = None,
        schema: str | None = None,
        asset_type: str = "tables",
        limit: int = 100,
    ) -> UCAssetList:
        """Enumerate UC assets.

        Args:
            catalog: Catalog name (required for schemas/tables/volumes/functions)
            schema: Schema name (required for tables/volumes/functions)
            asset_type: Type of assets to enumerate
            limit: Maximum number of assets to return

        Returns:
            UCAssetList with enumerated assets
        """
        return await self._catalog_browser.enumerate_assets(
            catalog=catalog, schema=schema, asset_type=asset_type, limit=limit
        )

    async def discover_tables(
        self,
        sql_text: str | None = None,
        source_code: str | None = None,
        task_sources: dict[str, dict[str, str]] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> TableDiscoveryResult:
        """Discover tables from SQL text or source code using LLM.

        Args:
            sql_text: SQL query text
            source_code: Adhoc source code (Python/Scala/SQL)
            task_sources: Dictionary mapping task keys to source info
            budget: Optional budget for token tracking

        Returns:
            TableDiscoveryResult with categorized tables
        """
        return await self._catalog_browser.discover_tables(
            sql_text=sql_text,
            source_code=source_code,
            task_sources=task_sources,
            budget=budget,
        )

    async def enrich_table_references(
        self,
        table_references_data: list[dict[str, Any] | TableReference],
    ) -> tuple[list[TableReference], dict[str, dict[str, Any]]]:
        """Enrich table references with metadata from Unity Catalog and Delta history.

        Args:
            table_references_data: List of table references (dicts or TableReference)

        Returns:
            Tuple of (enriched table references, table metadata dict)
        """
        return await self._catalog_browser.enrich_table_references(
            table_references_data
        )

    # =========================================================================
    # TableMetadataService delegates
    # =========================================================================

    async def fetch_table_metadata(
        self,
        table_name: str,
    ) -> UCTableMetadata | None:
        """Fetch comprehensive table metadata.

        Args:
            table_name: Fully qualified table name

        Returns:
            UCTableMetadata or None if not found
        """
        return await self._table_metadata.fetch_table_metadata(table_name)

    async def fetch_table_fingerprint(
        self,
        table_name: str,
        window_days: int = 30,
    ) -> TableFingerprint | None:
        """Generate comprehensive table fingerprint using QueryWorkloadService.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)
            window_days: Analysis window in days (default 30)

        Returns:
            TableFingerprint with comprehensive analysis, or None if unavailable
        """
        return await self._table_metadata.fetch_table_fingerprint(
            table_name, window_days
        )

    # =========================================================================
    # LineageService delegates
    # =========================================================================

    async def fetch_table_lineage(
        self,
        table_name: str,
        max_items: int = 10,
    ) -> TableLineage:
        """Fetch table lineage with transformer for LLM context.

        Args:
            table_name: Fully qualified table name
            max_items: Maximum items to return per direction

        Returns:
            TableLineage with summarized upstream/downstream
        """
        return await self._lineage.fetch_table_lineage(table_name, max_items)

    # =========================================================================
    # GovernanceService delegates
    # =========================================================================

    async def fetch_table_grants(
        self,
        table_name: str,
    ) -> TableGrants | None:
        """Fetch table grants and effective permissions.

        Args:
            table_name: Fully qualified table name

        Returns:
            TableGrants or None if access denied
        """
        return await self._governance.fetch_table_grants(table_name)

    async def analyze_access_patterns(
        self,
        table_name: str,
        window_days: int = 30,
    ) -> AccessPatterns | None:
        """Analyze table access patterns from query history + lineage.

        Args:
            table_name: Fully qualified table name
            window_days: Days to look back

        Returns:
            AccessPatterns with comprehensive usage metrics
        """
        return await self._governance.analyze_access_patterns(table_name, window_days)

    async def analyze_policy_coverage(
        self,
        scope: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> PolicyCoverageReport | None:
        """Analyze security policy coverage.

        Args:
            scope: 'catalog', 'schema', or 'table'
            catalog: Catalog name (required for schema/table scope)
            schema: Schema name (required for table scope)

        Returns:
            PolicyCoverageReport or None if scope invalid
        """
        return await self._governance.analyze_policy_coverage(
            scope, catalog, schema, _catalog_browser=self._catalog_browser
        )

    # =========================================================================
    # SchemaOperationsService delegates
    # =========================================================================

    async def analyze_table_schema(
        self,
        table_name: str,
        thresholds: AnomalyThresholds | None = None,
    ) -> SchemaAnalysis | None:
        """Analyze table schema for patterns and anomalies.

        Args:
            table_name: Fully qualified table name
            thresholds: Optional custom thresholds

        Returns:
            SchemaAnalysis or None if table not found
        """
        return await self._schema_ops.analyze_table_schema(
            table_name, thresholds, _metadata_service=self._table_metadata
        )

    async def detect_schema_drift(
        self,
        table_name: str,
        versions_to_analyze: int = 50,
    ) -> SchemaDriftAnalysis | None:
        """Detect schema drift over time using DESCRIBE HISTORY.

        Args:
            table_name: Fully qualified table name
            versions_to_analyze: Number of history versions to analyze

        Returns:
            SchemaDriftAnalysis or None if history unavailable
        """
        return await self._schema_ops.detect_schema_drift(
            table_name, versions_to_analyze, _storage_service=self._storage
        )

    async def generate_schema_diff(
        self,
        table_name: str,
        version_from: int,
        version_to: int | None = None,
    ) -> SchemaDiff | None:
        """Generate schema diff between versions using DESCRIBE HISTORY.

        Args:
            table_name: Fully qualified table name
            version_from: Starting version
            version_to: Ending version (defaults to current)

        Returns:
            SchemaDiff with actual column changes, or None if unavailable
        """
        return await self._schema_ops.generate_schema_diff(
            table_name, version_from, version_to
        )

    # =========================================================================
    # StorageAnalysisService delegates
    # =========================================================================

    async def fetch_delta_history(
        self,
        table_name: str,
        limit: int = 50,
    ) -> DeltaHistory | None:
        """Fetch Delta table history.

        Args:
            table_name: Fully qualified table name
            limit: Maximum history entries

        Returns:
            DeltaHistory or None if not a Delta table
        """
        return await self._storage.fetch_delta_history(table_name, limit)

    async def recommend_storage_optimization(
        self,
        table_name: str,
    ) -> StorageOptimizationReport | None:
        """Generate storage optimization recommendations.

        Args:
            table_name: Fully qualified table name

        Returns:
            StorageOptimizationReport or None if metadata unavailable
        """
        return await self._storage.recommend_storage_optimization(
            table_name,
            _metadata_service=self._table_metadata,
            _governance_service=self._governance,
        )

    async def analyze_query_impact(
        self,
        table_names: list[str],
        query_pattern: str | None = None,
    ) -> QueryImpactAnalysis | None:
        """Analyze query performance impact for table joins.

        Args:
            table_names: Tables involved in query
            query_pattern: Optional query pattern hint

        Returns:
            QueryImpactAnalysis or None if metadata unavailable
        """
        return await self._storage.analyze_query_impact(
            table_names, query_pattern, _metadata_service=self._table_metadata
        )

    async def attribute_table_costs(
        self,
        table_name: str,
        window_days: int = 30,
    ) -> CostBreakdown | None:
        """Attribute costs to a table.

        Args:
            table_name: Fully qualified table name
            window_days: Analysis window

        Returns:
            CostBreakdown or None if data unavailable
        """
        return await self._storage.attribute_table_costs(
            table_name, window_days, _metadata_service=self._table_metadata
        )
