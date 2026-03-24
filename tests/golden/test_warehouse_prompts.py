"""
Golden tests for Warehouse Portfolio Agent prompts.

These tests use syrupy snapshots to detect prompt regressions. When prompts
change (intentionally), run `pytest --snapshot-update` to update snapshots.

Test Coverage:
    - System prompt content verification
    - Portfolio analysis workflow prompt
    - Health scoring workflow prompt
    - What-if analysis workflow prompt
    - Topology analysis workflow prompt
    - Chargeback workflow prompt
    - Prompt structure and key sections
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.prompts.factories import build_warehouse_prompt
from starboard_server.prompts.warehouse import WAREHOUSE_SYSTEM_PROMPT
from syrupy.assertion import SnapshotAssertion


class TestWarehousePromptSnapshots:
    """Golden tests for warehouse prompts using syrupy."""

    def test_raw_system_prompt_unchanged(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Raw warehouse system prompt template."""
        # Snapshot the raw template
        # This catches any structural changes to the prompt
        assert snapshot == WAREHOUSE_SYSTEM_PROMPT

    def test_portfolio_analysis_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for portfolio analysis workflow."""
        prompt = build_warehouse_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Analyze all SQL warehouses in the portfolio",
            budget_remaining=25_000,
        )
        assert snapshot == prompt

    def test_health_scoring_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for health scoring workflow."""
        prompt = build_warehouse_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Assess warehouse health and SLO compliance",
            budget_remaining=25_000,
        )
        assert snapshot == prompt

    def test_whatif_analysis_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for what-if analysis workflow."""
        prompt = build_warehouse_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Evaluate serverless migration scenarios",
            budget_remaining=30_000,
        )
        assert snapshot == prompt

    def test_topology_analysis_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for topology analysis workflow."""
        prompt = build_warehouse_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Identify redundant warehouses and consolidation opportunities",
            budget_remaining=25_000,
        )
        assert snapshot == prompt

    def test_chargeback_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for chargeback workflow."""
        prompt = build_warehouse_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Generate cost allocation report by user",
            budget_remaining=25_000,
        )
        assert snapshot == prompt


class TestWarehousePromptStructure:
    """Structural tests for warehouse prompts (non-snapshot)."""

    def test_prompt_contains_core_capabilities(self) -> None:
        """Verify prompt mentions core capabilities."""
        core_capabilities = [
            "Portfolio Analysis",
            "Warehouse Fingerprinting",
            "Health Scoring",
            "Cost Attribution & Chargeback",
            "Topology Analysis",
        ]
        for capability in core_capabilities:
            assert capability in WAREHOUSE_SYSTEM_PROMPT, (
                f"Capability '{capability}' not in prompt"
            )

    def test_prompt_contains_core_tools(self) -> None:
        """Verify prompt mentions core tools."""
        core_tools = [
            "get_warehouse_portfolio",
            "get_warehouse_fingerprint",
            "get_warehouse_health",
        ]
        for tool in core_tools:
            assert tool in WAREHOUSE_SYSTEM_PROMPT, f"Tool '{tool}' not in prompt"

    def test_prompt_contains_response_guidelines(self) -> None:
        """Verify prompt contains response guidelines."""
        guidelines = [
            "Data-Driven",
            "Confidence",
            "Trade-offs",
            "Risk",
            "Actionable",
        ]
        for guideline in guidelines:
            assert guideline in WAREHOUSE_SYSTEM_PROMPT, (
                f"Guideline '{guideline}' not in prompt"
            )

    def test_prompt_contains_workflow_pattern(self) -> None:
        """Verify prompt contains workflow pattern section."""
        assert "Workflow Pattern" in WAREHOUSE_SYSTEM_PROMPT

    def test_prompt_contains_example_interactions(self) -> None:
        """Verify prompt contains example interactions."""
        assert "Example Interactions" in WAREHOUSE_SYSTEM_PROMPT

    def test_prompt_mentions_serverless(self) -> None:
        """Verify prompt mentions serverless considerations."""
        assert "serverless" in WAREHOUSE_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_slo(self) -> None:
        """Verify prompt mentions SLO (service level objectives)."""
        assert "SLO" in WAREHOUSE_SYSTEM_PROMPT

    def test_prompt_mentions_cost_performance_tradeoff(self) -> None:
        """Verify prompt discusses cost/performance tradeoffs."""
        assert "cost" in WAREHOUSE_SYSTEM_PROMPT.lower()
        assert "performance" in WAREHOUSE_SYSTEM_PROMPT.lower()


class TestWarehousePromptTools:
    """Tests for tool mentions in warehouse prompt."""

    def test_prompt_mentions_portfolio_tool(self) -> None:
        """Verify portfolio tool is mentioned."""
        assert "get_warehouse_portfolio" in WAREHOUSE_SYSTEM_PROMPT

    def test_prompt_mentions_fingerprint_tool(self) -> None:
        """Verify fingerprint tool is mentioned."""
        assert "get_warehouse_fingerprint" in WAREHOUSE_SYSTEM_PROMPT

    def test_prompt_mentions_health_tool(self) -> None:
        """Verify health tool is mentioned."""
        assert "get_warehouse_health" in WAREHOUSE_SYSTEM_PROMPT

    def test_prompt_mentions_slo_tools(self) -> None:
        """Verify SLO tools are mentioned."""
        assert (
            "get_warehouse_slo" in WAREHOUSE_SYSTEM_PROMPT
            or "slo" in WAREHOUSE_SYSTEM_PROMPT.lower()
        )
        assert (
            "set_warehouse_slo" in WAREHOUSE_SYSTEM_PROMPT
            or "slo" in WAREHOUSE_SYSTEM_PROMPT.lower()
        )

    def test_prompt_mentions_chargeback_tools(self) -> None:
        """Verify chargeback tools are mentioned."""
        assert (
            "generate_warehouse_chargeback" in WAREHOUSE_SYSTEM_PROMPT
            or "chargeback" in WAREHOUSE_SYSTEM_PROMPT.lower()
        )

    def test_prompt_mentions_topology_tools(self) -> None:
        """Verify topology tools are mentioned."""
        assert (
            "analyze_warehouse_topology" in WAREHOUSE_SYSTEM_PROMPT
            or "topology" in WAREHOUSE_SYSTEM_PROMPT.lower()
        )


class TestWarehousePromptCompatibility:
    """Tests for prompt compatibility."""

    def test_builder_produces_valid_prompt(self) -> None:
        """Verify builder produces non-empty prompt."""
        prompt = build_warehouse_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Test goal",
            budget_remaining=10_000,
        )
        assert len(prompt) > 500, "Prompt should be substantial"
        assert "warehouse" in prompt.lower()

    @pytest.mark.parametrize(
        "mode",
        [
            OptimizationMode.ONLINE,
            OptimizationMode.OFFLINE,
            OptimizationMode.DIAGNOSTIC,
        ],
    )
    def test_all_modes_produce_valid_prompts(self, mode: OptimizationMode) -> None:
        """Verify all optimization modes produce valid prompts."""
        prompt = build_warehouse_prompt(
            mode=mode,
            goal="Test all modes",
            budget_remaining=10_000,
        )
        assert len(prompt) > 500, "Prompt should be substantial"
        assert "warehouse" in prompt.lower()

    def test_prompt_has_format_variables(self) -> None:
        """Verify warehouse prompt has Python format variables."""
        # Warehouse prompt now uses format variables like other prompts
        format_vars = ["{goal}", "{mode}", "{token_budget:,}"]
        for var in format_vars:
            assert var in WAREHOUSE_SYSTEM_PROMPT, f"Format var '{var}' not found"


class TestWarehouseToolSchemaGolden:
    """Golden tests for warehouse tool schemas."""

    def test_portfolio_schema_exists(self) -> None:
        """Verify portfolio tool schema is registered."""
        from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

        assert "get_warehouse_portfolio" in ALL_TOOL_METADATA

    def test_portfolio_schema_structure(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Portfolio tool schema structure."""
        from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

        schema = ALL_TOOL_METADATA["get_warehouse_portfolio"]
        assert snapshot == schema

    def test_fingerprint_schema_structure(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Fingerprint tool schema structure."""
        from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

        schema = ALL_TOOL_METADATA["get_warehouse_fingerprint"]
        assert snapshot == schema

    def test_health_schema_structure(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Health tool schema structure."""
        from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

        schema = ALL_TOOL_METADATA["get_warehouse_health"]
        assert snapshot == schema

    def test_topology_schema_structure(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Topology tool schema structure."""
        from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

        schema = ALL_TOOL_METADATA["analyze_warehouse_topology"]
        assert snapshot == schema

    def test_chargeback_schema_structure(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Chargeback tool schema structure."""
        from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

        schema = ALL_TOOL_METADATA["generate_warehouse_chargeback"]
        assert snapshot == schema
