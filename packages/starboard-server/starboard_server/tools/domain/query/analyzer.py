# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure query analysis logic."""

from starboard_core.domain.models.query import ExplainPlanResult

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.query import transformers as query_transformers

logger = get_logger(__name__)


class QueryAnalyzer:
    """Pure query analysis logic (no I/O)."""

    @staticmethod
    def parse_explain_plan(plan_text: str) -> ExplainPlanResult:
        """
        Parse EXPLAIN plan text into structured facts.

        Args:
            plan_text: Raw EXPLAIN plan output

        Returns:
            ExplainPlanResult with parsed facts

        Example:
            >>> plan = "== Physical Plan ==\\nScan parquet table..."
            >>> result = QueryAnalyzer.parse_explain_plan(plan)
            >>> result.facts is not None
            True
        """
        facts = query_transformers.transform_explain_text(plan_text)

        return ExplainPlanResult(
            plan_text=plan_text,
            facts=facts,
        )
