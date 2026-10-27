# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Golden tests for Analytics Agent prompt.

These tests validate that the Analytics Agent prompt correctly instructs
the agent to follow the 5-step agentic RAG workflow.

Note: Tests for V2 features (STEP 0/0.5, discover_system_tables,
retrieve_past_learnings) were removed in fe22757 when Analytics V2
components were deprecated.
"""

import pytest
from starboard.prompts.analytics.v1 import (
    ANALYTICS_SYSTEM_PROMPT,
    PROMPT_VERSION,
)


class TestAnalyticsPromptStructure:
    """Test Analytics prompt structure and content."""

    def test_prompt_version(self):
        """Verify prompt has correct version."""
        assert PROMPT_VERSION == "1.0.0"

    def test_prompt_not_empty(self):
        """Verify prompt has substantial content."""
        assert len(ANALYTICS_SYSTEM_PROMPT) > 20000
        assert "Analytics" in ANALYTICS_SYSTEM_PROMPT

    def test_prompt_has_required_sections(self):
        """Verify all required top-level sections are present."""
        required_sections = [
            "GLOBAL LAWS",
            "COST UNIT RULES",
            "AGENTIC RAG WORKFLOW",
            "REFLEXION LOOP",
            "REASONING OUTPUT",
            "FINOPS-SPECIFIC NEXT STEPS",
            "OUTPUT SCHEMA",
            "ERROR HANDLING",
        ]

        for section in required_sections:
            assert section in ANALYTICS_SYSTEM_PROMPT, f"Missing section: {section}"


class TestAnalyticsWorkflow:
    """Test the mandatory 5-step workflow instructions."""

    def test_mandatory_workflow_declared(self):
        """Verify the 5-step workflow is declared as mandatory."""
        assert "REQUIRED 5-STEP WORKFLOW" in ANALYTICS_SYSTEM_PROMPT
        assert "ALL MUST COMPLETE" in ANALYTICS_SYSTEM_PROMPT

    def test_all_five_steps_present(self):
        """Verify all 5 steps are listed in the workflow."""
        assert "build_analytics_context" in ANALYTICS_SYSTEM_PROMPT
        assert "build_sql_query" in ANALYTICS_SYSTEM_PROMPT
        assert "validate_sql_query" in ANALYTICS_SYSTEM_PROMPT
        assert "execute_sql_query" in ANALYTICS_SYSTEM_PROMPT
        assert "complete" in ANALYTICS_SYSTEM_PROMPT

    def test_steps_are_mandatory(self):
        """Verify steps are marked MANDATORY not optional."""
        assert "build_analytics_context (MANDATORY" in ANALYTICS_SYSTEM_PROMPT
        assert "build_sql_query (MANDATORY" in ANALYTICS_SYSTEM_PROMPT
        assert "validate_sql_query (MANDATORY" in ANALYTICS_SYSTEM_PROMPT
        assert "execute_sql_query (MANDATORY" in ANALYTICS_SYSTEM_PROMPT

    def test_workflow_order_correct(self):
        """Verify build_analytics_context precedes build_sql_query in workflow."""
        rac_pos = ANALYTICS_SYSTEM_PROMPT.find("build_analytics_context (MANDATORY")
        sql_pos = ANALYTICS_SYSTEM_PROMPT.find("build_sql_query (MANDATORY")
        assert rac_pos < sql_pos, (
            "build_analytics_context must come before build_sql_query"
        )

    def test_complete_tool_mandatory(self):
        """Verify complete tool is declared mandatory at end."""
        assert "COMPLETE TOOL IS MANDATORY" in ANALYTICS_SYSTEM_PROMPT

    def test_reflexion_loop_documented(self):
        """Verify reflexion loop for validation failures is documented."""
        assert "REFLEXION LOOP" in ANALYTICS_SYSTEM_PROMPT
        assert (
            "max 3" in ANALYTICS_SYSTEM_PROMPT
            or "3 attempts" in ANALYTICS_SYSTEM_PROMPT
        )


class TestAnalyticsRagWorkflow:
    """Test RAG workflow instructions."""

    def test_rag_pattern_described(self):
        """Verify agentic RAG pattern is described."""
        assert (
            "agentic RAG" in ANALYTICS_SYSTEM_PROMPT
            or "Agentic RAG" in ANALYTICS_SYSTEM_PROMPT
        )

    def test_context_handle_pattern_documented(self):
        """Verify context handle (token-efficient RAG) pattern is explained."""
        assert "context_handle" in ANALYTICS_SYSTEM_PROMPT

    def test_build_analytics_context_always_first(self):
        """Verify build_analytics_context is the first step."""
        workflow_section = ANALYTICS_SYSTEM_PROMPT.split("AGENTIC RAG WORKFLOW")[
            1
        ].split("REFLEXION LOOP")[0]
        bac_pos = workflow_section.find("build_analytics_context")
        bsq_pos = workflow_section.find("build_sql_query")
        assert bac_pos < bsq_pos, (
            "build_analytics_context must appear before build_sql_query in workflow"
        )


class TestAnalyticsReasoningOutput:
    """Test reasoning output section."""

    def test_reasoning_section_exists(self):
        """Verify reasoning output section exists."""
        assert "REASONING OUTPUT" in ANALYTICS_SYSTEM_PROMPT

    def test_reasoning_examples_for_rag(self):
        """Verify RAG tool (build_analytics_context) is mentioned."""
        assert "build_analytics_context" in ANALYTICS_SYSTEM_PROMPT

    def test_reasoning_mentions_conversational_style(self):
        """Verify reasoning section includes guidance on communicating."""
        assert (
            "conversational" in ANALYTICS_SYSTEM_PROMPT
            or "reasoning" in ANALYTICS_SYSTEM_PROMPT.lower()
        )


class TestAnalyticsBackwardCompatibility:
    """Test backward compatibility with core V1 features."""

    def test_global_laws_unchanged(self):
        """Verify global laws section is preserved."""
        assert "1. GLOBAL LAWS" in ANALYTICS_SYSTEM_PROMPT
        assert "EXACTLY ONE" in ANALYTICS_SYSTEM_PROMPT
        assert (
            "Never combine, sum, mix, compare, or convert DBUs and dollars"
            in ANALYTICS_SYSTEM_PROMPT
        )

    def test_cost_unit_rules_unchanged(self):
        """Verify cost unit rules section is preserved."""
        assert "2. COST UNIT RULES" in ANALYTICS_SYSTEM_PROMPT
        assert "DBUs and USD are different units" in ANALYTICS_SYSTEM_PROMPT
        assert "NEVER aggregate" in ANALYTICS_SYSTEM_PROMPT

    def test_output_schema_present(self):
        """Verify output schema section is preserved with key fields."""
        assert "OUTPUT SCHEMA" in ANALYTICS_SYSTEM_PROMPT
        assert "cost_summary" in ANALYTICS_SYSTEM_PROMPT
        assert "findings" in ANALYTICS_SYSTEM_PROMPT
        assert "visualization" in ANALYTICS_SYSTEM_PROMPT
        assert "next_steps" in ANALYTICS_SYSTEM_PROMPT


@pytest.fixture
def v1_prompt():
    """Provide V1 prompt for tests."""
    return ANALYTICS_SYSTEM_PROMPT


class TestAnalyticsPromptQuality:
    """Test overall quality and clarity of the prompt."""

    def test_prompt_has_clear_structure(self, v1_prompt):
        """Verify prompt is well-structured with clear section divisions."""
        section_dividers = v1_prompt.count("=" * 70)
        assert section_dividers >= 10, "Should have clear section divisions"

    def test_no_contradictions(self, v1_prompt):
        """Verify build_analytics_context is not marked as both REQUIRED and OPTIONAL."""
        assert "build_analytics_context (REQUIRED)" not in v1_prompt

    def test_formatting_consistent(self, v1_prompt):
        """Verify step numbering and section formatting is consistent."""
        assert "Step 1:" in v1_prompt
        assert "Step 2:" in v1_prompt
        assert "Step 3:" in v1_prompt
        assert "Step 4:" in v1_prompt

    def test_finops_next_steps_present(self, v1_prompt):
        """Verify FinOps-specific next steps section is present."""
        assert "FINOPS-SPECIFIC NEXT STEPS" in v1_prompt

    def test_error_handling_documented(self, v1_prompt):
        """Verify error handling guidance is in the prompt."""
        assert "ERROR HANDLING" in v1_prompt
