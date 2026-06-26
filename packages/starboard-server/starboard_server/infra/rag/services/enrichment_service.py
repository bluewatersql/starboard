# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
LLM-based enrichment service for table metadata.

Uses LLM to add business context, grain, use cases, and column-level semantics
to extracted metadata. Implements async batch processing with concurrency control.

Pattern:
    service = EnrichmentService(llm_client, max_concurrent=10)
    enriched_tables = await service.enrich_all_tables(tables)
"""

from __future__ import annotations

import asyncio
import json
import re

import structlog
from starboard_core.rag.models import TableMetadata

from starboard_server.adapters.llm.openai.client import OpenAIProvider

logger = structlog.get_logger(__name__)


class EnrichmentService:
    """
    LLM-based enrichment service for table metadata.

    Adds business context, grain, common use cases, and column-level semantics
    to extracted table metadata using an LLM.

    Attributes:
        llm_client: Client for LLM completions
        max_concurrent: Maximum concurrent LLM calls (default: 10)
    """

    ENRICHMENT_PROMPT_SYSTEM_PROMPT = """You are “System Table Semantics Analyst”, a meticulous data engineer specializing in Databricks system tables and metadata-driven documentation.

GOAL
Given a table description (name, catalog, schema, type, comment) and an ordered list of columns, produce a concise, accurate explanation of the table’s purpose and each column’s meaning, returning ONLY valid JSON that matches the provided schema.

HARD REQUIREMENTS (must follow)
1) Output MUST be a single JSON object and MUST validate against the provided JSON schema.
2) Output MUST contain every column exactly once, preserving the input column order exactly.
3) Do NOT include any extra keys beyond the schema.
4) Do NOT include markdown, code fences, comments, or prose outside JSON.
5) If you are unsure about a column’s meaning, set "business_meaning" to null (not an empty string) and set "cardinality_estimate" to "unknown".
6) Keep “business_context” to 1–2 sentences.
7) Keep “common_use_cases” to 2–4 concrete items.

INTERPRETATION RULES
- Use the TABLE metadata (name, schema, comment) as the primary signal for business context and grain.
- Use common Databricks naming conventions when applicable (e.g., *_id, *_time, *_at, *_type, *_state, *_name).
- Prefer plain English. Avoid repeating the column name as the meaning unless you add real semantics.

CARDINALITY ESTIMATE RULES (choose one)
Allowed: "unique" | "near-unique" | "high" | "medium" | "low" | "unknown"

COLUMN TYPES:
Allowd: "identifier" | "temporal" | "dimension" | "metric" | "flag" | "other"

Heuristics:
- Primary IDs (e.g., statement_id, query_id, run_id, event_id, request_id, log_id) → "unique" or "near-unique"
- Strong identifiers that are likely per-row unique but could be reused across partitions/time (e.g., execution_id, task_id depending on context) → "near-unique"
- Foreign keys / entity refs (workspace_id, account_id, user_id, cluster_id, warehouse_id, job_id, pipeline_id) → "high" or "medium"
  - Use "high" if many distinct values expected at scale; "medium" if constrained (e.g., few workspaces, few warehouses)
- Timestamps/dates:
  - event_time / start_time / end_time at full timestamp precision → usually "high"
  - date / day / hour buckets → "medium" or "low" depending on bucket size
- Status/enums/categories/booleans (state, status, type, category, success, is_*) → "low"
- Free-form text (message, error, query_text, user_agent) → "high" or "unknown" (often "high" but pick "unknown" if unclear)
- Numeric measures (bytes, duration_ms, cost, cpu_percent) → usually "high" or "medium" (pick "unknown" if no clue)
- If the column name is self-explanatory (e.g., workspace_id, created_at), set business_meaning to null rather than restating the name.

GRAIN GUIDANCE
- State what one row represents (e.g., “one query execution”, “one audit event”, “one billing usage line item”, “one cluster state transition”), including the natural primary key(s) if inferable.

OUTPUT FORMAT
Return ONLY the JSON object in exactly this shape (no extra keys, no markdown, no code fences).
Preserve input column order exactly. Do not omit any column.

JSON SCHEMA:
{
    "business_context": string,
    "grain": string,
    "common_use_cases": string[],
    "columns": [
        {
            "name": string,
            "column_type": string,
            "business_meaning": string | null,
            "cardinality_estimate": string
        }
    ]
}

Now perform the task for the provided input.
"""

    ENRICHMENT_PROMPT_TEMPLATE = """Analyze this Databricks system table and provide business context and column semantics outputting the required JSON format.

TABLE: {table_name}
CATALOG: {catalog}
SCHEMA: {schema}
TYPE: {table_type}
COMMENT: {comment}

COLUMNS:
{columns_list}

RELATIONSHIPS:
{relationships_list}

JOIN COLUMNS:
{common_join_columns_list}
"""

    def __init__(
        self,
        llm_client: OpenAIProvider,
        *,
        max_concurrent: int = 10,
    ):
        """
        Initialize enrichment service.

        Args:
            llm_client: LLM client for completions
            max_concurrent: Maximum concurrent LLM calls. Default is 10 to avoid
                          rate limiting. Adjust based on your LLM provider's limits.
        """
        self.llm_client = llm_client
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

        logger.info(
            "enrichment_service_initialized",
            max_concurrent=max_concurrent,
        )

    async def enrich_table(self, table: TableMetadata) -> TableMetadata:
        """
        Enrich single table with LLM-generated context.

        Args:
            table: Table metadata to enrich

        Returns:
            Enriched table metadata (modifies in place and returns)

        Raises:
            Exception: If LLM call fails or response is invalid

        Example:
            >>> service = EnrichmentService(llm_client)
            >>> table = TableMetadata(...)
            >>> enriched = await service.enrich_table(table)
            >>> print(enriched.business_context)
        """
        logger.info(
            "enriching_table",
            table=table.full_name,
            columns=len(table.columns),
        )

        # Build prompt
        columns_list = "\n".join(
            f"  - {col.column_name} ({col.data_type}): {col.comment or 'no comment'}"
            for col in table.columns
        )

        if table.relationships:
            relationships_list = "\n".join(
                f"  - {rel.from_table} -> {rel.to_table} ({', '.join(rel.join_types) if rel.join_types else 'UNKNOWN'})"
                for rel in table.relationships
            )
        else:
            relationships_list = " - No relationships"

        if table.common_join_columns:
            common_join_columns_list = "\n".join(
                f"  - {col}" for col in table.common_join_columns
            )
        else:
            common_join_columns_list = " - No join columns"

        prompt = self.ENRICHMENT_PROMPT_TEMPLATE.format(
            table_name=table.table_name,
            catalog=table.table_catalog,
            schema=table.table_schema,
            table_type=table.table_type,
            comment=table.comment or "no comment",
            columns_list=columns_list if columns_list else "No columns",
            relationships_list=relationships_list,
            common_join_columns_list=common_join_columns_list,
        )

        try:
            # Call LLM
            response = await self.llm_client.async_client.chat.completions.create(
                model=self.llm_client.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.ENRICHMENT_PROMPT_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=self.llm_client.temperature,
                max_tokens=self.llm_client.max_tokens,
            )

            # Extract content from response
            response_content = response.choices[0].message.content
            if response_content is None:
                raise ValueError("LLM returned empty response")

            # Parse response (handle markdown wrappers)
            content = self._extract_json(response_content)
            enrichment = json.loads(content)

            # Update table metadata
            table.business_context = enrichment.get("business_context")
            table.grain = enrichment.get("grain")
            table.common_use_cases = enrichment.get("common_use_cases", [])

            # Update column metadata
            enrichment_columns = enrichment.get("columns", [])
            if len(enrichment_columns) != len(table.columns):
                logger.warning(
                    "column_count_mismatch",
                    table=table.full_name,
                    expected=len(table.columns),
                    received=len(enrichment_columns),
                )

            for col, enrichment_col in zip(table.columns, enrichment_columns):
                col.business_meaning = enrichment_col.get("business_meaning")
                col.column_type = enrichment_col.get("column_type")
                col.cardinality_estimate = enrichment_col.get("cardinality_estimate")

            logger.info(
                "table_enriched",
                table=table.full_name,
            )

            return table

        except json.JSONDecodeError as e:
            response_preview = (
                response_content[:200]
                if "response_content" in locals() and response_content is not None
                else "N/A"
            )
            logger.error(
                "enrichment_json_parse_failed",
                table=table.full_name,
                error=str(e),
                response=response_preview,
            )
            raise
        except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
            logger.error(
                "enrichment_failed",
                table=table.full_name,
                error=str(e),
            )
            raise

    async def enrich_all_tables(
        self,
        tables: list[TableMetadata],
        *,
        fail_fast: bool = False,
    ) -> list[TableMetadata]:
        """
        Enrich multiple tables concurrently with rate limiting.

        Uses semaphore to limit concurrent LLM calls and avoid rate limits.
        By default, continues processing even if some tables fail (graceful degradation).

        Args:
            tables: List of table metadata to enrich
            fail_fast: If True, raise on first error. If False (default),
                      continue processing and return partial results.

        Returns:
            List of enriched tables (same order as input).
            Failed enrichments are returned unchanged with error logged.

        Example:
            >>> service = EnrichmentService(llm_client, max_concurrent=5)
            >>> tables = extractor.extract_tables(schemas=["billing"])
            >>> enriched = await service.enrich_all_tables(tables)
            >>> successful = [t for t in enriched if t.business_context is not None]
        """
        if not tables:
            logger.info("no_tables_to_enrich")
            return []

        logger.info(
            "enriching_tables_batch",
            total_tables=len(tables),
            max_concurrent=self.max_concurrent,
        )

        async def enrich_with_limit(table: TableMetadata) -> TableMetadata:
            """Enrich table with semaphore for rate limiting."""
            async with self._semaphore:
                return await self.enrich_table(table)

        # Submit all tasks
        tasks = [enrich_with_limit(table) for table in tables]

        # Gather results (capture exceptions unless fail_fast)
        results: list[TableMetadata | BaseException]
        if fail_fast:
            async with asyncio.TaskGroup() as tg:
                tg_tasks = [tg.create_task(t) for t in tasks]
            results = [t.result() for t in tg_tasks]
        else:
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        enriched_tables = []
        failed_count = 0

        for table, result in zip(tables, results):
            if isinstance(result, BaseException):
                logger.error(
                    "table_enrichment_failed",
                    table=table.full_name,
                    error=str(result),
                )
                # Return original table unchanged
                enriched_tables.append(table)
                failed_count += 1
            else:
                # Type narrowing: result is TableMetadata here
                enriched_tables.append(result)

        logger.info(
            "enrichment_batch_complete",
            total=len(tables),
            succeeded=len(tables) - failed_count,
            failed=failed_count,
        )

        return enriched_tables

    def _extract_json(self, response: str) -> str:
        """
        Extract JSON from LLM response.

        Handles common LLM response formats:
        - Plain JSON
        - Markdown code blocks (```json ... ```)
        - JSON embedded in prose

        Args:
            response: Raw LLM response

        Returns:
            Extracted JSON string

        Raises:
            ValueError: If no valid JSON found
        """
        content = response.strip()

        # Remove markdown code blocks
        if content.startswith("```json"):
            content = content[7:].strip()
        elif content.startswith("```"):
            content = content[3:].strip()

        if content.endswith("```"):
            content = content[:-3].strip()

        # Try to extract JSON object
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        if not content:
            raise ValueError("No JSON content found in response")

        return content
