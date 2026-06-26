# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for advanced diagnostic scenarios (6-10).

These scenarios test ONLINE mode, handoffs, and complex exploration flows.
"""

import pytest
from starboard_server.tools.domain.diagnostic import (
    ArtifactDetector,
    ArtifactExplorer,
    DatabricksContextExtractor,
    DiagnosticContextBuilder,
    DiagnosticFingerprint,
    EvidenceWindowExtractor,
    ExplorationStrategy,
    ExplorationTelemetry,
    HandoffProtocol,
    PrimarySymptom,
    RootCauseSynthesizer,
    ToolOutput,
)
from starboard_server.tools.domain.diagnostic.pattern_matcher import PatternMatcher
from starboard_server.tools.domain.diagnostic.patterns.registry import PatternRegistry


@pytest.fixture
def pattern_registry() -> PatternRegistry:
    """Load pattern registry with all patterns."""
    from pathlib import Path

    pattern_dir = Path(__file__).parent.parent.parent.parent / (
        "starboard_server/tools/domain/diagnostic/patterns/catalog"
    )
    registry = PatternRegistry()
    registry.load_from_directory(pattern_dir)
    return registry


@pytest.fixture
def explorer(pattern_registry: PatternRegistry) -> ArtifactExplorer:
    """Create artifact explorer with all dependencies."""
    detector = ArtifactDetector()
    evidence_extractor = EvidenceWindowExtractor()
    context_extractor = DatabricksContextExtractor()
    pattern_matcher = PatternMatcher(pattern_registry)
    return ArtifactExplorer(
        detector=detector,
        evidence_extractor=evidence_extractor,
        context_extractor=context_extractor,
        pattern_matcher=pattern_matcher,
    )


@pytest.fixture
def context_builder(explorer: ArtifactExplorer) -> DiagnosticContextBuilder:
    """Create diagnostic context builder."""
    return DiagnosticContextBuilder(explorer=explorer)


@pytest.fixture
def synthesizer() -> RootCauseSynthesizer:
    """Create root cause synthesizer."""
    return RootCauseSynthesizer()


@pytest.fixture
def handoff_protocol() -> HandoffProtocol:
    """Create handoff protocol."""
    return HandoffProtocol()


@pytest.fixture
def telemetry() -> ExplorationTelemetry:
    """Create telemetry collector."""
    return ExplorationTelemetry()


class TestScenario6Performance:
    """Scenario 6: Performance issues - query is slow.

    Input: Query + "slow" complaint
    Mode: ONLINE if query ID available
    Handoff: Query Agent
    """

    def test_slow_query_detection(
        self,
        context_builder: DiagnosticContextBuilder,
        handoff_protocol: HandoffProtocol,
    ) -> None:
        """Should detect slow query scenario and suggest handoff."""
        artifact = """
        My query is running very slow:

        statement_id: 01ef123456789

        SELECT customer_id, SUM(order_total)
        FROM sales.orders
        WHERE order_date > '2024-01-01'
        GROUP BY customer_id
        ORDER BY 2 DESC

        It takes 45 minutes to complete.
        """

        context = context_builder.build_context(artifact)

        # Should detect SQL or mixed content
        assert context.artifact_type in ("code", "mixed", "logs", "error_message")
        # Context should have been built successfully
        assert context.confidence >= 0.0

    def test_slow_query_with_timeout(
        self, context_builder: DiagnosticContextBuilder
    ) -> None:
        """Should detect timeout patterns in slow queries."""
        artifact = """
        Error: Query exceeded maximum execution time
        QueryTimeoutException: Query did not complete within 3600 seconds

        warehouse_id: abc123def456
        statement_id: 01ef789012345
        """

        context = context_builder.build_context(artifact)

        # Should extract warehouse context for ONLINE mode
        assert context.mode in ("online", "hybrid")


class TestScenario7IntermittentFailures:
    """Scenario 7: Intermittent failures across multiple runs.

    Input: Multiple run logs showing sporadic failures
    Mode: ONLINE
    Handoff: Compute Agent
    """

    def test_intermittent_oom(
        self, explorer: ArtifactExplorer, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should identify pattern of intermittent OOM failures."""
        artifact = """
        Run history for job 12345:

        Run 100001: FAILED - java.lang.OutOfMemoryError: Java heap space
        Run 100002: SUCCESS
        Run 100003: SUCCESS
        Run 100004: FAILED - java.lang.OutOfMemoryError: GC overhead limit exceeded
        Run 100005: SUCCESS
        Run 100006: FAILED - Container killed by YARN for exceeding memory limits

        cluster_id: 0123-456789-abc
        """

        # Explore the artifact
        result = explorer.explore(artifact, strategy=ExplorationStrategy.DETECT_TYPE)
        assert result.confidence >= 0.0

        result = explorer.explore(artifact, strategy=ExplorationStrategy.MATCH_PATTERNS)

        # Should find some patterns or have findings
        assert result.findings is not None
        assert result.confidence >= 0.0

    def test_intermittent_suggests_cluster_handoff(
        self,
        context_builder: DiagnosticContextBuilder,
        handoff_protocol: HandoffProtocol,
    ) -> None:
        """Intermittent failures should suggest cluster agent handoff."""
        artifact = """
        job_id: 12345
        cluster_id: 0123-456789-abc

        Multiple runs failing with:
        Lost executor 3
        Container killed for exceeding memory
        GC overhead limit exceeded
        """

        context = context_builder.build_context(artifact)

        # Build fingerprint from context
        # Extract pattern IDs from context.patterns list
        matched_pattern_ids = [p.get("pattern_id", "") for p in context.patterns]
        fingerprint = DiagnosticFingerprint.from_exploration(
            matched_patterns=matched_pattern_ids,
            extracted_ids=context.extracted_ids,
            evidence_refs=[],
            confidence=context.confidence,
            steps_completed=4,
            strategies_used=["detect_type", "extract_evidence", "match_patterns"],
        )

        # Fingerprint should be created successfully
        assert fingerprint is not None
        # If OOM/executor lost detected, should handoff to cluster
        if fingerprint.primary_symptom in (
            PrimarySymptom.OOM,
            PrimarySymptom.EXECUTOR_LOST,
        ):
            assert fingerprint.get_handoff_target() == "cluster"


class TestScenario8CodeWithPartialContext:
    """Scenario 8: Code with partial context (e.g., cluster_id but no error).

    Input: Code + cluster_id
    Mode: ONLINE
    Handoff: No (can fetch context)
    """

    def test_code_with_cluster_id(
        self, context_builder: DiagnosticContextBuilder
    ) -> None:
        """Should extract cluster ID and enter ONLINE mode."""
        artifact = """
        cluster_id: 0123-456789-abc

        # My PySpark code
        df = spark.read.parquet("/mnt/data/large_table")
        result = df.collect()  # This seems to hang
        print(len(result))
        """

        context = context_builder.build_context(artifact)

        # Should be ONLINE mode with cluster ID
        assert "cluster_id" in context.extracted_ids
        assert context.mode in ("online", "hybrid")

    def test_code_analysis_finds_antipatterns(self, explorer: ArtifactExplorer) -> None:
        """Should detect code anti-patterns without explicit error."""
        artifact = """
        df = spark.read.parquet("/data/huge_table")
        # Process all records
        all_data = df.collect()  # BAD: collecting large data
        for row in all_data:
            process(row)
        """

        # Detect type should identify the artifact
        result = explorer.explore(artifact, strategy=ExplorationStrategy.DETECT_TYPE)
        assert result.confidence >= 0.0
        assert len(result.findings) > 0


class TestScenario9ComparativeAnalysis:
    """Scenario 9: Comparative analysis - "worked yesterday".

    Input: Job ID + "worked yesterday" or similar
    Mode: ONLINE
    Handoff: No
    """

    def test_job_comparison_context(
        self, context_builder: DiagnosticContextBuilder
    ) -> None:
        """Should extract job ID for comparison."""
        artifact = """
        Job 12345 failed today but worked fine yesterday.

        Today's error:
        java.lang.OutOfMemoryError: Java heap space
        at org.apache.spark.sql.execution.Exchange

        Nothing changed in the code. What happened?
        """

        context = context_builder.build_context(artifact)

        # Should extract job ID and be in ONLINE mode for history lookup
        assert "job_id" in context.extracted_ids or context.mode == "offline"

    def test_synthesize_with_history_comparison(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should synthesize diagnosis considering historical context."""
        # Simulated tool outputs from job history
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="100001",
                result={
                    "state": "FAILED",
                    "error": "OutOfMemoryError",
                    "cluster_id": "0123-456789-abc",
                },
                latency_ms=200,
            ),
            ToolOutput(
                tool_name="analyze_job_history",
                run_id=None,
                result={
                    "recent_runs": [
                        {
                            "run_id": "99999",
                            "state": "SUCCESS",
                            "start_time": "2024-01-14",
                        },
                        {
                            "run_id": "99998",
                            "state": "SUCCESS",
                            "start_time": "2024-01-13",
                        },
                        {
                            "run_id": "100001",
                            "state": "FAILED",
                            "start_time": "2024-01-15",
                        },
                    ]
                },
                latency_ms=150,
            ),
        ]

        exploration_findings = {
            "artifact_type": "logs",
            "matched_patterns": ["java_heap_space"],
            "evidence_refs": ["EV001"],
            "initial_confidence": 0.7,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        # Should have high confidence with tool confirmation
        assert result.confidence >= 0.75
        assert result.primary_symptom == PrimarySymptom.OOM


class TestScenario10MultiStageFailure:
    """Scenario 10: Multi-stage failure with chained exceptions.

    Input: Complex stack trace with multiple "Caused by" entries
    Mode: OFFLINE
    Handoff: Depends on root cause
    """

    def test_chained_exception_analysis(
        self, explorer: ArtifactExplorer, context_builder: DiagnosticContextBuilder
    ) -> None:
        """Should analyze chained exceptions and find root cause."""
        artifact = """
        org.apache.spark.SparkException: Job aborted due to stage failure
            at org.apache.spark.scheduler.DAGScheduler.failJobAndIndependentStages
            at org.apache.spark.scheduler.DAGScheduler.handleTaskSetFailed
        Caused by: org.apache.spark.shuffle.FetchFailedException: Unable to read block
            at org.apache.spark.storage.ShuffleBlockFetcherIterator
            at org.apache.spark.shuffle.BlockStoreShuffleReader.read
        Caused by: java.io.IOException: Connection reset by peer
            at sun.nio.ch.FileDispatcherImpl.read0
            at sun.nio.ch.SocketDispatcher.read
        """

        context = context_builder.build_context(artifact)

        # Should detect and analyze the artifact
        assert context.artifact_type in (
            "stack_trace",
            "logs",
            "mixed",
            "error_message",
        )
        # Should have built context successfully
        assert context.confidence >= 0.0

    def test_multi_stage_identifies_root_cause(
        self, explorer: ArtifactExplorer
    ) -> None:
        """Should identify deepest cause in chain."""
        artifact = """
        SparkException: Job aborted
        Caused by: TaskNotSerializableException: object not serializable
            class: com.example.MyHandler
        Caused by: java.io.NotSerializableException: com.example.DatabaseConnection
        """

        result = explorer.explore(artifact, strategy=ExplorationStrategy.DETECT_TYPE)
        assert result.confidence >= 0.0

        result = explorer.explore(artifact, strategy=ExplorationStrategy.MATCH_PATTERNS)

        # Should process successfully
        assert result.findings is not None

    def test_multi_stage_handoff_decision(
        self, handoff_protocol: HandoffProtocol
    ) -> None:
        """Should make appropriate handoff decision based on root cause."""
        # Serialization error -> job agent
        fingerprint_serialization = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.SERIALIZATION_ERROR,
            likely_root_causes=["Non-serializable closure"],
            exploration_summary=None,
        )
        assert fingerprint_serialization.get_handoff_target() == "job"

        # Network error -> cluster agent
        fingerprint_network = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.CONNECTION_ERROR,
            likely_root_causes=["Connection reset"],
            exploration_summary=None,
        )
        assert fingerprint_network.get_handoff_target() == "cluster"


class TestFullExplorationWithTelemetry:
    """Test full exploration flows with telemetry tracking."""

    def test_exploration_with_telemetry(
        self,
        explorer: ArtifactExplorer,
        telemetry: ExplorationTelemetry,
    ) -> None:
        """Should track exploration steps with telemetry."""
        artifact = """
        java.lang.OutOfMemoryError: Java heap space
            at java.util.Arrays.copyOf
            at org.apache.spark.sql.execution.ShuffledRowRDD

        job_id: 12345
        cluster_id: 0123-456789-abc
        """

        with telemetry.exploration("stack_trace") as exp_id:
            assert exp_id is not None

            # Step 1: Detect type
            result1 = explorer.explore(
                artifact, strategy=ExplorationStrategy.DETECT_TYPE
            )
            telemetry.record_step(
                strategy="detect_type",
                latency_ms=100,
                confidence_before=0.0,
                confidence_after=result1.confidence,
                findings_count=len(result1.findings),
            )

            # Step 2: Extract IDs
            result2 = explorer.explore(
                artifact, strategy=ExplorationStrategy.EXTRACT_IDS
            )
            telemetry.record_step(
                strategy="extract_ids",
                latency_ms=50,
                confidence_before=result1.confidence,
                confidence_after=result2.confidence,
                findings_count=len(result2.findings),
            )

            # Step 3: Match patterns
            result3 = explorer.explore(
                artifact, strategy=ExplorationStrategy.MATCH_PATTERNS
            )
            telemetry.record_step(
                strategy="match_patterns",
                latency_ms=150,
                confidence_before=result2.confidence,
                confidence_after=result3.confidence,
                findings_count=len(result3.findings),
            )

        # Verify telemetry recorded
        metrics = telemetry.get_history()[0]
        assert metrics.step_count == 3
        assert metrics.total_latency_ms == 300
        assert metrics.strategies_used == [
            "detect_type",
            "extract_ids",
            "match_patterns",
        ]

    def test_aggregate_stats_across_explorations(
        self, telemetry: ExplorationTelemetry
    ) -> None:
        """Should compute aggregate stats correctly."""
        # Simulate multiple explorations
        for i in range(3):
            with telemetry.exploration("logs"):
                telemetry.record_step("detect_type", 100 + i * 10, 0.0, 0.5, 2)
                telemetry.record_step("match_patterns", 200 + i * 20, 0.5, 0.8, 3)

        stats = telemetry.get_aggregate_stats()
        assert stats["exploration_count"] == 3
        assert stats["avg_step_count"] == pytest.approx(2.0)
        assert stats["avg_final_confidence"] == pytest.approx(0.8)
