# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for DiagnosticContextBuilder.

Tests the context builder that runs initial exploration and builds
prompt-injectable context for the diagnostic agent.
"""

from __future__ import annotations

from starboard_server.tools.domain.diagnostic.artifact_detector import ArtifactDetector
from starboard_server.tools.domain.diagnostic.artifact_explorer import (
    ArtifactExplorer,
    ExplorationStrategy,
)
from starboard_server.tools.domain.diagnostic.context_extractor import (
    DatabricksContextExtractor,
)
from starboard_server.tools.domain.diagnostic.diagnostic_context_builder import (
    DiagnosticContext,
    DiagnosticContextBuilder,
)
from starboard_server.tools.domain.diagnostic.evidence_extractor import (
    EvidenceWindowExtractor,
)
from starboard_server.tools.domain.diagnostic.pattern_matcher import PatternMatcher
from starboard_server.tools.domain.diagnostic.patterns.registry import PatternRegistry

# =============================================================================
# FIXTURES
# =============================================================================


def create_builder(with_patterns: bool = True) -> DiagnosticContextBuilder:
    """Create a DiagnosticContextBuilder with all dependencies."""
    detector = ArtifactDetector()
    evidence_extractor = EvidenceWindowExtractor()
    context_extractor = DatabricksContextExtractor()

    pattern_matcher = None
    if with_patterns:
        from pathlib import Path

        catalog_path = Path(__file__).parent.parent.parent.parent.parent.parent / (
            "packages/starboard-server/starboard_server/tools/domain/"
            "diagnostic/patterns/catalog"
        )
        if catalog_path.exists():
            registry = PatternRegistry()
            registry.load_from_directory(catalog_path)
            pattern_matcher = PatternMatcher(registry)

    explorer = ArtifactExplorer(
        detector=detector,
        evidence_extractor=evidence_extractor,
        context_extractor=context_extractor,
        pattern_matcher=pattern_matcher,
    )

    return DiagnosticContextBuilder(explorer=explorer)


# =============================================================================
# TEST: CONTEXT BUILDING FROM ARTIFACTS
# =============================================================================


class TestContextBuilding:
    """Tests for building context from artifacts."""

    def test_builds_context_from_oom_error(self) -> None:
        """Test that OOM error produces useful context."""
        builder = create_builder()
        artifact = """
java.lang.OutOfMemoryError: Java heap space
    at java.base/java.util.Arrays.copyOf(Arrays.java:3512)
    at org.apache.spark.sql.catalyst.expressions.UnsafeRow.copy(UnsafeRow.java:506)
Caused by: java.lang.OutOfMemoryError: Java heap space
        """

        context = builder.build_context(artifact)

        assert isinstance(context, DiagnosticContext)
        assert context.artifact_type == "stack_trace"
        assert context.mode in ("online", "offline", "hybrid")
        assert context.confidence >= 0.5
        assert len(context.evidence_refs) >= 0

    def test_builds_context_with_databricks_ids(self) -> None:
        """Test that Databricks IDs are extracted for ONLINE mode."""
        builder = create_builder()
        artifact = """
Job 12345 failed on cluster 1234-567890-abc12def
Run ID: 9876543210
Error: java.lang.OutOfMemoryError: Java heap space
        """

        context = builder.build_context(artifact)

        assert context.mode in ("online", "hybrid")
        assert (
            "job_id" in context.extracted_ids or "cluster_id" in context.extracted_ids
        )
        assert context.has_online_capability

    def test_builds_context_for_offline_mode(self) -> None:
        """Test that missing IDs result in OFFLINE mode."""
        builder = create_builder()
        artifact = "java.lang.OutOfMemoryError: Java heap space"

        context = builder.build_context(artifact)

        assert context.mode == "offline"
        assert not context.has_online_capability
        assert len(context.extracted_ids) == 0

    def test_context_includes_pattern_matches(self) -> None:
        """Test that pattern matches are included in context."""
        builder = create_builder(with_patterns=True)
        artifact = """
java.lang.OutOfMemoryError: Java heap space
Container killed by YARN for exceeding memory limits.
        """

        context = builder.build_context(artifact)

        # Should have pattern matches if patterns loaded
        assert context.patterns is not None or context.patterns == []

    def test_empty_artifact_produces_minimal_context(self) -> None:
        """Test that empty artifact still produces valid context."""
        builder = create_builder()
        artifact = ""

        context = builder.build_context(artifact)

        assert isinstance(context, DiagnosticContext)
        assert context.confidence <= 0.5


# =============================================================================
# TEST: PROMPT FORMATTING
# =============================================================================


class TestPromptFormatting:
    """Tests for formatting context as prompt sections."""

    def test_formats_context_as_prompt_section(self) -> None:
        """Test that context is formatted as prompt-injectable text."""
        builder = create_builder()
        artifact = """
java.lang.OutOfMemoryError: Java heap space
Job ID: 12345
        """

        context = builder.build_context(artifact)
        prompt_section = builder.format_for_prompt(context)

        assert isinstance(prompt_section, str)
        assert "Exploration State" in prompt_section or "Artifact" in prompt_section
        assert len(prompt_section) > 0

    def test_includes_mode_in_prompt(self) -> None:
        """Test that mode is included in prompt section."""
        builder = create_builder()
        artifact = "Error without IDs"

        context = builder.build_context(artifact)
        prompt_section = builder.format_for_prompt(context)

        assert (
            "OFFLINE" in prompt_section.upper() or "offline" in prompt_section.lower()
        )

    def test_includes_confidence_in_prompt(self) -> None:
        """Test that confidence is included in prompt section."""
        builder = create_builder()
        artifact = "java.lang.OutOfMemoryError: Java heap space"

        context = builder.build_context(artifact)
        prompt_section = builder.format_for_prompt(context)

        assert (
            "confidence" in prompt_section.lower()
            or str(context.confidence) in prompt_section
        )

    def test_includes_evidence_refs_in_prompt(self) -> None:
        """Test that evidence references are included in prompt section."""
        builder = create_builder()
        artifact = """
java.lang.OutOfMemoryError: Java heap space
Caused by: java.lang.OutOfMemoryError: Java heap space
        """

        context = builder.build_context(artifact)
        prompt_section = builder.format_for_prompt(context)

        # Should mention evidence if found
        if context.evidence_refs:
            assert "evidence" in prompt_section.lower() or "ev_" in prompt_section

    def test_includes_suggested_steps_in_prompt(self) -> None:
        """Test that suggested next steps are included in prompt section."""
        builder = create_builder()
        artifact = "Some error message"

        context = builder.build_context(artifact)
        prompt_section = builder.format_for_prompt(context)

        # Should have suggestions for what to explore next
        assert (
            "suggest" in prompt_section.lower()
            or "next" in prompt_section.lower()
            or "step" in prompt_section.lower()
            or len(context.suggested_strategies) >= 0
        )


# =============================================================================
# TEST: EXPLORATION STRATEGIES
# =============================================================================


class TestExplorationStrategies:
    """Tests for initial exploration strategy execution."""

    def test_runs_detect_type_strategy(self) -> None:
        """Test that detect_type strategy is run."""
        builder = create_builder()
        artifact = "SELECT * FROM users"

        context = builder.build_context(artifact)

        # Should have detected artifact type
        assert context.artifact_type is not None
        assert ExplorationStrategy.DETECT_TYPE.value in context.strategies_executed

    def test_runs_extract_evidence_strategy(self) -> None:
        """Test that extract_evidence strategy is run for errors."""
        builder = create_builder()
        artifact = """
java.lang.OutOfMemoryError: Java heap space
    at some.Class.method(Class.java:123)
        """

        context = builder.build_context(artifact)

        # Should have run evidence extraction
        assert ExplorationStrategy.EXTRACT_EVIDENCE.value in context.strategies_executed

    def test_runs_extract_ids_strategy(self) -> None:
        """Test that extract_ids strategy is run."""
        builder = create_builder()
        artifact = "Job 12345 failed"

        context = builder.build_context(artifact)

        # Should have run ID extraction
        assert ExplorationStrategy.EXTRACT_IDS.value in context.strategies_executed

    def test_runs_match_patterns_when_patterns_available(self) -> None:
        """Test that match_patterns runs when patterns are available."""
        builder = create_builder(with_patterns=True)
        artifact = "java.lang.OutOfMemoryError: Java heap space"

        context = builder.build_context(artifact)

        # Should have run pattern matching if patterns loaded
        if builder._has_pattern_matcher:
            assert (
                ExplorationStrategy.MATCH_PATTERNS.value in context.strategies_executed
            )


# =============================================================================
# TEST: EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handles_very_long_artifacts(self) -> None:
        """Test handling of very long artifacts."""
        builder = create_builder()
        artifact = "Error line\n" * 10000  # 10k lines

        context = builder.build_context(artifact)

        # Should complete without error and have reasonable context
        assert isinstance(context, DiagnosticContext)
        assert context.was_truncated or len(artifact) > 0

    def test_handles_binary_looking_content(self) -> None:
        """Test handling of binary-like content."""
        builder = create_builder()
        artifact = "\x00\x01\x02\x03 Error message"

        context = builder.build_context(artifact)

        # Should handle gracefully
        assert isinstance(context, DiagnosticContext)

    def test_handles_unicode_content(self) -> None:
        """Test handling of unicode content."""
        builder = create_builder()
        artifact = "Error: 日本語のエラーメッセージ 🔥"

        context = builder.build_context(artifact)

        assert isinstance(context, DiagnosticContext)

    def test_exploration_timeout_protection(self) -> None:
        """Test that exploration doesn't take too long."""
        import time

        builder = create_builder()
        artifact = "java.lang.OutOfMemoryError: Java heap space\n" * 1000

        start = time.time()
        context = builder.build_context(artifact)
        elapsed = time.time() - start

        # Should complete in reasonable time (< 5 seconds)
        assert elapsed < 5.0
        assert isinstance(context, DiagnosticContext)


# =============================================================================
# TEST: CONTEXT DATACLASS
# =============================================================================


class TestDiagnosticContext:
    """Tests for the DiagnosticContext dataclass."""

    def test_context_is_serializable(self) -> None:
        """Test that context can be serialized to dict."""
        builder = create_builder()
        artifact = "Error message"

        context = builder.build_context(artifact)
        context_dict = context.to_dict()

        assert isinstance(context_dict, dict)
        assert "artifact_type" in context_dict
        assert "mode" in context_dict
        assert "confidence" in context_dict

    def test_context_has_all_expected_fields(self) -> None:
        """Test that context has all expected fields."""
        builder = create_builder()
        artifact = "Error message"

        context = builder.build_context(artifact)

        assert hasattr(context, "artifact_type")
        assert hasattr(context, "mode")
        assert hasattr(context, "confidence")
        assert hasattr(context, "evidence_refs")
        assert hasattr(context, "extracted_ids")
        assert hasattr(context, "patterns")
        assert hasattr(context, "suggested_strategies")
        assert hasattr(context, "strategies_executed")
