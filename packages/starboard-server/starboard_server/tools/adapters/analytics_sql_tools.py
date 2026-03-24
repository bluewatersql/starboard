"""Analytics SQL Generation Tools (Agentic RAG Workflow).

Provides agent-callable tools for the agentic RAG pattern:
1. build_sql_query: Generate SQL from user query + RAG context
2. validate_sql_query: Validate SQL with syntax + EXPLAIN gates
3. execute_sql_query: Execute validated SQL on Databricks

These tools implement a multi-step workflow where the agent controls RAG discovery and SQL generation.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import polars as pl
from starboard_core.rag.models import RAGContext

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.analytics.dataframe_profiler import profile_dataframe
from starboard_server.tools.domain.analytics_sql.llm_sql_generator import (
    LLMSQLGenerator,
)
from starboard_server.tools.domain.analytics_sql.models import (
    QueryDomain,
    QueryIntent,
    QueryIntentContext,
)
from starboard_server.tools.domain.analytics_sql.sql_validator import SQLValidator
from starboard_server.tools.services.direct_chart_builder import (
    DirectChartConfigBuilder,
)

if TYPE_CHECKING:
    from starboard_server.adapters.databricks.async_sql_executor import AsyncSQLExecutor
    from starboard_server.adapters.llm.base import BaseLLMClient
    from starboard_server.tools.services.query_result_cache import QueryResultCache

logger = get_logger(__name__)


class AnalyticsSQLTools:
    """Agent-callable tools for Analytics agentic RAG workflow.

    Provides three main tools:
    - build_sql_query: LLM-powered SQL generation from RAG context
    - validate_sql_query: Two-gate validation (syntax + EXPLAIN)
    - execute_sql_query: Execute validated SQL on Databricks with caching and visualization
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        sql_executor: AsyncSQLExecutor,
        sql_validator: SQLValidator,
        result_cache: QueryResultCache | None = None,
    ):
        """Initialize Analytics SQL tools.

        Args:
            llm_client: LLM client for SQL generation
            sql_executor: SQL executor for query execution
            sql_validator: SQL validator (with EXPLAIN support)
            result_cache: Optional result cache for query results (enables frontend data fetching)
        """
        self.llm_client = llm_client
        self.sql_executor = sql_executor
        self.sql_validator = sql_validator
        self.result_cache = result_cache

        # Store LLM hints for later use in execute_sql_query
        self.current_llm_hints: dict[str, Any] | None = None

        # RAG context cache (session-scoped, thread-safe via instance state)
        # Stores RAGContext by handle to avoid LLM serialization issues and reduce token usage
        self._rag_context_cache: dict[str, RAGContext] = {}
        self._context_timestamps: dict[str, float] = {}
        self._context_ttl = 3600  # 1 hour TTL

        # Create SQL generator (used by build_sql_query)
        # No validator or max_iterations - agent controls validation and reflexion
        self.sql_generator = LLMSQLGenerator(
            llm_client=llm_client,  # type: ignore[arg-type]
            temperature=0.2,  # Low temperature for structured SQL output
            max_tokens=getattr(self.llm_client, "max_tokens", 7500),
        )

        # Create chart config builder (replaces VisualizationService)
        self.chart_builder = DirectChartConfigBuilder()

        logger.debug(
            "analytics_sql_tools_initialized",
            extra={
                "caching_enabled": result_cache is not None,
            },
        )

    def store_rag_context(self, context: RAGContext) -> str:
        """Store RAG context and return handle.

        This is called by build_analytics_context tool to store the retrieved context
        and return an opaque handle to the agent. The agent passes this handle to
        build_sql_query without needing to see or manipulate the full context.

        Args:
            context: RAGContext to store

        Returns:
            Unique handle string (format: "ctx_{12_char_hex}")
        """
        import uuid

        handle = f"ctx_{uuid.uuid4().hex[:12]}"
        self._rag_context_cache[handle] = context
        self._context_timestamps[handle] = time.time()

        # Cleanup expired contexts (keep cache bounded)
        self._cleanup_expired_contexts()

        logger.debug(
            "rag_context_stored",
            extra={
                "context_handle": handle,
                "tables_count": len(context.tables),
                "nuance_count": len(context.nuance),
                "codebook_count": len(context.codebook),
                "cache_size": len(self._rag_context_cache),
            },
        )

        return handle

    def _retrieve_rag_context(self, context_handle: str) -> RAGContext | None:
        """Retrieve RAG context by handle.

        Args:
            context_handle: Context handle returned by build_analytics_context

        Returns:
            RAGContext if found and not expired, None otherwise
        """
        if context_handle not in self._rag_context_cache:
            logger.warning(
                "context_handle_not_found",
                extra={"context_handle": context_handle},
            )
            return None

        # Check expiration
        timestamp = self._context_timestamps.get(context_handle, 0)
        age_seconds = time.time() - timestamp

        if age_seconds > self._context_ttl:
            logger.warning(
                "context_handle_expired",
                extra={
                    "context_handle": context_handle,
                    "age_seconds": age_seconds,
                    "ttl_seconds": self._context_ttl,
                },
            )
            del self._rag_context_cache[context_handle]
            del self._context_timestamps[context_handle]
            return None

        logger.debug(
            "rag_context_retrieved",
            extra={
                "context_handle": context_handle,
                "age_seconds": age_seconds,
            },
        )
        return self._rag_context_cache[context_handle]

    def _cleanup_expired_contexts(self) -> None:
        """Remove expired contexts to prevent unbounded cache growth."""
        current_time = time.time()
        expired = [
            handle
            for handle, timestamp in self._context_timestamps.items()
            if current_time - timestamp > self._context_ttl
        ]

        for handle in expired:
            del self._rag_context_cache[handle]
            del self._context_timestamps[handle]

        if expired:
            logger.debug(
                "expired_contexts_cleaned",
                extra={
                    "expired_count": len(expired),
                    "remaining": len(self._rag_context_cache),
                },
            )

    async def build_sql_query(
        self,
        user_query: str,
        context_handle: str,
        previous_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate SQL from user query using cached RAG context.

        Args:
            user_query: Natural language query from the user
            context_handle: Handle to cached RAG context (from build_analytics_context)
            previous_errors: Optional list of previous validation errors for reflexion loop

        Returns:
            Dict with:
                - sql: Generated SQL query string
                - confidence: Confidence score (0.0-1.0)
                - missing_context: List of missing context types (if confidence < 0.7)
                - reasoning: LLM reasoning about the SQL generation
                - success: Whether generation succeeded
                - error: Error message if generation failed
        """
        # Retrieve context from cache using handle
        rag_ctx = self._retrieve_rag_context(context_handle)

        if rag_ctx is None:
            error_msg = (
                f"Invalid or expired context_handle: {context_handle}. "
                "Please call build_analytics_context again to get a fresh context."
            )
            logger.error(
                "build_sql_query_invalid_handle",
                extra={"context_handle": context_handle, "user_query": user_query},
            )
            return {
                "success": False,
                "error": error_msg,
                "sql": None,
                "confidence": 0.0,
                "missing_context": ["valid_rag_context"],
                "reasoning": "Context handle is invalid or expired. Re-run build_analytics_context.",
            }

        logger.debug(
            "build_sql_query_called",
            extra={
                "user_query": user_query,
                "context_handle": context_handle,
                "rag_context_tables": len(rag_ctx.tables),
                "rag_context_nuance": len(rag_ctx.nuance),
                "has_previous_errors": previous_errors is not None
                and len(previous_errors) > 0,
            },
        )

        # Build minimal intent context (agent already classified, but generator needs it)
        # Extract domain from tables if possible (prefer rag_resource_domain)
        domain = QueryDomain.BILLING  # Default, could be smarter
        source = "default"
        table_domain_raw = None
        if rag_ctx.tables:
            table_domain_raw = rag_ctx.tables[0].domain
            if table_domain_raw:
                try:
                    domain = QueryDomain(table_domain_raw)
                    source = "rag_resource_domain"
                except ValueError:
                    logger.warning(
                        "unmapped_table_domain",
                        extra={"table_domain_raw": table_domain_raw},
                    )

        logger.debug(
            "intent_resolution_context",
            extra={
                "resolved_domain": domain.value,
                "source": source,
                "table_domain_raw": table_domain_raw,
            },
        )

        intent_context = QueryIntentContext(
            intent=QueryIntent.COST_ANALYSIS,  # Default for analytics
            domain=domain,
            confidence=1.0,  # Agent controls classification
            metrics=[],
            dimensions=[],
            reasoning="Agent-driven workflow",  # Required field
        )

        # Generate SQL using LLM (single-shot, no internal validation)
        try:
            sql_result = await self.sql_generator.generate(
                user_query=user_query,
                intent_context=intent_context,
                rag_context=rag_ctx,
                previous_errors=previous_errors,
            )
        except Exception as e:
            logger.error(
                "sql_generation_failed",
                extra={
                    "user_query": user_query,
                    "error": str(e),
                },
            )
            raise ValueError(f"SQL generation failed: {str(e)}") from e

        # Store LLM hints for later use in execute_sql_query
        self.current_llm_hints = sql_result

        return sql_result

    async def validate_sql_query(
        self, sql: str, runtime_validation: bool = False
    ) -> dict[str, Any]:
        """Validate SQL query using two-gate validation.

        Gate 1: SQLglot syntax validation
        Gate 2: EXPLAIN plan validation (runtime)

        Args:
            sql: SQL query to validate

        Returns:
            Dict with:
            - is_valid: True if passed both gates
            - errors: List of error messages (empty if valid)
            - warnings: List of warnings (may exist even if valid)
            - validation_method: Which gates were used
        """
        logger.debug(
            "validate_sql_query_called",
            extra={"sql_preview": sql[:100]},
        )

        validation_result = await self.sql_validator.validate(sql, runtime_validation)

        logger.debug(
            "sql_validation_complete",
            extra={
                "is_valid": validation_result.is_valid,
                "validation_method": validation_result.validation_method,
                "errors_count": len(validation_result.errors),
                "warnings_count": len(validation_result.warnings),
            },
        )

        return validation_result.model_dump()

    async def execute_sql_query(
        self,
        sql: str,
    ) -> dict[str, Any]:
        """Execute validated SQL query on Databricks with caching, formatting, and profiling.

        IMPORTANT: SQL must be validated first with validate_sql_query.

        This method:
        1. Pre-execution syntax gate (defense-in-depth)
        2. Checks cache (using normalized SQL hash) - returns immediately if cache hit
        3. Executes SQL on Databricks (if cache miss)
        4. Serializes results (handles dates, decimals, NaN, etc.)
        5. Profiles DataFrame (statistics, distributions, trends)
        6. Caches results for frontend visualization
        7. Returns LLM-optimized formatted results

        Args:
            sql: Validated SQL query to execute

        Returns:
            Dict with:
            - results: JSON-safe query results (serialized)
            - row_count: Number of rows returned
            - execution_time_ms: Query execution time
            - sql: Original SQL query
            - data_reference: Unique ID for cached data (if caching enabled)
            - formatted_results: LLM-optimized profile with:
                - numeric_stats: Aggregations, min/max, percentiles
                - categorical_stats: Top values and distributions
                - temporal_stats: Date ranges
                - sample_rows: Representative sample (up to 20 rows)
                - trend: Time-series trend if applicable

        Raises:
            RuntimeError: If query execution fails
            ValueError: If SQL fails syntax validation gate
        """
        # Gate 1: Defense-in-depth syntax validation before execution.
        # Even though validate_sql_query should have been called first,
        # re-validate here to block any bypass path (e.g., direct tool call).
        syntax_result = self.sql_validator._validate_syntax(sql)
        if not syntax_result.is_valid:
            logger.warning(
                "execute_sql_query_blocked_by_syntax_gate",
                extra={
                    "sql_preview": sql[:100],
                    "errors": syntax_result.errors,
                },
            )
            raise ValueError(
                f"SQL blocked by pre-execution validation: {'; '.join(syntax_result.errors)}"
            )

        start_time = time.perf_counter()

        logger.debug(
            "execute_sql_query_called",
            extra={"sql_preview": sql[:100]},
        )

        try:
            sql_cache_key = self.sql_validator.generate_sql_cache_key(sql)
        except Exception as e:
            logger.debug(
                "sql_cache_key_generation_failed",
                extra={
                    "error": str(e),
                },
            )
            sql_cache_key = None

        try:
            # Execute SQL query (AsyncSQLExecutor has its own Layer 1 cache)
            df = await self.sql_executor.execute_sql(
                sql=sql,
                use_cache=True,
                sql_cache_key=sql_cache_key,
            )

            # Calculate execution time
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Profile DataFrame for LLM consumption
            # This provides rich statistics, distributions, and sample rows
            formatted_results = self._profile_results(df, sql)

            # Cache result (Layer 2: frontend data fetching)
            data_reference: str | None = None
            if self.result_cache is not None:
                try:
                    data_reference = await self.result_cache.cache_result_by_sql(
                        sql=sql,
                        df=df,
                        sql_cache_key=sql_cache_key,
                    )
                    logger.debug(
                        "query_result_cached",
                        extra={
                            "data_reference": data_reference,
                            "sql_preview": sql[:100],
                            "sql_cache_key": sql_cache_key,
                            "row_count": df.height,
                        },
                    )
                except Exception as cache_error:
                    # Don't fail query execution if caching fails
                    logger.warning(
                        "result_caching_failed",
                        extra={
                            "error": str(cache_error),
                            "sql_preview": sql[:100],
                        },
                    )

            logger.debug(
                "sql_query_executed_results",
                extra={
                    "row_count": df.height,
                    "execution_time_ms": execution_time_ms,
                    "has_formatted_results": bool(formatted_results),
                    "numeric_columns": len(formatted_results.get("numeric_stats", {})),
                    "categorical_columns": len(
                        formatted_results.get("categorical_stats", {})
                    ),
                    "data_reference": data_reference,
                },
            )

            # Generate visualization (always available with DirectChartConfigBuilder)
            visualization_output = None
            if data_reference:
                try:
                    visualization_output = self._generate_visualization(
                        _sql=sql,
                        data_profile=formatted_results,
                        data_reference=data_reference,
                    )

                    logger.debug(
                        "execute_sql_query_visualization_added",
                        extra={
                            "has_chart_config": "chart_config" in visualization_output,
                            "chart_config_type": type(
                                visualization_output.get("chart_config")
                            ).__name__
                            if visualization_output.get("chart_config")
                            else None,
                            "chart_config_keys": list(
                                visualization_output["chart_config"].keys()
                            )
                            if visualization_output.get("chart_config")
                            else [],
                            "visualization_keys": list(visualization_output.keys()),
                        },
                    )
                except Exception as viz_error:
                    # Don't fail query execution if visualization fails
                    logger.warning(
                        "visualization_generation_failed",
                        extra={
                            "error": str(viz_error),
                            "sql_preview": sql[:100],
                        },
                    )

            result = {
                "formatted_results": formatted_results,
                "visualization": visualization_output,
                "row_count": df.height,
                "metadata": {
                    "execution_time_ms": execution_time_ms,
                },
            }

            logger.debug(
                "execute_sql_query_complete",
                extra={
                    "result": result,
                },
            )

            return result

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "sql_query_execution_failed",
                extra={
                    "sql_preview": sql[:100],
                    "error": str(e),
                    "execution_time_ms": execution_time_ms,
                },
            )
            raise RuntimeError(f"Query execution failed: {str(e)}") from e

    def _profile_results(self, df: pl.DataFrame, sql: str) -> dict[str, Any]:
        """Profile DataFrame results for LLM consumption.

        Uses profile_dataframe to generate comprehensive statistics including:
        - Numeric aggregations (sum, min, max, mean, percentiles)
        - Categorical distributions (top values)
        - Temporal ranges
        - Time-series trends (if applicable)
        - Sample rows

        Args:
            df: Polars DataFrame with query results
            sql: SQL query (for logging)

        Returns:
            Profile dict with comprehensive statistics
        """
        if len(df) == 0:
            return {
                "row_count": 0,
                "column_count": 0,
                "columns": [],
                "numeric_stats": {},
                "categorical_stats": {},
                "temporal_stats": {},
                "trend": None,
                "sample_rows": [],
            }

        # Auto-detect time and metric columns for trend analysis
        time_col = None
        metric_col = None

        # Look for common time columns
        for col in df.columns:
            col_lower = col.lower()
            if any(word in col_lower for word in ["time", "date", "timestamp"]):
                time_col = col
                break

        # Look for cost/metric columns
        for col in df.columns:
            col_lower = col.lower()
            if any(
                word in col_lower
                for word in ["cost", "price", "spend", "dbu", "amount", "usage"]
            ):
                metric_col = col
                break

        try:
            # Generate comprehensive profile
            profile = profile_dataframe(
                df,
                max_categories=30,
                max_top_values=10,
                sample_rows=min(20, len(df)),
                trend_time_column=time_col,
                trend_metric_column=metric_col,
            )

            logger.debug(
                "results_profiled",
                extra={
                    "row_count": profile["row_count"],
                    "column_count": profile["column_count"],
                    "numeric_columns": len(profile["numeric_stats"]),
                    "categorical_columns": len(profile["categorical_stats"]),
                    "has_trend": profile["trend"] is not None,
                },
            )

            return profile

        except Exception as e:
            logger.warning(
                "result_profiling_failed",
                extra={
                    "error": str(e),
                    "sql_preview": sql[:100],
                },
            )
            # Return minimal profile on error
            return {
                "row_count": len(df),
                "column_count": len(df.columns),
                "columns": df.columns,
                "numeric_stats": {},
                "categorical_stats": {},
                "temporal_stats": {},
                "trend": None,
                "sample_rows": [],
            }

    def _transform_llm_hints_to_builder_format(
        self, llm_hints: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Transform LLM visualization_hints to DirectChartConfigBuilder format.

        LLM generates hints in one format, but DirectChartConfigBuilder expects a different format.
        This method bridges the gap.

        LLM format:
            {
                "recommended_chart_types": ["line", "area"],  # Array of types
                "primary_metric": "total_cost_usd",           # Y-axis field
                "primary_dimension": "usage_date",            # X-axis field
                "is_time_series": true,
                "is_top_n": false,
                "aggregation_type": "sum"
            }

        Builder format:
            {
                "chart_type": "line",           # Single type (first from array)
                "x_field": "usage_date",        # X-axis field
                "y_field": "total_cost_usd",    # Y-axis field
                "x_type": "temporal",           # Encoding type
                "y_type": "quantitative"        # Encoding type
            }

        Args:
            llm_hints: Visualization hints from LLM SQL generator

        Returns:
            Transformed hints compatible with DirectChartConfigBuilder, or None if hints invalid
        """
        if not llm_hints:
            return None

        # Pick first recommended chart type
        chart_types = llm_hints.get("recommended_chart_types", [])
        if not chart_types:
            logger.warning(
                "llm_hints_missing_chart_types",
                extra={"llm_hints": llm_hints},
            )
            return None

        chart_type = chart_types[0] if isinstance(chart_types, list) else chart_types

        # Map to encoding types based on query characteristics
        is_time_series = llm_hints.get("is_time_series", False)
        x_type = "temporal" if is_time_series else "nominal"

        builder_hints = {
            "chart_type": chart_type,
            "x_field": llm_hints.get("primary_dimension"),
            "y_field": llm_hints.get("primary_metric"),
            "x_type": x_type,
            "y_type": "quantitative",
            "aggregation_type": llm_hints.get("aggregation_type"),
        }

        logger.debug(
            "llm_hints_transformed",
            extra={
                "llm_hints": llm_hints,
                "builder_hints": builder_hints,
            },
        )

        return builder_hints

    def _generate_visualization(
        self,
        _sql: str,
        *,
        data_profile: dict[str, Any],
        data_reference: str,
    ) -> dict[str, Any]:
        """Generate visualization config deterministically from LLM hints.

        This method builds ChartConfig directly from the hints generated during
        SQL creation, eliminating the need for a second LLM call.

        Args:
            _sql: SQL query (not currently used, retained for interface compatibility)
            data_profile: Data profile from _profile_results
            data_reference: Cache reference for frontend data fetching

        Returns:
            VisualizationOutput dict with chart recommendation and config
        """

        # Extract LLM hints from build_sql_query
        llm_hints = (
            self.current_llm_hints.get("visualization_hints", {})
            if self.current_llm_hints
            else None
        )

        logger.debug(
            "visualization_building_from_hints",
            extra={
                "llm_hints": llm_hints,
                "data_reference": data_reference,
            },
        )

        # Transform LLM hints to DirectChartConfigBuilder format
        builder_hints = self._transform_llm_hints_to_builder_format(llm_hints)

        # Build visualization deterministically from hints
        visualization_output = self.chart_builder.build_from_hints(
            hints=builder_hints,
            data_profile=data_profile,
            data_reference=data_reference,
        )

        logger.debug(
            "visualization_generated",
            extra={
                "has_visualization": visualization_output.has_visualization,
                "chart_type": (
                    visualization_output.chart_recommendation.chart_type.value
                    if visualization_output.chart_recommendation
                    else None
                ),
                "data_reference": data_reference,
            },
        )

        # Convert chart_config to dict for JSON serialization
        chart_config_dict = None
        if visualization_output.chart_config:
            chart_config_dict = visualization_output.chart_config.model_dump()
            logger.debug(
                "chart_config_serialized",
                extra={
                    "chart_config": chart_config_dict,
                    "has_chart_type": "chart_type" in chart_config_dict,
                    "has_title": "title" in chart_config_dict,
                    "keys": list(chart_config_dict.keys()),
                },
            )

        # Convert to dict for JSON serialization
        return {
            "summary": visualization_output.summary,
            "chart_recommendation": (
                {
                    "chart_type": visualization_output.chart_recommendation.chart_type.value,
                    "reasoning": visualization_output.chart_recommendation.reasoning,
                    "confidence": visualization_output.chart_recommendation.confidence,
                }
                if visualization_output.chart_recommendation
                else None
            ),
            "chart_config": chart_config_dict,
            "data_reference": visualization_output.data_reference,
            "has_visualization": visualization_output.has_visualization,
        }
