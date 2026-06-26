# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden tests for Cluster Agent prompts.

These tests use syrupy snapshots to detect prompt regressions. When prompts
change (intentionally), run `pytest --snapshot-update` to update snapshots.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.prompts.cluster.v1 import CLUSTER_SYSTEM_PROMPT, PROMPT_VERSION
from starboard_server.prompts.factories import build_cluster_prompt
from syrupy.assertion import SnapshotAssertion


class TestClusterPromptSnapshots:
    """Golden tests for cluster prompts using syrupy."""

    def test_prompt_version(self, snapshot: SnapshotAssertion) -> None:
        """Ensure prompt version is tracked and stable."""
        assert snapshot == PROMPT_VERSION

    def test_raw_system_prompt_unchanged(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Raw cluster system prompt template."""
        assert snapshot == CLUSTER_SYSTEM_PROMPT

    def test_online_mode_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for online mode."""
        prompt = build_cluster_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Optimize cluster configuration",
            budget_remaining=25_000,
        )
        assert snapshot == prompt


class TestClusterPromptStructure:
    """Structural tests for cluster prompts (non-snapshot)."""

    def test_prompt_contains_cluster_tools(self) -> None:
        """Verify prompt mentions cluster tools."""
        cluster_tools = [
            "get_cluster_config",
            "get_cluster_metrics",
        ]
        for tool in cluster_tools:
            assert tool in CLUSTER_SYSTEM_PROMPT, f"Tool '{tool}' not in prompt"

    def test_prompt_contains_required_sections(self) -> None:
        """Verify prompt contains required sections."""
        sections = [
            "Tools Available",
            "Workflow",
            "Output Format",
        ]
        for section in sections:
            assert section in CLUSTER_SYSTEM_PROMPT, f"Section '{section}' missing"

    def test_prompt_contains_format_placeholders(self) -> None:
        """Verify prompt contains format placeholders."""
        placeholders = ["{token_budget:,}", "{mode}", "{goal}"]
        for placeholder in placeholders:
            assert placeholder in CLUSTER_SYSTEM_PROMPT, f"'{placeholder}' missing"


class TestClusterPromptCompatibility:
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
        prompt = build_cluster_prompt(
            mode=mode,
            goal="Test all modes",
            budget_remaining=10_000,
        )
        assert len(prompt) > 500, "Prompt should be substantial"
        assert "cluster" in prompt.lower()

    def test_version_is_semver(self) -> None:
        """Verify prompt version follows semantic versioning."""
        parts = PROMPT_VERSION.split(".")
        assert len(parts) == 3, "Version must be MAJOR.MINOR.PATCH"
