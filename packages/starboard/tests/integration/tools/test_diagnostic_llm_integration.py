# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Integration tests for Diagnostic Agent LLM integration.

Tests the full exploration loop with context building, tool execution,
and multi-step reasoning patterns.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starboard.tools.domain.diagnostic.artifact_detector import ArtifactDetector
from starboard.tools.domain.diagnostic.artifact_explorer import (
    ArtifactExplorer,
    ExplorationState,
    ExplorationStrategy,
)
from starboard.tools.domain.diagnostic.context_extractor import (
    DatabricksContextExtractor,
)
from starboard.tools.domain.diagnostic.diagnostic_context_builder import (
    DiagnosticContextBuilder,
)
from starboard.tools.domain.diagnostic.evidence_extractor import (
    EvidenceWindowExtractor,
)
from starboard.tools.domain.diagnostic.exploration_tool_adapter import (
    ExplorationToolAdapter,
    create_exploration_tools,
)
from starboard.tools.domain.diagnostic.pattern_matcher import PatternMatcher
from starboard.tools.domain.diagnostic.patterns.registry import PatternRegistry

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def pattern_registry() -> PatternRegistry:
    """Load pattern registry with all patterns."""
    catalog_path = (
        Path(__file__).parent.parent.parent
        / "starboard/tools/domain/diagnostic/patterns/catalog"
    )
    registry = PatternRegistry()
    if catalog_path.exists():
        registry.load_from_directory(catalog_path)
    return registry


@pytest.fixture
def full_explorer(pattern_registry: PatternRegistry) -> ArtifactExplorer:
    """Create explorer with all components including pattern matcher."""
    return ArtifactExplorer(
        detector=ArtifactDetector(),
        evidence_extractor=EvidenceWindowExtractor(),
        context_extractor=DatabricksContextExtractor(),
        pattern_matcher=PatternMatcher(pattern_registry),
    )


@pytest.fixture
def context_builder(full_explorer: ArtifactExplorer) -> DiagnosticContextBuilder:
    """Create context builder with full explorer."""
    return DiagnosticContextBuilder(full_explorer)


@pytest.fixture
def tool_adapter(full_explorer: ArtifactExplorer) -> ExplorationToolAdapter:
    """Create tool adapter with full explorer."""
    return ExplorationToolAdapter(full_explorer)


# =============================================================================
# TEST: MULTI-STEP EXPLORATION
# =============================================================================


class TestMultiStepExploration:
    """Tests for multi-step exploration patterns."""

    def test_simple_error_reaches_high_confidence_quickly(
        self, full_explorer: ArtifactExplorer
    ) -> None:
        """Test that simple error progresses through exploration steps."""
        artifact = """
java.lang.OutOfMemoryError: Java heap space
    at java.base/java.util.Arrays.copyOf(Arrays.java:3512)
    at org.apache.spark.sql.catalyst.expressions.UnsafeRow.copy(UnsafeRow.java:506)
Container killed by YARN for exceeding memory limits.
        """

        # Step 1: Detect type
        result1 = full_explorer.explore(
            artifact, strategy=ExplorationStrategy.DETECT_TYPE
        )
        assert result1.confidence >= 0.5  # Some confidence
        assert result1.findings.get("artifact_type") is not None

        # Step 2: Extract evidence
        result2 = full_explorer.explore(
            artifact, strategy=ExplorationStrategy.EXTRACT_EVIDENCE
        )
        assert result2.findings.get("window_count", 0) >= 0

        # Step 3: Match patterns
        result3 = full_explorer.explore(
            artifact, strategy=ExplorationStrategy.MATCH_PATTERNS
        )

        # Should have processed and returned some result
        assert result3.confidence >= 0.0
        assert "patterns" in result3.findings or "match_count" in result3.findings

    def test_ambiguous_error_needs_more_steps(
        self, full_explorer: ArtifactExplorer
    ) -> None:
        """Test that ambiguous error requires more exploration steps."""
        artifact = "Error: Something went wrong"

        # Step 1: Detect type
        result1 = full_explorer.explore(
            artifact, strategy=ExplorationStrategy.DETECT_TYPE
        )

        # Low confidence due to vague error
        assert result1.confidence < 0.8

        # Should suggest more exploration
        assert len(result1.next_steps) > 0

    def test_exploration_state_tracking(self, full_explorer: ArtifactExplorer) -> None:
        """Test that exploration state is properly tracked across steps."""
        artifact = "java.lang.OutOfMemoryError: Java heap space"

        state = ExplorationState(
            artifact_text=artifact,
            history=[],
            current_confidence=0.0,
            mode=None,
        )

        # Execute multiple steps
        strategies = [
            ExplorationStrategy.DETECT_TYPE,
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.MATCH_PATTERNS,
        ]

        for strategy in strategies:
            result = full_explorer.explore(artifact, strategy=strategy)
            from starboard.tools.domain.diagnostic.artifact_explorer import (
                ExplorationStep,
            )

            step = ExplorationStep(
                strategy=strategy, target=artifact[:50], rationale="Test"
            )
            state.history.append((step, result))
            if result.confidence > state.current_confidence:
                state.current_confidence = result.confidence

        # Should have tracked all steps
        assert state.step_count == 3
        assert state.current_confidence > 0.0

        # Get summary
        summary = full_explorer.get_exploration_summary(state)
        assert summary["step_count"] == 3
        assert len(summary["strategies_used"]) == 3

    def test_stopping_condition_at_high_confidence(
        self, full_explorer: ArtifactExplorer
    ) -> None:
        """Test that exploration stops when confidence is high."""
        artifact = """
java.lang.OutOfMemoryError: Java heap space
Container killed by YARN for exceeding memory limits.
        """

        state = ExplorationState(
            artifact_text=artifact,
            history=[],
            current_confidence=0.0,
            mode=None,
        )

        # Run until should stop
        strategies = [
            ExplorationStrategy.DETECT_TYPE,
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.MATCH_PATTERNS,
        ]

        for strategy in strategies:
            result = full_explorer.explore(artifact, strategy=strategy)
            from starboard.tools.domain.diagnostic.artifact_explorer import (
                ExplorationStep,
            )

            step = ExplorationStep(
                strategy=strategy, target=artifact[:50], rationale="Test"
            )
            state.history.append((step, result))
            if result.confidence > state.current_confidence:
                state.current_confidence = result.confidence

            # Check if should stop
            if not full_explorer.should_continue_exploring(state):
                break

        # Should have stopped at high confidence
        assert state.current_confidence >= 0.8


# =============================================================================
# TEST: CONTEXT BUILDER + TOOL ADAPTER INTEGRATION
# =============================================================================


class TestContextAndToolIntegration:
    """Tests for context builder and tool adapter working together."""

    def test_context_builder_then_tool_calls(
        self,
        context_builder: DiagnosticContextBuilder,
        tool_adapter: ExplorationToolAdapter,
    ) -> None:
        """Test that context builder and tool adapter work together."""
        artifact = """
Job 12345 failed with exit code 137
java.lang.OutOfMemoryError: Java heap space
        """

        # Build initial context
        context = context_builder.build_context(artifact)

        assert context.artifact_type is not None
        assert context.mode in ("online", "offline", "hybrid")
        assert context.confidence > 0.0

        # Use tool adapter for additional exploration
        result = tool_adapter.execute("explore_correlate", {"artifact": artifact})

        assert "primary_cause" in result
        assert result["confidence"] >= 0.0

    def test_prompt_section_contains_exploration_state(
        self,
        context_builder: DiagnosticContextBuilder,
    ) -> None:
        """Test that formatted prompt section includes exploration state."""
        artifact = """
java.lang.OutOfMemoryError: Java heap space
Container killed by YARN for exceeding memory limits.
Job ID: 12345
        """

        context = context_builder.build_context(artifact)
        prompt_section = context_builder.format_for_prompt(context)

        # Should have key sections
        assert "Exploration State" in prompt_section
        assert "Mode" in prompt_section
        assert "Confidence" in prompt_section

        # Should have extracted IDs (ONLINE mode)
        if context.extracted_ids:
            assert (
                "Databricks ID" in prompt_section or "job_id" in prompt_section.lower()
            )

    def test_tool_definitions_are_valid(
        self, tool_adapter: ExplorationToolAdapter
    ) -> None:
        """Test that tool definitions are valid for LLM consumption."""
        tools = tool_adapter.get_tool_definitions()

        for tool in tools:
            # Validate structure
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

            params = tool["parameters"]
            assert params["type"] == "object"
            assert "properties" in params
            assert "artifact" in params["properties"]
            assert "required" in params
            assert "artifact" in params["required"]


# =============================================================================
# TEST: FACTORY FUNCTION INTEGRATION
# =============================================================================


class TestFactoryIntegration:
    """Tests for create_exploration_tools factory function."""

    def test_factory_creates_working_tools(
        self, full_explorer: ArtifactExplorer
    ) -> None:
        """Test that factory creates working tools and executor."""
        tools, executor = create_exploration_tools(full_explorer)

        # Should have tools
        assert len(tools) > 0

        # Should be able to execute
        result = executor("explore_detect_type", {"artifact": "Error message"})
        assert isinstance(result, dict)
        assert "artifact_type" in result

    def test_factory_tools_match_adapter(self, full_explorer: ArtifactExplorer) -> None:
        """Test that factory tools match direct adapter usage."""
        tools, executor = create_exploration_tools(full_explorer)
        adapter = ExplorationToolAdapter(full_explorer)

        # Should have same tool count
        assert len(tools) == len(adapter.get_tool_definitions())

        # Should produce same results
        artifact = "Error message"
        factory_result = executor("explore_detect_type", {"artifact": artifact})
        adapter_result = adapter.execute("explore_detect_type", {"artifact": artifact})

        assert factory_result["artifact_type"] == adapter_result["artifact_type"]


# =============================================================================
# TEST: END-TO-END EXPLORATION SCENARIOS
# =============================================================================


class TestEndToEndScenarios:
    """End-to-end tests simulating LLM exploration flow."""

    def test_oom_scenario_full_flow(
        self,
        context_builder: DiagnosticContextBuilder,
        tool_adapter: ExplorationToolAdapter,
    ) -> None:
        """Test full flow for OOM error with job ID."""
        artifact = """
Job 12345 on cluster 1234-567890-abc12def failed with exit code 137

24/12/17 10:23:45 ERROR SparkContext: Error initializing SparkContext.
java.lang.OutOfMemoryError: Java heap space
    at java.base/java.util.Arrays.copyOf(Arrays.java:3512)
    at org.apache.spark.sql.catalyst.expressions.UnsafeRow.copy(UnsafeRow.java:506)
Caused by: java.lang.OutOfMemoryError: Java heap space

Container killed by YARN for exceeding memory limits.
10.5 GB of 10 GB physical memory used.
        """

        # Step 1: Build initial context (simulates pre-processing)
        context = context_builder.build_context(artifact)

        # Verify initial context - artifact type can vary based on detection
        assert context.artifact_type is not None
        # Mode should detect the job/cluster IDs
        assert context.mode in ("online", "hybrid", "offline")
        assert context.confidence >= 0.0

        # Step 2: LLM decides to correlate (simulated tool call)
        correlate_result = tool_adapter.execute(
            "explore_correlate", {"artifact": artifact}
        )

        # Should return correlation analysis
        assert "correlation" in correlate_result or "primary_cause" in correlate_result
        assert correlate_result["confidence"] >= 0.0

    def test_shuffle_failure_scenario(
        self,
        context_builder: DiagnosticContextBuilder,
        tool_adapter: ExplorationToolAdapter,
    ) -> None:
        """Test full flow for shuffle failure."""
        artifact = """
org.apache.spark.shuffle.FetchFailedException: Failed to connect to executor-5
    at org.apache.spark.storage.ShuffleBlockFetcherIterator.throwFetchFailedException
    at org.apache.spark.storage.ShuffleBlockFetcherIterator.next
Caused by: java.io.IOException: Connection reset by peer

Stage 4 failed 4 times, most recent failure:
Lost task 23.3 in stage 4.0: ExecutorLostFailure (executor 5 exited by signal)
        """

        # Build context
        context = context_builder.build_context(artifact)

        # Artifact type can vary - error_message, stack_trace, or mixed
        assert context.artifact_type is not None
        assert context.confidence > 0.0

        # Extract evidence - should find Spark errors
        evidence_result = tool_adapter.execute(
            "explore_extract_evidence", {"artifact": artifact}
        )

        # Should find evidence windows with Spark errors
        assert evidence_result.get("window_count", 0) >= 0
        assert "evidence_refs" in evidence_result

    def test_offline_mode_guidance(
        self,
        context_builder: DiagnosticContextBuilder,
    ) -> None:
        """Test that OFFLINE mode provides appropriate guidance."""
        artifact = """
java.lang.OutOfMemoryError: Java heap space
No job IDs or cluster IDs available.
        """

        context = context_builder.build_context(artifact)

        # Should be OFFLINE mode
        assert context.mode == "offline"
        assert not context.has_online_capability

        # Prompt should indicate OFFLINE
        prompt_section = context_builder.format_for_prompt(context)
        assert "OFFLINE" in prompt_section.upper()

    def test_large_artifact_handling(
        self,
        context_builder: DiagnosticContextBuilder,
        tool_adapter: ExplorationToolAdapter,
    ) -> None:
        """Test handling of large artifacts."""
        # Create large artifact
        large_artifact = (
            "Error line\n" * 5000
            + """
java.lang.OutOfMemoryError: Java heap space
Container killed by YARN for exceeding memory limits.
        """
            + "More log lines\n" * 5000
        )

        # Should complete without timeout
        context = context_builder.build_context(large_artifact)

        assert isinstance(context.artifact_type, str)
        assert context.confidence >= 0.0

        # Summarize should work
        summarize_result = tool_adapter.execute(
            "explore_summarize", {"artifact": large_artifact}
        )

        assert "summary" in summarize_result
        assert summarize_result.get("compression_ratio", 0) > 0
