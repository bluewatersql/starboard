"""Analytics SQL - LLM-based SQL Generator (Agentic Pattern).

Generates SQL queries using LLM with RAG context. NO internal validation or loops.
The agent controls validation and reflexion externally.

Pattern: Single-Shot Generation
1. Take user query + RAG context
2. Generate SQL once
3. Return SQL (agent validates separately)
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.analytics_sql.models import (
    QueryIntentContext,
    RAGContext,
)

logger = get_logger(__name__)

# Supported visualization chart types (single source of truth)
SUPPORTED_CHART_TYPES = ["bar", "line", "area", "scatter", "histogram", "table"]


class LLMClient(Protocol):
    """Protocol for LLM client."""

    async def json_response(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate JSON response from LLM.

        Args:
            messages: List of message dictionaries with role and content
            schema: Optional JSON schema for structured output
            max_tokens: Optional maximum tokens for the response
            temperature: Optional temperature override
            **kwargs: Additional generation parameters

        Returns:
            Parsed JSON response dictionary
        """
        ...


class LLMSQLGenerator:
    """LLM-based SQL generator for agentic RAG workflow.

    This generator uses an LLM to create SQL queries from natural language,
    enriched with RAG context (tables, nuance, codebook, etc.).

    NO internal validation or reflexion loops - the agent controls the workflow:
    - Agent gathers RAG context
    - Agent calls generate() to get SQL
    - Agent validates SQL externally
    - If validation fails, agent gathers more RAG context and calls generate() again
    """

    def __init__(
        self,
        llm_client: LLMClient,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ):
        """Initialize SQL generator.

        Args:
            llm_client: LLM client for SQL generation
            temperature: LLM temperature for generation (default: 0.2, low for structured SQL)
            max_tokens: Maximum tokens for LLM response (default: 2000)
        """
        self.llm_client = llm_client
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def generate(
        self,
        user_query: str,
        intent_context: QueryIntentContext,
        rag_context: RAGContext,
        previous_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate SQL from user query and RAG context (single-shot, no validation).

        Agent workflow:
        1. Agent gathers RAG context (tables, nuance, codebook, etc.)
        2. Agent calls this method to generate SQL
        3. Agent validates SQL externally (validate_sql_query tool)
        4. If validation fails, agent gathers more context and calls this method again

        Args:
            user_query: Original natural language query
            intent_context: Classified intent and parameters
            rag_context: RAG-retrieved context (tables, nuance, codebook, facets, learnings)
            previous_errors: Optional validation errors from previous attempt (for reflexion)

        Returns:
            Dict with:
                - success: bool - Whether generation succeeded
                - sql: str - Generated SQL query
                - explanation: str - Brief explanation of query logic

        Raises:
            ValueError: If user_query is empty
            RuntimeError: If LLM generation fails
        """
        if not user_query or not user_query.strip():
            raise ValueError("User query cannot be empty")

        try:
            # Build prompt with RAG context
            prompt = self._build_prompt(
                user_query=user_query,
                intent_context=intent_context,
                rag_context=rag_context,
                previous_errors=previous_errors,
            )

            logger.debug(
                "llm_sql_generation_start",
                extra={
                    "user_query": user_query,
                    "has_previous_errors": bool(previous_errors),
                    "rag_context_size": {
                        "tables": len(rag_context.tables),
                        "nuance": len(rag_context.nuance),
                        "codebook": len(rag_context.codebook),
                        "facets": len(rag_context.facets),
                        "learnings": len(rag_context.learnings),
                    },
                },
            )

            # Generate SQL with LLM
            messages = [
                {
                    "role": "system",
                    "content": "You are a SQL expert. Return only SQL code, no markdown formatting.",
                },
                {"role": "user", "content": prompt},
            ]

            # JSON schema for structured SQL output
            sql_schema = {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Generated SQL query"},
                    "explanation": {
                        "type": "string",
                        "description": "Brief explanation of the query logic",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence score 0.0-1.0 for SQL correctness",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "missing_context": {
                        "type": "array",
                        "description": "List of context types missing for high confidence",
                        "items": {
                            "type": "string",
                            "enum": [
                                "field_names",  # Need table_columns, columns or codebook
                                "table_schema",  # Need detailed schema info
                                "join_keys",  # Need nuance about how to join tables
                                "value_examples",  # Need facets for valid values
                                "calculation_formulas",  # Need formulas for cost calculations
                                "none",  # All context available
                            ],
                        },
                    },
                    "confidence_reasoning": {
                        "type": "string",
                        "description": "Brief explanation of confidence level",
                    },
                    "visualization_hints": {
                        "type": "object",
                        "description": "Hints for visualization service to recommend appropriate charts",
                        "properties": {
                            "query_intent": {
                                "type": "string",
                                "description": "Brief summary of what user wants to see (1 sentence)",
                            },
                            "recommended_chart_types": {
                                "type": "array",
                                "description": "Chart types suitable for this query (1-3 types)",
                                "items": {
                                    "type": "string",
                                    "enum": SUPPORTED_CHART_TYPES,
                                },
                                "minItems": 1,
                                "maxItems": 3,
                            },
                            "primary_metric": {
                                "type": "string",
                                "description": "Main numeric column to visualize (null if not applicable)",
                            },
                            "primary_dimension": {
                                "type": "string",
                                "description": "Main dimension/grouping column (null if not applicable)",
                            },
                            "is_time_series": {
                                "type": "boolean",
                                "description": "True if query involves temporal analysis",
                            },
                            "is_top_n": {
                                "type": "boolean",
                                "description": "True if query is ranking/sorting top N items",
                            },
                            "aggregation_type": {
                                "type": "string",
                                "description": "Type of aggregation used",
                                "enum": ["sum", "count", "avg", "min", "max", "none"],
                            },
                        },
                        "required": [
                            "query_intent",
                            "recommended_chart_types",
                            "is_time_series",
                            "is_top_n",
                            "aggregation_type",
                        ],
                    },
                },
                "required": [
                    "sql",
                    "explanation",
                    "confidence",
                    "missing_context",
                    "confidence_reasoning",
                    "visualization_hints",
                ],
                "additionalProperties": False,
            }

            # Use low temperature for deterministic SQL generation (POC uses 0.1)
            sql_temp = 0.1
            llm_response = await self.llm_client.json_response(
                messages=messages,
                schema=sql_schema,
                temperature=sql_temp,
                max_tokens=self.max_tokens,
            )

            sql = llm_response.get("sql", "")
            explanation = llm_response.get("explanation", "")

            if not sql or not sql.strip():
                raise RuntimeError("LLM returned empty SQL")

            logger.debug(
                "llm_sql_generation_query",
                extra={
                    "user_query": user_query,
                    "sql_query": sql,
                },
            )

            logger.debug(
                "llm_sql_generation_success",
                extra={
                    "user_query": user_query,
                    "confidence": llm_response.get("confidence"),
                    "missing_context": llm_response.get("missing_context"),
                    "confidence_reasoning": llm_response.get("confidence_reasoning"),
                    "explanation": explanation,
                },
            )

            return {
                "success": True,
                "sql": sql.strip(),
                "explanation": explanation,
                "confidence": llm_response.get("confidence"),
                "missing_context": llm_response.get("missing_context"),
                "confidence_reasoning": llm_response.get("confidence_reasoning"),
                "visualization_hints": llm_response.get("visualization_hints", {}),
            }

        except Exception as e:
            logger.error(
                "llm_sql_generation_error",
                extra={
                    "user_query": user_query[:100],
                    "error": str(e),
                },
            )
            raise RuntimeError(f"SQL generation failed: {str(e)}") from e

    def _build_prompt(
        self,
        user_query: str,
        intent_context: QueryIntentContext,
        rag_context: RAGContext,
        previous_errors: list[str] | None = None,
    ) -> str:
        """Build prompt for LLM SQL generation (POC-style).

        Args:
            user_query: Original user query
            intent_context: Classified intent and parameters
            rag_context: RAG context with tables, nuance, codebook, facets, learnings
            previous_errors: Validation errors from previous attempt (for reflexion)

        Returns:
            Prompt string (concise, structured, POC-validated)
        """
        # Build metadata payload (JSON format like POC)
        metadata = {
            "tables": [t.table_name for t in rag_context.tables],
            "context": rag_context.model_dump(exclude_none=True),
            "intent": intent_context.intent.value,
            "domain": intent_context.domain.value,
        }

        # Base prompt
        prompt = f"""You are a Databricks SQL expert working with the Databricks system tables.

User Question: {user_query}

CONTEXT:
{json.dumps(metadata, indent=2)}

Generate a valid Databricks SQL query that answers the user's question. Follow these rules:

## Query Structure & Joins
1. **Prefer LEFT JOIN by default** unless a specific join strategy is required (e.g., INNER JOIN for existence checks, SEMI JOIN for filtering)
   - Use LEFT JOIN to preserve all records from the primary table
   - Only use INNER JOIN when you specifically need to exclude non-matching records
   - Consider SEMI/ANTI JOIN for existence-based filtering (more efficient than IN/NOT IN)

2. **Handle SCD (Slowly Changing Dimension) tables appropriately:**
   - Use ROW_NUMBER() with QUALIFY for current record selection:
```sql
     SELECT *
     FROM scd_table
     QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY effective_date DESC) = 1
```
   - Alternative pattern: `WHERE is_current = TRUE` if available
   - For point-in-time queries, use: `WHERE effective_date <= target_date AND (end_date > target_date OR end_date IS NULL)`

## Table & Column Selection
3. Use only the tables and table context provided.
   - Do not make up or use columns not explicitly provided in the context.

4. Always include the relevant domain table for context (e.g. warehouse, cluster, job, pipeline, etc.)
   - Do not show only cost/price tables without resource model context

5. Always include user-friendly names when available (e.g. Job Name, Pipeline Name, Cluster Name, etc.)

## Filtering & Performance
6. **Always include date filters** as early as possible (push down predicates):
   - Example: `WHERE usage_date >= CURRENT_DATE - INTERVAL 30 DAYS`
   - Place date filters before joins when possible

7. **For cost calculations**, join usage with list_prices using temporal join:
```sql
   usage.sku_name = list_prices.sku_name
   AND usage.usage_date BETWEEN list_prices.pricing_start_time AND list_prices.pricing_end_time
```

8. When creating cross-domain queries, ensure consistent grain and units of measure (day, hour, DBU, USD$)
   - If consistent grain is not possible, use most granular grain available.

## Performance Optimizations
9. **Aggregation optimizations:**
   - Pre-aggregate before joins when possible
   - Use GROUP BY on fewer columns first, then add more granularity if needed
   - Consider using APPROX_COUNT_DISTINCT() for large cardinality estimates

10. **Predicate pushdown:**
    - Apply WHERE filters before JOINs
    - Use partition pruning when available (e.g., filter on partition columns first)

11. **Column pruning:**
    - Select only necessary columns, avoid SELECT *
    - Push column selection down in CTEs/subqueries

12. **Join optimizations:**
    - Put smaller/filtered tables first in join order when possible
    - Use broadcast hints for small dimension tables: `/*+ BROADCAST(small_table) */`
    - Consider bucketing/sorting hints for large joins

13. **CTE vs Subquery:**
    - Use CTEs for readability and reusability
    - Databricks optimizes CTEs, so no performance penalty for reuse

## Data Type Handling
14. Pay attention to column data types and ensure valid operations:
    - Navigate complex types (struct<..>, array<..>, map<..>, etc.) appropriately
    - Use dot notation for structs: `column.field`
    - Use element access for arrays: `column[0]` or `EXPLODE(column)`
    - Avoid operations on incompatible types (ex: math/binary operations on struct<..> and decimal)
    - Cast appropriately when needed: `CAST(column AS type)`

## Safety & Standards
15. Use fully qualified table names (system.schema.table)

16. Add LIMIT 1000 for safety (unless aggregation returns limited rows)

## Additional Best Practices
17. **For temporal queries:** Use date_trunc() or window functions for time-based grouping

18. **For top-N queries:** Use QUALIFY with ROW_NUMBER() instead of subqueries

19. **For deduplication:** Prefer QUALIFY over DISTINCT when possible for better performance

20. **Null handling:** Be explicit about NULL behavior in joins and aggregations

CONFIDENCE SCORING:
After generating SQL, assess your confidence (0.0-1.0):

HIGH (0.8-1.0): All column names, join keys, and logic available from context
MEDIUM (0.6-0.79): Minor assumptions made, query likely works
LOW (0.0-0.59): Significant guessing, likely to fail

Confidence reducers:
- Missing column names or data types → cap at 0.7
- Unknown join keys → cap at 0.7
- Guessing field names or using generic patterns → cap at 0.6
- Missing required filter values or calculation formulas → cap at 0.8

If confidence < 0.7, list missing context:
Examples: ["field_names"], ["join_keys"], ["calculation_formulas"], ["valid_filter_values"]

Return your SQL, explanation, confidence score, missing context, and reasoning.
"""

        # Add Reflexion context if this is a correction attempt
        if previous_errors:
            prompt += "\nIMPORTANT: Previous SQL failed validation with these errors:"

            if isinstance(previous_errors, str):
                try:
                    error_list = json.loads(previous_errors)
                except json.JSONDecodeError:
                    error_list = [previous_errors]  # Single error string
            else:
                error_list = previous_errors  # Already a list

            for error in error_list:
                prompt += f"- {error}"
            prompt += "\n\nFix ALL errors using the context above. Check column names, table names, and syntax carefully"

        # Add visualization guidance
        prompt += """

VISUALIZATION HINTS:
Recommend appropriate charts based on query structure.

SUPPORTED TYPES (use ONLY these):
- "line" / "area" - Time-series (GROUP BY date/time)
- "bar" - Categories or rankings (GROUP BY category, TOP N)
- "scatter" - Two numeric correlations (no GROUP BY)
- "histogram" - Single numeric distribution
- "table" - Default for complex queries (>5 columns, <5 rows, many JOINs)

DECISION LOGIC:
- GROUP BY date/time + metric → ["line", "area"]
- GROUP BY category + ORDER BY + LIMIT → ["bar"]
- Two numerics, no GROUP BY → ["scatter"]
- Otherwise → ["table"]

RETURN FORMAT:
{
    "query_intent": "<brief description>",
    "recommended_chart_types": ["<type>"],
    "primary_metric": "<column_name>",
    "primary_dimension": "<column_name or null>",
    "is_time_series": <bool>,
    "is_top_n": <bool>,
    "aggregation_type": "<sum|avg|count|etc>"
}

EXAMPLES:

"Show warehouse costs over 30 days"
→ {recommended_chart_types: ["line", "area"], primary_metric: "list_cost",
   primary_dimension: "usage_date", is_time_series: true}

"Top 10 warehouses by cost"
→ {recommended_chart_types: ["bar"], primary_metric: "list_cost",
   primary_dimension: "warehouse_id", is_top_n: true}

"Usage vs cost correlation"
→ {recommended_chart_types: ["scatter"], primary_metric: "list_cost",
   primary_dimension: null, is_time_series: false}
"""

        prompt += "\nReturn only the SQL query, no explanations."

        logger.debug(
            "llm_sql_generation_prompt",
            extra={"prompt": prompt},
        )

        return prompt
