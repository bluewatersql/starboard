# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Catalog browser service for UC asset enumeration and discovery.

Handles catalog/schema/table browsing, LLM-based table discovery,
and table reference enrichment.
"""

from __future__ import annotations

from typing import Any

from starboard_core.domain.analyzers import TableAnalyzer
from starboard_core.domain.models.databricks import TableReference
from starboard_core.domain.models.uc import (
    TableDiscoveryResult,
    UCAssetInfo,
    UCAssetList,
)

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.services.uc.base import (
    UCServiceBase,
    classify_table_type,
    parse_timestamp,
)

logger = get_logger(__name__)


class CatalogBrowserService(UCServiceBase):
    """Service for browsing UC assets and discovering tables."""

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
                (catalogs/schemas/tables/volumes/functions)
            limit: Maximum number of assets to return

        Returns:
            UCAssetList with enumerated assets

        Raises:
            ValueError: If required parameters are missing
        """
        logger.debug(
            "enumerating_assets", asset_type=asset_type, catalog=catalog, schema=schema
        )

        if asset_type == "catalogs":
            raw_assets = await self.uc_provider.list_catalogs(limit=limit)
            assets = tuple(
                UCAssetInfo(
                    name=a.get("name", ""),
                    full_name=a.get("name", ""),
                    asset_type="catalog",
                    owner=a.get("owner"),
                    created_at=parse_timestamp(a.get("created_at")),
                    comment=a.get("comment"),
                )
                for a in raw_assets
            )
        elif asset_type == "schemas":
            if not catalog:
                raise ValueError("Catalog is required to list schemas")
            raw_assets = await self.uc_provider.list_schemas(catalog, limit=limit)
            assets = tuple(
                UCAssetInfo(
                    name=a.get("name", ""),
                    full_name=f"{catalog}.{a.get('name', '')}",
                    asset_type="schema",
                    owner=a.get("owner"),
                    created_at=parse_timestamp(a.get("created_at")),
                    comment=a.get("comment"),
                )
                for a in raw_assets
            )
        elif asset_type == "tables":
            if not catalog or not schema:
                raise ValueError("Catalog and schema are required to list tables")
            raw_assets = await self.uc_provider.list_tables(
                catalog, schema, limit=limit
            )
            assets = tuple(
                UCAssetInfo(
                    name=a.get("name", ""),
                    full_name=f"{catalog}.{schema}.{a.get('name', '')}",
                    asset_type=classify_table_type(a),
                    owner=a.get("owner"),
                    created_at=parse_timestamp(a.get("created_at")),
                    comment=a.get("comment"),
                )
                for a in raw_assets
            )
        elif asset_type == "volumes":
            if not catalog or not schema:
                raise ValueError("Catalog and schema are required to list volumes")
            raw_assets = await self.uc_provider.list_volumes(
                catalog, schema, limit=limit
            )
            assets = tuple(
                UCAssetInfo(
                    name=a.get("name", ""),
                    full_name=f"{catalog}.{schema}.{a.get('name', '')}",
                    asset_type="volume",
                    owner=a.get("owner"),
                    created_at=parse_timestamp(a.get("created_at")),
                    comment=a.get("comment"),
                )
                for a in raw_assets
            )
        elif asset_type == "functions":
            if not catalog or not schema:
                raise ValueError("Catalog and schema are required to list functions")
            raw_assets = await self.uc_provider.list_functions(
                catalog, schema, limit=limit
            )
            assets = tuple(
                UCAssetInfo(
                    name=a.get("name", ""),
                    full_name=f"{catalog}.{schema}.{a.get('name', '')}",
                    asset_type="function",
                    owner=a.get("owner"),
                    created_at=parse_timestamp(a.get("created_at")),
                    comment=a.get("comment"),
                )
                for a in raw_assets
            )
        else:
            raise ValueError(f"Unknown asset type: {asset_type}")

        return UCAssetList(
            catalog=catalog,
            schema=schema,
            asset_type=asset_type,
            assets=assets,
            total_count=len(assets),
            truncated=len(assets) >= limit,
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

        Raises:
            RuntimeError: If discovery provider is not configured

        Examples:
            >>> service = CatalogBrowserService(uc_provider, discovery_provider=llm)
            >>> result = await service.discover_tables(sql_text="SELECT * FROM t1")
            >>> "t1" in result.all_tables
            True
        """
        if not self.discovery_provider:
            raise RuntimeError(
                "Table discovery requires a discovery_provider (LLM-based). "
                "Initialize UCService with discovery_provider parameter."
            )

        all_tables: list[TableReference] = []

        # Process SQL text if provided
        if sql_text:
            logger.debug("discovering_tables_from_sql")
            tables = await self.discovery_provider.extract_tables(
                sql_text, budget=budget
            )
            all_tables.extend(tables)

        # Process source code if provided
        if source_code:
            logger.debug("discovering_tables_from_source_code")
            tables = await self.discovery_provider.extract_tables(
                source_code, budget=budget
            )
            all_tables.extend(tables)

        # Process task sources if provided
        if task_sources:
            for task_key, source_info in task_sources.items():
                source_text = source_info.get("source", "")
                if source_text:
                    logger.debug("discovering_tables_from_task", task_key=task_key)
                    tables = await self.discovery_provider.extract_tables(
                        source_text, budget=budget
                    )
                    all_tables.extend(tables)

        if not all_tables:
            logger.debug("no_tables_discovered")
            return TableDiscoveryResult(
                all_tables=[],
                source_tables=[],
                target_tables=[],
                tables_and_views=[],
                table_references=[],
            )

        # Apply domain logic: deduplicate and categorize
        unique_tables = TableAnalyzer.deduplicate_tables(all_tables)
        result = TableAnalyzer.categorize_tables(unique_tables)

        logger.debug(
            f"Discovered {len(result.all_tables)} unique tables "
            f"({len(result.tables_and_views)} tables/views)"
        )

        return result

    async def enrich_table_references(
        self,
        table_references_data: list[dict[str, Any] | TableReference],
    ) -> tuple[list[TableReference], dict[str, dict[str, Any]]]:
        """Enrich table references with metadata from Unity Catalog and Delta history.

        Args:
            table_references_data: List of table references (dicts or TableReference)

        Returns:
            Tuple of (enriched table references, table metadata dict)

        Examples:
            >>> service = CatalogBrowserService(uc_provider, enricher_provider=enricher)
            >>> refs = [{"resolved_3part": "catalog.schema.table1", ...}]
            >>> enriched, metadata = await service.enrich_table_references(refs)
            >>> len(enriched) == 1
            True
        """
        if not table_references_data:
            logger.debug("no_table_references_to_enrich")
            return [], {}

        if not self.enricher_provider:
            logger.warning("table_enricher_not_configured")
            # Convert to TableReference objects but don't enrich
            table_references = TableAnalyzer.convert_table_reference_dicts(
                table_references_data
            )
            return table_references, {}

        # Convert dicts to TableReference objects
        table_references = TableAnalyzer.convert_table_reference_dicts(
            table_references_data
        )

        # Enrich tables using enricher
        logger.debug("enriching_table_references", count=len(table_references))
        await self.enricher_provider.enrich_tables(table_references)

        # Build metadata dictionary
        table_metadata: dict[str, dict[str, Any]] = {}
        for table in table_references:
            if table.details:
                table_metadata[table.resolved_3part] = {
                    "details": table.details,
                    "history": table.history,
                }

        enriched_count = len(table_metadata)
        logger.debug(
            "enriched_table_references",
            enriched_count=enriched_count,
            total=len(table_references),
        )

        return table_references, table_metadata
