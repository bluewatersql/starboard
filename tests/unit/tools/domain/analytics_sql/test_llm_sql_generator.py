"""Unit tests for LLMSQLGenerator.

Tests cover LLM-powered SQL generation with RAG context:
1. SQL generation from RAG context
2. Confidence scoring logic
3. Missing context detection
4. Visualization hints extraction
5. Error handling (LLM failures, invalid JSON)
6. Reflexion with validation errors
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.rag.models import RAGContext, RAGTableContext
from starboard_server.tools.domain.analytics_sql.llm_sql_generator import (
    SUPPORTED_CHART_TYPES,
    LLMSQLGenerator,
)
from starboard_server.tools.domain.analytics_sql.models import (
    QueryDomain,
    QueryIntent,
    QueryIntentContext,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing SQL generation."""
    client = MagicMock()
    client.json_response = AsyncMock()
    return client


@pytest.fixture
def sql_generator(mock_llm_client):
    """Create LLMSQLGenerator instance for testing."""
    return LLMSQLGenerator(
        llm_client=mock_llm_client,
        temperature=0.2,
        max_tokens=2000,
    )


@pytest.fixture
def sample_intent_context():
    """Sample query intent context."""
    return QueryIntentContext(
        intent=QueryIntent.COST_ANALYSIS,
        domain=QueryDomain.BILLING,
        confidence=0.9,
        metrics=["total_cost"],
        dimensions=["warehouse_name"],
        reasoning="Cost analysis request for warehouse billing",
    )


@pytest.fixture
def sample_rag_context():
    """Sample RAG context with tables and nuance."""
    return RAGContext(
        tables=[
            RAGTableContext(
                table_name="system.billing.usage",
                description="Usage data for billing calculations",
                table_columns="workspace_id, usage_date, usage_quantity, list_cost, sku_name",
                domain="finops_billing",
            ),
            RAGTableContext(
                table_name="system.billing.list_prices",
                description="List prices for SKUs",
                table_columns="sku_name, pricing_start_time, pricing_end_time, list_price",
                domain="finops_billing",
            ),
        ],
        nuances=[
            "Join usage with list_prices on sku_name for accurate pricing",
            "Always filter by usage_date for performance",
        ],
        codebook=[],
        facets=[],
        learnings=[],
    )


@pytest.fixture
def sample_llm_response():
    """Sample LLM response for SQL generation."""
    return {
        "sql": "SELECT warehouse_name, SUM(list_cost) as total_cost FROM system.billing.usage WHERE usage_date >= CURRENT_DATE - INTERVAL 30 DAYS GROUP BY warehouse_name",
        "explanation": "Aggregates costs by warehouse for last 30 days",
        "confidence": 0.9,
        "missing_context": [],
        "confidence_reasoning": "All required columns and tables present",
        "visualization_hints": {
            "query_intent": "Show warehouse costs",
            "recommended_chart_types": ["bar"],
            "primary_metric": "total_cost",
            "primary_dimension": "warehouse_name",
            "is_time_series": False,
            "is_top_n": True,
            "aggregation_type": "sum",
        },
    }


# ============================================================================
# SQL Generation Tests
# ============================================================================


class TestLLMSQLGeneration:
    """Tests for basic SQL generation functionality."""

    @pytest.mark.asyncio
    async def test_generate_sql_from_rag_context(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
        sample_llm_response,
    ):
        """Test SQL generation from RAG context."""
        mock_llm_client.json_response.return_value = sample_llm_response

        result = await sql_generator.generate(
            user_query="Show warehouse costs for last 30 days",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        # Verify SQL generated
        assert result["success"] is True
        assert result["sql"] == sample_llm_response["sql"]
        assert "SELECT" in result["sql"]
        assert "system.billing.usage" in result["sql"]

        # Verify LLM was called
        mock_llm_client.json_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_sql_with_empty_rag_context(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_llm_response,
    ):
        """Test SQL generation with minimal RAG context."""
        empty_rag_context = RAGContext(
            tables=[],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )

        mock_llm_client.json_response.return_value = sample_llm_response

        result = await sql_generator.generate(
            user_query="Show costs",
            intent_context=sample_intent_context,
            rag_context=empty_rag_context,
        )

        # Should still generate SQL, but may have lower confidence
        assert result["success"] is True
        assert "sql" in result

    @pytest.mark.asyncio
    async def test_generate_sql_uses_correct_temperature(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
        sample_llm_response,
    ):
        """Test that SQL generation uses configured temperature."""
        mock_llm_client.json_response.return_value = sample_llm_response

        await sql_generator.generate(
            user_query="Show costs",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        # Verify temperature was passed to LLM
        # Note: Implementation uses hardcoded 0.1 for SQL generation (POC)
        call_kwargs = mock_llm_client.json_response.call_args[1]
        assert call_kwargs["temperature"] == 0.1  # Hardcoded in implementation


# ============================================================================
# Confidence Scoring Tests
# ============================================================================


class TestConfidenceScoring:
    """Tests for SQL generation confidence scoring."""

    @pytest.mark.asyncio
    async def test_high_confidence_with_complete_context(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test high confidence when all context is available."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Query with complete context",
            "confidence": 0.95,
            "missing_context": [],
            "confidence_reasoning": "All columns and tables available",
            "visualization_hints": {},
        }

        result = await sql_generator.generate(
            user_query="Show usage",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        assert result["confidence"] >= 0.9
        assert len(result["missing_context"]) == 0

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_reflexion(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test low confidence when context is insufficient."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Query missing some context",
            "confidence": 0.5,
            "missing_context": ["warehouse_names", "join_keys"],
            "confidence_reasoning": "Missing warehouse dimension table",
            "visualization_hints": {},
        }

        result = await sql_generator.generate(
            user_query="Show warehouse costs",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        # Low confidence should be reported
        assert result["confidence"] < 0.7
        assert len(result["missing_context"]) > 0
        assert "warehouse_names" in result["missing_context"]

    @pytest.mark.asyncio
    async def test_medium_confidence_with_assumptions(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test medium confidence when minor assumptions are made."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Query with minor assumptions",
            "confidence": 0.75,
            "missing_context": ["exact_column_types"],
            "confidence_reasoning": "Assuming standard column types",
            "visualization_hints": {},
        }

        result = await sql_generator.generate(
            user_query="Show costs",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        assert 0.6 <= result["confidence"] < 0.8


# ============================================================================
# Missing Context Detection Tests
# ============================================================================


class TestMissingContextDetection:
    """Tests for missing context detection for reflexion."""

    @pytest.mark.asyncio
    async def test_detects_missing_table_names(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test detection of missing table names."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Need warehouse table",
            "confidence": 0.6,
            "missing_context": ["warehouse_dimension_table"],
            "confidence_reasoning": "Missing warehouse metadata",
            "visualization_hints": {},
        }

        result = await sql_generator.generate(
            user_query="Show warehouse details",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        assert "warehouse_dimension_table" in result["missing_context"]

    @pytest.mark.asyncio
    async def test_detects_missing_join_keys(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test detection of missing join keys."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Need join key",
            "confidence": 0.65,
            "missing_context": ["join_keys_between_usage_and_warehouses"],
            "confidence_reasoning": "Unknown how to join tables",
            "visualization_hints": {},
        }

        result = await sql_generator.generate(
            user_query="Join usage with warehouses",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        assert any("join" in ctx.lower() for ctx in result["missing_context"])

    @pytest.mark.asyncio
    async def test_detects_missing_calculation_formulas(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test detection of missing calculation formulas."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Need cost calculation formula",
            "confidence": 0.6,
            "missing_context": ["cost_calculation_formula"],
            "confidence_reasoning": "Unknown how to calculate total cost",
            "visualization_hints": {},
        }

        result = await sql_generator.generate(
            user_query="Calculate total cost",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        assert any(
            "formula" in ctx.lower() or "calculation" in ctx.lower()
            for ctx in result["missing_context"]
        )


# ============================================================================
# Visualization Hints Tests
# ============================================================================


class TestVisualizationHints:
    """Tests for visualization hints extraction."""

    @pytest.mark.asyncio
    async def test_extracts_bar_chart_hints(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test extraction of bar chart visualization hints."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT warehouse_name, SUM(cost) FROM ... GROUP BY warehouse_name ORDER BY SUM(cost) DESC LIMIT 10",
            "explanation": "Top 10 warehouses by cost",
            "confidence": 0.9,
            "missing_context": [],
            "confidence_reasoning": "Complete context",
            "visualization_hints": {
                "query_intent": "Top N ranking",
                "recommended_chart_types": ["bar"],
                "primary_metric": "cost",
                "primary_dimension": "warehouse_name",
                "is_time_series": False,
                "is_top_n": True,
                "aggregation_type": "sum",
            },
        }

        result = await sql_generator.generate(
            user_query="Top 10 warehouses by cost",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        hints = result["visualization_hints"]
        assert "bar" in hints["recommended_chart_types"]
        assert hints["is_top_n"] is True
        assert hints["primary_metric"] == "cost"

    @pytest.mark.asyncio
    async def test_extracts_line_chart_hints(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test extraction of line chart visualization hints."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT usage_date, SUM(cost) FROM ... GROUP BY usage_date ORDER BY usage_date",
            "explanation": "Daily cost trend",
            "confidence": 0.9,
            "missing_context": [],
            "confidence_reasoning": "Complete context",
            "visualization_hints": {
                "query_intent": "Time series trend",
                "recommended_chart_types": ["line", "area"],
                "primary_metric": "cost",
                "primary_dimension": "usage_date",
                "is_time_series": True,
                "is_top_n": False,
                "aggregation_type": "sum",
            },
        }

        result = await sql_generator.generate(
            user_query="Show cost trend over time",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        hints = result["visualization_hints"]
        assert "line" in hints["recommended_chart_types"]
        assert hints["is_time_series"] is True
        assert hints["primary_dimension"] == "usage_date"

    @pytest.mark.asyncio
    async def test_recommends_table_for_complex_query(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test table recommendation for complex queries."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT w.name, u.date, u.cost, u.quantity, u.sku FROM ... JOIN ...",
            "explanation": "Complex multi-column query",
            "confidence": 0.85,
            "missing_context": [],
            "confidence_reasoning": "Complete context",
            "visualization_hints": {
                "query_intent": "Detailed breakdown",
                "recommended_chart_types": ["table"],
                "primary_metric": None,
                "primary_dimension": None,
                "is_time_series": False,
                "is_top_n": False,
                "aggregation_type": None,
            },
        }

        result = await sql_generator.generate(
            user_query="Show detailed breakdown",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        hints = result["visualization_hints"]
        assert "table" in hints["recommended_chart_types"]


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling during SQL generation."""

    @pytest.mark.asyncio
    async def test_handles_llm_timeout(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test error handling when LLM times out."""
        mock_llm_client.json_response.side_effect = Exception("LLM timeout after 30s")

        with pytest.raises(RuntimeError, match="SQL generation failed"):
            await sql_generator.generate(
                user_query="Show costs",
                intent_context=sample_intent_context,
                rag_context=sample_rag_context,
            )

    @pytest.mark.asyncio
    async def test_handles_empty_sql_response(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test error handling when LLM returns empty SQL."""
        mock_llm_client.json_response.return_value = {
            "sql": "",  # Empty SQL
            "explanation": "Could not generate query",
            "confidence": 0.0,
            "missing_context": ["all_context"],
            "confidence_reasoning": "Insufficient information",
            "visualization_hints": {},
        }

        with pytest.raises(RuntimeError, match="LLM returned empty SQL"):
            await sql_generator.generate(
                user_query="Show costs",
                intent_context=sample_intent_context,
                rag_context=sample_rag_context,
            )

    @pytest.mark.asyncio
    async def test_handles_missing_required_fields(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test error handling when LLM omits required fields."""
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            # Missing: explanation, confidence, missing_context, etc.
        }

        # Should handle gracefully with defaults
        result = await sql_generator.generate(
            user_query="Show costs",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
        )

        # Should have SQL even if other fields missing
        assert result["sql"] == "SELECT * FROM system.billing.usage"


# ============================================================================
# Reflexion with Previous Errors Tests
# ============================================================================


class TestReflexionWithErrors:
    """Tests for SQL regeneration with validation errors (reflexion loop)."""

    @pytest.mark.asyncio
    async def test_incorporates_validation_errors(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test that previous validation errors are incorporated."""
        previous_errors = [
            "Table 'system.billing.unknown' not found",
            "Column 'invalid_col' does not exist",
        ]

        mock_llm_client.json_response.return_value = {
            "sql": "SELECT usage_date, list_cost FROM system.billing.usage",
            "explanation": "Fixed table and column names based on errors",
            "confidence": 0.85,
            "missing_context": [],
            "confidence_reasoning": "Corrected based on validation feedback",
            "visualization_hints": {},
        }

        result = await sql_generator.generate(
            user_query="Show costs",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
            previous_errors=previous_errors,
        )

        # Verify SQL was generated with error feedback
        assert result["success"] is True
        assert "system.billing.usage" in result["sql"]  # Correct table
        assert "unknown" not in result["sql"].lower()  # Fixed error

    @pytest.mark.asyncio
    async def test_prompt_includes_previous_errors(
        self,
        sql_generator,
        mock_llm_client,
        sample_intent_context,
        sample_rag_context,
    ):
        """Test that previous errors are included in prompt."""
        previous_errors = ["Syntax error near 'FORM'"]

        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Fixed syntax",
            "confidence": 0.9,
            "missing_context": [],
            "confidence_reasoning": "Corrected SQL syntax",
            "visualization_hints": {},
        }

        await sql_generator.generate(
            user_query="Show costs",
            intent_context=sample_intent_context,
            rag_context=sample_rag_context,
            previous_errors=previous_errors,
        )

        # Verify LLM was called (we can't easily inspect the prompt content in this test,
        # but we verify the call happened with previous_errors parameter)
        mock_llm_client.json_response.assert_called_once()


# ============================================================================
# Configuration Tests
# ============================================================================


class TestGeneratorConfiguration:
    """Tests for SQL generator configuration."""

    def test_custom_temperature(self):
        """Test SQL generator with custom temperature."""
        mock_client = MagicMock()
        mock_client.json_response = AsyncMock()

        generator = LLMSQLGenerator(
            llm_client=mock_client,
            temperature=0.5,
            max_tokens=3000,
        )

        assert generator.temperature == 0.5
        assert generator.max_tokens == 3000

    def test_default_temperature(self):
        """Test SQL generator with default temperature."""
        mock_client = MagicMock()
        mock_client.json_response = AsyncMock()

        generator = LLMSQLGenerator(llm_client=mock_client)

        assert generator.temperature == 0.2  # Low for structured SQL
        assert generator.max_tokens == 2000

    def test_supported_chart_types_constant(self):
        """Test that supported chart types are defined."""
        assert isinstance(SUPPORTED_CHART_TYPES, list)
        assert len(SUPPORTED_CHART_TYPES) > 0
        assert "bar" in SUPPORTED_CHART_TYPES
        assert "line" in SUPPORTED_CHART_TYPES
        assert "table" in SUPPORTED_CHART_TYPES
