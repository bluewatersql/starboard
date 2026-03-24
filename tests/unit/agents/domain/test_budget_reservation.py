"""
Unit Tests: Budget Reservation

Tests for finalization budget reservation to guarantee valid completion
even when approaching token budget limits.
"""

import pytest


def _create_test_state(
    budget_remaining: int,
    current_step: int = 1,
    completed: bool = False,
    final_output: dict | None = None,
):
    """Create a minimal AgentState for testing."""
    from starboard_server.agents.state.agent_state import (
        AgentState,
        Message,
        WorkingMemory,
    )

    return AgentState(
        user_id="test_user",
        conversation_history=(
            Message(role="system", content="You are a test agent"),
            Message(role="user", content="Test request"),
        ),
        working_memory=WorkingMemory(),
        current_step=current_step,
        goal="Test goal",
        mode="ONLINE",
        context={},
        budget_remaining=budget_remaining,
        completed=completed,
        final_output=final_output,
    )


class TestFinalizationBudgetConstant:
    """Tests for FINALIZATION_BUDGET constant."""

    def test_finalization_budget_constant_defined(self) -> None:
        """FINALIZATION_BUDGET constant exists."""
        from starboard_server.agents.domain.domain_agent import FINALIZATION_BUDGET

        assert FINALIZATION_BUDGET is not None
        assert isinstance(FINALIZATION_BUDGET, int)

    def test_finalization_budget_reasonable_minimum(self) -> None:
        """FINALIZATION_BUDGET is at least 1000 tokens."""
        from starboard_server.agents.domain.domain_agent import FINALIZATION_BUDGET

        # Need enough for complete tool to generate structured output
        assert FINALIZATION_BUDGET >= 1000

    def test_finalization_budget_reasonable_maximum(self) -> None:
        """FINALIZATION_BUDGET is at most 5000 tokens."""
        from starboard_server.agents.domain.domain_agent import FINALIZATION_BUDGET

        # Shouldn't be so large that it wastes budget
        assert FINALIZATION_BUDGET <= 5000


class TestShouldContinueReasoning:
    """Tests for _should_continue_reasoning function."""

    def test_should_continue_respects_finalization_budget(self) -> None:
        """Reasoning stops when only finalization budget remains."""
        from starboard_server.agents.domain.domain_agent import (
            FINALIZATION_BUDGET,
            _should_continue_reasoning,
        )

        # State with budget exactly at threshold
        state = _create_test_state(budget_remaining=FINALIZATION_BUDGET)

        # Should NOT continue - need to reserve budget for completion
        assert _should_continue_reasoning(state, max_steps=15) is False

    def test_reasoning_continues_with_sufficient_budget(self) -> None:
        """Reasoning continues when budget > FINALIZATION_BUDGET."""
        from starboard_server.agents.domain.domain_agent import (
            FINALIZATION_BUDGET,
            _should_continue_reasoning,
        )

        # State with plenty of budget
        state = _create_test_state(budget_remaining=FINALIZATION_BUDGET + 5000)

        # Should continue - have budget for reasoning AND completion
        assert _should_continue_reasoning(state, max_steps=15) is True

    def test_reasoning_stops_when_completed(self) -> None:
        """Reasoning stops when state.completed is True."""
        from starboard_server.agents.domain.domain_agent import (
            FINALIZATION_BUDGET,
            _should_continue_reasoning,
        )

        state = _create_test_state(
            budget_remaining=FINALIZATION_BUDGET + 10000,
            completed=True,
            final_output={"summary": {"overview": "done"}},
        )

        assert _should_continue_reasoning(state, max_steps=15) is False

    def test_reasoning_stops_at_max_steps(self) -> None:
        """Reasoning stops when max_steps reached."""
        from starboard_server.agents.domain.domain_agent import (
            FINALIZATION_BUDGET,
            _should_continue_reasoning,
        )

        state = _create_test_state(
            budget_remaining=FINALIZATION_BUDGET + 10000,
            current_step=15,  # At max
        )

        assert _should_continue_reasoning(state, max_steps=15) is False

    def test_reasoning_continues_below_max_steps(self) -> None:
        """Reasoning continues when below max_steps."""
        from starboard_server.agents.domain.domain_agent import (
            FINALIZATION_BUDGET,
            _should_continue_reasoning,
        )

        state = _create_test_state(
            budget_remaining=FINALIZATION_BUDGET + 5000,
            current_step=5,  # Well below max
        )

        assert _should_continue_reasoning(state, max_steps=15) is True


class TestBudgetExhaustionBehavior:
    """Tests for behavior when budget is exhausted."""

    def test_budget_below_threshold_stops_reasoning(self) -> None:
        """When budget < FINALIZATION_BUDGET, reasoning stops."""
        from starboard_server.agents.domain.domain_agent import (
            FINALIZATION_BUDGET,
            _should_continue_reasoning,
        )

        # State with budget below threshold
        state = _create_test_state(budget_remaining=FINALIZATION_BUDGET - 100)

        # Must stop to preserve completion budget
        assert _should_continue_reasoning(state, max_steps=15) is False

    def test_zero_budget_stops_reasoning(self) -> None:
        """When budget is 0, reasoning stops."""
        from starboard_server.agents.domain.domain_agent import (
            _should_continue_reasoning,
        )

        state = _create_test_state(budget_remaining=0)

        assert _should_continue_reasoning(state, max_steps=15) is False

    def test_negative_budget_stops_reasoning(self) -> None:
        """When budget is negative (enforcement off), reasoning stops."""
        from starboard_server.agents.domain.domain_agent import (
            _should_continue_reasoning,
        )

        # Budget can go negative when enforce_budget=False
        state = _create_test_state(budget_remaining=-500)

        assert _should_continue_reasoning(state, max_steps=15) is False


class TestPartialReportGeneration:
    """Tests for partial report generation when budget is exhausted."""

    def test_partial_report_has_required_structure(self) -> None:
        """Partial report includes all required fields for UI rendering."""
        from unittest.mock import MagicMock

        from starboard_server.agents.config.agent_config import AgentConfig
        from starboard_server.agents.domain.domain_agent import DomainAgent
        from starboard_server.agents.state.agent_state import WorkingMemory

        # Create minimal agent setup
        mock_llm = MagicMock()
        mock_registry = MagicMock()
        config = AgentConfig(domain="job", model="test-model")

        agent = DomainAgent(
            llm_client=mock_llm,
            tool_registry=mock_registry,
            config=config,
            enable_metrics=False,
        )

        # Create state with tools used
        working_memory = WorkingMemory()
        working_memory = working_memory.add_tool_used("resolve_job")
        working_memory = working_memory.add_tool_used("get_job_config")

        state = _create_test_state(
            budget_remaining=1500,
            current_step=4,
        )
        # Replace working memory
        from dataclasses import replace

        state = replace(state, working_memory=working_memory)

        # Generate partial report
        report = agent._generate_partial_report(state)

        # Verify required fields exist
        assert "report_type" in report
        assert "summary" in report
        assert "analysis" in report
        assert "next_steps" in report

        # Verify summary structure
        assert "overview" in report["summary"]
        assert "current_state" in report["summary"]

        # Verify next_steps are valid
        assert len(report["next_steps"]) >= 1
        for step in report["next_steps"]:
            assert "id" in step
            assert "number" in step
            assert "title" in step
            assert "action_type" in step

    def test_partial_report_includes_tools_used(self) -> None:
        """Partial report summary mentions tools that were used."""
        from dataclasses import replace
        from unittest.mock import MagicMock

        from starboard_server.agents.config.agent_config import AgentConfig
        from starboard_server.agents.domain.domain_agent import DomainAgent
        from starboard_server.agents.state.agent_state import WorkingMemory

        mock_llm = MagicMock()
        mock_registry = MagicMock()
        config = AgentConfig(domain="query", model="test-model")

        agent = DomainAgent(
            llm_client=mock_llm,
            tool_registry=mock_registry,
            config=config,
            enable_metrics=False,
        )

        # Create state with specific tools used
        working_memory = WorkingMemory()
        working_memory = working_memory.add_tool_used("resolve_query")
        working_memory = working_memory.add_tool_used("analyze_query_plan")

        state = _create_test_state(budget_remaining=1000)
        state = replace(state, working_memory=working_memory)

        report = agent._generate_partial_report(state)

        # Check tools are mentioned in summary
        overview = report["summary"]["overview"]
        assert "resolve_query" in overview or "analyze_query_plan" in overview

    def test_partial_report_has_budget_exhausted_flag(self) -> None:
        """Partial report includes budget_exhausted flag for UI warning banner."""
        from unittest.mock import MagicMock

        from starboard_server.agents.config.agent_config import AgentConfig
        from starboard_server.agents.domain.domain_agent import DomainAgent

        mock_llm = MagicMock()
        mock_registry = MagicMock()
        config = AgentConfig(domain="job", model="test-model")

        agent = DomainAgent(
            llm_client=mock_llm,
            tool_registry=mock_registry,
            config=config,
            enable_metrics=False,
        )

        state = _create_test_state(budget_remaining=1500)
        report = agent._generate_partial_report(state)

        # budget_exhausted flag is used by frontend to show warning banner
        assert report.get("budget_exhausted") is True


class TestOutputBuilderBudgetStatus:
    """Tests for OutputBuilder status detection with budget exhaustion."""

    def test_status_budget_exceeded_from_flag(self) -> None:
        """Status is budget_exceeded when budget_exhausted flag is set."""
        from starboard_server.agents.config.agent_config import AgentConfig
        from starboard_server.agents.domain.output_builder import OutputBuilder

        config = AgentConfig(domain="job", model="test-model")
        builder = OutputBuilder(config=config)

        state = _create_test_state(
            budget_remaining=1500,
            completed=True,
            final_output={"budget_exhausted": True, "summary": {"overview": "partial"}},
        )

        status = builder._determine_status(state)
        assert status == "budget_exceeded"

    def test_status_budget_exceeded_from_threshold(self) -> None:
        """Status is budget_exceeded when below finalization threshold."""
        from starboard_server.agents.config.agent_config import AgentConfig
        from starboard_server.agents.domain.domain_agent import FINALIZATION_BUDGET
        from starboard_server.agents.domain.output_builder import OutputBuilder

        config = AgentConfig(domain="job", model="test-model")
        builder = OutputBuilder(config=config)

        state = _create_test_state(
            budget_remaining=FINALIZATION_BUDGET - 100,
            completed=False,
        )

        status = builder._determine_status(state)
        assert status == "budget_exceeded"

    def test_status_success_when_completed_normally(self) -> None:
        """Status is success when completed without budget issues."""
        from starboard_server.agents.config.agent_config import AgentConfig
        from starboard_server.agents.domain.domain_agent import FINALIZATION_BUDGET
        from starboard_server.agents.domain.output_builder import OutputBuilder

        config = AgentConfig(domain="job", model="test-model")
        builder = OutputBuilder(config=config)

        state = _create_test_state(
            budget_remaining=FINALIZATION_BUDGET + 5000,
            completed=True,
            final_output={"summary": {"overview": "done"}, "next_steps": []},
        )

        status = builder._determine_status(state)
        assert status == "success"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
