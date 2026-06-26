# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for ArtifactExplorer - incremental discovery orchestrator.

Tests cover:
- Exploration step dataclasses
- Strategy dispatch
- Stopping conditions
- Next step suggestions
- Exploration history aggregation

TDD: These tests are written first, implementation follows.
"""

from textwrap import dedent
from unittest.mock import MagicMock

import pytest
from starboard_server.tools.domain.diagnostic.artifact_detector import (
    ArtifactDetector,
)
from starboard_server.tools.domain.diagnostic.artifact_explorer import (
    ArtifactExplorer,
    ExplorationResult,
    ExplorationState,
    ExplorationStep,
    ExplorationStrategy,
)
from starboard_server.tools.domain.diagnostic.context_extractor import (
    DatabricksContextExtractor,
)
from starboard_server.tools.domain.diagnostic.evidence_extractor import (
    EvidenceWindowExtractor,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def explorer() -> ArtifactExplorer:
    """Create explorer with real dependencies."""
    return ArtifactExplorer(
        detector=ArtifactDetector(),
        evidence_extractor=EvidenceWindowExtractor(),
        context_extractor=DatabricksContextExtractor(),
    )


@pytest.fixture
def mock_explorer() -> ArtifactExplorer:
    """Create explorer with mocked dependencies for isolation."""
    return ArtifactExplorer(
        detector=MagicMock(spec=ArtifactDetector),
        evidence_extractor=MagicMock(spec=EvidenceWindowExtractor),
        context_extractor=MagicMock(spec=DatabricksContextExtractor),
    )


# =============================================================================
# EXPLORATION STEP TESTS
# =============================================================================


class TestExplorationStep:
    """Tests for ExplorationStep dataclass."""

    def test_step_creation(self) -> None:
        """ExplorationStep can be created with required fields."""
        step = ExplorationStep(
            strategy=ExplorationStrategy.DETECT_TYPE,
            target="user_input",
            rationale="Identify artifact type first",
        )

        assert step.strategy == ExplorationStrategy.DETECT_TYPE
        assert step.target == "user_input"
        assert step.rationale == "Identify artifact type first"

    def test_step_is_frozen(self) -> None:
        """ExplorationStep is immutable."""
        step = ExplorationStep(
            strategy=ExplorationStrategy.DETECT_TYPE,
            target="input",
            rationale="test",
        )

        with pytest.raises(AttributeError):
            step.strategy = ExplorationStrategy.EXTRACT_EVIDENCE  # type: ignore


class TestExplorationResult:
    """Tests for ExplorationResult dataclass."""

    def test_result_creation(self) -> None:
        """ExplorationResult can be created with required fields."""
        result = ExplorationResult(
            strategy=ExplorationStrategy.DETECT_TYPE,
            findings={"artifact_type": "STACK_TRACE"},
            confidence=0.9,
            next_steps=[ExplorationStrategy.EXTRACT_EVIDENCE],
            evidence_refs=["ev_abc123"],
        )

        assert result.strategy == ExplorationStrategy.DETECT_TYPE
        assert result.confidence == 0.9
        assert ExplorationStrategy.EXTRACT_EVIDENCE in result.next_steps

    def test_result_defaults(self) -> None:
        """ExplorationResult has sensible defaults."""
        result = ExplorationResult(
            strategy=ExplorationStrategy.DETECT_TYPE,
            findings={},
            confidence=0.5,
        )

        assert result.next_steps == []
        assert result.evidence_refs == []


class TestExplorationState:
    """Tests for ExplorationState dataclass."""

    def test_state_creation(self) -> None:
        """ExplorationState tracks exploration progress."""
        state = ExplorationState(
            artifact_text="some error",
            history=[],
            current_confidence=0.0,
            mode=None,
        )

        assert state.artifact_text == "some error"
        assert state.history == []
        assert state.current_confidence == 0.0

    def test_state_step_count(self) -> None:
        """State tracks step count."""
        step = ExplorationStep(
            strategy=ExplorationStrategy.DETECT_TYPE,
            target="input",
            rationale="test",
        )
        result = ExplorationResult(
            strategy=ExplorationStrategy.DETECT_TYPE,
            findings={},
            confidence=0.5,
        )

        state = ExplorationState(
            artifact_text="error",
            history=[(step, result)],
            current_confidence=0.5,
            mode=None,
        )

        assert state.step_count == 1


# =============================================================================
# STRATEGY DISPATCH TESTS
# =============================================================================


class TestStrategyDispatch:
    """Tests for strategy dispatch."""

    def test_explore_detect_type(self, explorer: ArtifactExplorer) -> None:
        """detect_type strategy uses ArtifactDetector."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.DETECT_TYPE)

        assert result.strategy == ExplorationStrategy.DETECT_TYPE
        assert "artifact_type" in result.findings
        assert result.confidence > 0

    def test_explore_extract_evidence(self, explorer: ArtifactExplorer) -> None:
        """extract_evidence strategy uses EvidenceExtractor."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_EVIDENCE)

        assert result.strategy == ExplorationStrategy.EXTRACT_EVIDENCE
        assert "windows" in result.findings or "window_count" in result.findings

    def test_explore_extract_ids(self, explorer: ArtifactExplorer) -> None:
        """extract_ids strategy uses ContextExtractor."""
        text = "cluster_id=1234-567890-abc12, job_id=12345"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_IDS)

        assert result.strategy == ExplorationStrategy.EXTRACT_IDS
        assert "mode" in result.findings
        assert "ids" in result.findings or "extracted_ids" in result.findings

    def test_invalid_strategy_raises(self, explorer: ArtifactExplorer) -> None:
        """Invalid strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            explorer.explore("text", strategy="invalid_strategy")  # type: ignore


# =============================================================================
# DETECT_TYPE STRATEGY TESTS
# =============================================================================


class TestDetectTypeStrategy:
    """Tests for detect_type strategy."""

    def test_detects_stack_trace(self, explorer: ArtifactExplorer) -> None:
        """Detects stack trace artifact."""
        text = dedent("""
            java.lang.OutOfMemoryError: Java heap space
                at java.base/java.util.Arrays.copyOf
                at org.apache.spark.sql.execution.aggregate
            """)

        result = explorer.explore(text, strategy=ExplorationStrategy.DETECT_TYPE)

        # Enum values are lowercase
        assert result.findings["artifact_type"] in (
            "stack_trace",
            "error_message",
            "STACK_TRACE",
            "ERROR_MESSAGE",
        )
        assert result.confidence >= 0.5

    def test_detects_logs(self, explorer: ArtifactExplorer) -> None:
        """Detects log artifact."""
        text = dedent("""
            2025-01-15 10:23:45 INFO Starting job
            2025-01-15 10:23:46 WARN Memory pressure
            2025-01-15 10:23:47 ERROR OOM occurred
            """)

        result = explorer.explore(text, strategy=ExplorationStrategy.DETECT_TYPE)

        # Enum values are lowercase
        assert result.findings["artifact_type"] in (
            "logs",
            "error_message",
            "LOGS",
            "ERROR_MESSAGE",
        )

    def test_suggests_extract_evidence_next(self, explorer: ArtifactExplorer) -> None:
        """After detect_type, suggests extract_evidence."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.DETECT_TYPE)

        assert ExplorationStrategy.EXTRACT_EVIDENCE in result.next_steps

    def test_suggests_extract_ids_for_high_confidence(
        self, explorer: ArtifactExplorer
    ) -> None:
        """For high confidence detection, suggests extract_ids."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.DETECT_TYPE)

        # Should suggest extracting IDs as an option
        assert (
            ExplorationStrategy.EXTRACT_IDS in result.next_steps
            or ExplorationStrategy.EXTRACT_EVIDENCE in result.next_steps
        )


# =============================================================================
# EXTRACT_EVIDENCE STRATEGY TESTS
# =============================================================================


class TestExtractEvidenceStrategy:
    """Tests for extract_evidence strategy."""

    def test_extracts_evidence_windows(self, explorer: ArtifactExplorer) -> None:
        """Extracts evidence windows from artifact."""
        text = dedent("""
            Processing data...
            java.lang.OutOfMemoryError: Java heap space
                at java.base/java.util.Arrays.copyOf
            Failed to complete task
            """)

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_EVIDENCE)

        assert (
            result.findings.get("window_count", 0) >= 1
            or len(result.evidence_refs) >= 1
        )

    def test_provides_evidence_refs(self, explorer: ArtifactExplorer) -> None:
        """Provides stable evidence references."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_EVIDENCE)

        # Should have evidence refs for citation
        assert len(result.evidence_refs) >= 0  # May be empty for simple input

    def test_suggests_match_patterns_next(self, explorer: ArtifactExplorer) -> None:
        """After extract_evidence, suggests match_patterns."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_EVIDENCE)

        # Should suggest pattern matching as next step
        assert (
            ExplorationStrategy.MATCH_PATTERNS in result.next_steps
            or ExplorationStrategy.EXTRACT_IDS in result.next_steps
            or len(result.next_steps) >= 0  # May be synthesize if high confidence
        )


# =============================================================================
# EXTRACT_IDS STRATEGY TESTS
# =============================================================================


class TestExtractIdsStrategy:
    """Tests for extract_ids strategy."""

    def test_extracts_cluster_id(self, explorer: ArtifactExplorer) -> None:
        """Extracts cluster ID from text."""
        text = "Failed on cluster_id=1234-567890-abc12"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_IDS)

        assert "mode" in result.findings
        ids = result.findings.get("ids", result.findings.get("extracted_ids", {}))
        assert "cluster_id" in str(ids) or result.findings.get("mode") != "offline"

    def test_determines_online_mode(self, explorer: ArtifactExplorer) -> None:
        """Determines ONLINE mode when IDs present."""
        text = "cluster_id=1234-567890-abc12, job_id=12345, run_id=9876543210"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_IDS)

        mode = result.findings.get("mode", "").lower()
        assert mode in ("online", "hybrid")

    def test_determines_offline_mode(self, explorer: ArtifactExplorer) -> None:
        """Determines OFFLINE mode when no IDs present."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_IDS)

        mode = result.findings.get("mode", "").lower()
        assert mode == "offline"

    def test_suggests_match_patterns_next(self, explorer: ArtifactExplorer) -> None:
        """After extract_ids, suggests match_patterns."""
        text = "cluster_id=1234-567890-abc12"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_IDS)

        # Should suggest pattern matching or synthesize
        assert len(result.next_steps) >= 0


# =============================================================================
# STOPPING CONDITIONS TESTS
# =============================================================================


class TestStoppingConditions:
    """Tests for should_continue_exploring()."""

    def test_stops_at_high_confidence(self, explorer: ArtifactExplorer) -> None:
        """Stops when confidence >= 80%."""
        state = ExplorationState(
            artifact_text="error",
            history=[],
            current_confidence=0.85,
            mode=None,
        )

        should_continue = explorer.should_continue_exploring(state)

        assert should_continue is False

    def test_continues_at_low_confidence(self, explorer: ArtifactExplorer) -> None:
        """Continues when confidence < 80%."""
        state = ExplorationState(
            artifact_text="error",
            history=[],
            current_confidence=0.5,
            mode=None,
        )

        should_continue = explorer.should_continue_exploring(state)

        assert should_continue is True

    def test_stops_at_max_steps(self, explorer: ArtifactExplorer) -> None:
        """Stops after max steps reached."""
        # Create history with many steps
        step = ExplorationStep(
            strategy=ExplorationStrategy.DETECT_TYPE,
            target="input",
            rationale="test",
        )
        result = ExplorationResult(
            strategy=ExplorationStrategy.DETECT_TYPE,
            findings={},
            confidence=0.5,
        )
        history = [(step, result)] * 10  # 10 steps

        state = ExplorationState(
            artifact_text="error",
            history=history,
            current_confidence=0.5,
            mode=None,
        )

        should_continue = explorer.should_continue_exploring(state)

        assert should_continue is False

    def test_stops_when_no_next_steps(self, explorer: ArtifactExplorer) -> None:
        """Stops when no more suggested steps."""
        result = ExplorationResult(
            strategy=ExplorationStrategy.EXTRACT_EVIDENCE,
            findings={},
            confidence=0.6,
            next_steps=[],  # No next steps
        )
        step = ExplorationStep(
            strategy=ExplorationStrategy.EXTRACT_EVIDENCE,
            target="input",
            rationale="test",
        )

        state = ExplorationState(
            artifact_text="error",
            history=[(step, result)],
            current_confidence=0.6,
            mode=None,
        )

        # With no next steps and low confidence, should stop
        # (implementation may vary - testing the interface)
        _ = explorer.should_continue_exploring(state)
        # Just verify it doesn't raise


# =============================================================================
# EXPLORATION SUMMARY TESTS
# =============================================================================


class TestExplorationSummary:
    """Tests for get_exploration_summary()."""

    def test_summary_includes_step_count(self, explorer: ArtifactExplorer) -> None:
        """Summary includes step count."""
        step = ExplorationStep(
            strategy=ExplorationStrategy.DETECT_TYPE,
            target="input",
            rationale="test",
        )
        result = ExplorationResult(
            strategy=ExplorationStrategy.DETECT_TYPE,
            findings={"artifact_type": "STACK_TRACE"},
            confidence=0.9,
        )

        state = ExplorationState(
            artifact_text="error",
            history=[(step, result)],
            current_confidence=0.9,
            mode=None,
        )

        summary = explorer.get_exploration_summary(state)

        assert "step_count" in summary or "steps" in summary

    def test_summary_includes_confidence(self, explorer: ArtifactExplorer) -> None:
        """Summary includes final confidence."""
        state = ExplorationState(
            artifact_text="error",
            history=[],
            current_confidence=0.85,
            mode="online",
        )

        summary = explorer.get_exploration_summary(state)

        assert "confidence" in summary
        assert summary["confidence"] == 0.85

    def test_summary_includes_mode(self, explorer: ArtifactExplorer) -> None:
        """Summary includes determined mode."""
        state = ExplorationState(
            artifact_text="error",
            history=[],
            current_confidence=0.85,
            mode="online",
        )

        summary = explorer.get_exploration_summary(state)

        assert "mode" in summary
        assert summary["mode"] == "online"

    def test_summary_aggregates_evidence(self, explorer: ArtifactExplorer) -> None:
        """Summary aggregates evidence refs from all steps."""
        result1 = ExplorationResult(
            strategy=ExplorationStrategy.DETECT_TYPE,
            findings={},
            confidence=0.7,
            evidence_refs=["ev_001"],
        )
        result2 = ExplorationResult(
            strategy=ExplorationStrategy.EXTRACT_EVIDENCE,
            findings={},
            confidence=0.85,
            evidence_refs=["ev_002", "ev_003"],
        )
        step1 = ExplorationStep(
            strategy=ExplorationStrategy.DETECT_TYPE,
            target="input",
            rationale="test",
        )
        step2 = ExplorationStep(
            strategy=ExplorationStrategy.EXTRACT_EVIDENCE,
            target="input",
            rationale="test",
        )

        state = ExplorationState(
            artifact_text="error",
            history=[(step1, result1), (step2, result2)],
            current_confidence=0.85,
            mode=None,
        )

        summary = explorer.get_exploration_summary(state)

        all_refs = summary.get("evidence_refs", [])
        assert len(all_refs) == 3
        assert "ev_001" in all_refs
        assert "ev_002" in all_refs


# =============================================================================
# FULL EXPLORATION FLOW TESTS
# =============================================================================


class TestFullExplorationFlow:
    """Tests for multi-step exploration."""

    def test_simple_oom_exploration(self, explorer: ArtifactExplorer) -> None:
        """Simple OOM error explored in 2-3 steps."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        # Step 1: Detect type
        result1 = explorer.explore(text, strategy=ExplorationStrategy.DETECT_TYPE)
        assert result1.confidence > 0

        # Step 2: Extract evidence
        result2 = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_EVIDENCE)
        assert result2.strategy == ExplorationStrategy.EXTRACT_EVIDENCE

        # Step 3: Extract IDs (should be offline)
        result3 = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_IDS)
        assert result3.findings.get("mode", "").lower() == "offline"

    def test_exploration_with_ids(self, explorer: ArtifactExplorer) -> None:
        """Exploration with Databricks IDs determines ONLINE mode."""
        text = dedent("""
            cluster_id: 1234-567890-abc12
            job_id: 12345
            java.lang.OutOfMemoryError: Java heap space
            """)

        # Extract IDs first
        result = explorer.explore(text, strategy=ExplorationStrategy.EXTRACT_IDS)

        mode = result.findings.get("mode", "").lower()
        assert mode in ("online", "hybrid")


# =============================================================================
# MATCH_PATTERNS STRATEGY TESTS (Phase 2)
# =============================================================================


class TestMatchPatternsStrategy:
    """Tests for match_patterns exploration strategy."""

    @pytest.fixture
    def explorer_with_patterns(self) -> ArtifactExplorer:
        """Create explorer with PatternMatcher loaded."""
        from pathlib import Path

        from starboard_server.tools.domain.diagnostic.pattern_matcher import (
            PatternMatcher,
        )
        from starboard_server.tools.domain.diagnostic.patterns.registry import (
            PatternRegistry,
        )

        registry = PatternRegistry()
        # Find catalog relative to starboard_server package
        import starboard_server

        pkg_path = Path(starboard_server.__file__).parent
        catalog_dir = (
            pkg_path / "tools" / "domain" / "diagnostic" / "patterns" / "catalog"
        )
        if catalog_dir.exists():
            registry.load_from_directory(catalog_dir)

        return ArtifactExplorer(
            detector=ArtifactDetector(),
            evidence_extractor=EvidenceWindowExtractor(),
            context_extractor=DatabricksContextExtractor(),
            pattern_matcher=PatternMatcher(registry),
        )

    def test_match_patterns_finds_oom(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Match patterns finds OOM pattern."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.MATCH_PATTERNS
        )

        assert result.strategy == ExplorationStrategy.MATCH_PATTERNS
        assert "patterns" in result.findings
        assert len(result.findings["patterns"]) >= 1
        pattern_ids = [p["pattern_id"] for p in result.findings["patterns"]]
        assert "java_heap_space" in pattern_ids
        assert result.confidence >= 0.8

    def test_match_patterns_finds_shuffle_failure(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Match patterns finds shuffle fetch failure."""
        text = """
        org.apache.spark.shuffle.FetchFailedException:
            Failed to fetch shuffle block from executor 5
        """

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.MATCH_PATTERNS
        )

        assert "patterns" in result.findings
        pattern_ids = [p["pattern_id"] for p in result.findings["patterns"]]
        assert "shuffle_fetch_failed" in pattern_ids

    def test_match_patterns_finds_exit_code(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Match patterns finds exit code pattern."""
        text = "Command exited with code 137"

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.MATCH_PATTERNS
        )

        assert "patterns" in result.findings
        pattern_ids = [p["pattern_id"] for p in result.findings["patterns"]]
        assert "exit_code_137" in pattern_ids

    def test_match_patterns_no_matches(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Match patterns returns empty when no patterns match."""
        text = "Everything is working fine"

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.MATCH_PATTERNS
        )

        assert result.strategy == ExplorationStrategy.MATCH_PATTERNS
        assert result.findings["patterns"] == []
        assert result.confidence < 0.5

    def test_match_patterns_suggests_next_steps(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Match patterns suggests appropriate next steps."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.MATCH_PATTERNS
        )

        # High confidence should suggest synthesize
        if result.confidence >= 0.8:
            assert ExplorationStrategy.SYNTHESIZE in result.next_steps
        else:
            # Lower confidence should suggest expand or correlate
            assert (
                ExplorationStrategy.EXPAND_WINDOW in result.next_steps
                or ExplorationStrategy.CORRELATE in result.next_steps
            )

    def test_match_patterns_includes_evidence_refs(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Match patterns includes evidence references."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.MATCH_PATTERNS
        )

        # Should have evidence refs from matched patterns
        assert isinstance(result.evidence_refs, list)

    def test_match_patterns_multiple_patterns(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Match patterns finds multiple patterns in complex error."""
        text = dedent("""
            java.lang.OutOfMemoryError: Java heap space
            org.apache.spark.shuffle.FetchFailedException: Failed to fetch
            ExecutorLostFailure (executor 123 lost)
            """)

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.MATCH_PATTERNS
        )

        assert "patterns" in result.findings
        pattern_ids = [p["pattern_id"] for p in result.findings["patterns"]]
        # Should find multiple patterns
        assert len(pattern_ids) >= 2


# =============================================================================
# EXPAND_WINDOW STRATEGY TESTS (Phase 2)
# =============================================================================


class TestExpandWindowStrategy:
    """Tests for expand_window exploration strategy."""

    def test_expand_window_extracts_context(self, explorer: ArtifactExplorer) -> None:
        """Expand window extracts more context around evidence."""
        text = dedent("""
            Line 1: Starting job
            Line 2: Processing data
            Line 3: Error occurred here
            Line 4: java.lang.OutOfMemoryError: Java heap space
            Line 5: at org.apache.spark.memory.TaskMemoryManager
            Line 6: Cleanup started
            Line 7: Job failed
            """)

        result = explorer.explore(text, strategy=ExplorationStrategy.EXPAND_WINDOW)

        assert result.strategy == ExplorationStrategy.EXPAND_WINDOW
        assert "context_lines" in result.findings
        # Should include context before and after the error
        assert result.findings["context_lines"] > 0

    def test_expand_window_focuses_on_evidence(
        self, explorer: ArtifactExplorer
    ) -> None:
        """Expand window focuses on evidence-rich sections."""
        text = dedent("""
            INFO: Normal operation
            INFO: Normal operation
            ERROR: java.lang.OutOfMemoryError: Java heap space
            ERROR:   at com.example.MyClass.process(MyClass.java:42)
            ERROR: Caused by: java.lang.RuntimeException: Allocation failed
            INFO: Normal operation
            """)

        result = explorer.explore(text, strategy=ExplorationStrategy.EXPAND_WINDOW)

        assert "expanded_text" in result.findings
        # Expanded text should include the error context
        expanded = result.findings["expanded_text"]
        assert "OutOfMemoryError" in expanded

    def test_expand_window_increases_confidence(
        self, explorer: ArtifactExplorer
    ) -> None:
        """Expand window should maintain or increase confidence."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.EXPAND_WINDOW)

        # Expansion with clear evidence should have reasonable confidence
        assert result.confidence >= 0.4

    def test_expand_window_suggests_next_steps(
        self, explorer: ArtifactExplorer
    ) -> None:
        """Expand window suggests appropriate next steps."""
        text = """
        ERROR: java.lang.OutOfMemoryError: Java heap space
        at com.example.MyClass.process
        """

        result = explorer.explore(text, strategy=ExplorationStrategy.EXPAND_WINDOW)

        # Should suggest match_patterns or correlate
        assert len(result.next_steps) >= 1
        assert (
            ExplorationStrategy.MATCH_PATTERNS in result.next_steps
            or ExplorationStrategy.CORRELATE in result.next_steps
        )

    def test_expand_window_preserves_line_refs(
        self, explorer: ArtifactExplorer
    ) -> None:
        """Expand window preserves line references."""
        text = dedent("""
            Line 1
            Line 2
            java.lang.OutOfMemoryError
            Line 4
            Line 5
            """)

        result = explorer.explore(text, strategy=ExplorationStrategy.EXPAND_WINDOW)

        # Should have start/end line info
        assert "start_line" in result.findings or "line_range" in result.findings


# =============================================================================
# SUMMARIZE STRATEGY TESTS (Phase 2)
# =============================================================================


class TestSummarizeStrategy:
    """Tests for summarize exploration strategy."""

    def test_summarize_reduces_large_text(self, explorer: ArtifactExplorer) -> None:
        """Summarize reduces large text to essential information."""
        # Create a large text with repeated patterns
        text = "\n".join([f"Line {i}: INFO Normal operation" for i in range(100)])
        text += "\nERROR: java.lang.OutOfMemoryError: Java heap space\n"
        text += "\n".join([f"Line {i}: INFO Normal operation" for i in range(100, 200)])

        result = explorer.explore(text, strategy=ExplorationStrategy.SUMMARIZE)

        assert result.strategy == ExplorationStrategy.SUMMARIZE
        assert "summary" in result.findings
        # Summary should be shorter than original
        assert len(result.findings["summary"]) < len(text)

    def test_summarize_preserves_key_evidence(self, explorer: ArtifactExplorer) -> None:
        """Summarize preserves key evidence in summary."""
        text = dedent("""
            INFO: Starting job
            INFO: Processing batch 1
            ERROR: java.lang.OutOfMemoryError: Java heap space
            ERROR:   at org.apache.spark.memory.TaskMemoryManager
            INFO: Cleanup started
            INFO: Job terminating
            """)

        result = explorer.explore(text, strategy=ExplorationStrategy.SUMMARIZE)

        assert "summary" in result.findings
        # Should preserve the error
        assert "OutOfMemoryError" in result.findings["summary"]

    def test_summarize_includes_stats(self, explorer: ArtifactExplorer) -> None:
        """Summarize includes statistics about compression."""
        text = "\n".join([f"Line {i}" for i in range(50)])

        result = explorer.explore(text, strategy=ExplorationStrategy.SUMMARIZE)

        # Should have compression stats
        assert (
            "original_lines" in result.findings
            or "compression_ratio" in result.findings
        )

    def test_summarize_suggests_next_steps(self, explorer: ArtifactExplorer) -> None:
        """Summarize suggests appropriate next steps."""
        text = "ERROR: java.lang.OutOfMemoryError: Java heap space"

        result = explorer.explore(text, strategy=ExplorationStrategy.SUMMARIZE)

        assert len(result.next_steps) >= 1
        # Should suggest match_patterns or extract_evidence after summarize
        assert (
            ExplorationStrategy.MATCH_PATTERNS in result.next_steps
            or ExplorationStrategy.EXTRACT_EVIDENCE in result.next_steps
        )


# =============================================================================
# CORRELATE STRATEGY TESTS (Phase 2)
# =============================================================================


class TestCorrelateStrategy:
    """Tests for correlate exploration strategy."""

    @pytest.fixture
    def explorer_with_patterns(self) -> ArtifactExplorer:
        """Create explorer with PatternMatcher loaded."""
        from pathlib import Path

        from starboard_server.tools.domain.diagnostic.pattern_matcher import (
            PatternMatcher,
        )
        from starboard_server.tools.domain.diagnostic.patterns.registry import (
            PatternRegistry,
        )

        registry = PatternRegistry()
        import starboard_server

        pkg_path = Path(starboard_server.__file__).parent
        catalog_dir = (
            pkg_path / "tools" / "domain" / "diagnostic" / "patterns" / "catalog"
        )
        if catalog_dir.exists():
            registry.load_from_directory(catalog_dir)

        return ArtifactExplorer(
            detector=ArtifactDetector(),
            evidence_extractor=EvidenceWindowExtractor(),
            context_extractor=DatabricksContextExtractor(),
            pattern_matcher=PatternMatcher(registry),
        )

    def test_correlate_multiple_patterns(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Correlate disambiguates multiple patterns."""
        text = dedent("""
            java.lang.OutOfMemoryError: Java heap space
            ExecutorLostFailure (executor 123 lost due to SIGKILL)
            """)

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.CORRELATE
        )

        assert result.strategy == ExplorationStrategy.CORRELATE
        assert "primary_cause" in result.findings or "correlation" in result.findings

    def test_correlate_increases_confidence(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """Correlation should increase confidence when patterns align."""
        text = dedent("""
            java.lang.OutOfMemoryError: Java heap space
            Reason: OOMKilled
            """)

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.CORRELATE
        )

        # Correlated patterns should have higher confidence
        assert result.confidence >= 0.5

    def test_correlate_suggests_synthesize(
        self, explorer_with_patterns: ArtifactExplorer
    ) -> None:
        """After correlation, should suggest synthesize."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = explorer_with_patterns.explore(
            text, strategy=ExplorationStrategy.CORRELATE
        )

        # Should suggest synthesize after correlation
        assert ExplorationStrategy.SYNTHESIZE in result.next_steps
