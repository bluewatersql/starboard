# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden tests for Analytics Agent prompts.

These tests use syrupy snapshots to detect prompt regressions. When prompts
change (intentionally), run `pytest --snapshot-update` to update snapshots.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.prompts.analytics.v1 import (
    ANALYTICS_SYSTEM_PROMPT,
    PROMPT_VERSION,
)
from starboard_server.prompts.factories import build_analytics_prompt
from syrupy.assertion import SnapshotAssertion


class TestAnalyticsPromptSnapshots:
    """Golden tests for analytics prompts using syrupy."""

    def test_prompt_version(self, snapshot: SnapshotAssertion) -> None:
        """Ensure prompt version is tracked and stable."""
        assert snapshot == PROMPT_VERSION

    def test_raw_system_prompt_unchanged(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Raw analytics system prompt template."""
        assert snapshot == ANALYTICS_SYSTEM_PROMPT

    def test_online_mode_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for online mode."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Analyze cost trends",
            budget_remaining=25_000,
        )
        assert snapshot == prompt


class TestAnalyticsPromptStructure:
    """Structural tests for analytics prompts (non-snapshot)."""

    def test_prompt_mentions_finops(self) -> None:
        """Verify prompt mentions FinOps."""
        assert "FinOps" in ANALYTICS_SYSTEM_PROMPT

    def test_prompt_mentions_cost(self) -> None:
        """Verify prompt mentions cost analysis."""
        assert "cost" in ANALYTICS_SYSTEM_PROMPT.lower()

    def test_prompt_contains_required_sections(self) -> None:
        """Verify prompt contains required sections."""
        sections = [
            "GLOBAL LAWS",
            "WORKFLOW",
            "OUTPUT SCHEMA",
        ]
        for section in sections:
            assert section in ANALYTICS_SYSTEM_PROMPT, f"Section '{section}' missing"

    def test_prompt_contains_format_placeholders(self) -> None:
        """Verify prompt contains format placeholders."""
        placeholders = ["{goal}", "{mode}"]
        for placeholder in placeholders:
            assert placeholder in ANALYTICS_SYSTEM_PROMPT, f"'{placeholder}' missing"


class TestAnalyticsPromptCompatibility:
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
        prompt = build_analytics_prompt(
            mode=mode,
            goal="Test all modes",
            budget_remaining=10_000,
        )
        assert len(prompt) > 500, "Prompt should be substantial"
        assert "analytics" in prompt.lower() or "finops" in prompt.lower()

    def test_version_is_semver(self) -> None:
        """Verify prompt version follows semantic versioning."""
        parts = PROMPT_VERSION.split(".")
        assert len(parts) == 3, "Version must be MAJOR.MINOR.PATCH"
