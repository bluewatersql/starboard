# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden tests for Diagnostic Agent prompts.

These tests validate the structure and key components of the diagnostic
agent prompt, ensuring consistent behavior across updates.

Tests cover:
- Prompt version and metadata
- Core principles (artifact-first, evidence-based)
- Mode detection (ONLINE/OFFLINE)
- Exit code triage logic
- Exploration strategy (5-step pattern)
- Response format structure
- Handoff protocol
"""

from starboard.prompts.diagnostic.v1 import (
    DIAGNOSTIC_SYSTEM_PROMPT,
    PROMPT_VERSION,
)


class TestPromptVersioning:
    """Test prompt versioning and metadata."""

    def test_prompt_version_format(self):
        """Prompt version follows semantic versioning."""
        parts = PROMPT_VERSION.split(".")
        assert len(parts) == 3, "Version should be MAJOR.MINOR.PATCH"
        assert all(p.isdigit() for p in parts), "All version parts should be numeric"

    def test_prompt_version_value(self):
        """Prompt version is 1.0.0 for initial artifact-first release."""
        assert PROMPT_VERSION == "1.0.0"


class TestCorePrinciples:
    """Test core diagnostic principles are present."""

    def test_artifact_first_principle(self):
        """Artifact-first analysis is emphasized."""
        assert "Artifact-First" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "analyze" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        assert "logs" in DIAGNOSTIC_SYSTEM_PROMPT.lower()

    def test_evidence_based_principle(self):
        """Evidence-based findings are required."""
        assert "Evidence-Based" in DIAGNOSTIC_SYSTEM_PROMPT
        assert (
            "cite" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "evidence" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_signal_decoding_principle(self):
        """Exit code signal decoding is documented."""
        assert "Signal Decoding" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "137" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "SIGKILL" in DIAGNOSTIC_SYSTEM_PROMPT

    def test_handoff_ready_principle(self):
        """Handoff readiness is emphasized."""
        assert "Handoff" in DIAGNOSTIC_SYSTEM_PROMPT
        assert (
            "DiagnosticFingerprint" in DIAGNOSTIC_SYSTEM_PROMPT
            or "Fingerprint" in DIAGNOSTIC_SYSTEM_PROMPT
        )


class TestModeDetection:
    """Test ONLINE/OFFLINE mode documentation."""

    def test_offline_mode_documented(self):
        """OFFLINE mode is documented with fallback guidance."""
        assert "OFFLINE" in DIAGNOSTIC_SYSTEM_PROMPT
        # Should explain what happens without IDs
        assert (
            "No Databricks IDs" in DIAGNOSTIC_SYSTEM_PROMPT
            or "artifacts alone" in DIAGNOSTIC_SYSTEM_PROMPT
        )

    def test_online_mode_documented(self):
        """ONLINE mode is documented with tool usage."""
        assert "ONLINE" in DIAGNOSTIC_SYSTEM_PROMPT
        # Should explain tool fetching when IDs available
        assert (
            "IDs available" in DIAGNOSTIC_SYSTEM_PROMPT
            or "tool" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_tool_call_limit_documented(self):
        """Tool call limit is documented (max 6)."""
        assert "6" in DIAGNOSTIC_SYSTEM_PROMPT
        # Should mention cap or limit
        assert (
            "cap" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "limit" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "max" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )


class TestExitCodeTriage:
    """Test exit code triage documentation."""

    def test_exit_137_documented(self):
        """Exit code 137 (SIGKILL) is documented with proof requirements."""
        assert "137" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "SIGKILL" in DIAGNOSTIC_SYSTEM_PROMPT
        # Should require proof for OOM
        assert (
            "OOMKilled" in DIAGNOSTIC_SYSTEM_PROMPT
            or "proof" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_exit_143_documented(self):
        """Exit code 143 (SIGTERM) is documented."""
        assert "143" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "SIGTERM" in DIAGNOSTIC_SYSTEM_PROMPT

    def test_exit_139_documented(self):
        """Exit code 139 (SIGSEGV) is documented."""
        assert "139" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "SIGSEGV" in DIAGNOSTIC_SYSTEM_PROMPT

    def test_exit_1_documented(self):
        """Exit code 1 (general error) is documented."""
        # Exit code 1 should be mentioned
        assert (
            "Exit Code 1" in DIAGNOSTIC_SYSTEM_PROMPT
            or "exit code 1" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_no_assumption_warning(self):
        """Warning against assuming 137 = OOM is present."""
        assert (
            "NEVER assume 137 = OOM" in DIAGNOSTIC_SYSTEM_PROMPT
            or "proof" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )


class TestExplorationStrategy:
    """Test 5-step exploration pattern documentation."""

    def test_detect_step_documented(self):
        """DETECT step is documented."""
        assert "DETECT" in DIAGNOSTIC_SYSTEM_PROMPT
        assert (
            "artifact type" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "type" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_extract_step_documented(self):
        """EXTRACT step is documented."""
        assert "EXTRACT" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "evidence" in DIAGNOSTIC_SYSTEM_PROMPT.lower()

    def test_match_step_documented(self):
        """MATCH step is documented."""
        assert "MATCH" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "pattern" in DIAGNOSTIC_SYSTEM_PROMPT.lower()

    def test_expand_step_documented(self):
        """EXPAND step is documented."""
        assert "EXPAND" in DIAGNOSTIC_SYSTEM_PROMPT

    def test_synthesize_step_documented(self):
        """SYNTHESIZE step is documented."""
        assert "SYNTHESIZE" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "diagnosis" in DIAGNOSTIC_SYSTEM_PROMPT.lower()

    def test_stopping_conditions_documented(self):
        """Stopping conditions are documented with confidence thresholds."""
        # Should mention confidence thresholds
        assert (
            "80%" in DIAGNOSTIC_SYSTEM_PROMPT
            or "confidence" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )
        # Should mention max steps
        assert (
            "6" in DIAGNOSTIC_SYSTEM_PROMPT or "max" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_confidence_framing_documented(self):
        """Confidence-driven response framing is documented."""
        # Should have different responses for different confidence levels
        assert "≥90%" in DIAGNOSTIC_SYSTEM_PROMPT or "90%" in DIAGNOSTIC_SYSTEM_PROMPT
        assert (
            "definitive" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "root cause is" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )


class TestResponseFormat:
    """Test response format structure documentation."""

    def test_overview_section_documented(self):
        """OVERVIEW section is documented."""
        assert "OVERVIEW" in DIAGNOSTIC_SYSTEM_PROMPT

    def test_findings_section_documented(self):
        """FINDINGS section is documented."""
        assert "FINDINGS" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "evidence" in DIAGNOSTIC_SYSTEM_PROMPT.lower()

    def test_recommendations_section_documented(self):
        """RECOMMENDATIONS section is documented."""
        assert (
            "RECOMMENDATIONS" in DIAGNOSTIC_SYSTEM_PROMPT
            or "Recommendation" in DIAGNOSTIC_SYSTEM_PROMPT
        )

    def test_next_steps_section_documented(self):
        """NEXT STEPS section is documented."""
        assert (
            "NEXT STEPS" in DIAGNOSTIC_SYSTEM_PROMPT
            or "Next Steps" in DIAGNOSTIC_SYSTEM_PROMPT
        )


class TestHandoffProtocol:
    """Test handoff protocol documentation."""

    def test_diagnostic_fingerprint_documented(self):
        """DiagnosticFingerprint structure is documented."""
        assert (
            "diagnostic_fingerprint" in DIAGNOSTIC_SYSTEM_PROMPT
            or "DiagnosticFingerprint" in DIAGNOSTIC_SYSTEM_PROMPT
        )

    def test_primary_symptom_documented(self):
        """Primary symptom field is documented."""
        assert "primary_symptom" in DIAGNOSTIC_SYSTEM_PROMPT

    def test_evidence_snippets_documented(self):
        """Evidence snippets in fingerprint are documented."""
        assert (
            "evidence_snippets" in DIAGNOSTIC_SYSTEM_PROMPT
            or "evidence" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_specialist_routing_documented(self):
        """Routing to specialists is documented."""
        # Should mention routing to different agents
        assert (
            "Cluster Agent" in DIAGNOSTIC_SYSTEM_PROMPT
            or "cluster" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )
        assert (
            "Query Agent" in DIAGNOSTIC_SYSTEM_PROMPT
            or "query" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )
        assert (
            "Job Agent" in DIAGNOSTIC_SYSTEM_PROMPT
            or "job" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )


class TestToolsDocumentation:
    """Test tool documentation in prompt."""

    def test_offline_tools_documented(self):
        """Offline tools are documented."""
        assert "request_user_input" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "complete" in DIAGNOSTIC_SYSTEM_PROMPT

    def test_online_tools_documented(self):
        """Online context enrichment tools are documented."""
        assert (
            "get_spark_logs" in DIAGNOSTIC_SYSTEM_PROMPT
            or "spark_logs" in DIAGNOSTIC_SYSTEM_PROMPT
        )
        assert (
            "get_cluster_events" in DIAGNOSTIC_SYSTEM_PROMPT
            or "cluster_events" in DIAGNOSTIC_SYSTEM_PROMPT
        )
        assert (
            "get_run_output" in DIAGNOSTIC_SYSTEM_PROMPT
            or "run_output" in DIAGNOSTIC_SYSTEM_PROMPT
        )

    def test_tool_priorities_documented(self):
        """Tool priorities and costs are documented."""
        assert "CRITICAL" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "HIGH" in DIAGNOSTIC_SYSTEM_PROMPT
        assert "tokens" in DIAGNOSTIC_SYSTEM_PROMPT.lower()


class TestWorkflowDocumentation:
    """Test workflow documentation."""

    def test_with_artifacts_workflow(self):
        """Workflow with artifacts is documented."""
        assert (
            "WITH Artifacts" in DIAGNOSTIC_SYSTEM_PROMPT
            or "Artifacts" in DIAGNOSTIC_SYSTEM_PROMPT
        )
        assert (
            "evidence windows" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "evidence" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_without_artifacts_workflow(self):
        """Workflow without artifacts is documented."""
        assert (
            "WITHOUT Artifacts" in DIAGNOSTIC_SYSTEM_PROMPT
            or "Question Only" in DIAGNOSTIC_SYSTEM_PROMPT
        )


class TestErrorHandling:
    """Test error handling documentation."""

    def test_tool_failure_handling(self):
        """Tool failure handling is documented."""
        assert "fail" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        assert (
            "acknowledge" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "limitation" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_insufficient_evidence_handling(self):
        """Insufficient evidence handling is documented."""
        assert (
            "insufficient" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "confidence" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_no_fabrication_rule(self):
        """No fabrication rule is documented."""
        assert (
            "fabricate" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
            or "speculate" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )


class TestPromptComposition:
    """Test prompt composition with shared guidelines."""

    def test_includes_tool_execution_guidelines(self):
        """Prompt includes shared tool execution guidelines."""
        # Should have tool execution patterns
        assert (
            "TOOL_EXECUTION" in DIAGNOSTIC_SYSTEM_PROMPT
            or "parallel" in DIAGNOSTIC_SYSTEM_PROMPT.lower()
        )

    def test_includes_complete_tool_guidelines(self):
        """Prompt includes complete tool guidelines."""
        assert "complete" in DIAGNOSTIC_SYSTEM_PROMPT.lower()

    def test_token_budget_placeholder(self):
        """Token budget placeholder is present."""
        assert (
            "{token_budget" in DIAGNOSTIC_SYSTEM_PROMPT
            or "token_budget" in DIAGNOSTIC_SYSTEM_PROMPT
        )

    def test_mode_placeholder(self):
        """Mode placeholder is present."""
        assert "{mode}" in DIAGNOSTIC_SYSTEM_PROMPT

    def test_goal_placeholder(self):
        """Goal placeholder is present."""
        assert "{goal}" in DIAGNOSTIC_SYSTEM_PROMPT
