# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden tests for Discovery Agent v2 prompts.

These tests use syrupy snapshots to detect prompt regressions. When prompts
change (intentionally), run `pytest --snapshot-update` to update snapshots.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.prompts.discovery.v2 import (
    DISCOVERY_SYSTEM_PROMPT,
    PROMPT_VERSION,
)
from starboard_server.prompts.factories import build_discovery_prompt
from syrupy.assertion import SnapshotAssertion


class TestDiscoveryV2PromptSnapshots:
    """Golden tests for discovery v2 prompts using syrupy."""

    def test_prompt_version(self, snapshot: SnapshotAssertion) -> None:
        """Ensure prompt version is tracked and stable."""
        assert snapshot == PROMPT_VERSION

    def test_raw_system_prompt_unchanged(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Raw discovery v2 system prompt template."""
        assert snapshot == DISCOVERY_SYSTEM_PROMPT

    def test_online_mode_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for online mode."""
        prompt = build_discovery_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Run a comprehensive workspace health assessment",
            budget_remaining=25_000,
        )
        assert snapshot == prompt


class TestDiscoveryV2PromptStructure:
    """Structural tests for discovery v2 prompts (non-snapshot)."""

    def test_prompt_contains_discovery_tools(self) -> None:
        """Verify prompt mentions discovery tools."""
        discovery_tools = [
            "discover_active_products",
            "run_discovery_queries",
            "analyze_discovery_domain",
            "synthesize_discovery_report",
            "complete",
        ]
        for tool in discovery_tools:
            assert tool in DISCOVERY_SYSTEM_PROMPT, f"Tool '{tool}' not in prompt"

    def test_prompt_contains_required_sections(self) -> None:
        """Verify prompt contains required sections."""
        sections = [
            "Workflow",
            "Phase 1: Audit",
            "Phase 2: Query",
            "Phase 3: Analyze",
            "Phase 4: Synthesize",
            "Phase 5: Complete",
            "Output Format",
            "Error Handling",
        ]
        for section in sections:
            assert section in DISCOVERY_SYSTEM_PROMPT, f"Section '{section}' missing"

    def test_prompt_contains_format_placeholders(self) -> None:
        """Verify prompt contains format placeholders."""
        placeholders = ["{token_budget}", "{mode}", "{goal}"]
        for placeholder in placeholders:
            assert placeholder in DISCOVERY_SYSTEM_PROMPT, f"'{placeholder}' missing"

    def test_prompt_version_is_v2(self) -> None:
        """Verify this is the v2 prompt."""
        major = int(PROMPT_VERSION.split(".")[0])
        assert major == 2, f"Expected v2 prompt, got {PROMPT_VERSION}"


class TestDiscoveryV2PromptCompatibility:
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
        prompt = build_discovery_prompt(
            mode=mode,
            goal="Test all modes",
            budget_remaining=10_000,
        )
        assert len(prompt) > 500, "Prompt should be substantial"
        assert "discovery" in prompt.lower()

    def test_version_is_semver(self) -> None:
        """Verify prompt version follows semantic versioning."""
        parts = PROMPT_VERSION.split(".")
        assert len(parts) == 3, "Version must be MAJOR.MINOR.PATCH"
