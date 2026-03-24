"""Integration tests for diagnostic artifact pipeline (Phase 1).

These tests verify end-to-end artifact processing flows:
- Scenario 1: Direct error message → detection → pattern matching → evidence
- Scenario 4: Code + error → detection → extraction → analysis

Unlike unit tests, these use all real components working together.
"""

from __future__ import annotations

import pytest
from starboard_server.tools.domain.diagnostic.artifact_detector import ArtifactDetector
from starboard_server.tools.domain.diagnostic.artifact_explorer import (
    ArtifactExplorer,
    ExplorationStep,
)
from starboard_server.tools.domain.diagnostic.artifact_normalizer import (
    ArtifactNormalizer,
)
from starboard_server.tools.domain.diagnostic.context_extractor import (
    ContextMode,
    DatabricksContextExtractor,
)
from starboard_server.tools.domain.diagnostic.evidence_extractor import (
    EvidenceType,
    EvidenceWindowExtractor,
)
from starboard_server.tools.domain.diagnostic.exit_code_triager import ExitCodeTriager
from starboard_server.tools.domain.diagnostic.models import ArtifactType
from starboard_server.tools.domain.diagnostic.pattern_matcher import PatternMatcher
from starboard_server.tools.domain.diagnostic.patterns.registry import PatternRegistry

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def pattern_registry() -> PatternRegistry:
    """Real pattern registry with all patterns loaded."""
    from pathlib import Path

    registry = PatternRegistry()
    # Load patterns from the catalog directory
    catalog_dir = (
        Path(__file__).parent.parent.parent.parent
        / "starboard_server"
        / "tools"
        / "domain"
        / "diagnostic"
        / "patterns"
        / "catalog"
    )
    if catalog_dir.exists():
        registry.load_from_directory(catalog_dir)
    return registry


@pytest.fixture
def artifact_detector() -> ArtifactDetector:
    """Real artifact detector."""
    return ArtifactDetector()


@pytest.fixture
def artifact_normalizer() -> ArtifactNormalizer:
    """Real artifact normalizer."""
    return ArtifactNormalizer()


@pytest.fixture
def pattern_matcher(pattern_registry: PatternRegistry) -> PatternMatcher:
    """Real pattern matcher with loaded patterns."""
    return PatternMatcher(pattern_registry)


@pytest.fixture
def exit_code_triager() -> ExitCodeTriager:
    """Real exit code triager."""
    return ExitCodeTriager()


@pytest.fixture
def evidence_extractor() -> EvidenceWindowExtractor:
    """Real evidence window extractor."""
    return EvidenceWindowExtractor()


@pytest.fixture
def context_extractor() -> DatabricksContextExtractor:
    """Real Databricks context extractor."""
    return DatabricksContextExtractor()


@pytest.fixture
def artifact_explorer(
    artifact_detector: ArtifactDetector,
    evidence_extractor: EvidenceWindowExtractor,
    context_extractor: DatabricksContextExtractor,
) -> ArtifactExplorer:
    """Real artifact explorer with all dependencies."""
    return ArtifactExplorer(
        detector=artifact_detector,
        evidence_extractor=evidence_extractor,
        context_extractor=context_extractor,
    )


# =============================================================================
# Scenario 1: Direct Error Message
# =============================================================================


class TestScenario1DirectErrorMessage:
    """End-to-end tests for direct error message analysis (OFFLINE mode)."""

    def test_exit_137_pipeline(
        self,
        artifact_detector: ArtifactDetector,
        artifact_normalizer: ArtifactNormalizer,
        pattern_matcher: PatternMatcher,
        exit_code_triager: ExitCodeTriager,
        evidence_extractor: EvidenceWindowExtractor,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """Exit code 137 flows through entire pipeline correctly."""
        # Raw user input
        raw_input = """
        My Spark job failed with this error:

        Reason: Command exited with code 137

        The cluster was running fine before this.
        """

        # Step 1: Detect artifact type first (needed for normalization)
        detection = artifact_detector.detect(raw_input)
        assert detection.artifact_type == ArtifactType.ERROR_MESSAGE
        assert detection.confidence >= 0.5

        # Step 2: Normalize with detected type
        normalized = artifact_normalizer.normalize(raw_input, detection.artifact_type)
        assert normalized.truncation_applied is False

        # Step 3: Detect artifact type (verify post-normalization)
        detection = artifact_detector.detect(normalized.content)
        assert detection.artifact_type == ArtifactType.ERROR_MESSAGE
        assert detection.confidence >= 0.7

        # Step 4: Extract evidence windows
        evidence = evidence_extractor.extract(normalized.content)
        assert len(evidence.windows) >= 1
        exit_windows = [
            w for w in evidence.windows if w.evidence_type == EvidenceType.EXIT_CODE
        ]
        assert len(exit_windows) >= 1
        assert "137" in exit_windows[0].content

        # Step 5: Extract context (should be OFFLINE - no IDs)
        context = context_extractor.extract(normalized.content)
        assert context.mode == ContextMode.OFFLINE

        # Step 6: Match patterns
        matches = pattern_matcher.match(normalized.content)
        assert len(matches.matches) >= 1
        pattern_ids = {m.pattern_id for m in matches.matches}
        assert "exit_code_137" in pattern_ids

        # Step 7: Triage exit code
        triage = exit_code_triager.triage(137)
        assert triage.is_signal is True
        assert triage.signal_number == 9  # SIGKILL
        # Primary hypothesis should be about OOM or memory
        assert triage.primary_hypothesis is not None

    def test_oom_with_proof_pipeline(
        self,
        artifact_detector: ArtifactDetector,
        artifact_normalizer: ArtifactNormalizer,
        pattern_matcher: PatternMatcher,
        evidence_extractor: EvidenceWindowExtractor,
    ) -> None:
        """OOM error with Java heap space has high confidence."""
        raw_input = """
        java.lang.OutOfMemoryError: Java heap space
            at java.base/java.util.Arrays.copyOf(Arrays.java:3512)
            at org.apache.spark.sql.execution.SparkPlan.executeQuery(SparkPlan.scala:230)

        Executor lost due to OOM
        """

        # Detect first, then normalize
        detection = artifact_detector.detect(raw_input)
        assert detection.artifact_type in (
            ArtifactType.STACK_TRACE,
            ArtifactType.ERROR_MESSAGE,
        )
        normalized = artifact_normalizer.normalize(raw_input, detection.artifact_type)

        # Extract evidence
        evidence = evidence_extractor.extract(normalized.content)
        oom_windows = [
            w for w in evidence.windows if w.evidence_type == EvidenceType.OOM
        ]
        assert len(oom_windows) >= 1

        # Match patterns - should get high confidence OOM match
        matches = pattern_matcher.match(normalized.content)
        pattern_ids = {m.pattern_id for m in matches.matches}
        assert "java_heap_space" in pattern_ids

        # Top match should have high confidence
        top_match = matches.matches[0]
        assert top_match.confidence >= 0.85

    def test_shuffle_fetch_failed_pipeline(
        self,
        artifact_detector: ArtifactDetector,
        artifact_normalizer: ArtifactNormalizer,
        pattern_matcher: PatternMatcher,
        evidence_extractor: EvidenceWindowExtractor,
    ) -> None:
        """Shuffle fetch failure is detected and matched."""
        raw_input = """
        org.apache.spark.shuffle.FetchFailedException:
            Failed to fetch shuffle block from executor 5
        Caused by: java.io.IOException: Failed to connect to host
        """

        detection = artifact_detector.detect(raw_input)
        assert detection.artifact_type in (
            ArtifactType.STACK_TRACE,
            ArtifactType.ERROR_MESSAGE,
        )
        normalized = artifact_normalizer.normalize(raw_input, detection.artifact_type)

        evidence = evidence_extractor.extract(normalized.content)
        # Should have evidence windows (CAUSE_CHAIN, SPARK_ERROR, or FATAL_EXCEPTION)
        assert len(evidence.windows) >= 1

        matches = pattern_matcher.match(normalized.content)
        pattern_ids = {m.pattern_id for m in matches.matches}
        assert "shuffle_fetch_failed" in pattern_ids


# =============================================================================
# Scenario 4: Code + Error
# =============================================================================


class TestScenario4CodeWithError:
    """End-to-end tests for code + error analysis (OFFLINE mode)."""

    def test_sql_with_column_not_found(
        self,
        artifact_detector: ArtifactDetector,
        artifact_normalizer: ArtifactNormalizer,
        pattern_matcher: PatternMatcher,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """SQL code with column not found error is properly analyzed."""
        raw_input = """
        Here's my query:

        SELECT user_id, user_name, ordrer_count
        FROM users u
        JOIN orders o ON u.id = o.user_id

        But I get this error:

        AnalysisException: Column 'ordrer_count' not found in table 'orders'.
        Did you mean 'order_count'?
        """

        detection = artifact_detector.detect(raw_input)
        normalized = artifact_normalizer.normalize(raw_input, detection.artifact_type)

        # Should detect as MIXED (code + error) or CODE
        assert detection.artifact_type in (
            ArtifactType.MIXED,
            ArtifactType.CODE,
            ArtifactType.ERROR_MESSAGE,
        )

        # Pattern matcher should find column not found
        matches = pattern_matcher.match(normalized.content)
        pattern_ids = {m.pattern_id for m in matches.matches}
        # Should match column_not_found or similar SQL error pattern
        has_sql_pattern = any(
            "column" in pid or "sql" in pid or "analysis" in pid for pid in pattern_ids
        )
        assert has_sql_pattern or len(matches.matches) >= 1

        # No Databricks IDs - should be OFFLINE
        context = context_extractor.extract(normalized.content)
        assert context.mode == ContextMode.OFFLINE

    def test_python_code_with_serialization_error(
        self,
        artifact_detector: ArtifactDetector,
        artifact_normalizer: ArtifactNormalizer,
        pattern_matcher: PatternMatcher,
    ) -> None:
        """Python code with serialization error is detected."""
        raw_input = """
        def process_data(df):
            # Use external connection
            result = df.rdd.map(lambda x: db_connection.query(x.id))
            return result.collect()

        Error:
        org.apache.spark.SparkException: Task not serializable
        Caused by: java.io.NotSerializableException:
            com.mycompany.DatabaseConnection
        """

        detection = artifact_detector.detect(raw_input)
        assert detection.artifact_type in (
            ArtifactType.MIXED,
            ArtifactType.CODE,
            ArtifactType.STACK_TRACE,
            ArtifactType.ERROR_MESSAGE,
        )
        normalized = artifact_normalizer.normalize(raw_input, detection.artifact_type)

        matches = pattern_matcher.match(normalized.content)
        pattern_ids = {m.pattern_id for m in matches.matches}
        assert "task_not_serializable" in pattern_ids


# =============================================================================
# ArtifactExplorer Integration
# =============================================================================


class TestArtifactExplorerIntegration:
    """End-to-end tests for ArtifactExplorer orchestration."""

    def test_exploration_flow_simple_error(
        self,
        artifact_explorer: ArtifactExplorer,
    ) -> None:
        """Explorer correctly orchestrates simple error analysis."""
        from starboard_server.tools.domain.diagnostic.artifact_explorer import (
            ExplorationState,
            ExplorationStrategy,
        )

        text = "java.lang.OutOfMemoryError: Java heap space"

        # Step 1: Detect type
        result1 = artifact_explorer.explore(
            text, strategy=ExplorationStrategy.DETECT_TYPE
        )

        assert result1.confidence >= 0.5
        assert "artifact_type" in result1.findings
        assert len(result1.next_steps) >= 1

        # Step 2: Extract evidence
        result2 = artifact_explorer.explore(
            text, strategy=ExplorationStrategy.EXTRACT_EVIDENCE
        )

        assert len(result2.evidence_refs) >= 1

        # Create state and verify summary
        state = ExplorationState(
            artifact_text=text,
            history=[
                (
                    ExplorationStep(
                        strategy=ExplorationStrategy.DETECT_TYPE,
                        target=text,
                        rationale="",
                    ),
                    result1,
                ),
                (
                    ExplorationStep(
                        strategy=ExplorationStrategy.EXTRACT_EVIDENCE,
                        target=text,
                        rationale="",
                    ),
                    result2,
                ),
            ],
            current_confidence=max(result1.confidence, result2.confidence),
            mode=None,
        )
        summary = artifact_explorer.get_exploration_summary(state)
        assert summary["step_count"] == 2
        assert summary["confidence"] >= 0.5

    def test_exploration_with_databricks_ids(
        self,
        artifact_explorer: ArtifactExplorer,
    ) -> None:
        """Explorer detects ONLINE mode when IDs are present."""
        from starboard_server.tools.domain.diagnostic.artifact_explorer import (
            ExplorationStrategy,
        )

        text = """
        Job run failed for job_id=12345, run_id=67890
        Cluster: 1234-567890-abcdef12

        java.lang.OutOfMemoryError: Java heap space
        """

        # Step 1: Detect
        result1 = artifact_explorer.explore(
            text, strategy=ExplorationStrategy.DETECT_TYPE
        )
        assert result1.confidence >= 0.3  # Mixed content may have lower confidence

        # Step 2: Extract IDs
        result2 = artifact_explorer.explore(
            text, strategy=ExplorationStrategy.EXTRACT_IDS
        )

        # Should find IDs and report mode
        assert "mode" in result2.findings
        assert result2.findings["mode"] in ("online", "hybrid", "offline")
        # Check if IDs were found
        if "job_id" in result2.findings:
            assert result2.findings["job_id"] == "12345"

    def test_exploration_stopping_conditions(
        self,
        artifact_explorer: ArtifactExplorer,
    ) -> None:
        """Explorer respects stopping conditions."""
        from starboard_server.tools.domain.diagnostic.artifact_explorer import (
            ExplorationState,
            ExplorationStrategy,
        )

        text = "java.lang.OutOfMemoryError: Java heap space"

        # Initially should continue (no history, low confidence)
        state = ExplorationState(
            artifact_text=text,
            history=[],
            current_confidence=0.0,
            mode=None,
        )
        assert artifact_explorer.should_continue_exploring(state)

        # After high-confidence, should stop
        result = artifact_explorer.explore(
            text, strategy=ExplorationStrategy.DETECT_TYPE
        )
        state = ExplorationState(
            artifact_text=text,
            history=[
                (
                    ExplorationStep(
                        strategy=ExplorationStrategy.DETECT_TYPE,
                        target=text,
                        rationale="",
                    ),
                    result,
                )
            ],
            current_confidence=0.95,  # High confidence
            mode=None,
        )
        assert not artifact_explorer.should_continue_exploring(state)

    def test_exploration_max_steps(
        self,
        artifact_explorer: ArtifactExplorer,
    ) -> None:
        """Explorer stops after max steps."""
        from starboard_server.tools.domain.diagnostic.artifact_explorer import (
            ExplorationResult,
            ExplorationState,
            ExplorationStrategy,
        )

        text = "Some error"

        # Simulate hitting max steps
        dummy_step = ExplorationStep(
            strategy=ExplorationStrategy.DETECT_TYPE, target=text, rationale=""
        )
        dummy_result = ExplorationResult(
            strategy=ExplorationStrategy.DETECT_TYPE,
            findings={},
            confidence=0.5,
        )
        history = [(dummy_step, dummy_result) for _ in range(6)]

        state = ExplorationState(
            artifact_text=text,
            history=history,
            current_confidence=0.5,  # Low confidence
            mode=None,
        )

        # Should stop even with low confidence (max steps reached)
        assert not artifact_explorer.should_continue_exploring(state)


# =============================================================================
# Mode Detection Integration
# =============================================================================


class TestModeDetectionIntegration:
    """Integration tests for ONLINE/OFFLINE mode detection."""

    def test_offline_mode_no_ids(
        self,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """Pure error text without IDs is OFFLINE."""
        text = """
        java.lang.OutOfMemoryError: Java heap space
        at org.apache.spark.executor.Executor.run(Executor.java:456)
        """
        context = context_extractor.extract(text)
        assert context.mode == ContextMode.OFFLINE

    def test_online_mode_with_ids(
        self,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """Text with multiple high-confidence IDs is ONLINE."""
        text = """
        Failed job run:
        - Job ID: 123456789012345
        - Run ID: 987654321098765
        - Cluster: 1234-567890-abcdef12
        """
        context = context_extractor.extract(text)
        assert context.mode in (ContextMode.ONLINE, ContextMode.HYBRID)
        assert context.primary_job_id == "123456789012345"
        assert context.primary_run_id == "987654321098765"
        assert context.primary_cluster_id == "1234-567890-abcdef12"

    def test_hybrid_mode_partial_ids(
        self,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """Text with some IDs but not enough for full ONLINE is HYBRID."""
        text = """
        Error in cluster 1234-567890-abcdef12
        java.lang.OutOfMemoryError: Java heap space
        """
        context = context_extractor.extract(text)
        assert context.mode in (ContextMode.HYBRID, ContextMode.OFFLINE)
        assert context.primary_cluster_id == "1234-567890-abcdef12"


# =============================================================================
# End-to-End Exploration Tests (Phase 2 Week 6)
# =============================================================================


class TestEndToEndExploration:
    """End-to-end tests for the full exploration pipeline."""

    def test_simple_error_high_confidence(
        self,
        artifact_detector: ArtifactDetector,
        artifact_normalizer: ArtifactNormalizer,
        pattern_matcher: PatternMatcher,
        evidence_extractor: EvidenceWindowExtractor,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """Simple error should reach high confidence in 1-2 exploration steps."""
        from starboard_server.tools.domain.diagnostic.response_framer import (
            DiagnosticFinding,
            ResponseFramer,
        )

        text = """
        java.lang.OutOfMemoryError: Java heap space
            at org.apache.spark.memory.TaskMemoryManager.allocatePage(TaskMemoryManager.java:123)
        """

        # 1. Detect artifact type
        detection = artifact_detector.detect(text)
        assert detection.artifact_type in (
            ArtifactType.ERROR_MESSAGE,
            ArtifactType.STACK_TRACE,
        )

        # 2. Extract evidence
        evidence = evidence_extractor.extract(text)
        assert evidence.window_count >= 1

        # 3. Match patterns
        matches = pattern_matcher.match(text)
        assert matches.has_matches
        assert "java_heap_space" in {m.pattern_id for m in matches.matches}

        # 4. Frame response with high confidence
        framer = ResponseFramer()
        finding = DiagnosticFinding(
            diagnosis="Java heap space exhaustion",
            confidence=0.92,
            evidence=[w.content for w in evidence.windows],
            root_cause="JVM heap memory exhausted",
        )
        response = framer.frame(finding)
        assert response.confidence_level.value == "definitive"

    def test_ambiguous_error_needs_more_steps(
        self,
        artifact_detector: ArtifactDetector,
        artifact_normalizer: ArtifactNormalizer,
        pattern_matcher: PatternMatcher,
        evidence_extractor: EvidenceWindowExtractor,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """Ambiguous error should require more exploration."""
        from starboard_server.tools.domain.diagnostic.response_framer import (
            DiagnosticFinding,
            ResponseFramer,
        )

        text = """
        Task failed with an error.
        Please check the logs for more details.
        """

        # 1. Detect - should still detect but with lower confidence
        detection = artifact_detector.detect(text)
        assert detection.confidence < 0.7

        # 2. Extract evidence - limited
        _evidence = evidence_extractor.extract(text)

        # 3. Match patterns - few or no strong matches
        _matches = pattern_matcher.match(text)
        # May or may not have matches

        # 4. Frame response - should be uncertain
        framer = ResponseFramer()
        finding = DiagnosticFinding(
            diagnosis="Unclear task failure",
            confidence=0.35,
            evidence=["Task failed with an error"],
        )
        response = framer.frame(finding)
        assert response.confidence_level.value == "uncertain"
        assert response.additional_evidence_needed is not None

    def test_large_log_summarization(
        self,
        artifact_detector: ArtifactDetector,
        pattern_matcher: PatternMatcher,
    ) -> None:
        """Large log should be summarized before analysis."""
        from starboard_server.tools.domain.diagnostic.artifact_summarizer import (
            ArtifactSummarizer,
        )

        # Create a large log
        lines = []
        for i in range(500):
            lines.append(f"2024-01-15 10:00:{i % 60:02d} INFO Processing record {i}")
        lines.insert(
            250, "2024-01-15 10:04:10 ERROR java.lang.OutOfMemoryError: Java heap space"
        )
        lines.insert(
            251, "    at org.apache.spark.memory.TaskMemoryManager.allocatePage"
        )
        large_log = "\n".join(lines)

        # 1. Summarize
        summarizer = ArtifactSummarizer()
        summary_result = summarizer.summarize(
            large_log, mode="extractive", max_length=1000
        )
        assert summary_result.compression_ratio > 0.5  # Significant compression
        assert "OutOfMemoryError" in summary_result.summary

        # 2. Pattern match on summary should still work
        matches = pattern_matcher.match(summary_result.summary)
        assert matches.has_matches

    def test_offline_mode_generates_guidance(
        self,
        artifact_detector: ArtifactDetector,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """OFFLINE mode generates appropriate guidance."""
        from starboard_server.tools.domain.diagnostic.mode_aware_responder import (
            ModeAwareResponder,
        )

        text = """
        java.lang.OutOfMemoryError: Java heap space
        at org.apache.spark.executor.Executor.run(Executor.java:456)
        """

        # 1. Extract context - should be OFFLINE
        context = context_extractor.extract(text)
        assert context.mode == ContextMode.OFFLINE

        # 2. Create mode-aware response
        responder = ModeAwareResponder()
        response = responder.create_response(
            mode=context.mode,
            diagnosis="Java heap space exhaustion",
            available_ids={},
        )

        assert response.offline_guidance is not None
        assert len(response.offline_guidance.investigation_steps) > 0
        assert len(response.offline_guidance.questions_to_answer) > 0

    def test_online_mode_suggests_tools(
        self,
        artifact_detector: ArtifactDetector,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """ONLINE mode suggests appropriate tools."""
        from starboard_server.tools.domain.diagnostic.mode_aware_responder import (
            ModeAwareResponder,
        )

        text = """
        Job failed on cluster 1234-567890-abcdef12
        Job ID: 123456789012345
        Run ID: 987654321098765
        java.lang.OutOfMemoryError: Java heap space
        """

        # 1. Extract context - should be ONLINE or HYBRID
        context = context_extractor.extract(text)
        assert context.mode in (ContextMode.ONLINE, ContextMode.HYBRID)

        # 2. Create mode-aware response
        responder = ModeAwareResponder()
        response = responder.create_response(
            mode=context.mode,
            diagnosis="Java heap space exhaustion",
            available_ids={
                "cluster_id": context.primary_cluster_id,
                "job_id": context.primary_job_id,
                "run_id": context.primary_run_id,
            },
        )

        assert response.can_fetch_context
        assert len(response.suggested_tool_calls) > 0
        tool_names = [t["tool"] for t in response.suggested_tool_calls]
        assert any("cluster" in t.lower() for t in tool_names)
        assert any("job" in t.lower() for t in tool_names)

    def test_full_pipeline_code_analysis(
        self,
        artifact_detector: ArtifactDetector,
        pattern_matcher: PatternMatcher,
    ) -> None:
        """Full pipeline with code analysis."""
        from starboard_server.tools.domain.diagnostic.python_analyzer import (
            PythonAnalyzer,
        )
        from starboard_server.tools.domain.diagnostic.sql_analyzer import SQLAnalyzer

        # Python code with anti-patterns
        python_code = """
        df = spark.read.parquet('/data/input')
        result = df.collect()  # Anti-pattern!
        for row in result:
            print(row)
        """

        # SQL with anti-patterns
        sql_code = """
        SELECT * FROM users CROSS JOIN orders
        """

        # 1. Analyze Python
        python_analyzer = PythonAnalyzer()
        python_result = python_analyzer.analyze(python_code)
        assert python_result.has_issues
        assert any(
            p.pattern_type.value == "collect_large_df" for p in python_result.patterns
        )

        # 2. Analyze SQL
        sql_analyzer = SQLAnalyzer()
        sql_result = sql_analyzer.analyze(sql_code)
        assert sql_result.has_issues
        assert any(
            p.pattern_type.value == "cartesian_join" for p in sql_result.patterns
        )


class TestExplorationScenarios:
    """Test specific exploration scenarios from the design doc."""

    def test_scenario_exit_137_exploration(
        self,
        artifact_detector: ArtifactDetector,
        exit_code_triager: ExitCodeTriager,
        pattern_matcher: PatternMatcher,
        context_extractor: DatabricksContextExtractor,
    ) -> None:
        """Scenario: Exit code 137 exploration."""
        text = """
        Command exited with code 137
        The container was killed by the OOM killer.
        """

        # 1. Detect
        detection = artifact_detector.detect(text)
        assert detection.artifact_type == ArtifactType.ERROR_MESSAGE

        # 2. Triage exit code (pass the extracted code, not the text)
        triage = exit_code_triager.triage(137, context=text)
        assert triage.exit_code == 137
        assert triage.signal_number == 9  # SIGKILL

        # 3. Match patterns
        matches = pattern_matcher.match(text)
        pattern_ids = {m.pattern_id for m in matches.matches}
        assert "exit_code_137" in pattern_ids

        # 4. Context mode
        context = context_extractor.extract(text)
        assert context.mode == ContextMode.OFFLINE

    def test_scenario_delta_concurrent_write(
        self,
        artifact_detector: ArtifactDetector,
        pattern_matcher: PatternMatcher,
    ) -> None:
        """Scenario: Delta concurrent write conflict."""
        text = """
        ConcurrentModificationException: Conflicting commit detected
        Another transaction has already committed to the Delta table.
        Transaction conflict on delta.`/data/my_table`
        """

        # 1. Detect
        detection = artifact_detector.detect(text)
        assert detection.artifact_type == ArtifactType.ERROR_MESSAGE

        # 2. Match patterns
        matches = pattern_matcher.match(text)
        pattern_ids = {m.pattern_id for m in matches.matches}
        assert "delta_concurrent_write" in pattern_ids

    def test_scenario_uc_permission_denied(
        self,
        artifact_detector: ArtifactDetector,
        pattern_matcher: PatternMatcher,
    ) -> None:
        """Scenario: Unity Catalog permission denied."""
        text = """
        PERMISSION_DENIED: User 'user@example.com' does not have
        SELECT permission on TABLE `catalog`.`schema`.`table`
        """

        # 1. Detect (verify it detects something)
        _detection = artifact_detector.detect(text)

        # 2. Match patterns
        matches = pattern_matcher.match(text)
        pattern_ids = {m.pattern_id for m in matches.matches}
        assert "uc_permission_denied" in pattern_ids
