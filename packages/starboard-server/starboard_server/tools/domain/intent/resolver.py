# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure intent resolution logic.

Follows the pattern:
1. Detect context keywords
2. Extract candidate tokens (IDs, names, etc.)
3. Classify intent based on keywords + tokens
4. Generate friendly name

No I/O, no state, no dependencies on infrastructure.
"""

import re

from starboard_server.infra.constraints.utils import StringUtils
from starboard_server.tools.domain.intent.models import (
    ContextKeyword,
    IntentResolutionInput,
    IntentResolutionResult,
    IntentType,
)


class IntentResolver:
    """
    Pure intent resolution logic.

    All methods are static and side-effect free.
    No dependencies on infrastructure, state, or I/O.
    """

    # Keyword patterns for context detection
    JOB_KEYWORDS = [" job ", " jobs ", " job:", "job_id", "job id"]
    QUERY_KEYWORDS = [
        " query ",
        " queries ",
        " sql ",
        " statement ",
        "statement_id",
        "statement id",
        "select ",
        " explain ",
    ]
    PIPELINE_KEYWORDS = [
        " pipeline ",
        " pipelines ",
        " dlt ",
        " delta live table",
        " workflow ",
    ]
    TABLE_KEYWORDS = [" table ", " tables ", " from ", " into "]
    WAREHOUSE_KEYWORDS = [
        " warehouse ",
        " warehouses ",
        " endpoint ",
        " sql warehouse",
    ]
    CLUSTER_KEYWORDS = [" cluster ", " clusters ", "cluster_id", "cluster id"]

    @staticmethod
    def detect_context_keywords(text: str) -> set[ContextKeyword]:
        """
        Detect high-level context keywords from user input.

        Args:
            text: User input text

        Returns:
            Set of detected context keywords

        Example:
            >>> IntentResolver.detect_context_keywords("optimize job 12345")
            {ContextKeyword.JOB}
            >>> IntentResolver.detect_context_keywords("why is my query slow?")
            {ContextKeyword.QUERY}
        """
        keywords: set[ContextKeyword] = set()
        lowered = f" {text.lower()} "  # Pad for boundary matching

        if any(k in lowered for k in IntentResolver.JOB_KEYWORDS):
            keywords.add(ContextKeyword.JOB)

        if any(k in lowered for k in IntentResolver.QUERY_KEYWORDS):
            keywords.add(ContextKeyword.QUERY)
            keywords.add(ContextKeyword.SQL)

        if any(k in lowered for k in IntentResolver.PIPELINE_KEYWORDS):
            keywords.add(ContextKeyword.PIPELINE)

        if any(k in lowered for k in IntentResolver.TABLE_KEYWORDS):
            keywords.add(ContextKeyword.TABLE)

        if any(k in lowered for k in IntentResolver.WAREHOUSE_KEYWORDS):
            keywords.add(ContextKeyword.WAREHOUSE)

        if any(k in lowered for k in IntentResolver.CLUSTER_KEYWORDS):
            keywords.add(ContextKeyword.CLUSTER)

        return keywords

    @staticmethod
    def extract_job_id(text: str) -> str | None:
        """
        Extract job ID from text.

        Job IDs are typically long integers (5+ digits).

        Args:
            text: Input text

        Returns:
            Job ID if found, None otherwise

        Example:
            >>> IntentResolver.extract_job_id("optimize job 266829928906781")
            "266829928906781"
        """
        # Look for long integers (5+ digits) - likely job IDs
        match = re.search(r"\b(\d{5,})\b", text)
        return match.group(1) if match else None

    @staticmethod
    def extract_statement_id(text: str) -> str | None:
        """
        Extract statement ID (UUID) from text.

        Uses StringUtils.extract_uuids for consistency.

        Args:
            text: Input text

        Returns:
            Statement ID if found, None otherwise

        Example:
            >>> IntentResolver.extract_statement_id(
            ...     "statement id 01f0b1f6-f307-12a1-b6ef-3bfa899a4654"
            ... )
            "01f0b1f6-f307-12a1-b6ef-3bfa899a4654"
        """
        uuids = StringUtils.extract_uuids(text, unique=True)
        return uuids[0] if uuids else None

    @staticmethod
    def extract_table_name(text: str) -> str | None:
        """
        Extract table name from text.

        Looks for SQL-like table references: catalog.schema.table or schema.table

        Args:
            text: Input text

        Returns:
            Table name if found, None otherwise

        Example:
            >>> IntentResolver.extract_table_name("analyze table sales.fact_orders")
            "sales.fact_orders"
        """
        # Pattern: catalog.schema.table or schema.table or just table
        match = re.search(
            r"\b([a-z0-9_]+(?:\.[a-z0-9_]+){0,2})\b",
            text.lower(),
        )
        if match:
            name = match.group(1)
            # Exclude common SQL keywords
            sql_keywords = {
                "select",
                "from",
                "where",
                "table",
                "into",
                "insert",
                "update",
                "delete",
            }
            if name not in sql_keywords:
                return name
        return None

    @staticmethod
    def classify_intent(
        text: str,  # noqa: ARG004
        keywords: set[ContextKeyword],
        parameters: dict[str, str],
    ) -> tuple[IntentType, float, str]:
        """
        Classify intent based on keywords and extracted parameters.

        Uses a two-tier approach:
        1. Keyword-based classification (highest confidence)
        2. Pattern-based inference from ID types (fallback when no keywords)

        Args:
            text: User input text
            keywords: Detected context keywords
            parameters: Extracted parameters (job_id, statement_id, etc.)

        Returns:
            Tuple of (intent, confidence, reasoning)

        Example:
            >>> # With keyword
            >>> keywords = {ContextKeyword.JOB}
            >>> params = {"job_id": "12345"}
            >>> IntentResolver.classify_intent("optimize job 12345", keywords, params)
            (IntentType.OPTIMIZE_JOB, 0.9, "...")
            >>>
            >>> # Without keyword (pattern inference)
            >>> keywords = set()
            >>> params = {"statement_id": "abc-123-def"}
            >>> IntentResolver.classify_intent("tune abc-123-def", keywords, params)
            (IntentType.OPTIMIZE_QUERY, 0.85, "Inferred query intent from UUID pattern...")
        """
        # TIER 1: Keyword-based classification (highest confidence)

        # Job intent
        if ContextKeyword.JOB in keywords:
            confidence = 0.9 if "job_id" in parameters else 0.7
            reasoning = "Detected 'job' keyword in input" + (
                f" with job ID {parameters['job_id']}" if "job_id" in parameters else ""
            )
            return IntentType.OPTIMIZE_JOB, confidence, reasoning

        # Query/SQL intent
        if ContextKeyword.QUERY in keywords or ContextKeyword.SQL in keywords:
            confidence = 0.9 if "statement_id" in parameters else 0.7
            reasoning = "Detected 'query' or 'sql' keyword in input" + (
                f" with statement ID {parameters['statement_id'][:8]}..."
                if "statement_id" in parameters
                else ""
            )
            return IntentType.OPTIMIZE_QUERY, confidence, reasoning

        # Pipeline/Table intent
        if ContextKeyword.PIPELINE in keywords or ContextKeyword.TABLE in keywords:
            confidence = 0.8 if "table_name" in parameters else 0.6
            reasoning = "Detected 'pipeline' or 'table' keyword in input" + (
                f" referencing {parameters['table_name']}"
                if "table_name" in parameters
                else ""
            )
            return IntentType.OPTIMIZE_PIPELINE, confidence, reasoning

        # TIER 2: Pattern-based inference (no keywords, but ID patterns detected)

        # UUID pattern → query statement ID
        if "statement_id" in parameters:
            confidence = 0.85
            reasoning = (
                f"Inferred query intent from UUID pattern (statement_id: "
                f"{parameters['statement_id'][:8]}...{parameters['statement_id'][-8:]})"
            )
            return IntentType.OPTIMIZE_QUERY, confidence, reasoning

        # Long integer pattern → job ID
        if "job_id" in parameters:
            confidence = 0.85
            reasoning = (
                f"Inferred job intent from long integer pattern (job_id: "
                f"{parameters['job_id']})"
            )
            return IntentType.OPTIMIZE_JOB, confidence, reasoning

        # Table name pattern → pipeline/table optimization
        if "table_name" in parameters:
            confidence = 0.7
            reasoning = (
                f"Inferred pipeline/table intent from table reference "
                f"({parameters['table_name']})"
            )
            return IntentType.OPTIMIZE_PIPELINE, confidence, reasoning

        # TIER 3: Fallback when no keywords or patterns detected
        return (
            IntentType.GENERAL_INQUIRY,
            0.5,
            "No specific optimization keywords or ID patterns detected; treating as general inquiry",
        )

    @staticmethod
    def generate_friendly_name(
        intent: IntentType,
        parameters: dict[str, str],
    ) -> str:
        """
        Generate a friendly conversation name based on intent and parameters.

        Args:
            intent: Classified intent
            parameters: Extracted parameters

        Returns:
            Friendly name suggestion (max 100 chars)

        Example:
            >>> IntentResolver.generate_friendly_name(
            ...     IntentType.OPTIMIZE_JOB,
            ...     {"job_id": "12345"}
            ... )
            "Job Optimization for 12345"
        """
        if intent == IntentType.OPTIMIZE_JOB:
            if "job_id" in parameters:
                return f"Job Optimization for {parameters['job_id']}"
            return "Job Optimization"

        if intent == IntentType.OPTIMIZE_QUERY:
            if "statement_id" in parameters:
                statement_id = parameters["statement_id"]
                # Shorten UUID for display
                short_id = f"{statement_id[:8]}...{statement_id[-8:]}"
                return f"Query Optimization for {short_id}"
            return "Query Optimization"

        if intent == IntentType.OPTIMIZE_PIPELINE:
            if "table_name" in parameters:
                return f"Pipeline Optimization for {parameters['table_name']}"
            return "Pipeline Optimization"

        return "General Query"

    @staticmethod
    def resolve_intent(input_data: IntentResolutionInput) -> IntentResolutionResult:
        """
        Resolve user intent from input.

        This is the main entry point for intent resolution.
        Pure logic - no API calls, no state.

        Args:
            input_data: Intent resolution input

        Returns:
            IntentResolutionResult with classification and parameters

        Example:
            >>> input_data = IntentResolutionInput(
            ...     user_input="Optimize job 12345"
            ... )
            >>> result = IntentResolver.resolve_intent(input_data)
            >>> result.intent
            IntentType.OPTIMIZE_JOB
            >>> result.parameters["job_id"]
            "12345"
        """
        text = input_data.user_input

        # Step 1: Detect context keywords
        keywords = IntentResolver.detect_context_keywords(text)

        # Step 2: Extract candidate parameters
        parameters: dict[str, str] = {}

        job_id = IntentResolver.extract_job_id(text)
        if job_id:
            parameters["job_id"] = job_id

        statement_id = IntentResolver.extract_statement_id(text)
        if statement_id:
            parameters["statement_id"] = statement_id

        table_name = IntentResolver.extract_table_name(text)
        if table_name:
            parameters["table_name"] = table_name

        # Step 3: Classify intent
        intent, confidence, reasoning = IntentResolver.classify_intent(
            text, keywords, parameters
        )

        # Step 4: Generate friendly name
        friendly_name = IntentResolver.generate_friendly_name(intent, parameters)

        # Build result
        result = IntentResolutionResult(
            intent=intent,
            confidence=confidence,
            parameters=parameters,
            reasoning=reasoning,
            suggested_friendly_name=friendly_name,
            matched_keywords=[k.value for k in keywords],
            extracted_tokens=list(parameters.values()),
        )

        return result
