# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for multi-agent metrics and observability."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starboard.agents.observability.metrics import (
    AgentMetrics,
    MultiAgentMetrics,
    RoutingMetrics,
    SpecialistMetrics,
    TransitionMetrics,
    get_metrics,
)


class TestRoutingMetrics:
    """Tests for RoutingMetrics dataclass."""

    def test_routing_metrics_creation(self):
        """Should create routing metrics with required fields."""
        metrics = RoutingMetrics(
            domain="query",
            confidence=0.95,
            clarification_needed=False,
            reasoning="Statement ID detected",
        )

        assert metrics.domain == "query"
        assert metrics.confidence == 0.95
        assert metrics.clarification_needed is False
        assert metrics.reasoning == "Statement ID detected"
        assert metrics.extracted_ids == {}
        assert isinstance(metrics.timestamp, datetime)

    def test_routing_metrics_with_extracted_ids(self):
        """Should store extracted identifiers."""
        metrics = RoutingMetrics(
            domain="query",
            confidence=1.0,
            clarification_needed=False,
            reasoning="Statement ID found",
            extracted_ids={"statement_id": "abc123"},
        )

        assert metrics.extracted_ids == {"statement_id": "abc123"}

    def test_routing_metrics_timestamp_utc(self):
        """Timestamp should be UTC."""
        metrics = RoutingMetrics(
            domain="query",
            confidence=0.9,
            clarification_needed=False,
            reasoning="Test",
        )

        assert metrics.timestamp.tzinfo == UTC


class TestTransitionMetrics:
    """Tests for TransitionMetrics dataclass."""

    def test_transition_metrics_creation(self):
        """Should create transition metrics."""
        metrics = TransitionMetrics(
            from_agent="router",
            to_agent="query",
            reason="Statement ID routing",
            context_size=1024,
        )

        assert metrics.from_agent == "router"
        assert metrics.to_agent == "query"
        assert metrics.reason == "Statement ID routing"
        assert metrics.context_size == 1024
        assert isinstance(metrics.timestamp, datetime)


class TestSpecialistMetrics:
    """Tests for SpecialistMetrics dataclass."""

    def test_specialist_metrics_creation(self):
        """Should create specialist execution metrics."""
        metrics = SpecialistMetrics(
            domain="query",
            duration_seconds=2.5,
            tokens_used=1500,
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.015,
            tools_called=3,
        )

        assert metrics.domain == "query"
        assert metrics.duration_seconds == 2.5
        assert metrics.tokens_used == 1500
        assert metrics.input_tokens == 1000
        assert metrics.output_tokens == 500
        assert metrics.cost_usd == 0.015
        assert metrics.tools_called == 3
        assert metrics.success is True
        assert metrics.error is None

    def test_specialist_metrics_with_failure(self):
        """Should record failure information."""
        metrics = SpecialistMetrics(
            domain="query",
            duration_seconds=1.0,
            tokens_used=100,
            input_tokens=100,
            output_tokens=0,
            cost_usd=0.001,
            tools_called=0,
            success=False,
            error="Timeout",
        )

        assert metrics.success is False
        assert metrics.error == "Timeout"

    def test_specialist_metrics_with_tools_used(self):
        """Should record tools used."""
        metrics = SpecialistMetrics(
            domain="query",
            duration_seconds=2.0,
            tokens_used=1000,
            input_tokens=800,
            output_tokens=200,
            cost_usd=0.01,
            tools_called=2,
            tools_used=["resolve_query", "analyze_query_plan"],
        )

        assert metrics.tools_used == ["resolve_query", "analyze_query_plan"]


class TestMultiAgentMetrics:
    """Tests for MultiAgentMetrics class."""

    def test_initialization(self):
        """Should initialize with empty lists."""
        metrics = MultiAgentMetrics()

        assert metrics.routing_decisions == []
        assert metrics.transitions == []
        assert metrics.specialist_executions == []

    def test_record_routing_decision(self):
        """Should record routing decision."""
        metrics = MultiAgentMetrics()

        metrics.record_routing_decision(
            domain="query",
            confidence=0.95,
            clarification_needed=False,
            reasoning="Statement ID detected",
            extracted_ids={"statement_id": "abc123"},
        )

        assert len(metrics.routing_decisions) == 1
        decision = metrics.routing_decisions[0]
        assert decision.domain == "query"
        assert decision.confidence == 0.95
        assert decision.extracted_ids == {"statement_id": "abc123"}

    def test_record_agent_transition(self):
        """Should record agent transition."""
        metrics = MultiAgentMetrics()

        metrics.record_agent_transition(
            from_agent="router",
            to_agent="query",
            reason="Statement ID found",
            context_size=1024,
        )

        assert len(metrics.transitions) == 1
        transition = metrics.transitions[0]
        assert transition.from_agent == "router"
        assert transition.to_agent == "query"
        assert transition.context_size == 1024

    def test_record_specialist_execution(self):
        """Should record specialist execution."""
        metrics = MultiAgentMetrics()

        metrics.record_specialist_execution(
            domain="query",
            duration_seconds=2.5,
            tokens_used=1500,
            cost_usd=0.015,
            tools_called=3,
            tools_used=["resolve_query", "analyze_query_plan", "complete"],
            model="gpt-4o",
            temperature=0.5,
            input_tokens=1000,
            output_tokens=500,
        )

        assert len(metrics.specialist_executions) == 1
        execution = metrics.specialist_executions[0]
        assert execution.domain == "query"
        assert execution.duration_seconds == 2.5
        assert execution.tokens_used == 1500
        assert execution.cost_usd == 0.015
        assert execution.tools_called == 3
        assert len(execution.tools_used) == 3

    def test_get_routing_accuracy_empty(self):
        """Should handle empty routing decisions."""
        metrics = MultiAgentMetrics()

        accuracy = metrics.get_routing_accuracy()

        assert accuracy["total_decisions"] == 0
        assert accuracy["avg_confidence"] == 0.0
        assert accuracy["clarification_rate"] == 0.0
        assert accuracy["by_domain"] == {}

    def test_get_routing_accuracy_single_decision(self):
        """Should calculate accuracy for single decision."""
        metrics = MultiAgentMetrics()

        metrics.record_routing_decision(
            domain="query",
            confidence=0.95,
            clarification_needed=False,
            reasoning="Test",
        )

        accuracy = metrics.get_routing_accuracy()

        assert accuracy["total_decisions"] == 1
        assert accuracy["avg_confidence"] == 0.95
        assert accuracy["clarification_rate"] == 0.0
        assert "query" in accuracy["by_domain"]
        assert accuracy["by_domain"]["query"]["count"] == 1
        assert accuracy["by_domain"]["query"]["avg_confidence"] == 0.95

    def test_get_routing_accuracy_multiple_decisions(self):
        """Should calculate accuracy across multiple decisions."""
        metrics = MultiAgentMetrics()

        # Add multiple decisions
        metrics.record_routing_decision("query", 0.9, False, "Test 1")
        metrics.record_routing_decision("job", 0.8, False, "Test 2")
        metrics.record_routing_decision("query", 1.0, False, "Test 3")
        metrics.record_routing_decision("diagnostic", 0.5, True, "Test 4")

        accuracy = metrics.get_routing_accuracy()

        assert accuracy["total_decisions"] == 4
        assert accuracy["avg_confidence"] == (0.9 + 0.8 + 1.0 + 0.5) / 4
        assert accuracy["clarification_rate"] == 0.25  # 1 out of 4

        # Check per-domain stats
        assert accuracy["by_domain"]["query"]["count"] == 2
        assert accuracy["by_domain"]["query"]["avg_confidence"] == 0.95
        assert accuracy["by_domain"]["diagnostic"]["clarification_rate"] == 1.0

    def test_get_cost_summary_empty(self):
        """Should handle empty specialist executions."""
        metrics = MultiAgentMetrics()

        cost_summary = metrics.get_cost_summary()

        assert cost_summary["total_cost_usd"] == 0.0
        assert cost_summary["total_tokens"] == 0
        assert cost_summary["by_domain"] == {}

    def test_get_cost_summary_single_execution(self):
        """Should calculate cost for single execution."""
        metrics = MultiAgentMetrics()

        metrics.record_specialist_execution(
            domain="query",
            duration_seconds=2.0,
            tokens_used=1000,
            cost_usd=0.01,
            tools_called=2,
            input_tokens=800,
            output_tokens=200,
        )

        cost_summary = metrics.get_cost_summary()

        assert cost_summary["total_cost_usd"] == 0.01
        assert cost_summary["total_tokens"] == 1000
        assert "query" in cost_summary["by_domain"]
        assert cost_summary["by_domain"]["query"]["total_cost_usd"] == 0.01
        assert cost_summary["by_domain"]["query"]["avg_cost_usd"] == 0.01

    def test_get_cost_summary_multiple_executions(self):
        """Should calculate cost across multiple executions."""
        metrics = MultiAgentMetrics()

        # Add multiple executions
        metrics.record_specialist_execution(
            "query", 2.0, 1000, 0.01, 2, input_tokens=800, output_tokens=200
        )
        metrics.record_specialist_execution(
            "job", 3.0, 1500, 0.015, 3, input_tokens=1000, output_tokens=500
        )
        metrics.record_specialist_execution(
            "query", 1.5, 800, 0.008, 1, input_tokens=600, output_tokens=200
        )

        cost_summary = metrics.get_cost_summary()

        assert cost_summary["total_cost_usd"] == 0.033
        assert cost_summary["total_tokens"] == 3300

        # Check per-domain stats
        assert cost_summary["by_domain"]["query"]["executions"] == 2
        assert cost_summary["by_domain"]["query"]["total_cost_usd"] == pytest.approx(
            0.018, rel=1e-6
        )
        assert cost_summary["by_domain"]["query"]["avg_tokens"] == 900

        assert cost_summary["by_domain"]["job"]["executions"] == 1
        assert cost_summary["by_domain"]["job"]["total_cost_usd"] == 0.015

    def test_get_transition_stats_empty(self):
        """Should handle empty transitions."""
        metrics = MultiAgentMetrics()

        stats = metrics.get_transition_stats()

        assert stats["total_transitions"] == 0
        assert stats["unique_paths"] == 0
        assert stats["most_common_transitions"] == []

    def test_get_transition_stats_single_path(self):
        """Should track single transition path."""
        metrics = MultiAgentMetrics()

        metrics.record_agent_transition("router", "query", "Test", 1024)

        stats = metrics.get_transition_stats()

        assert stats["total_transitions"] == 1
        assert stats["unique_paths"] == 1
        assert stats["most_common_transitions"] == [("router->query", 1)]

    def test_get_transition_stats_multiple_paths(self):
        """Should track multiple transition paths and frequency."""
        metrics = MultiAgentMetrics()

        # Add transitions
        metrics.record_agent_transition("router", "query", "Test", 1024)
        metrics.record_agent_transition("router", "query", "Test", 1024)
        metrics.record_agent_transition("router", "job", "Test", 512)
        metrics.record_agent_transition("router", "query", "Test", 1024)
        metrics.record_agent_transition("query", "diagnostic", "Test", 2048)

        stats = metrics.get_transition_stats()

        assert stats["total_transitions"] == 5
        assert stats["unique_paths"] == 3

        # Most common should be router->query (3 times)
        assert stats["most_common_transitions"][0] == ("router->query", 3)
        assert stats["most_common_transitions"][1][0] in [
            "router->job",
            "query->diagnostic",
        ]

    def test_clear_metrics(self):
        """Should clear all collected metrics."""
        metrics = MultiAgentMetrics()

        # Add some data
        metrics.record_routing_decision("query", 0.9, False, "Test")
        metrics.record_agent_transition("router", "query", "Test", 1024)
        metrics.record_specialist_execution(
            "query", 2.0, 1000, 0.01, 2, input_tokens=800, output_tokens=200
        )

        # Verify data exists
        assert len(metrics.routing_decisions) == 1
        assert len(metrics.transitions) == 1
        assert len(metrics.specialist_executions) == 1

        # Clear
        metrics.clear()

        # Verify cleared
        assert len(metrics.routing_decisions) == 0
        assert len(metrics.transitions) == 0
        assert len(metrics.specialist_executions) == 0


class TestGlobalMetrics:
    """Tests for global metrics instance."""

    def test_get_metrics_returns_instance(self):
        """Should return global metrics instance."""
        metrics = get_metrics()

        assert isinstance(metrics, MultiAgentMetrics)

    def test_get_metrics_returns_same_instance(self):
        """Should return same instance on multiple calls."""
        metrics1 = get_metrics()
        metrics2 = get_metrics()

        assert metrics1 is metrics2

    def test_global_metrics_persists_data(self):
        """Global metrics should persist data across calls."""
        metrics = get_metrics()
        metrics.clear()  # Start fresh

        metrics.record_routing_decision("query", 0.9, False, "Test")

        # Get instance again
        metrics2 = get_metrics()

        # Should have same data
        assert len(metrics2.routing_decisions) == 1
        assert metrics2.routing_decisions[0].domain == "query"

        # Clean up
        metrics.clear()


class TestMetricsIntegration:
    """Integration tests combining multiple metric types."""

    def test_full_request_workflow(self):
        """Test complete metrics workflow for a request."""
        metrics = MultiAgentMetrics()

        # 1. Record routing decision
        metrics.record_routing_decision(
            domain="query",
            confidence=0.95,
            clarification_needed=False,
            reasoning="Statement ID detected",
            extracted_ids={"statement_id": "abc123"},
        )

        # 2. Record transition
        metrics.record_agent_transition(
            from_agent="router",
            to_agent="query",
            reason="Statement ID routing",
            context_size=1024,
        )

        # 3. Record specialist execution
        metrics.record_specialist_execution(
            domain="query",
            duration_seconds=2.5,
            tokens_used=1500,
            cost_usd=0.015,
            tools_called=3,
            tools_used=["resolve_query", "analyze_query_plan", "complete"],
            input_tokens=1000,
            output_tokens=500,
        )

        # Verify all recorded
        assert len(metrics.routing_decisions) == 1
        assert len(metrics.transitions) == 1
        assert len(metrics.specialist_executions) == 1

        # Verify summaries
        accuracy = metrics.get_routing_accuracy()
        assert accuracy["total_decisions"] == 1

        cost_summary = metrics.get_cost_summary()
        assert cost_summary["total_cost_usd"] == 0.015

        transition_stats = metrics.get_transition_stats()
        assert transition_stats["total_transitions"] == 1

    def test_multi_domain_metrics(self):
        """Test metrics across multiple domains."""
        metrics = MultiAgentMetrics()

        # Query domain
        metrics.record_routing_decision("query", 0.95, False, "Statement ID")
        metrics.record_specialist_execution(
            "query", 2.0, 1000, 0.01, 2, input_tokens=800, output_tokens=200
        )

        # Job domain
        metrics.record_routing_decision("job", 0.90, False, "Job ID")
        metrics.record_specialist_execution(
            "job", 3.0, 1500, 0.015, 3, input_tokens=1000, output_tokens=500
        )

        # Diagnostic domain (with clarification)
        metrics.record_routing_decision("diagnostic", 0.65, True, "Ambiguous")

        # Verify per-domain stats
        accuracy = metrics.get_routing_accuracy()
        assert len(accuracy["by_domain"]) == 3
        assert accuracy["by_domain"]["diagnostic"]["clarification_rate"] == 1.0
        assert accuracy["by_domain"]["query"]["clarification_rate"] == 0.0

        cost_summary = metrics.get_cost_summary()
        assert len(cost_summary["by_domain"]) == 2  # Only 2 executed
        assert cost_summary["total_cost_usd"] == 0.025


class TestAgentMetricsExportJson:
    """Tests for AgentMetrics.export_json async method."""

    @pytest.mark.asyncio
    async def test_export_json_writes_file(self, tmp_path: Path) -> None:
        """export_json should write metrics to a JSON file asynchronously."""
        metrics = AgentMetrics(
            session_id="test-session",
            agent_type="reasoning",
            model="gpt-4o",
        )
        metrics.record_step(step_number=1, duration=1.5, tokens_used=500)
        metrics.record_tool(tool_name="resolve_query", success=True, duration=0.5)
        metrics.finalize()

        filepath = tmp_path / "metrics.json"
        await metrics.export_json(filepath)

        assert filepath.exists()
        data = json.loads(filepath.read_text())
        assert data["session_id"] == "test-session"
        assert data["agent_type"] == "reasoning"
        assert data["model"] == "gpt-4o"
        assert data["total_tokens"] == 500
        assert len(data["steps"]) == 1
        assert len(data["tool_calls"]) == 1
        assert data["tool_calls"][0]["tool_name"] == "resolve_query"
        assert data["tool_calls"][0]["success"] is True

    @pytest.mark.asyncio
    async def test_export_json_creates_parent_directories(self, tmp_path: Path) -> None:
        """export_json should create parent directories if they do not exist."""
        metrics = AgentMetrics(
            session_id="test-session",
            agent_type="reasoning",
            model="gpt-4o",
        )

        filepath = tmp_path / "nested" / "dir" / "metrics.json"
        await metrics.export_json(filepath)

        assert filepath.exists()
        data = json.loads(filepath.read_text())
        assert data["session_id"] == "test-session"

    @pytest.mark.asyncio
    async def test_export_json_empty_metrics(self, tmp_path: Path) -> None:
        """export_json should handle metrics with no steps or tools."""
        metrics = AgentMetrics(
            session_id="empty-session",
            agent_type="router",
            model="gpt-4o-mini",
        )

        filepath = tmp_path / "empty_metrics.json"
        await metrics.export_json(filepath)

        data = json.loads(filepath.read_text())
        assert data["session_id"] == "empty-session"
        assert data["total_tokens"] == 0
        assert data["tool_calls"] == []
        assert data["steps"] == []
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_export_json_with_errors(self, tmp_path: Path) -> None:
        """export_json should include recorded errors."""
        metrics = AgentMetrics(
            session_id="error-session",
            agent_type="reasoning",
            model="gpt-4o",
        )
        metrics.record_error("timeout")
        metrics.record_error("rate_limit")

        filepath = tmp_path / "error_metrics.json"
        await metrics.export_json(filepath)

        data = json.loads(filepath.read_text())
        assert data["errors"] == ["timeout", "rate_limit"]
