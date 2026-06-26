# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure query resolution logic."""

from __future__ import annotations

import re

from starboard_core.domain.models.query import (
    QueryResolutionInput,
    QueryResolutionResult,
    QuerySource,
)

from starboard_server.infra.constraints.utils import SQLUtils, StringUtils
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Permissive pattern for Databricks statement IDs that may not be strict UUIDs.
# Matches hex-dash patterns with 4+ segments and 20+ total hex chars.
_STATEMENT_ID_RE = re.compile(
    r"\b([0-9a-fA-F]{4,}-(?:[0-9a-fA-F]{2,}-){2,}[0-9a-fA-F]{4,})\b"
)


class QueryResolver:
    """

    Pure query resolution logic.

    All methods are static and side-effect free.
    No dependencies on infrastructure, state, or I/O.
    """

    @staticmethod
    def extract_statement_id(target: str) -> str | None:
        """
        Extract statement ID from target string.

        Tries strict UUID matching first, then falls back to a permissive
        hex-dash pattern for Databricks IDs that aren't standard UUIDs.

        Args:
            target: Input string that may contain a statement ID

        Returns:
            Statement ID if found, None otherwise

        Example:
            >>> QueryResolver.extract_statement_id("01f1163f-849f-1e74-9dae-2fae4d830b14")
            '01f1163f-849f-1e74-9dae-2fae4d830b14'
            >>> QueryResolver.extract_statement_id("b01f1163f-849f-1e74-9dae-2fae4d830b14")
            'b01f1163f-849f-1e74-9dae-2fae4d830b14'
            >>> QueryResolver.extract_statement_id("SELECT * FROM table")
        """
        # Try strict UUID first
        ids = StringUtils.extract_uuids(target, unique=True)
        if ids:
            return ids[0]

        # Fallback: permissive hex-dash pattern for non-standard Databricks IDs
        match = _STATEMENT_ID_RE.search(target)
        if match:
            candidate = match.group(1)
            hex_chars = candidate.replace("-", "")
            if len(hex_chars) >= 20:
                return candidate

        return None

    @staticmethod
    def classify_query_input(target: str) -> QuerySource:
        """
        Classify query input type based on content analysis.

        Args:
            target: Input string to classify

        Returns:
            QuerySource classification

        Example:
            >>> QueryResolver.classify_query_input("SELECT * FROM table")
            QuerySource.RAW_SQL
            >>> QueryResolver.classify_query_input("abc-123-def-456")
            QuerySource.QUERY_HISTORY
            >>> QueryResolver.classify_query_input("find my query")
            QuerySource.UNKNOWN
        """
        # Check if it's valid SQL
        if SQLUtils.is_valid_sql(target):
            return QuerySource.RAW_SQL

        # Try to extract statement ID
        if QueryResolver.extract_statement_id(target):
            return QuerySource.QUERY_HISTORY

        return QuerySource.UNKNOWN

    @staticmethod
    def resolve_from_classification(
        classification: dict | None,
    ) -> QueryResolutionResult:
        """
        Resolve query using LLM classification hints.

        Args:
            target: Original target string
            classification: Optional LLM classification result

        Returns:
            QueryResolutionResult with partial resolution

        Example:
            >>> classification = {
            ...     "input_type": "statement_id",
            ...     "target": "abc-123",
            ...     "confidence": "high"
            ... }
            >>> result = QueryResolver.resolve_from_classification(
            ...     "Find query abc-123",
            ...     classification
            ... )
            >>> result.source
            QuerySource.QUERY_HISTORY
        """
        if not classification:
            return QueryResolutionResult(
                source=QuerySource.UNKNOWN,
                statement_id=None,
                sql_text=None,
            )

        confidence = classification.get("confidence", "")
        if confidence not in ["high", "medium"]:
            return QueryResolutionResult(
                source=QuerySource.UNKNOWN,
                statement_id=None,
                sql_text=None,
            )

        input_type = classification.get("input_type", "")
        target_value = classification.get("target")

        match input_type:
            case "statement_id":
                logger.debug("LLM resolved statement ID from raw input")
                return QueryResolutionResult(
                    source=QuerySource.QUERY_HISTORY,
                    statement_id=target_value,
                    sql_text=None,
                )
            case "sql":
                logger.debug("LLM resolved SQL from raw input")
                return QueryResolutionResult(
                    source=QuerySource.RAW_SQL,
                    statement_id=None,
                    sql_text=target_value,
                )
            case _:
                logger.debug("unknown_input_type", input_type=input_type)
                return QueryResolutionResult(
                    source=QuerySource.UNKNOWN,
                    statement_id=None,
                    sql_text=None,
                )

    @staticmethod
    def resolve_query(input_data: QueryResolutionInput) -> QueryResolutionResult:
        """
        Resolve query from input (classification + fallback).

        This is pure logic - no API calls, no state.
        Returns a partial result that may need API enrichment.

        Args:
            input_data: Query resolution input

        Returns:
            QueryResolutionResult (may be partial, sql_text may be None)

        Example:
            >>> input_data = QueryResolutionInput(
            ...     target="SELECT * FROM table",
            ...     classification=None
            ... )
            >>> result = QueryResolver.resolve_query(input_data)
            >>> result.source
            QuerySource.RAW_SQL
        """
        # Try classification first
        if input_data.classification:
            result = QueryResolver.resolve_from_classification(
                input_data.classification,
            )
            if result.source != QuerySource.UNKNOWN:
                return result

        # Fallback to manual classification
        source = QueryResolver.classify_query_input(input_data.target)

        if source == QuerySource.RAW_SQL:
            logger.debug("resolved_raw_sql")
            return QueryResolutionResult(
                source=QuerySource.RAW_SQL,
                statement_id=None,
                sql_text=input_data.target,
            )
        elif source == QuerySource.QUERY_HISTORY:
            statement_id = QueryResolver.extract_statement_id(input_data.target)
            logger.debug("extracted_statement_id", statement_id=statement_id)
            return QueryResolutionResult(
                source=QuerySource.QUERY_HISTORY,
                statement_id=statement_id,
                sql_text=None,  # Needs API enrichment
            )
        else:
            return QueryResolutionResult(
                source=QuerySource.UNKNOWN,
                statement_id=None,
                sql_text=None,
            )
