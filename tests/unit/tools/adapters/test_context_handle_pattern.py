"""Unit tests for context handle pattern in Analytics SQL tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.rag.models import RAGContext, RAGTableContext
from starboard_server.tools.adapters.analytics_sql_tools import AnalyticsSQLTools
from starboard_server.tools.adapters.rag_tools import AnalyticsContextTools


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    client = MagicMock()
    client.max_tokens = 4096
    return client


@pytest.fixture
def mock_sql_executor():
    """Mock SQL executor for testing."""
    return MagicMock()


@pytest.fixture
def mock_sql_validator():
    """Mock SQL validator for testing."""
    return MagicMock()


@pytest.fixture
def analytics_sql_tools(mock_llm_client, mock_sql_executor, mock_sql_validator):
    """Create AnalyticsSQLTools instance for testing."""
    return AnalyticsSQLTools(
        llm_client=mock_llm_client,
        sql_executor=mock_sql_executor,
        sql_validator=mock_sql_validator,
        result_cache=None,
    )


@pytest.fixture
def mock_vector_store():
    """Mock vector store for testing."""
    return MagicMock()


@pytest.fixture
def mock_embedding_provider():
    """Mock embedding provider for testing."""
    return MagicMock()


@pytest.fixture
def analytics_context_tools(
    mock_vector_store, mock_embedding_provider, analytics_sql_tools
):
    """Create AnalyticsContextTools instance for testing."""
    return AnalyticsContextTools(
        vector_store=mock_vector_store,
        embedding_provider=mock_embedding_provider,
        analytics_sql_tools=analytics_sql_tools,
    )


class TestContextHandlePattern:
    """Test context handle pattern for RAG context storage and retrieval."""

    def test_store_rag_context_generates_handle(self, analytics_sql_tools):
        """Test that storing RAG context generates a valid handle."""
        # Create sample RAG context
        rag_context = RAGContext(
            tables=[
                RAGTableContext(
                    table_name="system.billing.usage",
                    description="Usage data",
                    table_columns="id, cost",
                    domain="finops_billing",
                )
            ],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )

        # Store context
        handle = analytics_sql_tools.store_rag_context(rag_context)

        # Verify handle format
        assert isinstance(handle, str)
        assert handle.startswith("ctx_")
        assert len(handle) == 16  # "ctx_" + 12 hex chars

    def test_retrieve_rag_context_success(self, analytics_sql_tools):
        """Test that retrieving RAG context by valid handle succeeds."""
        # Create and store context
        rag_context = RAGContext(
            tables=[
                RAGTableContext(
                    table_name="system.billing.usage",
                    description="Usage data",
                    table_columns="id, cost",
                    domain="finops_billing",
                )
            ],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )
        handle = analytics_sql_tools.store_rag_context(rag_context)

        # Retrieve context
        retrieved = analytics_sql_tools._retrieve_rag_context(handle)

        # Verify retrieved context matches
        assert retrieved is not None
        assert len(retrieved.tables) == 1
        assert retrieved.tables[0].table_name == "system.billing.usage"

    def test_retrieve_invalid_handle(self, analytics_sql_tools):
        """Test that retrieving with invalid handle returns None."""
        result = analytics_sql_tools._retrieve_rag_context("ctx_invalid123")
        assert result is None

    def test_multiple_contexts_isolated(self, analytics_sql_tools):
        """Test that multiple contexts are stored independently."""
        # Store first context
        context1 = RAGContext(
            tables=[
                RAGTableContext(
                    table_name="table1",
                    description="First table",
                    table_columns="col1",
                    domain="domain1",
                )
            ],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )
        handle1 = analytics_sql_tools.store_rag_context(context1)

        # Store second context
        context2 = RAGContext(
            tables=[
                RAGTableContext(
                    table_name="table2",
                    description="Second table",
                    table_columns="col2",
                    domain="domain2",
                )
            ],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )
        handle2 = analytics_sql_tools.store_rag_context(context2)

        # Verify handles are different
        assert handle1 != handle2

        # Verify contexts are isolated
        retrieved1 = analytics_sql_tools._retrieve_rag_context(handle1)
        retrieved2 = analytics_sql_tools._retrieve_rag_context(handle2)

        assert retrieved1.tables[0].table_name == "table1"
        assert retrieved2.tables[0].table_name == "table2"

    @pytest.mark.asyncio
    async def test_build_sql_query_with_valid_handle(
        self, analytics_sql_tools, mock_llm_client
    ):
        """Test build_sql_query with valid context handle."""
        # Store context
        rag_context = RAGContext(
            tables=[
                RAGTableContext(
                    table_name="system.billing.usage",
                    description="Usage data",
                    table_columns="workspace_id, usage_date, usage_quantity",
                    domain="finops_billing",
                )
            ],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )
        handle = analytics_sql_tools.store_rag_context(rag_context)

        # Mock LLM response
        mock_llm_client.generate_chat_completion = AsyncMock(
            return_value=MagicMock(
                content='{"sql": "SELECT * FROM system.billing.usage", "confidence": 0.9, "missing_context": [], "reasoning": "Test"}',
                model="gpt-4",
                usage=MagicMock(
                    prompt_tokens=100, completion_tokens=50, total_tokens=150
                ),
            )
        )

        # Call build_sql_query with handle
        result = await analytics_sql_tools.build_sql_query(
            user_query="Show usage data",
            context_handle=handle,
        )

        # Verify result structure
        assert "sql" in result
        assert "confidence" in result
        assert result["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_build_sql_query_with_invalid_handle(self, analytics_sql_tools):
        """Test build_sql_query with invalid context handle."""
        result = await analytics_sql_tools.build_sql_query(
            user_query="Show usage data",
            context_handle="ctx_invalid123",
        )

        # Verify error response
        assert result["success"] is False
        assert "Invalid or expired context_handle" in result["error"]
        assert result["confidence"] == 0.0
        assert "valid_rag_context" in result["missing_context"]

    @pytest.mark.asyncio
    async def test_analytics_context_tools_returns_handle(
        self, analytics_context_tools, mock_vector_store
    ):
        """Test that build_analytics_context returns handle + summary."""
        # Mock vector store search
        mock_vector_store.search_multi_collection = AsyncMock(
            return_value=RAGContext(
                tables=[
                    RAGTableContext(
                        table_name="system.billing.usage",
                        description="Usage data",
                        table_columns="id, cost",
                        domain="finops_billing",
                    )
                ],
                nuances=[],
                codebook=[],
                facets=[],
                learnings=[],
            )
        )

        # Call build_analytics_context
        result = await analytics_context_tools.build_analytics_context(
            user_query="Show usage data",
            rag_resource_domains=["finops_billing"],
        )

        # Verify result structure
        assert "context_handle" in result
        assert "summary" in result
        assert result["context_handle"].startswith("ctx_")
        assert result["summary"]["tables_found"] == 1
        assert result["summary"]["domains_searched"] == ["finops_billing"]

    def test_cleanup_expired_contexts(self, analytics_sql_tools):
        """Test that expired contexts are cleaned up."""
        import time

        # Store context
        rag_context = RAGContext(
            tables=[],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )
        handle = analytics_sql_tools.store_rag_context(rag_context)

        # Manually expire the context by setting old timestamp
        analytics_sql_tools._context_timestamps[handle] = (
            time.time() - analytics_sql_tools._context_ttl - 1
        )

        # Trigger cleanup
        analytics_sql_tools._cleanup_expired_contexts()

        # Verify context was removed
        assert handle not in analytics_sql_tools._rag_context_cache
        assert handle not in analytics_sql_tools._context_timestamps
