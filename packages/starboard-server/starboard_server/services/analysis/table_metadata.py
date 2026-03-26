"""Table metadata discovery and enrichment services."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from starboard_core.domain.models.databricks import TableReference
from starboard_core.domain.transformers import resolve_3part

from starboard_server.adapters.llm import create_llm_client
from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.exceptions import AdapterError
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.observability.logging import get_logger
from starboard_server.services.context.provider import SharedContextProvider
from starboard_server.services.context.transforms import (
    get_transformed,
    transform_delta_history,
    transform_table_metadata,
)

if TYPE_CHECKING:
    from starboard_server.adapters.databricks import AsyncDatabricksClient

logger = get_logger(__name__)

# Table extraction prompt and schema (inlined from legacy prompts module)
TABLE_EXTRACT_PROMPT = """You are a code auditor for Spark (Python, SQL, Scala).

Extract ALL referenced tables/views in the code.

EXTRACTION RULES:
1. Include catalog and schema when present (catalog.schema.table)
2. Resolve directionality:
   - Source: Tables in FROM, JOIN clauses, or df.read operations
   - Destination: Tables in INSERT, CREATE TABLE AS, or df.write operations
   - Both: Tables that are both read and written in the same code
3. Normalize identifiers:
   - Remove backticks: `catalog`.`table` → catalog.table
   - Remove quotes: "schema"."table" → schema.table
   - Lowercase unless explicitly case-sensitive
4. Detect table type based on context:
   - "table": Base tables or tables without special keywords
   - "system_table": System tables (information_schema, system)
   - "view": Tables in CREATE VIEW or after explicit view references
   - "temp_table": Temporary tables from CREATE TEMP TABLE or createOrReplaceTempView()
   - "temp_view": Temporary views from CREATE TEMP VIEW or createTempView()
   - "cte": Common Table Expressions (WITH clauses)
   - "table": Default if type cannot be determined
5. Include:
   - Base tables and views
   - CTEs (Common Table Expressions) as temporary sources
   - Temp views from CREATE TEMP VIEW
6. Exclude:
   - System tables (information_schema, system)
   - Variables or parameters (unless they resolve to actual tables)

LANGUAGE-SPECIFIC PATTERNS:
- SQL: FROM, JOIN, INSERT INTO, CREATE TABLE, CREATE VIEW, WITH (CTE)
- PySpark: spark.table(), df.read.table(), df.write.saveAsTable(), createTempView(), createOrReplaceTempView()
- Scala: spark.table(), spark.sql(), df.write.insertInto(), createTempView(), createOrReplaceTempView()

If code is malformed or language is unrecognized, return language="unknown" and empty tables array.
"""

TABLE_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string"},
        "tables": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "catalog": {"type": ["string", "null"]},
                    "schema": {"type": ["string", "null"]},
                    "table": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "table",
                            "system_table",
                            "view",
                            "temp_table",
                            "temp_view",
                            "cte",
                        ],
                    },
                    "is_source": {"type": "boolean"},
                    "is_destination": {"type": "boolean"},
                },
                "required": [
                    "raw",
                    "catalog",
                    "schema",
                    "table",
                    "type",
                    "is_source",
                    "is_destination",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["language", "tables"],
    "additionalProperties": False,
}


class TableDiscovery:
    """Discovers table references from source code using LLM analysis."""

    def __init__(
        self,
        llm: BaseLLMClient | None = None,
        default_catalog: str | None = None,
        default_schema: str | None = None,
    ):
        """
        Initialize table discovery service.

        Args:
            llm: LLM client for LLM interactions
            default_catalog: Default catalog for table resolution
            default_schema: Default schema for table resolution
        """
        self.cfg = EnvConfig.from_env()
        self.llm = llm or create_llm_client(cfg=self.cfg)
        self.default_catalog = default_catalog or self.cfg.default_catalog
        self.default_schema = default_schema or self.cfg.default_schema

    async def extract_tables(self, code: str, budget=None) -> list[TableReference]:
        """
        Extract table references from source code.

        Args:
            code: Source code to analyze
            budget: Optional TokenBudget for tracking token usage

        Returns:
            List of table references
        """
        messages = [
            {"role": "system", "content": TABLE_EXTRACT_PROMPT},
            {"role": "user", "content": f"CODE:\n{code}"},
        ]
        try:
            data = await self.llm.json_response(
                messages=messages,
                schema=TABLE_EXTRACT_SCHEMA,
                phase="table_extract",
                budget=budget,
            )
            items = data.get("tables", [])
        except (AdapterError, ValueError) as e:
            logger.warning(
                "LLM table extraction failed (%s); falling back to regex-lite.", e
            )
            items = []

        out: list[TableReference] = []
        for it in items:
            raw = it.get("raw") or it.get("table")

            cat, sch, tbl, fqn = resolve_3part(
                raw, self.default_catalog, self.default_schema
            )

            is_source = it.get("is_source", False)
            is_destination = it.get("is_destination", False)
            table_type = it.get("type", "table")  # Default to "table" if not specified

            out.append(
                TableReference(
                    raw=raw,
                    catalog=cat,
                    schema=sch,
                    table=tbl,
                    resolved_3part=fqn,
                    type=table_type,
                    is_source=is_source,
                    is_destination=is_destination,
                )
            )

        # Dedupe by fqn
        seen = set()
        deduped: list[TableReference] = []
        for t in out:
            if t.resolved_3part not in seen:
                seen.add(t.resolved_3part)
                deduped.append(t)

        return deduped


class TableEnricher:
    """Enriches table references with metadata and history from Databricks.

    Uses async facade methods with concurrent execution for parallel enrichment.
    """

    def __init__(self, api: AsyncDatabricksClient, max_workers: int | None = None):
        """Initialize table enricher.

        Args:
            api: Async Databricks client for metadata queries.
            max_workers: Maximum number of parallel tasks (default: from config or 4).
        """
        self.provider = SharedContextProvider(api)

        # Get parallelism setting from config
        if max_workers is None:
            cfg = EnvConfig.from_env()
            max_workers = cfg.tool_parallelism

        self.max_workers = max_workers
        logger.debug("table_enricher_initialized", max_workers=self.max_workers)

    async def _enrich_single_table(
        self, table: TableReference
    ) -> tuple[TableReference, Exception | None]:
        """
        Enrich a single table reference with metadata and history.

        Args:
            table: Table reference to enrich

        Returns:
            Tuple of (table, exception). Exception is None if successful.
        """
        try:
            # Only fetch metadata and history for actual tables and views
            # Skip temp tables, temp views, and CTEs as they don't exist in the catalog
            if table.type not in ("table", "view"):
                logger.debug(
                    "skipping_enrichment",
                    table_type=table.type,
                    table=table.resolved_3part,
                )
                return (table, None)

            logger.debug("enriching_table", table=table.resolved_3part)

            # Use transforms helper for direct provider access
            table.details = await get_transformed(
                self.provider,
                "table_metadata",
                table.resolved_3part,
                transform_fn=transform_table_metadata,
            )

            if table.details:
                tbl_format = table.details.get("format", "").upper()
                if tbl_format == "DELTA":
                    raw_history = await self.provider.get(
                        "delta_history", table.resolved_3part, limit=20
                    )
                    table.history = (
                        transform_delta_history(raw_history) if raw_history else None
                    )  # type: ignore[assignment]
                    logger.debug(
                        "enriched_delta_table",
                        table=table.resolved_3part,
                        history_entries=len(table.history) if table.history else 0,
                    )
                else:
                    logger.debug("enriched_non_delta_table", table=table.resolved_3part)
            else:
                logger.warning("no_metadata_found", table=table.resolved_3part)

            return (table, None)

        except (AdapterError, ValueError) as e:
            logger.error(
                "enrich_table_failed",
                table=table.resolved_3part,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return (table, e)

    async def enrich_tables(self, tables: list[TableReference]) -> None:
        """
        Enrich table references with metadata and history in-place using concurrent tasks.
        Only enriches actual tables and views, skipping temp tables, temp views, and CTEs.

        Handles exceptions gracefully - continues processing even if some tables fail.

        Args:
            tables: List of table references to enrich
        """
        if not tables:
            logger.debug("no_tables_to_enrich")
            return

        # Filter tables that need enrichment
        tables_to_enrich = [t for t in tables if t.type in ("table", "view")]

        skipped_count = len(tables) - len(tables_to_enrich)
        if skipped_count > 0:
            logger.debug("skipping_non_table_references", skipped_count=skipped_count)

        if not tables_to_enrich:
            logger.debug("no_tables_after_filtering")
            return

        logger.debug(
            "enriching_tables_concurrently",
            table_count=len(tables_to_enrich),
            max_workers=self.max_workers,
        )

        # Process tables concurrently using asyncio.gather with semaphore
        semaphore = asyncio.Semaphore(self.max_workers)

        async def bounded_enrich(table: TableReference):
            async with semaphore:
                return await self._enrich_single_table(table)

        # Run all enrichments concurrently
        results = await asyncio.gather(
            *[bounded_enrich(table) for table in tables_to_enrich],
            return_exceptions=True,
        )

        # Count results
        enriched_count = 0
        failed_count = 0
        failed_tables = []

        for i, result in enumerate(results):
            table = tables_to_enrich[i]
            if isinstance(result, BaseException):
                logger.error(
                    "unexpected_table_processing_error",
                    table=table.resolved_3part,
                    error_type=type(result).__name__,
                    error=str(result),
                )
                failed_count += 1
                failed_tables.append(table.resolved_3part)
            else:
                # Result is tuple[TableReference, Exception | None]
                _, error = result
                if error is None:
                    enriched_count += 1
                else:
                    failed_count += 1
                    failed_tables.append(table.resolved_3part)

        logger.debug(
            "table_enrichment_complete",
            enriched_count=enriched_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
        )

        if failed_tables:
            logger.warning("tables_failed_enrichment", tables=failed_tables)
