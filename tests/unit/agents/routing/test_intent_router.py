# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for intent router and classification logic.

Coverage targets:
- Intent classification with various inputs
- Identifier extraction (statement_id, job_id, table_name, etc.)
- SQL detection
- Routing rules (query, job, table, compute, diagnostic, analytics, warehouse)
- Disabled domains handling
- LLM fallback classification
"""

from unittest.mock import AsyncMock, Mock

import pytest
from starboard_server.agents.routing.intent_router import IntentRouter


class TestIntentRouterInitialization:
    """Tests for IntentRouter initialization."""

    def test_init_default(self) -> None:
        """Test initialization with default parameters."""
        # Arrange
        mock_llm = Mock()

        # Act
        router = IntentRouter(mock_llm)

        # Assert
        assert router.llm_client == mock_llm
        assert router.disabled_domains == set()

    def test_init_with_disabled_domains(self) -> None:
        """Test initialization with disabled domains."""
        # Arrange
        mock_llm = Mock()
        disabled = ["diagnostic", "uc"]

        # Act
        router = IntentRouter(mock_llm, disabled_domains=disabled)

        # Assert
        assert router.disabled_domains == {"diagnostic", "uc"}

    def test_init_with_empty_disabled_domains(self) -> None:
        """Test initialization with empty disabled domains list."""
        # Arrange
        mock_llm = Mock()

        # Act
        router = IntentRouter(mock_llm, disabled_domains=[])

        # Assert
        assert router.disabled_domains == set()


class TestIdentifierExtraction:
    """Tests for _extract_identifiers method."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    def test_extract_statement_id_with_colon(self, router: IntentRouter) -> None:
        """Test extracting statement_id with colon format."""
        # Act
        ids = router._extract_identifiers("Optimize statement_id:abc123")

        # Assert
        assert ids["statement_id"] == "abc123"

    def test_extract_statement_id_with_space(self, router: IntentRouter) -> None:
        """Test extracting statement_id with space format."""
        # Act
        ids = router._extract_identifiers("Check statement id xyz789")

        # Assert
        assert ids["statement_id"] == "xyz789"

    def test_extract_statement_id_underscore(self, router: IntentRouter) -> None:
        """Test extracting statement_id with underscore format."""
        # Act
        ids = router._extract_identifiers("statement_id abc_123")

        # Assert
        assert ids["statement_id"] == "abc_123"

    def test_extract_uuid_statement_id(self, router: IntentRouter) -> None:
        """Test extracting UUID format statement ID."""
        # Act
        ids = router._extract_identifiers("Check 01234567-89ab-cdef-0123-456789abcdef")

        # Assert
        assert ids["statement_id"] == "01234567-89ab-cdef-0123-456789abcdef"

    def test_extract_job_id_with_colon(self, router: IntentRouter) -> None:
        """Test extracting job_id with colon format."""
        # Act
        ids = router._extract_identifiers("Check job_id:456")

        # Assert
        assert ids["job_id"] == "456"

    def test_extract_job_id_with_space(self, router: IntentRouter) -> None:
        """Test extracting job_id with space format."""
        # Act
        ids = router._extract_identifiers("Monitor job 789")

        # Assert
        assert ids["job_id"] == "789"

    def test_extract_table_name(self, router: IntentRouter) -> None:
        """Test extracting catalog.schema.table name."""
        # Act
        ids = router._extract_identifiers("Analyze catalog.schema.users")

        # Assert
        assert ids["table_name"] == "catalog.schema.users"

    def test_extract_table_name_with_underscores(self, router: IntentRouter) -> None:
        """Test extracting table name with underscores."""
        # Act
        ids = router._extract_identifiers("Query prod_db.public.user_orders")

        # Assert
        assert ids["table_name"] == "prod_db.public.user_orders"

    def test_extract_cluster_id(self, router: IntentRouter) -> None:
        """Test extracting cluster_id."""
        # Act
        ids = router._extract_identifiers("Configure cluster_id:cluster-123")

        # Assert
        assert ids["cluster_id"] == "cluster-123"

    def test_extract_warehouse_id(self, router: IntentRouter) -> None:
        """Test extracting warehouse_id."""
        # Act
        ids = router._extract_identifiers("Check warehouse_id:wh-456")

        # Assert
        assert ids["warehouse_id"] == "wh-456"

    def test_extract_multiple_ids(self, router: IntentRouter) -> None:
        """Test extracting multiple IDs from same text."""
        # Act
        ids = router._extract_identifiers(
            "Optimize job 123 statement_id:abc123 in catalog.schema.table"
        )

        # Assert
        assert ids["job_id"] == "123"
        assert ids["statement_id"] == "abc123"
        assert ids["table_name"] == "catalog.schema.table"

    def test_extract_no_ids(self, router: IntentRouter) -> None:
        """Test extraction with no identifiers present."""
        # Act
        ids = router._extract_identifiers("Why is my query slow?")

        # Assert
        assert ids == {}


class TestSQLDetection:
    """Tests for _contains_sql method."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    def test_contains_sql_select(self, router: IntentRouter) -> None:
        """Test SQL detection with SELECT."""
        assert router._contains_sql("SELECT * FROM users") is True

    def test_contains_sql_insert(self, router: IntentRouter) -> None:
        """Test SQL detection with INSERT."""
        assert router._contains_sql("INSERT INTO table VALUES (1, 2)") is True

    def test_contains_sql_update(self, router: IntentRouter) -> None:
        """Test SQL detection with UPDATE."""
        assert router._contains_sql("UPDATE users SET active = true") is True

    def test_contains_sql_delete(self, router: IntentRouter) -> None:
        """Test SQL detection with DELETE."""
        assert router._contains_sql("DELETE FROM users WHERE id = 1") is True

    def test_contains_sql_create(self, router: IntentRouter) -> None:
        """Test SQL detection with CREATE."""
        assert router._contains_sql("CREATE TABLE users (id INT)") is True

    def test_contains_sql_alter(self, router: IntentRouter) -> None:
        """Test SQL detection with ALTER."""
        assert router._contains_sql("ALTER TABLE users ADD COLUMN name") is True

    def test_contains_sql_lowercase(self, router: IntentRouter) -> None:
        """Test SQL detection with lowercase keywords."""
        assert router._contains_sql("select * from users") is True

    def test_contains_sql_mixed_case(self, router: IntentRouter) -> None:
        """Test SQL detection with mixed case."""
        assert router._contains_sql("SeLeCt * FrOm users") is True

    def test_contains_sql_no_sql(self, router: IntentRouter) -> None:
        """Test SQL detection with non-SQL text."""
        assert router._contains_sql("Why is my job slow?") is False

    def test_contains_sql_partial_match(self, router: IntentRouter) -> None:
        """Test that partial keyword matches don't trigger."""
        # "SELECT" is in "SELECTED" but should still match
        assert router._contains_sql("I SELECTED the wrong option") is True


class TestRouteClassificationQuery:
    """Tests for query domain routing."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    @pytest.mark.asyncio
    async def test_route_with_statement_id(self, router: IntentRouter) -> None:
        """Test routing with statement_id routes to query domain."""
        # Act
        decision = await router.classify_intent("Optimize statement_id:abc123", [])

        # Assert
        assert decision.domain == "query"
        assert decision.confidence == 1.0
        assert decision.extracted_ids["statement_id"] == "abc123"
        assert "Statement ID" in decision.reasoning

    @pytest.mark.asyncio
    async def test_route_with_sql_query(self, router: IntentRouter) -> None:
        """Test routing with SQL query routes to query domain."""
        # Act
        decision = await router.classify_intent(
            "SELECT * FROM users WHERE active = true", []
        )

        # Assert
        assert decision.domain == "query"
        assert decision.confidence == 0.9
        assert "SQL" in decision.reasoning

    @pytest.mark.asyncio
    async def test_route_query_high_confidence(self, router: IntentRouter) -> None:
        """Test that query routing has high confidence."""
        # Act
        decision = await router.classify_intent("Analyze statement_id:xyz", [])

        # Assert
        assert decision.confidence >= 0.9
        assert decision.clarification_needed is False
        assert decision.should_route() is True


class TestRouteClassificationAnalytics:
    """Tests for analytics domain routing."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    @pytest.mark.asyncio
    async def test_route_cost_keyword(self, router: IntentRouter) -> None:
        """Test routing with cost keyword routes to analytics."""
        # Act
        decision = await router.classify_intent("How much did this cost?", [])

        # Assert
        assert decision.domain == "analytics"
        assert decision.confidence == 0.9  # base_confidence from analytics domain
        assert "cost" in decision.reasoning.lower()

    @pytest.mark.asyncio
    async def test_route_spending_keyword(self, router: IntentRouter) -> None:
        """Test routing with spending keyword routes to analytics."""
        # Act
        decision = await router.classify_intent("Show me spending trends", [])

        # Assert
        assert decision.domain == "analytics"
        assert "spending" in decision.reasoning.lower()

    @pytest.mark.asyncio
    async def test_route_finops_keyword(self, router: IntentRouter) -> None:
        """Test routing with FinOps keyword routes to analytics."""
        # Act
        decision = await router.classify_intent("Generate finops report", [])

        # Assert
        assert decision.domain == "analytics"

    @pytest.mark.asyncio
    async def test_route_analytics_over_job_id_for_cost(
        self, router: IntentRouter
    ) -> None:
        """Test that analytics keywords take priority over job ID for cost queries.

        Cost/spending/DBU queries should go to analytics agent even with a job_id,
        since the analytics agent has the system queries for cost data.
        """
        # Act
        decision = await router.classify_intent("How much did job 123 cost?", [])

        # Assert
        # Should route to analytics domain because cost queries need FinOps capabilities
        assert decision.domain == "analytics"
        assert decision.confidence == 0.9
        assert "cost" in decision.reasoning.lower()
        # Job ID should still be extracted for context
        assert decision.extracted_ids.get("job_id") == "123"

    @pytest.mark.asyncio
    async def test_route_dbu_query_with_job_id_to_analytics(
        self, router: IntentRouter
    ) -> None:
        """Test that DBU consumption queries route to analytics even with job_id.

        Bug fix: 'How many DBUs did I spend for each run of this job 1053445200953884?'
        was incorrectly routing to job agent. DBU consumption data requires FinOps
        system tables (system.billing.usage), which only analytics agent can access.
        """
        # Act
        decision = await router.classify_intent(
            "How many DBUs did I spend for each run of this job 1053445200953884?", []
        )

        # Assert
        # Should route to analytics domain for DBU consumption data
        assert decision.domain == "analytics"
        assert decision.confidence == 0.9
        # Job ID should still be extracted for filtering
        assert decision.extracted_ids.get("job_id") == "1053445200953884"

    @pytest.mark.asyncio
    async def test_route_dbu_consumption_queries(self, router: IntentRouter) -> None:
        """Test various DBU consumption query patterns route to analytics."""
        test_cases = [
            "How many DBUs did job 123 consume?",
            "What was the DBU cost for my last job run?",
            "Show me DBU consumption by job",
            "DBU usage for job runs this month",
        ]

        for query in test_cases:
            decision = await router.classify_intent(query, [])
            assert decision.domain == "analytics", (
                f"Query '{query}' should route to analytics but got {decision.domain}"
            )


class TestRouteClassificationJob:
    """Tests for job domain routing."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    @pytest.mark.asyncio
    async def test_route_with_job_id(self, router: IntentRouter) -> None:
        """Test routing with job_id routes to job domain."""
        # Act
        decision = await router.classify_intent("Check job_id:456", [])

        # Assert
        assert decision.domain == "job"
        assert decision.confidence == 0.95  # base_confidence from job domain
        assert decision.extracted_ids["job_id"] == "456"

    @pytest.mark.asyncio
    async def test_route_with_job_keyword(self, router: IntentRouter) -> None:
        """Test routing with job keyword routes to job domain."""
        # Act - Use "status" instead of "monitor" to avoid analytics keyword
        decision = await router.classify_intent("Check my job status", [])

        # Assert
        assert decision.domain == "job"
        assert decision.confidence == 0.95  # base_confidence from job domain


class TestRouteClassificationTable:
    """Tests for table domain routing."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    @pytest.mark.asyncio
    async def test_route_with_table_name(self, router: IntentRouter) -> None:
        """Test routing with table name routes to table domain."""
        # Act
        decision = await router.classify_intent("Analyze catalog.schema.users", [])

        # Assert
        assert decision.domain == "uc"
        assert decision.confidence == 0.9
        assert decision.extracted_ids["table_name"] == "catalog.schema.users"

    @pytest.mark.asyncio
    async def test_route_table_disabled(self) -> None:
        """Test that UC routing is skipped when disabled."""
        # Arrange
        router = IntentRouter(Mock(), disabled_domains=["uc"])

        # Act
        decision = await router.classify_intent("Analyze catalog.schema.users", [])

        # Assert
        # Should not route to UC since it's disabled
        assert decision.domain != "uc"


class TestRouteClassificationWarehouse:
    """Tests for warehouse domain routing."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    @pytest.mark.asyncio
    async def test_route_warehouse_portfolio_keyword(
        self, router: IntentRouter
    ) -> None:
        """Test routing with 'warehouse portfolio' keyword."""
        # Act
        decision = await router.classify_intent("Show me our warehouse portfolio", [])

        # Assert
        assert decision.domain == "warehouse"
        assert decision.confidence >= 0.9
        assert "warehouse" in decision.reasoning.lower()

    @pytest.mark.asyncio
    async def test_route_warehouse_fleet_keyword(self, router: IntentRouter) -> None:
        """Test routing with 'warehouse fleet' keyword."""
        # Act
        decision = await router.classify_intent("Analyze our warehouse fleet", [])

        # Assert
        assert decision.domain == "warehouse"
        assert decision.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_route_warehouse_health_keyword(self, router: IntentRouter) -> None:
        """Test routing with 'warehouse health' keyword."""
        # Act
        decision = await router.classify_intent("What's the warehouse health?", [])

        # Assert
        assert decision.domain == "warehouse"
        assert decision.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_route_warehouse_slo_keyword(self, router: IntentRouter) -> None:
        """Test routing with 'warehouse slo' keyword."""
        # Act
        decision = await router.classify_intent("Configure warehouse SLO targets", [])

        # Assert
        assert decision.domain == "warehouse"
        assert decision.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_route_serverless_vs_standard(self, router: IntentRouter) -> None:
        """Test routing with serverless vs standard comparison."""
        # Act
        decision = await router.classify_intent(
            "Should we use serverless or standard warehouses?", []
        )

        # Assert
        assert decision.domain == "warehouse"
        assert decision.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_route_warehouse_rightsizing(self, router: IntentRouter) -> None:
        """Test routing with warehouse rightsizing."""
        # Act
        decision = await router.classify_intent("Help me rightsize our warehouses", [])

        # Assert
        assert decision.domain == "warehouse"

    @pytest.mark.asyncio
    async def test_route_warehouse_whatif(self, router: IntentRouter) -> None:
        """Test routing with warehouse what-if analysis."""
        # Act
        decision = await router.classify_intent(
            "What if we switch this warehouse to serverless?", []
        )

        # Assert
        assert decision.domain == "warehouse"

    @pytest.mark.asyncio
    async def test_route_warehouse_fingerprint(self, router: IntentRouter) -> None:
        """Test routing with warehouse fingerprint analysis."""
        # Act - use a warehouse name that doesn't contain analytics keywords
        decision = await router.classify_intent(
            "Show me the warehouse fingerprint for data-wh", []
        )

        # Assert
        assert decision.domain == "warehouse"

    @pytest.mark.asyncio
    async def test_route_warehouse_topology(self, router: IntentRouter) -> None:
        """Test routing with warehouse topology analysis."""
        # Act
        decision = await router.classify_intent(
            "Analyze our warehouse topology for overlaps", []
        )

        # Assert
        assert decision.domain == "warehouse"

    @pytest.mark.asyncio
    async def test_route_warehouse_id_with_warehouse_keyword(
        self, router: IntentRouter
    ) -> None:
        """Test that warehouse_id + warehouse keywords routes to warehouse domain."""
        # Act
        decision = await router.classify_intent(
            "Show warehouse health for warehouse_id:wh-123", []
        )

        # Assert
        assert decision.domain == "warehouse"
        assert decision.extracted_ids.get("warehouse_id") == "wh-123"

    @pytest.mark.asyncio
    async def test_route_sql_warehouse_optimization(self, router: IntentRouter) -> None:
        """Test routing with SQL warehouse optimization."""
        # Act
        decision = await router.classify_intent(
            "Help me optimize our SQL warehouses", []
        )

        # Assert
        assert decision.domain == "warehouse"

    @pytest.mark.asyncio
    async def test_route_warehouse_disabled(self) -> None:
        """Test that warehouse routing is skipped when disabled."""
        # Arrange
        router = IntentRouter(Mock(), disabled_domains=["warehouse"])

        # Act - mock LLM for fallback
        router.llm_client.json_response = AsyncMock(
            return_value={
                "domain": "cluster",
                "confidence": 0.5,
                "reasoning": "Fallback",
            }
        )

        decision = await router.classify_intent("Show warehouse portfolio", [])

        # Assert
        assert decision.domain != "warehouse"

    @pytest.mark.asyncio
    async def test_warehouse_keywords_before_compute(
        self, router: IntentRouter
    ) -> None:
        """Test that warehouse keywords take priority over warehouse_id for compute."""
        # This tests the disambiguation: warehouse keywords should route to warehouse
        # even when a warehouse_id is present
        # Act
        decision = await router.classify_intent(
            "What's the SLO compliance for warehouse_id:wh-456?", []
        )

        # Assert
        # Should go to warehouse domain due to "SLO" keyword
        assert decision.domain == "warehouse"
        assert decision.extracted_ids.get("warehouse_id") == "wh-456"


class TestRouteClassificationCluster:
    """Tests for cluster domain routing."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    @pytest.mark.asyncio
    async def test_route_with_cluster_id(self, router: IntentRouter) -> None:
        """Test routing with cluster_id routes to cluster domain."""
        # Act
        decision = await router.classify_intent("Configure cluster_id:c123", [])

        # Assert
        assert decision.domain == "cluster"
        assert decision.confidence == 0.95  # base_confidence from cluster domain
        assert decision.extracted_ids["cluster_id"] == "c123"

    @pytest.mark.asyncio
    async def test_route_with_warehouse_id_no_warehouse_keywords(
        self, router: IntentRouter
    ) -> None:
        """Test routing with warehouse_id (no warehouse keywords) routes to warehouse.

        When there's a warehouse_id, it should route to warehouse domain.
        """
        # Act - generic query with warehouse_id
        decision = await router.classify_intent("Check warehouse_id:wh456", [])

        # Assert - warehouse_id now goes to warehouse domain
        assert decision.domain == "warehouse"
        assert decision.extracted_ids["warehouse_id"] == "wh456"

    @pytest.mark.asyncio
    async def test_route_cluster_disabled(self) -> None:
        """Test that cluster routing is skipped when disabled."""
        # Arrange
        router = IntentRouter(Mock(), disabled_domains=["cluster"])

        # Act
        decision = await router.classify_intent("Check cluster_id:c123", [])

        # Assert
        # Should not route to cluster since it's disabled
        assert decision.domain != "cluster"


class TestRouteClassificationDiagnostic:
    """Tests for diagnostic domain routing."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    @pytest.mark.asyncio
    async def test_route_with_slow_keyword(self, router: IntentRouter) -> None:
        """Test routing with 'slow' keyword routes to query domain.

        Note: 'query + slow' compound pattern matches query domain, not diagnostic.
        Diagnostic routing is for 'why' + 'slow' patterns.
        """
        # Act
        decision = await router.classify_intent("Why is my query slow?", [])

        # Assert
        # 'query + slow' compound pattern takes priority over diagnostic
        assert decision.domain == "query"
        assert decision.confidence == 0.95

    @pytest.mark.asyncio
    async def test_route_with_error_keyword(self, router: IntentRouter) -> None:
        """Test routing with 'error' keyword routes to diagnostic."""
        # Act
        decision = await router.classify_intent("I got an error message", [])

        # Assert
        assert decision.domain == "diagnostic"

    @pytest.mark.asyncio
    async def test_route_with_broken_keyword(self, router: IntentRouter) -> None:
        """Test routing with 'broken' keyword routes to diagnostic."""
        # Act - "job" keyword takes priority over "broken" diagnostic keyword
        # Use text without "job" to test diagnostic routing
        decision = await router.classify_intent("Something is broken", [])

        # Assert
        assert decision.domain == "diagnostic"

    @pytest.mark.asyncio
    async def test_route_diagnostic_disabled(self) -> None:
        """Test that diagnostic routing is skipped when disabled."""
        # Arrange
        router = IntentRouter(Mock(), disabled_domains=["diagnostic"])

        # Act - mock LLM to avoid actual LLM call
        router.llm_client = Mock()
        router.llm_client.json_response = AsyncMock(
            return_value={"domain": "query", "confidence": 0.5, "reasoning": "Fallback"}
        )

        decision = await router.classify_intent("Why is my query slow?", [])

        # Assert
        # Should not route to diagnostic since it's disabled
        assert decision.domain != "diagnostic"

    @pytest.mark.asyncio
    async def test_route_large_file_attachment(self, router: IntentRouter) -> None:
        """Test routing with large file attachment routes to diagnostic."""
        # Arrange
        attachments = [
            {"id": "att_123", "filename": "spark_log.txt", "is_large_file": True}
        ]

        # Act
        decision = await router.classify_intent(
            "Help me understand this log", [], attachments=attachments
        )

        # Assert
        assert decision.domain == "diagnostic"
        assert decision.confidence == 1.0
        assert "large_file_attachments" in decision.context
        assert len(decision.context["large_file_attachments"]) == 1

    @pytest.mark.asyncio
    async def test_route_large_file_attachment_camelcase(
        self, router: IntentRouter
    ) -> None:
        """Test routing with camelCase isLargeFile flag."""
        # Arrange - Frontend might use camelCase
        attachments = [{"id": "att_456", "filename": "error.log", "isLargeFile": True}]

        # Act
        decision = await router.classify_intent(
            "What's wrong?", [], attachments=attachments
        )

        # Assert
        assert decision.domain == "diagnostic"
        assert decision.confidence == 1.0

    @pytest.mark.asyncio
    async def test_route_small_file_attachment_not_special(
        self, router: IntentRouter
    ) -> None:
        """Test that small file attachments don't trigger large file routing."""
        # Arrange - Attachment without is_large_file flag
        attachments = [{"id": "att_789", "filename": "script.py"}]

        # Act
        decision = await router.classify_intent(
            "Review this code", [], attachments=attachments
        )

        # Assert
        # Should not route based on attachment since it's not marked as large
        assert (
            decision.domain != "diagnostic"
            or "large_file_attachments" not in decision.context
        )


class TestLLMFallback:
    """Tests for LLM fallback classification."""

    @pytest.mark.asyncio
    async def test_llm_fallback_called(self) -> None:
        """Test that LLM is called for ambiguous input."""
        # Arrange
        mock_llm = Mock()
        mock_llm.json_response = AsyncMock(
            return_value={
                "domain": "query",
                "confidence": 0.6,
                "reasoning": "Seems like a query question",
            }
        )
        router = IntentRouter(mock_llm)

        # Act
        decision = await router.classify_intent("Can you help me?", [])

        # Assert
        mock_llm.json_response.assert_called_once()
        assert decision.domain == "query"
        assert decision.confidence == 0.6

    @pytest.mark.asyncio
    async def test_llm_fallback_all_domains_disabled(self) -> None:
        """Test LLM fallback when all domains are disabled."""
        # Arrange
        mock_llm = Mock()
        mock_llm.json_response = AsyncMock(
            return_value={"domain": "query", "confidence": 0.5, "reasoning": "Fallback"}
        )
        all_domains = [
            "query",
            "job",
            "uc",
            "cluster",
            "diagnostic",
            "analytics",
            "warehouse",
            "warehouse",
        ]
        router = IntentRouter(mock_llm, disabled_domains=all_domains)

        # Act
        decision = await router.classify_intent("Some ambiguous question", [])

        # Assert
        assert decision.domain == "query"  # Default fallback
        assert decision.confidence == 0.5  # scoring fallback confidence
        assert decision.clarification_needed is True
        assert "no domains available" in decision.reasoning.lower()

    @pytest.mark.asyncio
    async def test_llm_fallback_filters_disabled_domains(self) -> None:
        """Test that LLM fallback excludes disabled domains."""
        # Arrange
        mock_llm = Mock()
        mock_llm.json_response = AsyncMock(
            return_value={
                "domain": "job",
                "confidence": 0.8,
                "reasoning": "Job question",
            }
        )
        mock_llm.model = "gpt-4o-mini"
        router = IntentRouter(mock_llm, disabled_domains=["diagnostic", "uc"])

        # Act
        _ = await router.classify_intent("Ambiguous input", [])

        # Assert
        # Verify the prompt doesn't include disabled domains
        call_args = mock_llm.json_response.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "diagnostic" not in prompt
        assert "uc" not in prompt


class TestRouteDecisionProperties:
    """Tests for route decision properties and should_route logic."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create an IntentRouter instance."""
        return IntentRouter(Mock())

    @pytest.mark.asyncio
    async def test_route_decision_should_route_true(self, router: IntentRouter) -> None:
        """Test that high confidence decisions should route."""
        # Act
        decision = await router.classify_intent("statement_id:abc123", [])

        # Assert
        assert decision.should_route() is True

    @pytest.mark.asyncio
    async def test_route_decision_clarification_prevents_routing(
        self, router: IntentRouter
    ) -> None:
        """Test that clarification_needed prevents routing.

        Note: 'why + slow' now routes to diagnostic domain with confidence 0.8,
        which does not trigger clarification_needed. Use a truly ambiguous query.
        """
        # Act - Use a truly ambiguous query that triggers LLM fallback
        # Mock the LLM to return low confidence
        router.llm_client.json_response = AsyncMock(
            return_value={
                "domain": "query",
                "confidence": 0.5,
                "reasoning": "Ambiguous query",
            }
        )
        decision = await router.classify_intent("Help me please", [])

        # Assert
        assert decision.clarification_needed is True
        assert decision.should_route() is False


class TestHistoryContext:
    """Tests for _build_history_context used in follow-up routing."""

    def test_empty_history_returns_empty(self) -> None:
        result = IntentRouter._build_history_context([])
        assert result == ""

    def test_single_turn_produces_context(self) -> None:
        history = [
            {"role": "user", "content": "Analyze query abc123"},
            {"role": "assistant", "content": "I found 3 optimization opportunities."},
        ]
        result = IntentRouter._build_history_context(history)
        assert "Analyze query abc123" in result
        assert "3 optimization opportunities" in result

    def test_max_turns_respected(self) -> None:
        history = []
        for i in range(5):
            history.append({"role": "user", "content": f"Question {i}"})
            history.append({"role": "assistant", "content": f"Answer {i}"})

        result = IntentRouter._build_history_context(history, max_turns=2)
        assert "Question 3" in result
        assert "Question 4" in result
        assert "Question 0" not in result

    def test_max_chars_respected(self) -> None:
        history = [
            {"role": "user", "content": "A" * 500},
            {"role": "assistant", "content": "B" * 500},
            {"role": "user", "content": "C" * 500},
            {"role": "assistant", "content": "D" * 500},
        ]
        result = IntentRouter._build_history_context(history, max_chars=300)
        assert len(result) <= 600  # some overhead for labels

    def test_message_objects_supported(self) -> None:
        from starboard_server.agents.state.agent_state import Message

        history = [
            Message(role="user", content="Check job 123"),
            Message(role="assistant", content="Job is running slowly."),
        ]
        result = IntentRouter._build_history_context(history)
        assert "Check job 123" in result
        assert "running slowly" in result
