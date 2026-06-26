# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Contract Tests: AgentOutput Schema Shape

These tests lock the current AgentOutput schema shape to prevent accidental
breaking changes. Run these tests before modifying agent output structures.

Contract coverage:
- AgentOutput field types and allowed values
- Status values (success, error, budget_exceeded, max_steps_reached)
- complete_report optionality and structure expectations
- next_steps structure (NextStepOption serialization)
- Metrics fields (tokens_used, cost_usd, duration_seconds, steps_taken)
- SSE output structure via FinalOutputEvent.to_sse_data()

These tests should fail loudly if schema changes occur, alerting developers
to update dependent consumers (frontend, CLI).
"""

import pytest
from starboard_server.agents.events.user_events import FinalOutputEvent
from starboard_server.agents.state.agent_state import AgentOutput
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)


class TestAgentOutputContract:
    """Contract tests that lock current AgentOutput shape."""

    # =========================================================================
    # Status Values Contract
    # =========================================================================

    @pytest.mark.parametrize(
        "status",
        ["success", "error", "budget_exceeded", "max_steps_reached"],
    )
    def test_valid_status_values(self, status: str) -> None:
        """Status must be one of the documented values.

        These are the ONLY valid status values. Adding new values requires
        updating all consumers (frontend, CLI).
        """
        output = AgentOutput(
            status=status,  # type: ignore
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            error_message="Error" if status == "error" else None,
        )
        assert output.status == status

    def test_status_is_required(self) -> None:
        """AgentOutput must have a status field."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
        )
        assert hasattr(output, "status")
        assert output.status is not None

    # =========================================================================
    # complete_report Contract
    # =========================================================================

    def test_complete_report_can_be_none(self) -> None:
        """complete_report is optional and can be None.

        Frontend handles this by showing fallback UI.
        """
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            complete_report=None,
        )
        assert output.complete_report is None

    def test_complete_report_can_be_dict(self) -> None:
        """complete_report can be any dict when present.

        NOTE: This is the weak typing we're hardening - complete_report
        is dict[str, Any] | None with no runtime validation.
        """
        report = {
            "report_type": "advisor",
            "summary": {"overview": "Test analysis"},
            "analysis": {"findings": []},
            "next_steps": [],
        }
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            complete_report=report,
        )
        assert output.complete_report == report
        assert output.complete_report["report_type"] == "advisor"

    def test_complete_report_expected_structure_advisor(self) -> None:
        """Document expected structure for advisor reports.

        Frontend expects these fields for AdvisorReportBubble:
        - report_type: "advisor"
        - summary: {overview, current_state}
        - analysis: {findings: [...]}
        - next_steps: [...]
        """
        advisor_report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Query analysis complete",
                "current_state": {
                    "cloud_provider": "aws",
                    "runtime_version": "14.3",
                },
            },
            "analysis": {
                "findings": [
                    {
                        "id": "finding_1",
                        "category": "QUERY",
                        "title": "Expensive join",
                        "recommendation": "Add index",
                        "impact_estimate": {"level": "high"},
                        "effort": {"level": "low"},
                        "rank": 1,
                    }
                ],
            },
            "next_steps": [
                {
                    "id": "step_1",
                    "number": 1,
                    "title": "View query plan",
                    "action_type": "continue",
                }
            ],
        }
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            complete_report=advisor_report,
        )
        assert output.complete_report["report_type"] == "advisor"
        assert "summary" in output.complete_report
        assert "analysis" in output.complete_report

    def test_complete_report_expected_structure_analytics(self) -> None:
        """Document expected structure for analytics reports.

        Frontend expects these fields for AnalyticsReportBubble:
        - report_type: "analytics"
        - summary: {overview}
        - findings: [...]
        - cost_summary: {...}
        - visualization: {...} (optional)
        """
        analytics_report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Cost analysis complete",
            },
            "findings": [
                {
                    "id": "finding_1",
                    "category": "COST_OPTIMIZATION",
                    "title": "Unused warehouse",
                    "recommendation": "Shut down",
                    "cost_impact": {"monthly_savings_usd": 500},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "total_monthly_cost_usd": 5000,
                "potential_savings_usd": 500,
            },
            "next_steps": [],
        }
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            complete_report=analytics_report,
        )
        assert output.complete_report["report_type"] == "analytics"
        assert "findings" in output.complete_report
        assert "cost_summary" in output.complete_report

    def test_complete_report_expected_structure_compute(self) -> None:
        """Document expected structure for compute reports.

        Frontend expects these fields for WarehouseReportBubble:
        - report_type: "warehouse"
        - summary: {overview}
        - portfolio_summary: {...} (optional)
        - health_metrics: {...} (optional)
        - warehouses: [...] (optional)
        """
        warehouse_report = {
            "report_type": "warehouse",
            "summary": {
                "overview": "Warehouse analysis complete",
            },
            "portfolio_summary": {
                "total_warehouses": 5,
                "active_warehouses": 3,
            },
            "next_steps": [],
        }
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            complete_report=warehouse_report,
        )
        assert output.complete_report["report_type"] == "warehouse"

    # =========================================================================
    # next_steps Contract
    # =========================================================================

    def test_next_steps_can_be_none(self) -> None:
        """next_steps is optional and can be None."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            next_steps=None,
        )
        assert output.next_steps is None

    def test_next_steps_accepts_next_step_option_objects(self) -> None:
        """next_steps can be a list of NextStepOption objects."""
        options = [
            NextStepOption(
                id="step_1",
                number=1,
                title="Continue analysis",
                description="Get more details",
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
            NextStepOption(
                id="step_2",
                number=2,
                title="Switch to cluster agent",
                description="Analyze cluster",
                action_type=ActionType.ROUTE,
                target_agent="cluster",
                tool_name=None,
                parameters={"cluster_id": "abc123"},
            ),
        ]
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            next_steps=options,
        )
        assert output.next_steps is not None
        assert len(output.next_steps) == 2
        assert output.next_steps[0].number == 1
        assert output.next_steps[1].number == 2

    def test_next_steps_max_nine_options(self) -> None:
        """next_steps should not exceed 9 options (UI constraint)."""
        options = [
            NextStepOption(
                id=f"step_{i}",
                number=i,
                title=f"Option {i}",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            )
            for i in range(1, 10)  # 1-9
        ]
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            next_steps=options,
        )
        assert len(output.next_steps) == 9

    def test_next_steps_exceeds_nine_raises(self) -> None:
        """next_steps with more than 9 options should raise ValueError."""
        options = [
            NextStepOption(
                id=f"step_{i}",
                number=i,
                title=f"Option {i}",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            )
            for i in range(1, 11)  # 1-10
        ]
        with pytest.raises(ValueError, match="next_steps must contain 1-9 options"):
            AgentOutput(
                status="success",
                recommendations=[],
                reasoning_trace=[],
                steps_taken=1,
                tools_used=[],
                tokens_used=100,
                cost_usd=0.01,
                duration_seconds=1.0,
                next_steps=options,
            )

    # =========================================================================
    # Metrics Contract
    # =========================================================================

    def test_metrics_fields_required(self) -> None:
        """Core metrics fields must be present."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=5,
            tools_used=["tool1", "tool2"],
            tokens_used=1500,
            cost_usd=0.025,
            duration_seconds=12.5,
        )
        assert output.steps_taken == 5
        assert output.tokens_used == 1500
        assert output.cost_usd == 0.025
        assert output.duration_seconds == 12.5
        assert output.tools_used == ["tool1", "tool2"]

    def test_metrics_non_negative_validation(self) -> None:
        """Metrics must be non-negative."""
        with pytest.raises(ValueError):
            AgentOutput(
                status="success",
                recommendations=[],
                reasoning_trace=[],
                steps_taken=-1,
                tools_used=[],
                tokens_used=100,
                cost_usd=0.01,
                duration_seconds=1.0,
            )

        with pytest.raises(ValueError):
            AgentOutput(
                status="success",
                recommendations=[],
                reasoning_trace=[],
                steps_taken=1,
                tools_used=[],
                tokens_used=-100,
                cost_usd=0.01,
                duration_seconds=1.0,
            )

    # =========================================================================
    # formatted_markdown Contract
    # =========================================================================

    def test_formatted_markdown_can_be_none(self) -> None:
        """formatted_markdown is optional and can be None."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            formatted_markdown=None,
        )
        assert output.formatted_markdown is None

    def test_formatted_markdown_can_be_string(self) -> None:
        """formatted_markdown can be a markdown string."""
        markdown = "## Analysis Report\n\nFindings:\n- Issue 1\n- Issue 2"
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            formatted_markdown=markdown,
        )
        assert output.formatted_markdown == markdown

    # =========================================================================
    # to_dict() Contract
    # =========================================================================

    def test_to_dict_contains_all_fields(self) -> None:
        """to_dict() must include all expected fields."""
        output = AgentOutput(
            status="success",
            recommendations=[{"title": "Test"}],
            reasoning_trace=[{"step": 1}],
            steps_taken=3,
            tools_used=["tool1"],
            tokens_used=500,
            cost_usd=0.005,
            duration_seconds=5.0,
            error_message=None,
            complete_report={"report_type": "advisor"},
            formatted_markdown="## Report",
        )

        result = output.to_dict()

        # Required top-level keys
        assert "status" in result
        assert "recommendations" in result
        assert "reasoning_trace" in result
        assert "steps_taken" in result
        assert "tools_used" in result
        assert "tokens_used" in result
        assert "cost_usd" in result
        assert "duration_seconds" in result
        assert "error_message" in result
        assert "complete_report" in result
        assert "formatted_markdown" in result

    def test_to_dict_next_steps_serialization(self) -> None:
        """to_dict() must serialize next_steps correctly."""
        options = [
            NextStepOption(
                id="step_1",
                number=1,
                title="Continue",
                description="Keep going",
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        ]
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            next_steps=options,
        )

        result = output.to_dict()

        assert "next_steps" in result
        assert len(result["next_steps"]) == 1
        assert result["next_steps"][0]["id"] == "step_1"
        assert result["next_steps"][0]["number"] == 1
        assert result["next_steps"][0]["title"] == "Continue"
        assert result["next_steps"][0]["action_type"] == "continue"


class TestFinalOutputEventContract:
    """Contract tests for FinalOutputEvent SSE shape."""

    def test_sse_data_structure(self) -> None:
        """SSE data must have expected top-level structure.

        Frontend expects:
        - message_id: string
        - output: {status, complete_report, next_steps, tokens_used, cost_usd, ...}
        - formatted_markdown: string | null
        """
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.5,
        )
        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(message_id="msg_test_123")

        # Top-level keys
        assert "message_id" in sse_data
        assert "output" in sse_data
        assert "formatted_markdown" in sse_data

        assert sse_data["message_id"] == "msg_test_123"

    def test_sse_output_nested_structure(self) -> None:
        """SSE output.{} must have expected nested structure.

        Frontend reads these fields from output:
        - status
        - complete_report
        - next_steps
        - tokens_used
        - cost_usd
        - duration_seconds
        - steps_taken
        """
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=3,
            tools_used=["tool1"],
            tokens_used=500,
            cost_usd=0.005,
            duration_seconds=5.0,
            complete_report={"report_type": "advisor"},
        )
        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(message_id="msg_test")

        output_data = sse_data["output"]

        # Required fields in output
        assert "status" in output_data
        assert "complete_report" in output_data
        assert "next_steps" in output_data
        assert "tokens_used" in output_data
        assert "cost_usd" in output_data
        assert "duration_seconds" in output_data
        assert "steps_taken" in output_data

        # Values
        assert output_data["status"] == "success"
        assert output_data["tokens_used"] == 500
        assert output_data["cost_usd"] == 0.005
        assert output_data["duration_seconds"] == 5.0
        assert output_data["steps_taken"] == 3

    def test_sse_all_status_values(self) -> None:
        """SSE must handle all status values."""
        for status in ["success", "error", "budget_exceeded", "max_steps_reached"]:
            output = AgentOutput(
                status=status,  # type: ignore
                recommendations=[],
                reasoning_trace=[],
                steps_taken=1,
                tools_used=[],
                tokens_used=100,
                cost_usd=0.01,
                duration_seconds=1.0,
                error_message="Test error" if status == "error" else None,
            )
            event = FinalOutputEvent(output=output)
            sse_data = event.to_sse_data(message_id="msg_test")

            assert sse_data["output"]["status"] == status

    def test_sse_complete_report_passthrough(self) -> None:
        """complete_report must be passed through to SSE unchanged."""
        report = {
            "report_type": "advisor",
            "summary": {"overview": "Test"},
            "analysis": {"findings": []},
        }
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            complete_report=report,
        )
        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(message_id="msg_test")

        assert sse_data["output"]["complete_report"]["report_type"] == "advisor"
        assert "summary" in sse_data["output"]["complete_report"]
        assert "analysis" in sse_data["output"]["complete_report"]

    def test_sse_next_steps_serialization(self) -> None:
        """next_steps must serialize correctly in SSE output."""
        options = [
            NextStepOption(
                id="step_1",
                number=1,
                title="Continue",
                description="Keep going",
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
            NextStepOption(
                id="step_2",
                number=2,
                title="Route",
                description="Go elsewhere",
                action_type=ActionType.ROUTE,
                target_agent="cluster",
                tool_name=None,
                parameters={"id": "123"},
            ),
        ]
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
            next_steps=options,
        )
        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(message_id="msg_test")

        next_steps = sse_data["output"]["next_steps"]
        assert len(next_steps) == 2

        # First option
        assert next_steps[0]["id"] == "step_1"
        assert next_steps[0]["number"] == 1
        assert next_steps[0]["title"] == "Continue"
        assert next_steps[0]["action_type"] == "continue"

        # Second option with routing
        assert next_steps[1]["id"] == "step_2"
        assert next_steps[1]["action_type"] == "route"
        assert next_steps[1]["target_agent"] == "cluster"
        assert next_steps[1]["parameters"] == {"id": "123"}


class TestNextStepOptionContract:
    """Contract tests for NextStepOption serialization."""

    def test_to_dict_all_fields(self) -> None:
        """to_dict must include all fields."""
        option = NextStepOption(
            id="opt_1",
            number=1,
            title="Test Option",
            description="A test option",
            action_type=ActionType.TOOL_CALL,
            target_agent="query",
            tool_name="analyze_query",
            parameters={"query_id": "abc123"},
        )

        result = option.to_dict()

        assert result["id"] == "opt_1"
        assert result["number"] == 1
        assert result["title"] == "Test Option"
        assert result["description"] == "A test option"
        assert result["action_type"] == "tool_call"
        assert result["target_agent"] == "query"
        assert result["tool_name"] == "analyze_query"
        assert result["parameters"] == {"query_id": "abc123"}

    def test_action_type_serialization(self) -> None:
        """ActionType enum must serialize to string value."""
        for action_type in ActionType:
            option = NextStepOption(
                id="opt_1",
                number=1,
                title="Test",
                description=None,
                action_type=action_type,
                target_agent=None,
                tool_name=None,
                parameters=None,
            )
            result = option.to_dict()

            # Must be string value, not enum
            assert result["action_type"] == action_type.value
            assert isinstance(result["action_type"], str)

    def test_from_dict_round_trip(self) -> None:
        """NextStepOption must round-trip through to_dict/from_dict."""
        original = NextStepOption(
            id="opt_1",
            number=1,
            title="Test",
            description="Desc",
            action_type=ActionType.ROUTE,
            target_agent="cluster",
            tool_name=None,
            parameters={"key": "value"},
        )

        data = original.to_dict()
        restored = NextStepOption.from_dict(data)

        assert restored.id == original.id
        assert restored.number == original.number
        assert restored.title == original.title
        assert restored.description == original.description
        assert restored.action_type == original.action_type
        assert restored.target_agent == original.target_agent
        assert restored.tool_name == original.tool_name
        assert restored.parameters == original.parameters


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
