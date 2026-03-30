# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for MCPAgentExecutor."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starboard_server.agents.output.envelope import (
    AgentMetrics,
    AgentResultEnvelope,
)
from starboard_server.agents.routing.routing_models import RouteDecision
from starboard_server.mcp.agent_bridge import (
    AGENT_DOMAINS,
    AGENT_TOOL_METADATA,
    LOW_CONFIDENCE_THRESHOLD,
    TOOL_NAME_TO_DOMAIN,
    MCPAgentExecutor,
)
from starboard_server.mcp.observability import TokenBudgetTracker


def _make_envelope(
    domain: str = "query",
    status: str = "success",
    payload: dict[str, Any] | None = None,
    tokens_used: int = 100,
) -> AgentResultEnvelope:
    """Create a test envelope."""
    return AgentResultEnvelope(
        domain=domain,
        timestamp=datetime.now(UTC),
        trace_id="test-trace",
        status=status,
        report_type="advisor",
        payload=payload or {"summary": "Test result"},
        metrics=AgentMetrics(
            tokens_used=tokens_used,
            cost_usd=0.01,
            duration_seconds=1.0,
            steps_taken=3,
        ),
    )


def _make_final_output_event(output: Any = None) -> MagicMock:
    """Create a mock FinalOutputEvent."""
    event = MagicMock()
    event.output = output
    return event


def _make_mock_agent(envelope: AgentResultEnvelope | None = None) -> MagicMock:
    """Create a mock DomainAgent with run_stream that yields a FinalOutputEvent."""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.domain = "query"

    async def mock_run_stream(**kwargs: Any) -> Any:
        if envelope is not None:
            event = _make_final_output_event(output=MagicMock())
            yield event
        else:
            # Yield nothing — no FinalOutputEvent
            return

    agent.run_stream = mock_run_stream
    return agent


def _make_executor(
    *,
    agent_factory: Any | None = None,
    intent_router: Any | None = None,
    token_budget: int | None = None,
    timeout: int = 120,
) -> MCPAgentExecutor:
    """Create an MCPAgentExecutor with mock dependencies."""
    factory = agent_factory or MagicMock()
    if agent_factory is None:
        factory.get_agent = MagicMock(return_value=_make_mock_agent())
        factory.events = None

    tracker = TokenBudgetTracker(default_budget=token_budget) if token_budget else None
    return MCPAgentExecutor(
        agent_factory=factory,
        intent_router=intent_router,
        token_budget_tracker=tracker,
        default_timeout=timeout,
    )


class TestAgentToolMetadata:
    """Tests for agent tool metadata constants."""

    def test_all_8_domains_defined(self) -> None:
        assert len(AGENT_DOMAINS) == 8

    def test_mcp_exposed_agents_exclude_discovery(self) -> None:
        """AGENT_TOOL_METADATA should only contain MCP-exposed agents (not discovery)."""
        assert len(AGENT_TOOL_METADATA) == 7
        names = {t["name"] for t in AGENT_TOOL_METADATA}
        assert "discovery_agent" not in names

    def test_tool_name_to_domain_mapping(self) -> None:
        assert TOOL_NAME_TO_DOMAIN["query_agent"] == "query"
        assert TOOL_NAME_TO_DOMAIN["job_agent"] == "job"
        assert TOOL_NAME_TO_DOMAIN["uc_agent"] == "uc"
        assert TOOL_NAME_TO_DOMAIN["cluster_agent"] == "cluster"
        assert TOOL_NAME_TO_DOMAIN["analytics_agent"] == "analytics"
        assert TOOL_NAME_TO_DOMAIN["warehouse_agent"] == "warehouse"
        assert TOOL_NAME_TO_DOMAIN["diagnostic_agent"] == "diagnostic"
        assert TOOL_NAME_TO_DOMAIN["discovery_agent"] == "discovery"

    def test_each_tool_has_required_fields(self) -> None:
        for tool in AGENT_TOOL_METADATA:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
            assert tool["parameters"]["required"] == ["message"]

    def test_low_confidence_threshold(self) -> None:
        assert LOW_CONFIDENCE_THRESHOLD == 0.7


class TestMCPAgentExecutorDirectDomain:
    """Tests for MCPAgentExecutor with a directly specified domain."""

    @pytest.mark.asyncio
    async def test_execute_with_direct_domain(self) -> None:
        envelope = _make_envelope(domain="query")
        agent = _make_mock_agent()

        factory = MagicMock()
        factory.get_agent = MagicMock(return_value=agent)
        factory.events = None

        executor = _make_executor(agent_factory=factory)

        # Patch _run_agent to return the envelope directly
        with patch.object(executor, "_run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = envelope

            resp = await executor.execute(
                message="Analyze my query",
                workspace_id="prod",
                domain="query",
                session_id="s1",
            )

        assert resp.status == "success"
        assert resp.workspace_id_used == "prod"
        assert resp.agent_domain == "query"
        assert resp.mcp_metadata is not None
        assert resp.mcp_metadata.confidence == 1.0
        assert resp.mcp_metadata.low_confidence is False
        assert resp.mcp_metadata.auto_selected_path is False
        assert resp.mcp_metadata.reasoning_summary == "Domain specified directly"

    @pytest.mark.asyncio
    async def test_execute_extracts_response_text(self) -> None:
        envelope = _make_envelope(payload={"summary": "Query is optimal"})
        executor = _make_executor()

        with patch.object(executor, "_run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = envelope

            resp = await executor.execute(
                message="Check query",
                workspace_id="prod",
                domain="query",
            )

        assert resp.response_text == "Query is optimal"

    @pytest.mark.asyncio
    async def test_execute_extracts_tools_used(self) -> None:
        envelope = _make_envelope(
            payload={
                "summary": "Done",
                "tools_used": ["resolve_query", "analyze_query_plan"],
            }
        )
        executor = _make_executor()

        with patch.object(executor, "_run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = envelope

            resp = await executor.execute(
                message="Check",
                workspace_id="prod",
                domain="query",
            )

        assert resp.tools_used == ["resolve_query", "analyze_query_plan"]

    @pytest.mark.asyncio
    async def test_execute_includes_envelope_in_response(self) -> None:
        envelope = _make_envelope()
        executor = _make_executor()

        with patch.object(executor, "_run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = envelope

            resp = await executor.execute(
                message="Check",
                workspace_id="prod",
                domain="query",
            )

        assert resp.envelope is not None
        assert resp.envelope["domain"] == "query"


class TestMCPAgentExecutorRouting:
    """Tests for MCPAgentExecutor with intent routing."""

    @pytest.mark.asyncio
    async def test_routes_when_no_domain_specified(self) -> None:
        envelope = _make_envelope(domain="job")

        router = MagicMock()
        router.classify_intent = AsyncMock(
            return_value=RouteDecision(
                domain="job",
                confidence=0.9,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Detected job keywords",
            )
        )

        factory = MagicMock()
        factory.get_agent = MagicMock(return_value=_make_mock_agent())
        factory.events = None

        executor = _make_executor(agent_factory=factory, intent_router=router)

        with patch.object(executor, "_run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = envelope

            resp = await executor.execute(
                message="Why is my job slow?",
                workspace_id="prod",
            )

        assert resp.status == "success"
        assert resp.agent_domain == "job"
        assert resp.mcp_metadata is not None
        assert resp.mcp_metadata.confidence == 0.9
        assert resp.mcp_metadata.low_confidence is False

    @pytest.mark.asyncio
    async def test_low_confidence_sets_flags(self) -> None:
        envelope = _make_envelope(domain="cluster")

        router = MagicMock()
        router.classify_intent = AsyncMock(
            return_value=RouteDecision(
                domain="cluster",
                confidence=0.5,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Uncertain routing",
            )
        )

        factory = MagicMock()
        factory.get_agent = MagicMock(return_value=_make_mock_agent())
        factory.events = None

        executor = _make_executor(agent_factory=factory, intent_router=router)

        with patch.object(executor, "_run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = envelope

            resp = await executor.execute(
                message="Something about clusters maybe?",
                workspace_id="prod",
            )

        assert resp.mcp_metadata is not None
        assert resp.mcp_metadata.low_confidence is True
        assert resp.mcp_metadata.auto_selected_path is True
        assert resp.mcp_metadata.confidence == 0.5

    @pytest.mark.asyncio
    async def test_no_domain_no_router_returns_error(self) -> None:
        executor = _make_executor(intent_router=None)

        resp = await executor.execute(
            message="Help me",
            workspace_id="prod",
            # No domain, no router
        )

        assert resp.status == "error"
        assert "no intent router" in resp.response_text.lower()


class TestMCPAgentExecutorTimeout:
    """Tests for MCPAgentExecutor timeout handling."""

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_response(self) -> None:
        executor = _make_executor(timeout=1)

        async def slow_run(*args: Any, **kwargs: Any) -> AgentResultEnvelope:
            await asyncio.sleep(10)
            return _make_envelope()

        with patch.object(executor, "_run_agent", side_effect=slow_run):
            resp = await executor.execute(
                message="Complex analysis",
                workspace_id="prod",
                domain="query",
            )

        assert resp.status == "timeout"
        assert "timed out" in resp.response_text.lower()
        assert resp.envelope is not None
        assert resp.envelope["status"] == "partial"
        assert resp.mcp_metadata is not None
        assert resp.mcp_metadata.domain_selected == "query"


class TestMCPAgentExecutorBudget:
    """Tests for MCPAgentExecutor token budget enforcement."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_returns_partial(self) -> None:
        executor = _make_executor(token_budget=100)
        # Exhaust the budget
        executor._token_budget_tracker.record_usage("s1", 200)  # type: ignore[union-attr]

        resp = await executor.execute(
            message="Analyze",
            workspace_id="prod",
            domain="query",
            session_id="s1",
        )

        assert resp.status == "partial"
        assert "budget exceeded" in resp.response_text.lower()
        assert resp.envelope is not None
        assert resp.envelope["status"] == "budget_exceeded"

    @pytest.mark.asyncio
    async def test_records_token_usage_after_execution(self) -> None:
        envelope = _make_envelope(tokens_used=250)

        executor = _make_executor(token_budget=10000)

        with patch.object(executor, "_run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = envelope

            await executor.execute(
                message="Check",
                workspace_id="prod",
                domain="query",
                session_id="s1",
            )

        assert executor._token_budget_tracker is not None
        assert executor._token_budget_tracker.get_used("s1") == 250


class TestMCPAgentExecutorErrors:
    """Tests for MCPAgentExecutor error handling."""

    @pytest.mark.asyncio
    async def test_agent_exception_returns_error_response(self) -> None:
        executor = _make_executor()

        with patch.object(
            executor, "_run_agent", side_effect=RuntimeError("Agent crashed")
        ):
            resp = await executor.execute(
                message="Do something",
                workspace_id="prod",
                domain="query",
            )

        assert resp.status == "error"
        assert "Agent crashed" in resp.response_text
        assert resp.mcp_metadata is not None
        assert resp.mcp_metadata.domain_selected == "query"

    @pytest.mark.asyncio
    async def test_conversation_id_passed_through(self) -> None:
        envelope = _make_envelope()
        executor = _make_executor()

        with patch.object(executor, "_run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = envelope

            resp = await executor.execute(
                message="Continue",
                workspace_id="prod",
                domain="query",
                conversation_id="conv-42",
            )

        assert resp.mcp_metadata is not None
        assert resp.mcp_metadata.conversation_id == "conv-42"
