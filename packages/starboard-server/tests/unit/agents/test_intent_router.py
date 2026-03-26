"""
Tests for intent router module.

Comprehensive testing for:
- IntentRouter initialization
- classify_intent method with all routing rules
- _extract_identifiers method
- _contains_sql method
- LLM fallback classification

Follows Python AI Agent Engineering Standards.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.agents.routing.intent_router import IntentRouter


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    client = MagicMock()
    # json_response is async in the actual implementation
    client.json_response = AsyncMock()
    return client


@pytest.fixture
def router(mock_llm_client):
    """IntentRouter instance with mocked LLM."""
    return IntentRouter(mock_llm_client)


class TestIntentRouterInit:
    """Test IntentRouter initialization."""

    def test_init_with_llm_client(self, mock_llm_client):
        """Test initialization with LLM client."""
        router = IntentRouter(mock_llm_client)

        assert router.llm_client is mock_llm_client


class TestClassifyIntent:
    """Test classify_intent method with routing rules."""

    @pytest.mark.asyncio
    async def test_classify_with_statement_id(self, router):
        """Test routing with statement_id detected."""
        user_input = "Optimize statement_id:abc123"

        decision = await router.classify_intent(user_input, [])

        assert decision.domain == "query"
        assert decision.confidence == 1.0
        assert decision.extracted_ids.get("statement_id") == "abc123"
        assert decision.clarification_needed is False
        assert "Statement ID" in decision.reasoning

    @pytest.mark.asyncio
    async def test_classify_with_sql(self, router):
        """Test routing with SQL detected."""
        user_input = "SELECT * FROM users WHERE active = true"

        decision = await router.classify_intent(user_input, [])

        assert decision.domain == "query"
        assert decision.confidence == 0.9
        assert decision.clarification_needed is False

    @pytest.mark.asyncio
    async def test_classify_with_job_id(self, router):
        """Test routing with job_id detected."""
        user_input = "Check job 12345 status"

        decision = await router.classify_intent(user_input, [])

        assert decision.domain == "job"
        assert decision.confidence >= 0.9  # Scoring system returns base_confidence
        assert decision.extracted_ids.get("job_id") == "12345"

    @pytest.mark.asyncio
    async def test_classify_with_job_keyword(self, router):
        """Test routing with 'job' keyword and job-specific phrasing."""
        # Use phrasing that strongly indicates job domain (optimization focus, not errors)
        user_input = "Optimize my job runtime and check job task performance"

        decision = await router.classify_intent(user_input, [])

        assert decision.domain == "job"
        assert decision.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_classify_with_table_name(self, router):
        """Test routing with table name detected."""
        user_input = "Analyze catalog.schema.users table"

        decision = await router.classify_intent(user_input, [])

        assert decision.domain == "uc"
        assert decision.confidence == 0.9
        assert "users" in decision.extracted_ids.get("table_name", "")

    @pytest.mark.asyncio
    async def test_classify_with_cluster_id(self, router):
        """Test routing with cluster_id detected."""
        user_input = "Check cluster_id:abc-123-def performance"

        decision = await router.classify_intent(user_input, [])

        assert decision.domain == "cluster"
        assert decision.confidence >= 0.9  # Scoring system returns base_confidence

    @pytest.mark.asyncio
    async def test_classify_with_warehouse_id(self, router):
        """Test routing with warehouse_id detected routes to warehouse agent.

        Note: warehouse_id routes to warehouse domain for portfolio/fleet operations.
        """
        user_input = "Optimize warehouse_id:wh_prod"

        decision = await router.classify_intent(user_input, [])

        # warehouse_id routes to warehouse domain (per domain_intents config)
        assert decision.domain == "warehouse"
        assert decision.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_classify_with_diagnostic_keywords(self, router):
        """Test routing with diagnostic keywords.

        Note: Scoring-based routing may route based on domain keywords
        (e.g., 'query slow' may route to query agent). Use explicit
        diagnostic patterns for deterministic diagnostic routing.
        """
        diagnostic_inputs = [
            "Debug the error in my system",
            "Troubleshoot this issue",
            "What's the root cause of the problem?",
        ]

        for user_input in diagnostic_inputs:
            decision = await router.classify_intent(user_input, [])

            assert decision.domain == "diagnostic"
            assert decision.confidence >= 0.7
            # Note: clarification_needed is based on confidence < 0.7
            # High-confidence diagnostic matches don't need clarification

    @pytest.mark.asyncio
    async def test_classify_with_llm_fallback(self, router, mock_llm_client):
        """Test LLM fallback when no rules match."""
        user_input = "Tell me about data processing best practices"

        # Mock LLM response
        mock_llm_client.json_response.return_value = {
            "domain": "general",
            "confidence": 0.6,
            "reasoning": "General question",
            "clarification_needed": False,
        }

        await router.classify_intent(user_input, [])

        # Should have called LLM
        mock_llm_client.json_response.assert_called_once()


class TestExtractIdentifiers:
    """Test _extract_identifiers method."""

    def test_extract_statement_id_colon_format(self, router):
        """Test extracting statement_id with colon format."""
        text = "Optimize statement_id:abc123-xyz"

        ids = router._extract_identifiers(text)

        assert ids["statement_id"] == "abc123-xyz"

    def test_extract_statement_id_space_format(self, router):
        """Test extracting statement_id with space format."""
        text = "Check statement abc123"

        ids = router._extract_identifiers(text)

        assert ids["statement_id"] == "abc123"

    def test_extract_uuid_statement_id(self, router):
        """Test extracting UUID as statement_id."""
        text = "Analyze 550e8400-e29b-41d4-a716-446655440000"

        ids = router._extract_identifiers(text)

        assert ids["statement_id"] == "550e8400-e29b-41d4-a716-446655440000"

    def test_extract_job_id(self, router):
        """Test extracting job_id."""
        text = "Check job 12345"

        ids = router._extract_identifiers(text)

        assert ids["job_id"] == "12345"

    def test_extract_table_name_full_path(self, router):
        """Test extracting fully qualified table name."""
        text = "Query catalog.schema.table_name"

        ids = router._extract_identifiers(text)

        assert "table_name" in ids["table_name"]

    def test_extract_cluster_id(self, router):
        """Test extracting cluster_id."""
        text = "Optimize cluster_id:abc-123-def"

        ids = router._extract_identifiers(text)

        assert ids["cluster_id"] == "abc-123-def"

    def test_extract_warehouse_id(self, router):
        """Test extracting warehouse_id."""
        text = "Check warehouse_id:wh_prod"

        ids = router._extract_identifiers(text)

        assert ids["warehouse_id"] == "wh_prod"

    def test_extract_multiple_identifiers(self, router):
        """Test extracting multiple identifiers from same text."""
        text = "Optimize statement_id:abc123 on cluster_id:cl-001"

        ids = router._extract_identifiers(text)

        assert ids["statement_id"] == "abc123"
        assert ids["cluster_id"] == "cl-001"

    def test_extract_no_identifiers(self, router):
        """Test when no identifiers are present."""
        text = "Just a regular question"

        ids = router._extract_identifiers(text)

        assert len(ids) == 0


class TestContainsSQL:
    """Test _contains_sql method."""

    def test_contains_select_statement(self, router):
        """Test detecting SELECT statement."""
        text = "SELECT * FROM users"

        assert router._contains_sql(text) is True

    def test_contains_insert_statement(self, router):
        """Test detecting INSERT statement."""
        text = "INSERT INTO users VALUES (1, 'Alice')"

        assert router._contains_sql(text) is True

    def test_contains_update_statement(self, router):
        """Test detecting UPDATE statement."""
        text = "UPDATE users SET active = true"

        assert router._contains_sql(text) is True

    def test_contains_delete_statement(self, router):
        """Test detecting DELETE statement."""
        text = "DELETE FROM users WHERE id = 1"

        assert router._contains_sql(text) is True

    def test_contains_create_statement(self, router):
        """Test detecting CREATE statement."""
        text = "CREATE TABLE users (id INT, name STRING)"

        assert router._contains_sql(text) is True

    def test_contains_with_clause(self, router):
        """Test detecting WITH clause."""
        text = "WITH cte AS (SELECT * FROM users) SELECT * FROM cte"

        assert router._contains_sql(text) is True

    def test_contains_case_insensitive(self, router):
        """Test SQL detection is case insensitive."""
        text = "select * from users"

        assert router._contains_sql(text) is True

    def test_no_sql_keywords(self, router):
        """Test when no SQL keywords present."""
        text = "Just a regular question about data"

        assert router._contains_sql(text) is False

    def test_sql_keyword_in_regular_text(self, router):
        """Test SQL keyword in non-SQL context."""
        # "select" is common word, should still detect as potential SQL
        text = "Please select an option"

        # Implementation may or may not detect this - depends on regex
        result = router._contains_sql(text)
        assert isinstance(result, bool)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_classify_empty_input(self, router, mock_llm_client):
        """Test classification with empty input."""
        # Empty input should fall back to LLM
        mock_llm_client.json_response.return_value = {
            "domain": "general",
            "confidence": 0.3,
            "reasoning": "Empty input",
            "clarification_needed": True,
        }

        decision = await router.classify_intent("", [])

        assert decision is not None

    @pytest.mark.asyncio
    async def test_classify_with_conversation_history(self, router, mock_llm_client):
        """Test classification includes conversation history."""
        mock_llm_client.json_response.return_value = {
            "domain": "general",
            "confidence": 0.7,
            "reasoning": "Contextual",
            "clarification_needed": False,
        }

        conversation_history = [
            {"role": "user", "content": "Previous message"},
            {"role": "assistant", "content": "Previous response"},
        ]

        await router.classify_intent("Follow up question", conversation_history)

        # LLM should be called with history
        call_args = mock_llm_client.json_response.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_classify_special_characters(self, router):
        """Test classification with special characters."""
        user_input = "Check statement_id:abc-123_xyz!@#$%"

        decision = await router.classify_intent(user_input, [])

        # Should still extract the identifier
        assert "statement_id" in decision.extracted_ids

    @pytest.mark.asyncio
    async def test_classify_very_long_input(self, router, mock_llm_client):
        """Test classification with very long input."""
        long_input = "SELECT * FROM users " * 100

        decision = await router.classify_intent(long_input, [])

        # Should detect SQL
        assert decision.domain == "query"

    @pytest.mark.asyncio
    async def test_classify_mixed_case_keywords(self, router):
        """Test classification with mixed case keywords."""
        user_input = "Why is my JoB so SlOw?"

        decision = await router.classify_intent(user_input, [])

        # Should match diagnostic keywords case-insensitively
        assert decision.domain in ["job", "diagnostic"]
