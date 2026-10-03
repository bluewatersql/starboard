# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Reasoning interface for query tools.

This module provides LLM-facing tools for query operations.
Uses domain logic directly - service layer was inlined.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_core.domain.models.query import (
    ExplainPlanInput,
    ExplainPlanResult,
    QueryResolutionInput,
    QueryResolutionResult,
    QuerySource,
)

from starboard.infra.observability.events import EventEmitter
from starboard.infra.observability.logging import get_logger
from starboard.infra.reliability.exceptions import MissingDataError
from starboard.services.context.transforms import get_explain_plan
from starboard.tools.adapters.base import BaseToolAdapter
from starboard.tools.domain.query.analyzer import QueryAnalyzer
from starboard.tools.domain.query.resolver import QueryResolver
from starboard.tools.domain.query.transformers import (
    transform_resolve_query_result,
)

if TYPE_CHECKING:
    from starboard.adapters.databricks import AsyncDatabricksClient
    from starboard.services.context.provider import SharedContextProvider

logger = get_logger(__name__)


class QueryTools(BaseToolAdapter):
    """Reasoning interface for query operations.

    Clean interface optimized for LLM reasoning. Uses SharedContextProvider
    directly with transforms and domain logic - service layer was inlined.

    Architecture:
        QueryTools → QueryResolver/QueryAnalyzer (domain) + transforms

    Example:
        >>> tools = QueryTools.from_provider(api, provider, events=events)
        >>> result = await tools.resolve_query("SELECT * FROM table")
    """

    def __init__(
        self,
        api: AsyncDatabricksClient,
        provider: SharedContextProvider,
        events: EventEmitter | None = None,
    ) -> None:
        """Initialize query tools.

        Args:
            api: AsyncDatabricksClient for query history lookup.
            provider: SharedContextProvider for EXPLAIN plans.
            events: Optional event emitter.
        """
        super().__init__(provider=provider, events=events)
        self.api = api

    @classmethod
    def from_provider(  # type: ignore[override]
        cls,
        api: AsyncDatabricksClient,
        provider: SharedContextProvider,
        events: EventEmitter | None = None,
    ) -> QueryTools:
        """Create QueryTools from API client and SharedContextProvider.

        Factory method for convenient construction.

        Args:
            api: AsyncDatabricksClient for query history lookup.
            provider: SharedContextProvider for EXPLAIN plans.
            events: Optional event emitter for observability.

        Returns:
            Configured QueryTools instance.
        """
        return cls(api=api, provider=provider, events=events)

    async def resolve_query(
        self,
        target: str,
        classification: dict | None = None,
    ) -> dict[str, Any]:
        """Resolve SQL text from user input.

        Args:
            target: Statement ID or raw SQL query.
            classification: Optional LLM classification hints.

        Returns:
            Dict with resolution result.

        Raises:
            MissingDataError: If SQL text cannot be resolved.

        Example:
            >>> result = await tools.resolve_query("SELECT * FROM table")
            >>> # Returns: {"source": "raw_sql", "sql_text": "SELECT ..."}
        """
        self.events.emit_info(
            source="query_tools",
            message="Resolving query",
            phase="execution",
        )

        input_data = QueryResolutionInput(
            target=target,
            classification=classification,
        )

        # Call domain logic directly
        result = QueryResolver.resolve_query(input_data)

        logger.debug(
            "resolve_query",
            extra={
                "result": result,
            },
        )
        # Enrich with API data if needed - BB-06: Fetch plan and metrics in single call
        if result.source == QuerySource.QUERY_HISTORY and result.statement_id:
            # Request plan and metrics to avoid unnecessary follow-up tool calls
            query = await self.api.get_query(
                result.statement_id,
                include_plan=True,
                include_metrics=True,
            )
            if query:
                logger.debug(
                    f"Successfully resolved query from statement ID: {result.statement_id}"
                )
                result = QueryResolutionResult(
                    source=result.source,
                    statement_id=result.statement_id,
                    sql_text=query.get("query_text"),
                    plan_text=query.get("plan_text"),
                    metrics=query.get("metrics"),
                )

        # Validate we got SQL text
        if not result.sql_text:
            logger.error("No valid SQL text found: {input_data.target}")
            raise MissingDataError(
                data_key="sql_text",
                source="resolve_query",
                details={"input": input_data.target},
            )

        # BB-06: Transform result to include distilled plan and metrics summaries
        # This allows the LLM to see key insights without needing separate tool calls
        raw_result = {
            "source": result.source.value,
            "statement_id": result.statement_id,
            "sql_text": result.sql_text,
            "plan_text": result.plan_text,
            "metrics": result.metrics,
        }

        return transform_resolve_query_result(raw_result)

    async def analyze_query_plan(self, sql_text: str) -> dict[str, Any]:
        """Generate and analyze EXPLAIN plan.

        Args:
            sql_text: SQL query to analyze.

        Returns:
            Dict with plan and facts.

        Example:
            >>> result = await tools.analyze_query_plan("SELECT * FROM table")
            >>> # Returns: {"plan_text": "...", "facts": {...}}
        """
        self.events.emit_info(
            source="query_tools",
            message="Analyzing query plan",
            phase="execution",
        )

        input_data = ExplainPlanInput(sql_text=sql_text)

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

        # Use transforms helper for EXPLAIN plan
        plan_text = await get_explain_plan(self.provider, input_data.sql_text)

        if not plan_text:
            return {"plan_text": "", "facts": None}

        # Parse plan using domain logic
        result: ExplainPlanResult = QueryAnalyzer.parse_explain_plan(plan_text)

        return {
            "plan_text": result.plan_text,
            "facts": result.facts,
        }

    async def analyze_explain_plan(self, explain_text: str) -> dict[str, Any]:
        """Extract key metrics from EXPLAIN plan.

        Args:
            explain_text: EXPLAIN plan output text.

        Returns:
            Dict with extracted facts from plan.

        Example:
            >>> result = await tools.analyze_explain_plan(plan_text)
            >>> # Returns: {"facts": {...}}
        """
        # Delegate to domain logic
        result = QueryAnalyzer.parse_explain_plan(explain_text)

        return {
            "facts": result.facts,
        }
