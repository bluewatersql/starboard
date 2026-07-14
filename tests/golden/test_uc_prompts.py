# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden tests for Unity Catalog (UC) prompts.

These tests use syrupy snapshots to detect prompt regressions. When prompts
change (intentionally), run `pytest --snapshot-update` to update snapshots.

Test Coverage:
    - System prompt version tracking
    - Table analysis workflow prompt
    - Lineage investigation prompt
    - Policy audit workflow prompt
    - Storage optimization prompt
    - Schema comparison workflow prompt
    - Cost attribution workflow prompt
    - Prompt structure and key sections
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard.prompts.factories import build_uc_prompt
from starboard.prompts.uc import PROMPT_VERSION, UC_SYSTEM_PROMPT
from syrupy.assertion import SnapshotAssertion


class TestUCPromptSnapshots:
    """Golden tests for UC prompts using syrupy."""

    def test_prompt_version(self, snapshot: SnapshotAssertion) -> None:
        """Ensure prompt version is tracked and stable."""
        assert snapshot == PROMPT_VERSION

    def test_raw_system_prompt_unchanged(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Raw UC system prompt template."""
        # Snapshot the raw template (before variable substitution)
        # This catches any structural changes to the prompt
        assert snapshot == UC_SYSTEM_PROMPT

    def test_table_analysis_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for basic table analysis workflow."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Analyze table structure, schema, and storage health",
            budget_remaining=25_000,
        )
        assert snapshot == prompt

    def test_lineage_investigation_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for lineage investigation workflow."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Trace data lineage and understand upstream/downstream dependencies",
            budget_remaining=30_000,
        )
        assert snapshot == prompt

    def test_policy_audit_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for policy audit workflow."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Audit access policies, grants, and security compliance",
            budget_remaining=20_000,
        )
        assert snapshot == prompt

    def test_storage_optimization_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for storage optimization workflow."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Recommend OPTIMIZE, VACUUM, and clustering strategies",
            budget_remaining=25_000,
        )
        assert snapshot == prompt

    def test_schema_comparison_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for schema comparison workflow."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Compare table schemas and assess migration impact",
            budget_remaining=25_000,
        )
        assert snapshot == prompt

    def test_cost_attribution_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for cost attribution workflow."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Attribute compute and storage costs to specific tables",
            budget_remaining=25_000,
        )
        assert snapshot == prompt

    def test_offline_mode_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt with offline mode (limited capabilities)."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.OFFLINE,
            goal="Analyze table metadata without SDK access",
            budget_remaining=15_000,
        )
        assert snapshot == prompt

    def test_diagnostic_mode_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt with diagnostic mode."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.DIAGNOSTIC,
            goal="Diagnose schema drift and table health issues",
            budget_remaining=25_000,
        )
        assert snapshot == prompt

    def test_low_budget_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt with constrained token budget."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Quick table health check",
            budget_remaining=5_000,
        )
        assert snapshot == prompt

    def test_high_budget_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt with generous token budget."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Comprehensive UC governance audit",
            budget_remaining=100_000,
        )
        assert snapshot == prompt

    def test_default_goal_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt with empty goal (uses default)."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="",  # Empty goal triggers default
            budget_remaining=25_000,
        )
        assert snapshot == prompt


class TestUCPromptStructure:
    """Structural tests for UC prompts (non-snapshot)."""

    def test_prompt_contains_core_tools(self) -> None:
        """Verify prompt mentions core UC tools."""
        core_tools = [
            "list_uc_assets",
            "get_table_metadata",
            "get_table_history",
            "get_table_lineage",
            "discover_tables",
        ]
        for tool in core_tools:
            assert tool in UC_SYSTEM_PROMPT, f"Core tool '{tool}' not in prompt"

    def test_prompt_contains_utility_tools(self) -> None:
        """Verify prompt mentions utility tools."""
        utility_tools = ["request_user_input", "complete"]
        for tool in utility_tools:
            assert tool in UC_SYSTEM_PROMPT, f"Utility tool '{tool}' not in prompt"

    def test_prompt_contains_required_sections(self) -> None:
        """Verify prompt contains all required sections."""
        required_sections = [
            "## Tools Available",
            "## Workflows",
            "## Reasoning Output",
            "## Focus Areas",
            "## Output Format",
            "## Error Handling",
            "## Ambiguity Handling",
        ]
        for section in required_sections:
            assert section in UC_SYSTEM_PROMPT, f"Section '{section}' not in prompt"

    def test_prompt_contains_workflow_types(self) -> None:
        """Verify prompt contains core workflow patterns."""
        workflows = [
            "Discovery & Exploration",
            "Table Analysis & Optimization",
            "Lineage & Dependencies",
        ]
        for workflow in workflows:
            assert workflow in UC_SYSTEM_PROMPT, f"Workflow '{workflow}' not in prompt"

    def test_prompt_contains_format_placeholders(self) -> None:
        """Verify prompt contains required format placeholders."""
        placeholders = ["{token_budget:,}", "{mode}", "{goal}"]
        for placeholder in placeholders:
            assert placeholder in UC_SYSTEM_PROMPT, (
                f"Placeholder '{placeholder}' missing"
            )

    def test_prompt_contains_error_handling_guidance(self) -> None:
        """Verify prompt has error handling guidance."""
        error_keywords = [
            "When tools fail",
            "DON'T retry repeatedly",
            "DO call 'complete'",
            "tool failures",
        ]
        for keyword in error_keywords:
            assert keyword in UC_SYSTEM_PROMPT, f"Error guidance '{keyword}' missing"

    def test_prompt_contains_ambiguity_handling(self) -> None:
        """Verify prompt has ambiguity handling guidance."""
        ambiguity_keywords = [
            "multiple tables",
            "Do NOT guess",
            "request_user_input",
            "numbered options",
        ]
        for keyword in ambiguity_keywords:
            assert keyword in UC_SYSTEM_PROMPT, (
                f"Ambiguity guidance '{keyword}' missing"
            )

    def test_prompt_contains_output_format_categories(self) -> None:
        """Verify prompt has correct output categories."""
        categories = ["SCHEMA", "LINEAGE", "POLICY", "STORAGE", "DATA"]
        for category in categories:
            assert category in UC_SYSTEM_PROMPT, f"Category '{category}' not in prompt"

    def test_prompt_contains_next_steps_structure(self) -> None:
        """Verify prompt documents interactive next steps structure."""
        next_step_elements = [
            "next_steps",
            "action_type",
            "target_agent",
            "tool_name",
            "parameters",
        ]
        for element in next_step_elements:
            assert element in UC_SYSTEM_PROMPT, (
                f"Next steps element '{element}' missing"
            )

    def test_formatted_prompt_substitutes_variables(self) -> None:
        """Verify format variables are properly substituted."""
        prompt = build_uc_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Test goal",
            budget_remaining=10_000,
        )
        # Check substitutions happened
        assert "10,000 tokens" in prompt
        assert "online" in prompt.lower()
        assert "Test goal" in prompt
        # Check no unsubstituted placeholders remain
        assert "{token_budget" not in prompt
        assert "{mode}" not in prompt
        assert "{goal}" not in prompt


class TestUCPromptCompatibility:
    """Tests for backward compatibility and integration."""

    def test_legacy_tool_mentions_present(self) -> None:
        """Verify core tools are mentioned in prompt."""
        # Tool names have been standardized to get_* prefix
        core_tools = [
            "get_table_metadata",
            "get_table_history",
            "discover_tables",
        ]
        for tool in core_tools:
            assert tool in UC_SYSTEM_PROMPT, f"Core tool '{tool}' not in prompt"

    def test_prompt_mentions_parallelization(self) -> None:
        """Verify parallelization guidance is present."""
        assert "PARALLEL" in UC_SYSTEM_PROMPT
        assert "parallel" in UC_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_parallel_calls(self) -> None:
        """Verify parallel call guidance is present."""
        assert "PARALLEL" in UC_SYSTEM_PROMPT

    def test_version_follows_semver(self) -> None:
        """Verify prompt version follows semantic versioning."""
        parts = PROMPT_VERSION.split(".")
        assert len(parts) == 3, "Version must be MAJOR.MINOR.PATCH"
        for part in parts:
            assert part.isdigit(), f"Version part '{part}' must be numeric"


@pytest.mark.parametrize(
    "mode",
    [
        OptimizationMode.ONLINE,
        OptimizationMode.OFFLINE,
        OptimizationMode.DIAGNOSTIC,
    ],
)
def test_all_modes_produce_valid_prompts(mode: OptimizationMode) -> None:
    """Verify all optimization modes produce valid prompts."""
    prompt = build_uc_prompt(
        mode=mode,
        goal="Test all modes",
        budget_remaining=10_000,
    )
    assert len(prompt) > 1000, "Prompt should be substantial"
    assert "Unity Catalog" in prompt
    assert mode.value in prompt.lower()
