"""Tests for diagnostic tool call governance."""

import pytest
from starboard_server.tools.domain.diagnostic.tool_governance import (
    ToolGovernance,
    ToolPriority,
    ToolRequest,
)


class TestToolPriority:
    """Tests for ToolPriority enum."""

    def test_priority_ordering(self) -> None:
        """Should have correct priority ordering (critical < high < medium < low)."""
        # Use the __lt__ method for proper ordering
        assert ToolPriority.CRITICAL < ToolPriority.HIGH
        assert ToolPriority.HIGH < ToolPriority.MEDIUM
        assert ToolPriority.MEDIUM < ToolPriority.LOW

    def test_all_priorities_defined(self) -> None:
        """Should have all expected priority levels."""
        expected = {"critical", "high", "medium", "low"}
        actual = {p.value for p in ToolPriority}
        assert expected == actual


class TestToolRequest:
    """Tests for ToolRequest dataclass."""

    def test_create_tool_request(self) -> None:
        """Should create a valid tool request."""
        request = ToolRequest(
            tool_name="get_run_output",
            priority=ToolPriority.HIGH,
            estimated_tokens=1000,
            rationale="Need job run details to confirm OOM",
        )
        assert request.tool_name == "get_run_output"
        assert request.priority == ToolPriority.HIGH
        assert request.estimated_tokens == 1000

    def test_tool_request_with_args(self) -> None:
        """Should create request with tool arguments."""
        request = ToolRequest(
            tool_name="get_cluster_events",
            priority=ToolPriority.MEDIUM,
            estimated_tokens=500,
            rationale="Check for cluster events",
            tool_args={"cluster_id": "0123-456789-abc"},
        )
        assert request.tool_args["cluster_id"] == "0123-456789-abc"


class TestToolGovernance:
    """Tests for ToolGovernance class."""

    @pytest.fixture
    def governance(self) -> ToolGovernance:
        """Create a ToolGovernance instance with default limits."""
        return ToolGovernance()

    @pytest.fixture
    def governance_strict(self) -> ToolGovernance:
        """Create a ToolGovernance with strict limits."""
        return ToolGovernance(max_tools_per_turn=3, token_budget=2000)

    def test_default_limits(self, governance: ToolGovernance) -> None:
        """Should have sensible default limits."""
        assert governance.max_tools_per_turn == 6
        assert governance.token_budget == 8000

    def test_approve_single_request(self, governance: ToolGovernance) -> None:
        """Should approve a single valid request."""
        requests = [
            ToolRequest(
                tool_name="get_run_output",
                priority=ToolPriority.HIGH,
                estimated_tokens=1000,
                rationale="Confirm failure details",
            )
        ]
        approved = governance.approve_requests(requests)
        assert len(approved) == 1
        assert approved[0].tool_name == "get_run_output"

    def test_enforce_max_tools_limit(self, governance_strict: ToolGovernance) -> None:
        """Should enforce maximum tools per turn limit."""
        requests = [
            ToolRequest(f"tool_{i}", ToolPriority.MEDIUM, 100, f"Reason {i}")
            for i in range(5)
        ]
        approved = governance_strict.approve_requests(requests)
        assert len(approved) == 3  # Limited to max_tools_per_turn

    def test_enforce_token_budget(self, governance_strict: ToolGovernance) -> None:
        """Should enforce token budget limit."""
        requests = [
            ToolRequest("tool_1", ToolPriority.HIGH, 1000, "Reason 1"),
            ToolRequest("tool_2", ToolPriority.HIGH, 1500, "Reason 2"),  # Total: 2500
            ToolRequest("tool_3", ToolPriority.HIGH, 1000, "Reason 3"),  # Would exceed
        ]
        approved = governance_strict.approve_requests(requests)
        # Should only approve first 2 (2500 tokens) since third would exceed 2000
        assert len(approved) <= 2

    def test_prioritize_critical_tools(self, governance_strict: ToolGovernance) -> None:
        """Should prioritize critical tools over lower priority."""
        requests = [
            ToolRequest("low_1", ToolPriority.LOW, 100, "Low priority 1"),
            ToolRequest("critical_1", ToolPriority.CRITICAL, 100, "Critical"),
            ToolRequest("low_2", ToolPriority.LOW, 100, "Low priority 2"),
            ToolRequest("high_1", ToolPriority.HIGH, 100, "High priority"),
            ToolRequest("low_3", ToolPriority.LOW, 100, "Low priority 3"),
        ]
        approved = governance_strict.approve_requests(requests)
        assert len(approved) == 3
        # Critical and high should be approved before low
        approved_names = [r.tool_name for r in approved]
        assert "critical_1" in approved_names
        assert "high_1" in approved_names

    def test_preserve_order_within_priority(self, governance: ToolGovernance) -> None:
        """Should preserve request order within same priority level."""
        requests = [
            ToolRequest("first", ToolPriority.HIGH, 100, "First high"),
            ToolRequest("second", ToolPriority.HIGH, 100, "Second high"),
            ToolRequest("third", ToolPriority.HIGH, 100, "Third high"),
        ]
        approved = governance.approve_requests(requests)
        approved_names = [r.tool_name for r in approved]
        assert approved_names == ["first", "second", "third"]

    def test_empty_requests(self, governance: ToolGovernance) -> None:
        """Should handle empty request list."""
        approved = governance.approve_requests([])
        assert approved == []

    def test_track_usage(self, governance: ToolGovernance) -> None:
        """Should track tool usage for the turn."""
        requests = [
            ToolRequest("tool_1", ToolPriority.HIGH, 500, "Reason 1"),
            ToolRequest("tool_2", ToolPriority.MEDIUM, 300, "Reason 2"),
        ]
        governance.approve_requests(requests)

        # Check usage stats
        usage = governance.get_usage_stats()
        assert usage["tools_approved"] == 2
        assert usage["tokens_allocated"] == 800
        assert usage["tools_remaining"] == 4
        assert usage["budget_remaining"] == 7200

    def test_reject_over_budget_tools(self, governance_strict: ToolGovernance) -> None:
        """Should reject individual tools that exceed remaining budget."""
        requests = [
            ToolRequest("small", ToolPriority.HIGH, 500, "Small tool"),
            ToolRequest("huge", ToolPriority.CRITICAL, 5000, "Exceeds budget"),
            ToolRequest("medium", ToolPriority.HIGH, 1000, "Medium tool"),
        ]
        approved = governance_strict.approve_requests(requests)
        approved_names = [r.tool_name for r in approved]
        # The huge tool should be rejected even though it's critical
        assert "huge" not in approved_names
        assert "small" in approved_names
        assert "medium" in approved_names

    def test_reset_for_new_turn(self, governance: ToolGovernance) -> None:
        """Should be able to reset for a new turn."""
        requests = [
            ToolRequest("tool_1", ToolPriority.HIGH, 1000, "Reason"),
        ]
        governance.approve_requests(requests)
        assert governance.get_usage_stats()["tools_approved"] == 1

        governance.reset()
        assert governance.get_usage_stats()["tools_approved"] == 0
        assert governance.get_usage_stats()["tokens_allocated"] == 0


class TestToolPriorityAssignment:
    """Tests for automatic priority assignment based on tool type."""

    @pytest.fixture
    def governance(self) -> ToolGovernance:
        return ToolGovernance()

    def test_get_default_priority_for_run_output(
        self, governance: ToolGovernance
    ) -> None:
        """get_run_output should have HIGH priority (key diagnostic tool)."""
        priority = governance.get_default_priority("get_run_output")
        assert priority == ToolPriority.HIGH

    def test_get_default_priority_for_cluster_events(
        self, governance: ToolGovernance
    ) -> None:
        """get_cluster_events should have MEDIUM priority."""
        priority = governance.get_default_priority("get_cluster_events")
        assert priority == ToolPriority.MEDIUM

    def test_get_default_priority_for_unknown_tool(
        self, governance: ToolGovernance
    ) -> None:
        """Unknown tools should have LOW priority."""
        priority = governance.get_default_priority("unknown_tool")
        assert priority == ToolPriority.LOW

    @pytest.mark.parametrize(
        "tool_name,expected_priority",
        [
            ("get_run_output", ToolPriority.HIGH),
            ("get_job_config", ToolPriority.MEDIUM),
            ("analyze_job_history", ToolPriority.MEDIUM),
            ("get_cluster_events", ToolPriority.MEDIUM),
            ("get_spark_logs", ToolPriority.MEDIUM),
            ("resolve_job", ToolPriority.HIGH),
        ],
    )
    def test_diagnostic_tool_priorities(
        self,
        governance: ToolGovernance,
        tool_name: str,
        expected_priority: ToolPriority,
    ) -> None:
        """Should assign appropriate priorities to diagnostic tools."""
        priority = governance.get_default_priority(tool_name)
        assert priority == expected_priority


class TestGovernanceReporting:
    """Tests for governance decision reporting."""

    @pytest.fixture
    def governance(self) -> ToolGovernance:
        return ToolGovernance(max_tools_per_turn=3, token_budget=1000)

    def test_report_includes_approved(self, governance: ToolGovernance) -> None:
        """Report should include approved tools."""
        requests = [
            ToolRequest("tool_1", ToolPriority.HIGH, 200, "Reason 1"),
            ToolRequest("tool_2", ToolPriority.MEDIUM, 200, "Reason 2"),
        ]
        governance.approve_requests(requests)
        report = governance.get_decision_report()

        assert len(report["approved"]) == 2
        assert report["approved"][0]["tool_name"] == "tool_1"

    def test_report_includes_rejected(self, governance: ToolGovernance) -> None:
        """Report should include rejected tools with reasons."""
        requests = [
            ToolRequest("tool_1", ToolPriority.HIGH, 500, "Reason 1"),
            ToolRequest("tool_2", ToolPriority.HIGH, 500, "Reason 2"),
            ToolRequest("tool_3", ToolPriority.HIGH, 500, "Reason 3"),  # Exceeds budget
            ToolRequest("tool_4", ToolPriority.HIGH, 100, "Reason 4"),  # Exceeds count
        ]
        governance.approve_requests(requests)
        report = governance.get_decision_report()

        assert len(report["rejected"]) >= 1
        # Should have rejection reasons
        for rejected in report["rejected"]:
            assert "reason" in rejected
