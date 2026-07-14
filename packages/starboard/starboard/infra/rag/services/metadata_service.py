# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Metadata extraction from Databricks system tables.

Extracts table and column metadata from information_schema with async concurrent
processing for improved performance. Supports optional "discovery by example" to
infer usage patterns from query history.

Pattern:
    extractor = MetadataExtractor(databricks_client, query_analyzer, max_workers=5)
    tables = await extractor.extract_tables(schemas=["billing", "compute"])
    # Tables now include columns, relationships, and usage patterns
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import structlog
from starboard_core.rag.models import (
    AnalysisResult,
    ColumnMetadata,
    RelationshipCondition,
    RelationshipMetadata,
    TableMetadata,
)

from starboard.infra.rag.domain.query_analyzer import QueryAnalyzer

logger = structlog.get_logger(__name__)


class DatabricksClient(Protocol):
    """Protocol for Databricks SQL client."""

    def execute_query(self, query: str) -> list[dict[str, Any]]:
        """
        Execute SQL query and return results as list of dicts.

        Args:
            query: SQL query to execute

        Returns:
            List of row dicts with column names as keys

        Raises:
            Exception: If query execution fails
        """
        ...


class MetadataExtractor:
    """
    Extract schema metadata from Databricks information_schema.

    Uses async concurrent column extraction with asyncio.gather() and a semaphore
    for concurrency control. Each coroutine wraps the sync Databricks SDK call in
    asyncio.to_thread() to avoid blocking the event loop.

    Attributes:
        databricks_client: Client for executing Databricks SQL queries
        query_analyzer: Query analyzer for discovery by example
        max_workers: Maximum concurrent column extractions (default: 5)
    """

    def __init__(
        self,
        databricks_client: DatabricksClient,
        query_analyzer: QueryAnalyzer,
        max_workers: int = 5,
        *,
        analysis_result: AnalysisResult | None = None,
    ):
        """
        Initialize metadata extractor.

        Args:
            databricks_client: Databricks SQL client
            query_analyzer: Query analyzer for discovery by example
            max_workers: Max concurrent connections for column extraction.
                        Default is 5 to stay well under typical warehouse limits.
                        Increase cautiously based on your warehouse capacity.
            analysis_result: Pre-computed analysis result to skip discovery.
                           Pass an empty AnalysisResult to disable discovery.
        """
        self.databricks_client = databricks_client
        self.query_analyzer = query_analyzer
        self.max_workers = max_workers
        self._analysis_result: AnalysisResult | None = analysis_result
        self._semaphore = asyncio.Semaphore(max_workers)

        logger.info("metadata_extractor_initialized", max_workers=max_workers)

    async def extract_tables(
        self,
        schemas: list[str],
        *,
        catalog: str = "system",
        excluded_tables: list[str] | None = None,
    ) -> list[TableMetadata]:
        """
        Extract table metadata from INFORMATION_SCHEMA.

        First fetches all table definitions, then extracts columns concurrently
        using asyncio.gather() with a semaphore for significant performance improvement.

        Discovery by example runs automatically on first call if not pre-computed.

        Args:
            schemas: List of schemas to extract (e.g., ["billing", "compute"])
            catalog: Catalog name (default: "system")
            excluded_tables: List of tables to exclude from extraction

        Returns:
            List of TableMetadata objects with columns populated

        Example:
            >>> extractor = MetadataExtractor(client, analyzer, max_workers=5)
            >>> tables = await extractor.extract_tables(
            ...     schemas=["billing", "compute"],
            ...     catalog="system",
            ... )
            >>> print(f"Extracted {len(tables)} tables")
        """
        if excluded_tables is None:
            excluded_tables = []

        # Discovery by example - runs once on first call
        if self._analysis_result is None:
            await self._discover_by_example()

        logger.info(
            "extracting_tables",
            catalog=catalog,
            schemas=schemas,
        )

        # Step 1: Get all table metadata (fast, single query)
        schema_filter = "', '".join(schemas)
        query = f"""
        SELECT
            table_catalog,
            table_schema,
            table_name,
            table_type,
            comment
        FROM system.information_schema.tables
        WHERE table_catalog = '{catalog}'
        AND table_schema IN ('{schema_filter}')
        ORDER BY table_schema, table_name
        """

        try:
            results = await asyncio.to_thread(
                self.databricks_client.execute_query, query
            )
        except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
            logger.error(
                "failed_to_fetch_tables",
                catalog=catalog,
                schemas=schemas,
                error=str(e),
            )
            raise

        # Create table shells (without columns yet)
        table_shells = []
        for row in results:
            full_name = f"{row.get('table_catalog') or catalog}.{row['table_schema']}.{row['table_name']}"
            if full_name in excluded_tables:
                logger.debug(
                    "skipping_excluded_table",
                    table=full_name,
                )
                continue

            table = TableMetadata(
                table_catalog=row.get("table_catalog") or catalog,
                table_schema=row["table_schema"],
                table_name=row["table_name"],
                table_type=row["table_type"],
                comment=row.get("comment"),
            )

            table_shells.append(table)

        logger.info(
            "fetched_table_definitions",
            count=len(table_shells),
        )

        # Step 2: Extract columns concurrently (the performance bottleneck)
        tables = await self._extract_columns_parallel(table_shells)

        logger.info(
            "completed_table_extraction",
            total_tables=len(tables),
            total_columns=sum(len(t.columns) for t in tables),
        )

        return tables

    async def _extract_columns_parallel(
        self,
        table_shells: list[TableMetadata],
    ) -> list[TableMetadata]:
        """
        Extract columns for all tables concurrently.

        Each coroutine wraps the sync SDK call in asyncio.to_thread() and is
        rate-limited by a shared semaphore.

        Args:
            table_shells: List of TableMetadata without columns

        Returns:
            List of TableMetadata with columns populated
        """

        async def fetch_columns_for_table(table: TableMetadata) -> TableMetadata:
            """
            Fetch columns for a single table with semaphore-limited concurrency.

            Wraps the sync SDK call in asyncio.to_thread() to avoid blocking.
            """
            async with self._semaphore:
                try:
                    table.columns = await self.extract_columns(table.full_name)
                    return table
                except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
                    logger.error(
                        "failed_to_extract_columns",
                        table=table.full_name,
                        error=str(e),
                    )
                    # Graceful degradation - return table with empty columns
                    table.columns = []
                    return table

        # Submit all tasks concurrently, capturing exceptions
        raw_results: list[TableMetadata | BaseException] = await asyncio.gather(
            *[fetch_columns_for_table(table) for table in table_shells],
            return_exceptions=True,
        )

        # Collect results and apply patterns
        tables = []
        for table, result in zip(table_shells, raw_results):
            if isinstance(result, BaseException):
                # Should rarely happen since we catch inside fetch_columns_for_table
                logger.error(
                    "unexpected_error_processing_table",
                    table=table.full_name,
                    error=str(result),
                )
                table.columns = []
                tables.append(table)
            else:
                enriched_table = self._apply_patterns_to_table(result)
                tables.append(enriched_table)

        return tables

    async def extract_columns(self, table_full_name: str) -> list[ColumnMetadata]:
        """
        Extract column metadata for a specific table.

        Wraps the sync Databricks SDK call in asyncio.to_thread() so the event
        loop is not blocked. Safe for concurrent invocation.

        Args:
            table_full_name: Fully qualified table name (catalog.schema.table)

        Returns:
            List of ColumnMetadata objects

        Raises:
            ValueError: If table_full_name format is invalid

        Example:
            >>> columns = await extractor.extract_columns("system.billing.usage")
            >>> print(f"Table has {len(columns)} columns")
        """
        parts = table_full_name.split(".")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid table name format: {table_full_name}. "
                f"Expected format: catalog.schema.table"
            )

        catalog, schema, table_name = parts

        query = f"""
        SELECT
            column_name,
            full_data_type AS data_type,
            is_nullable,
            comment
        FROM system.information_schema.columns
        WHERE table_catalog = '{catalog}'
          AND table_schema = '{schema}'
          AND table_name = '{table_name}'
        ORDER BY ordinal_position
        """

        try:
            results = await asyncio.to_thread(
                self.databricks_client.execute_query, query
            )
        except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
            logger.error(
                "failed_to_fetch_columns",
                table=table_full_name,
                error=str(e),
            )
            raise

        columns = []
        for row in results:
            column = ColumnMetadata(
                table_name=table_full_name,
                column_name=row["column_name"],
                data_type=row["data_type"],
                is_nullable=row.get("is_nullable") == "YES",
                comment=row.get("comment"),
            )

            columns.append(column)

        return columns

    async def _discover_by_example(self, lookback_days: int = 90) -> None:
        """
        Analyze query history to discover usage patterns (runs once on first call).

        Loads query history and analyzes it to extract join/aggregate/predicate
        patterns. Wraps the sync SDK call in asyncio.to_thread().

        Args:
            lookback_days: Days of query history to analyze (default: 90)
        """
        logger.info("starting_discovery_by_example", lookback_days=lookback_days)

        # Load query history that includes JOINs on system tables
        query = f"""
        WITH tw AS (
            SELECT event_id
            FROM system.access.table_lineage
            WHERE
                source_table_full_name ILIKE 'system.%'
                AND event_date > CURRENT_DATE() - INTERVAL {lookback_days} DAYS
            GROUP BY event_id
            HAVING COUNT(DISTINCT source_table_full_name) = 2
        )
        SELECT
            DISTINCT h.statement_text
        FROM system.access.table_lineage t
        JOIN tw ON t.event_id = tw.event_id
        JOIN system.query.history h
            ON t.statement_id = h.cache_origin_statement_id
        WHERE h.statement_text ILIKE '% join %'
        AND h.statement_type = 'SELECT'
        AND h.execution_status = 'FINISHED'
        LIMIT 7500
        """

        try:
            results = await asyncio.to_thread(
                self.databricks_client.execute_query, query
            )
            query_texts = [
                row["statement_text"] for row in results if row.get("statement_text")
            ]

            # Analyze all queries - pass empty string as table name since we're analyzing all tables
            # The analyzer will extract table names from the SQL itself
            self._analysis_result = self.query_analyzer.analyze_queries(
                [("", sql) for sql in query_texts]
            )

            logger.info(
                "completed_discovery_by_example",
                queries_analyzed=len(query_texts),
                joins=len(self._analysis_result.raw_joins or []),
                predicates=len(self._analysis_result.raw_predicates or []),
                aggregations=len(self._analysis_result.raw_aggregations or []),
            )
        except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
            logger.error("failed_discovery_by_example", error=str(e))
            # Create empty result to avoid retrying
            self._analysis_result = AnalysisResult(
                success_count=0,
                failed_count=1,
                join_summary=[],
                raw_joins=[],
                raw_predicates=[],
                raw_aggregations=[],
            )

    def _apply_patterns_to_table(self, table: TableMetadata) -> TableMetadata:
        """
        Apply discovered patterns to a single table.

        Args:
            table: Table to enrich

        Returns:
            Enriched table metadata
        """
        if self._analysis_result is None:
            logger.warning("no_analysis_result_available", table=table.full_name)
            return table

        # Get predicates by column
        # Use full_name for consistent matching (join records use full qualified names)
        for column in table.columns:
            predicates = self.query_analyzer.get_column_predicates(
                self._analysis_result, table.full_name, column.column_name
            )

            if predicates:
                column.example_filters = predicates[:10]  # Top 10 values

            aggregations = self.query_analyzer.get_column_aggregations(
                self._analysis_result, table.full_name, column.column_name
            )

            if aggregations:
                column.common_aggregations = aggregations

        # Get join columns
        join_columns = self.query_analyzer.get_join_columns(
            self._analysis_result, table.full_name, limit=10
        )

        if join_columns:
            table.common_join_columns = join_columns

        # Get relationships
        relationships = self._discover_relationships(table.full_name)

        if relationships:
            table.relationships = relationships

        return table

    def _discover_relationships(self, table_name: str) -> list[RelationshipMetadata]:
        """
        Discover table relationships from join patterns in analysis result.

        Uses join_summary which contains aggregated data including extended_conditions.
        Only includes relationships where both tables are in the system catalog.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)

        Returns:
            List of discovered relationships
        """
        if not self._analysis_result or not self._analysis_result.join_summary:
            return []

        relationships = []
        table_lower = table_name.lower()

        for join_summary_item in self._analysis_result.join_summary:
            from_table = join_summary_item.get("from_table", "").lower()
            # Use _table_matches for consistent matching (handles both full and base names)
            if not self.query_analyzer._table_matches(from_table, table_lower):
                continue

            to_table = join_summary_item.get("to_table", "")
            # Filter: only include relationships where both tables are in system catalog
            if not from_table.startswith("system.") or not to_table.lower().startswith(
                "system."
            ):
                continue

            join_types = join_summary_item.get("join_types", [])
            core_columns = join_summary_item.get("core_columns", "")

            # Convert extended_conditions from join_summary format to RelationshipCondition
            extended_conditions = []
            for ext_cond in join_summary_item.get("extended_conditions", []):
                extended_columns = ext_cond.get("extended_columns", "")
                frequency_num = ext_cond.get("frequency", 0)

                # Map frequency number to frequency string
                if frequency_num >= 100:
                    frequency_str = "very_common"
                elif frequency_num >= 20:
                    frequency_str = "common"
                elif frequency_num >= 5:
                    frequency_str = "occasional"
                else:
                    frequency_str = "rare"

                extended_conditions.append(
                    RelationshipCondition(
                        condition=extended_columns,
                        frequency=frequency_str,
                    )
                )

            rel = RelationshipMetadata(
                from_table=from_table,
                to_table=to_table,
                join_types=join_types,
                core_columns=core_columns,
                extended_conditions=extended_conditions,
            )
            relationships.append(rel)

        return relationships
