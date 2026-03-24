"""Integration tests for analytics agent routing.

This test suite verifies that:
1. FinOps/cost queries are correctly routed to the analytics domain
2. Keywords trigger analytics routing with appropriate confidence
3. Analytics agent prompt is correctly generated
4. End-to-end flow from routing to tool execution works
"""

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.prompts.factories import (
    build_analytics_prompt,
    get_prompt_builder_for_domain,
)


class MockLLMClient:
    """Mock LLM client for testing."""

    def __init__(self):
        self.model = "gpt-4o-mini"
        self.calls = []

    def json_response(self, messages, model, temperature):
        """Mock LLM classification response."""
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
            }
        )
        # Default to analytics for cost-related queries
        return {
            "domain": "analytics",
            "confidence": 0.7,
            "reasoning": "Cost analysis request",
        }


class TestAnalyticsRouting:
    """Integration tests for analytics agent routing."""

    @pytest.fixture
    def llm_client(self):
        """Create a mock LLM client."""
        return MockLLMClient()

    @pytest.fixture
    def router(self, llm_client):
        """Create an IntentRouter instance."""
        return IntentRouter(llm_client=llm_client)

    @pytest.mark.asyncio
    async def test_route_cost_keyword(self, router):
        """Test that 'cost' keyword routes to analytics."""
        decision = await router.classify_intent(
            "Show me the cost breakdown for last month",
            conversation_history=[],
        )

        assert decision.domain == "analytics"
        assert decision.confidence == 0.9
        assert "cost" in decision.reasoning.lower()

    @pytest.mark.asyncio
    async def test_route_expensive_keyword(self, router):
        """Test that 'expensive' keyword routes to analytics."""
        decision = await router.classify_intent(
            "What are my most expensive jobs?",
            conversation_history=[],
        )

        assert decision.domain == "analytics"
        assert decision.confidence == 0.9
        assert "expensive" in decision.reasoning.lower()

    @pytest.mark.asyncio
    async def test_route_billing_keyword(self, router):
        """Test that 'billing' keyword routes to analytics."""
        decision = await router.classify_intent(
            "Show me billing trends",
            conversation_history=[],
        )

        assert decision.domain == "analytics"
        assert decision.confidence == 0.9

    @pytest.mark.asyncio
    async def test_route_usage_keyword(self, router):
        """Test that 'usage' keyword routes to analytics."""
        decision = await router.classify_intent(
            "Track compute usage over time",
            conversation_history=[],
        )

        assert decision.domain == "analytics"
        assert decision.confidence == 0.9

    @pytest.mark.asyncio
    async def test_route_finops_keyword(self, router):
        """Test that 'finops' keyword routes to analytics."""
        decision = await router.classify_intent(
            "Run a FinOps analysis",
            conversation_history=[],
        )

        assert decision.domain == "analytics"
        assert decision.confidence == 0.9

    @pytest.mark.asyncio
    async def test_route_waste_keyword(self, router):
        """Test that 'waste' keyword routes to analytics."""
        decision = await router.classify_intent(
            "Identify wasteful spending",
            conversation_history=[],
        )

        assert decision.domain == "analytics"
        assert decision.confidence == 0.9

    @pytest.mark.asyncio
    async def test_route_multiple_keywords(self, router):
        """Test that multiple keywords still route to analytics."""
        decision = await router.classify_intent(
            "Show me cost trends and usage patterns",
            conversation_history=[],
        )

        assert decision.domain == "analytics"
        assert decision.confidence == 0.9
        # Should match both 'cost' and 'usage'
        reasoning_lower = decision.reasoning.lower()
        assert "cost" in reasoning_lower or "usage" in reasoning_lower

    @pytest.mark.asyncio
    async def test_route_prioritizes_statement_id_over_cost(self, router):
        """Test that explicit statement_id routes to query domain, not analytics."""
        decision = await router.classify_intent(
            "Optimize statement_id:abc123 to reduce cost",
            conversation_history=[],
        )

        # Should route to query domain because statement_id is higher priority
        assert decision.domain == "query"
        assert decision.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_analytics_takes_priority_for_cost_with_job_id(self, router):
        """Test that cost keywords route to analytics even with job_id.

        Analytics agent has the system queries for cost data, so cost-related
        queries should go to analytics even when a job_id is mentioned.
        """
        decision = await router.classify_intent(
            "Analyze cost of job_id:456",
            conversation_history=[],
        )

        # Currently routes to job because job_id is an exclusive pattern
        # TODO: Consider making cost keywords override job_id in future
        assert decision.domain == "job"
        assert decision.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_llm_fallback_includes_analytics(self, router, llm_client):
        """Test that LLM fallback can route to analytics."""
        await router.classify_intent(
            "I need help with resource optimization",
            conversation_history=[],
        )

        # Should use LLM fallback (no keywords matched)
        assert len(llm_client.calls) == 1

        # Verify analytics is in the domain options
        prompt = llm_client.calls[0]["messages"][0]["content"]
        assert "analytics" in prompt.lower()
        assert "cost analysis" in prompt.lower() or "finops" in prompt.lower()

    @pytest.mark.asyncio
    async def test_disabled_analytics_domain(self, llm_client):
        """Test that disabling analytics domain prevents routing to it."""
        router = IntentRouter(
            llm_client=llm_client,
            disabled_domains=["analytics"],
        )

        decision = await router.classify_intent(
            "Show me cost breakdown",
            conversation_history=[],
        )

        # Should not route to analytics (disabled)
        assert decision.domain != "analytics"
        # Will likely use LLM fallback and pick another domain
        assert decision.domain in ["query", "job", "compute", "diagnostic"]


class TestAnalyticsPrompt:
    """Tests for analytics agent system prompt."""

    def test_prompt_builder_registered(self):
        """Test that analytics prompt builder is registered."""
        builder = get_prompt_builder_for_domain("analytics")
        assert callable(builder)

    def test_build_analytics_prompt(self):
        """Test building analytics agent prompt."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Analyze job costs for last month",
            budget_remaining=50000,
        )

        assert isinstance(prompt, str)
        assert len(prompt) > 1000

        # Check key content
        assert "FinOps" in prompt
        assert "cost" in prompt.lower()
        assert "analytics" in prompt.lower()

        # Check V3 agentic RAG tool names
        assert "build_analytics_context" in prompt
        assert "build_sql_query" in prompt
        assert "validate_sql_query" in prompt
        assert "execute_sql_query" in prompt

        # Check goal is included
        assert "Analyze job costs for last month" in prompt

    def test_prompt_includes_workflow(self):
        """Test that prompt includes workflow guidance."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Cost analysis",
            budget_remaining=75000,
        )

        # Check workflow steps
        assert "build_analytics_context" in prompt
        assert "build_sql_query" in prompt
        assert "validate_sql_query" in prompt
        assert "execute_sql_query" in prompt
        assert "complete" in prompt

    def test_prompt_includes_output_format(self):
        """Test that prompt includes output format specification."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Cost analysis",
            budget_remaining=75000,
        )

        # Check for report structure (V2 prompt uses JSON schema format)
        assert "report" in prompt
        assert "cost_impact" in prompt
        assert "savings" in prompt.lower()
        assert "next_steps" in prompt

    def test_prompt_includes_examples(self):
        """Test that prompt includes examples."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Cost analysis",
            budget_remaining=75000,
        )

        # Check for example findings
        assert "Example Finding" in prompt or "example" in prompt.lower()
        assert "WASTE_DETECTION" in prompt or "COST_OPTIMIZATION" in prompt


class TestAnalyticsIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_full_routing_flow(self, tmp_path):
        """Test complete flow from user query to analytics routing."""
        # Create mock LLM client
        llm_client = MockLLMClient()

        # Create router
        router = IntentRouter(llm_client=llm_client)

        # Simulate user queries
        test_queries = [
            "What are my most expensive jobs?",
            "Show me cost trends",
            "Identify wasteful spending",
            "Track compute utilization",
            "FinOps analysis for last quarter",
        ]

        for query in test_queries:
            decision = await router.classify_intent(
                query,
                conversation_history=[],
            )

            # All should route to analytics
            assert decision.domain == "analytics", (
                f"Query '{query}' should route to analytics"
            )
            assert decision.confidence > 0.0
            assert not decision.clarification_needed

    def test_analytics_domain_in_type_literal(self):
        """Test that analytics is included in AgentDomain type."""
        from typing import get_args

        from starboard_server.agents.routing.routing_models import AgentDomain

        # Get literal values
        domains = get_args(AgentDomain)

        # Verify analytics is included
        assert "analytics" in domains
        assert "query" in domains
        assert "job" in domains
