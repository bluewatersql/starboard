"""
Golden tests for Router Agent prompts.

These tests use syrupy snapshots to detect prompt regressions. When prompts
change (intentionally), run `pytest --snapshot-update` to update snapshots.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.prompts.factories import build_router_prompt
from starboard_server.prompts.router.v1 import PROMPT_VERSION, ROUTER_SYSTEM_PROMPT
from syrupy.assertion import SnapshotAssertion


class TestRouterPromptSnapshots:
    """Golden tests for router prompts using syrupy."""

    def test_prompt_version(self, snapshot: SnapshotAssertion) -> None:
        """Ensure prompt version is tracked and stable."""
        assert snapshot == PROMPT_VERSION

    def test_raw_system_prompt_unchanged(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Raw router system prompt template."""
        assert snapshot == ROUTER_SYSTEM_PROMPT

    def test_online_mode_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for online mode."""
        prompt = build_router_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Route user request",
            budget_remaining=5_000,
        )
        assert snapshot == prompt


class TestRouterPromptStructure:
    """Structural tests for router prompts (non-snapshot)."""

    def test_prompt_mentions_domains(self) -> None:
        """Verify prompt mentions all routing domains."""
        domains = ["query", "job", "table", "compute", "diagnostic", "analytics"]
        for domain in domains:
            assert domain in ROUTER_SYSTEM_PROMPT, f"Domain '{domain}' not in prompt"

    def test_prompt_contains_tools(self) -> None:
        """Verify prompt mentions router tools."""
        tools = ["resolve_user_intent", "request_user_input", "complete"]
        for tool in tools:
            assert tool in ROUTER_SYSTEM_PROMPT, f"Tool '{tool}' not in prompt"

    def test_prompt_contains_workflow(self) -> None:
        """Verify prompt contains routing workflow."""
        assert "WORKFLOW" in ROUTER_SYSTEM_PROMPT


class TestRouterPromptCompatibility:
    """Tests for prompt compatibility."""

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
        prompt = build_router_prompt(
            mode=mode,
            goal="Test all modes",
            budget_remaining=5_000,
        )
        assert len(prompt) > 200, "Prompt should be substantial"
        assert "router" in prompt.lower() or "route" in prompt.lower()

    def test_version_is_semver(self) -> None:
        """Verify prompt version follows semantic versioning."""
        parts = PROMPT_VERSION.split(".")
        assert len(parts) == 3, "Version must be MAJOR.MINOR.PATCH"
