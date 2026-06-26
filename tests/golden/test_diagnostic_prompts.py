# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden tests for Diagnostic Agent prompts.

These tests use syrupy snapshots to detect prompt regressions. When prompts
change (intentionally), run `pytest --snapshot-update` to update snapshots.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.prompts.diagnostic.v1 import (
    DIAGNOSTIC_SYSTEM_PROMPT,
    PROMPT_VERSION,
)
from starboard_server.prompts.factories import build_diagnostic_prompt
from syrupy.assertion import SnapshotAssertion


class TestDiagnosticPromptSnapshots:
    """Golden tests for diagnostic prompts using syrupy."""

    def test_prompt_version(self, snapshot: SnapshotAssertion) -> None:
        """Ensure prompt version is tracked and stable."""
        assert snapshot == PROMPT_VERSION

    def test_raw_system_prompt_unchanged(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Raw diagnostic system prompt template."""
        assert snapshot == DIAGNOSTIC_SYSTEM_PROMPT

    def test_diagnostic_mode_prompt(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for diagnostic mode."""
        prompt = build_diagnostic_prompt(
            mode=OptimizationMode.DIAGNOSTIC,
            goal="Investigate job failure",
            budget_remaining=25_000,
        )
        assert snapshot == prompt


class TestDiagnosticPromptStructure:
    """Structural tests for diagnostic prompts (non-snapshot)."""

    def test_prompt_contains_core_tools(self) -> None:
        """Verify prompt mentions core tools."""
        core_tools = [
            "complete",
        ]
        for tool in core_tools:
            assert tool in DIAGNOSTIC_SYSTEM_PROMPT, f"Tool '{tool}' not in prompt"

    def test_prompt_contains_required_sections(self) -> None:
        """Verify prompt contains required sections."""
        sections = [
            "DIAGNOSTIC WORKFLOW",
            "OUTPUT FORMAT",
        ]
        for section in sections:
            assert section in DIAGNOSTIC_SYSTEM_PROMPT, f"Section '{section}' missing"

    def test_prompt_contains_format_placeholders(self) -> None:
        """Verify prompt contains format placeholders."""
        placeholders = ["{token_budget:,}", "{mode}", "{goal}"]
        for placeholder in placeholders:
            assert placeholder in DIAGNOSTIC_SYSTEM_PROMPT, f"'{placeholder}' missing"

    def test_prompt_mentions_troubleshooting(self) -> None:
        """Verify prompt mentions diagnostic/troubleshooting capabilities."""
        prompt_lower = DIAGNOSTIC_SYSTEM_PROMPT.lower()
        assert "diagnostic" in prompt_lower or "troubleshoot" in prompt_lower, (
            "Prompt should mention diagnostic or troubleshooting capabilities"
        )
        assert "root cause" in prompt_lower, "Prompt should mention root cause analysis"


class TestDiagnosticPromptCompatibility:
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
        prompt = build_diagnostic_prompt(
            mode=mode,
            goal="Test all modes",
            budget_remaining=10_000,
        )
        assert len(prompt) > 500, "Prompt should be substantial"
        assert "diagnostic" in prompt.lower() or "troubleshoot" in prompt.lower()

    def test_version_is_semver(self) -> None:
        """Verify prompt version follows semantic versioning."""
        parts = PROMPT_VERSION.split(".")
        assert len(parts) == 3, "Version must be MAJOR.MINOR.PATCH"
