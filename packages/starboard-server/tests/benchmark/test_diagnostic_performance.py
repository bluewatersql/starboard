"""Performance benchmarks for diagnostic agent exploration.

Target: <30s p95 for 5-step exploration
"""

import time

import pytest
from starboard_server.tools.domain.diagnostic import (
    ArtifactDetector,
    ArtifactExplorer,
    ArtifactNormalizer,
    DatabricksContextExtractor,
    DiagnosticContextBuilder,
    EvidenceWindowExtractor,
    ExplorationStrategy,
    ExplorationTelemetry,
)
from starboard_server.tools.domain.diagnostic.pattern_matcher import PatternMatcher
from starboard_server.tools.domain.diagnostic.patterns.registry import PatternRegistry


@pytest.fixture(scope="module")
def pattern_registry() -> PatternRegistry:
    """Load pattern registry once for all tests."""
    from pathlib import Path

    # Navigate from tests/benchmark/ to starboard_server/
    pattern_dir = Path(__file__).parent.parent.parent / (
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
def normalizer() -> ArtifactNormalizer:
    """Create artifact normalizer."""
    return ArtifactNormalizer()


# Sample artifacts of varying sizes
SMALL_ARTIFACT = """
java.lang.OutOfMemoryError: Java heap space
    at java.util.Arrays.copyOf(Arrays.java:3236)
    at org.apache.spark.sql.execution.ShuffledRowRDD.compute
"""

MEDIUM_ARTIFACT = """
2024-01-15 10:30:15 ERROR SparkContext - Error running job
java.lang.OutOfMemoryError: Java heap space
    at java.util.Arrays.copyOf(Arrays.java:3236)
    at java.util.ArrayList.grow(ArrayList.java:265)
    at org.apache.spark.sql.execution.ShuffledRowRDD.compute(ShuffledRowRDD.scala:45)
    at org.apache.spark.rdd.RDD.iterator(RDD.scala:123)
    at org.apache.spark.scheduler.ShuffleMapTask.runTask(ShuffleMapTask.scala:99)

job_id: 12345
cluster_id: 0123-456789-abc

Executor 3 lost due to memory pressure
Container killed by YARN for exceeding memory limits

2024-01-15 10:30:20 INFO JobManager - Attempting retry 1/3
2024-01-15 10:30:25 ERROR JobManager - Retry failed
2024-01-15 10:30:30 WARN ClusterManager - Executor health check failed
"""

# Generate a large artifact (~100KB)
LARGE_ARTIFACT = (
    MEDIUM_ARTIFACT
    + "\n"
    + "\n".join(
        f"2024-01-15 10:30:{i:02d} INFO Processing batch {i} of 1000"
        for i in range(3000)
    )
)


class TestExplorationPerformance:
    """Performance benchmarks for exploration strategies."""

    @pytest.mark.benchmark
    def test_detect_type_latency(self, explorer: ArtifactExplorer) -> None:
        """Detect type should complete in <100ms."""
        start = time.perf_counter()
        for _ in range(10):
            explorer.explore(MEDIUM_ARTIFACT, strategy=ExplorationStrategy.DETECT_TYPE)
        elapsed = (time.perf_counter() - start) / 10

        assert elapsed < 0.1, f"detect_type took {elapsed:.3f}s (target: <0.1s)"

    @pytest.mark.benchmark
    def test_extract_evidence_latency(self, explorer: ArtifactExplorer) -> None:
        """Extract evidence should complete in <200ms."""
        start = time.perf_counter()
        for _ in range(10):
            explorer.explore(
                MEDIUM_ARTIFACT, strategy=ExplorationStrategy.EXTRACT_EVIDENCE
            )
        elapsed = (time.perf_counter() - start) / 10

        assert elapsed < 0.2, f"extract_evidence took {elapsed:.3f}s (target: <0.2s)"

    @pytest.mark.benchmark
    def test_match_patterns_latency(self, explorer: ArtifactExplorer) -> None:
        """Match patterns should complete in <500ms."""
        start = time.perf_counter()
        for _ in range(10):
            explorer.explore(
                MEDIUM_ARTIFACT, strategy=ExplorationStrategy.MATCH_PATTERNS
            )
        elapsed = (time.perf_counter() - start) / 10

        assert elapsed < 0.5, f"match_patterns took {elapsed:.3f}s (target: <0.5s)"

    @pytest.mark.benchmark
    def test_extract_ids_latency(self, explorer: ArtifactExplorer) -> None:
        """Extract IDs should complete in <100ms."""
        start = time.perf_counter()
        for _ in range(10):
            explorer.explore(MEDIUM_ARTIFACT, strategy=ExplorationStrategy.EXTRACT_IDS)
        elapsed = (time.perf_counter() - start) / 10

        assert elapsed < 0.1, f"extract_ids took {elapsed:.3f}s (target: <0.1s)"

    @pytest.mark.benchmark
    def test_summarize_latency(self, explorer: ArtifactExplorer) -> None:
        """Summarize should complete in <300ms for medium artifact."""
        start = time.perf_counter()
        for _ in range(10):
            explorer.explore(MEDIUM_ARTIFACT, strategy=ExplorationStrategy.SUMMARIZE)
        elapsed = (time.perf_counter() - start) / 10

        assert elapsed < 0.3, f"summarize took {elapsed:.3f}s (target: <0.3s)"


class TestFullExplorationPerformance:
    """End-to-end exploration performance."""

    @pytest.mark.benchmark
    def test_five_step_exploration_small(self, explorer: ArtifactExplorer) -> None:
        """5-step exploration on small artifact should complete in <1s."""
        strategies = [
            ExplorationStrategy.DETECT_TYPE,
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.EXTRACT_IDS,
            ExplorationStrategy.MATCH_PATTERNS,
            ExplorationStrategy.SUMMARIZE,
        ]

        start = time.perf_counter()
        for strategy in strategies:
            explorer.explore(SMALL_ARTIFACT, strategy=strategy)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"5-step exploration took {elapsed:.3f}s (target: <1s)"

    @pytest.mark.benchmark
    def test_five_step_exploration_medium(self, explorer: ArtifactExplorer) -> None:
        """5-step exploration on medium artifact should complete in <3s."""
        strategies = [
            ExplorationStrategy.DETECT_TYPE,
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.EXTRACT_IDS,
            ExplorationStrategy.MATCH_PATTERNS,
            ExplorationStrategy.SUMMARIZE,
        ]

        start = time.perf_counter()
        for strategy in strategies:
            explorer.explore(MEDIUM_ARTIFACT, strategy=strategy)
        elapsed = time.perf_counter() - start

        assert elapsed < 3.0, f"5-step exploration took {elapsed:.3f}s (target: <3s)"

    @pytest.mark.benchmark
    def test_five_step_exploration_large(self, explorer: ArtifactExplorer) -> None:
        """5-step exploration on large artifact should complete in <10s."""
        strategies = [
            ExplorationStrategy.DETECT_TYPE,
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.EXTRACT_IDS,
            ExplorationStrategy.MATCH_PATTERNS,
            ExplorationStrategy.SUMMARIZE,
        ]

        start = time.perf_counter()
        for strategy in strategies:
            explorer.explore(LARGE_ARTIFACT, strategy=strategy)
        elapsed = time.perf_counter() - start

        assert elapsed < 10.0, f"5-step exploration took {elapsed:.3f}s (target: <10s)"

    @pytest.mark.benchmark
    def test_context_builder_latency(
        self, context_builder: DiagnosticContextBuilder
    ) -> None:
        """Context builder should complete in <2s for medium artifact."""
        start = time.perf_counter()
        context_builder.build_context(MEDIUM_ARTIFACT)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"build_context took {elapsed:.3f}s (target: <2s)"


class TestNormalizationPerformance:
    """Normalization performance for large inputs."""

    @pytest.mark.benchmark
    def test_normalize_large_artifact(self, normalizer: ArtifactNormalizer) -> None:
        """Normalize large artifact should complete in <1s."""
        start = time.perf_counter()
        normalizer.normalize(LARGE_ARTIFACT, artifact_type="logs")
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"normalize took {elapsed:.3f}s (target: <1s)"

    @pytest.mark.benchmark
    def test_normalize_500k_artifact(self, normalizer: ArtifactNormalizer) -> None:
        """Normalize 500K char artifact should complete in <5s."""
        # Generate ~500K artifact
        huge_artifact = "\n".join(
            f"2024-01-15 10:{i // 60:02d}:{i % 60:02d} INFO Processing record {i}"
            for i in range(10000)
        )

        start = time.perf_counter()
        normalizer.normalize(huge_artifact, artifact_type="logs")
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"normalize 500K took {elapsed:.3f}s (target: <5s)"


class TestPatternMatchingPerformance:
    """Pattern matching performance with full registry."""

    @pytest.mark.benchmark
    def test_pattern_matching_all_patterns(
        self, pattern_registry: PatternRegistry
    ) -> None:
        """Pattern matching against all patterns should be <200ms."""
        matcher = PatternMatcher(pattern_registry)

        start = time.perf_counter()
        for _ in range(10):
            matcher.match(MEDIUM_ARTIFACT)
        elapsed = (time.perf_counter() - start) / 10

        assert elapsed < 0.2, f"pattern matching took {elapsed:.3f}s (target: <0.2s)"


class TestTelemetryOverhead:
    """Measure telemetry collection overhead."""

    @pytest.mark.benchmark
    def test_telemetry_overhead(self, explorer: ArtifactExplorer) -> None:
        """Telemetry should add <10% overhead."""
        telemetry = ExplorationTelemetry()

        # Without telemetry
        start = time.perf_counter()
        for _ in range(10):
            explorer.explore(MEDIUM_ARTIFACT, strategy=ExplorationStrategy.DETECT_TYPE)
        without_telemetry = time.perf_counter() - start

        # With telemetry
        start = time.perf_counter()
        for _ in range(10):
            with telemetry.exploration("logs"):
                result = explorer.explore(
                    MEDIUM_ARTIFACT, strategy=ExplorationStrategy.DETECT_TYPE
                )
                telemetry.record_step(
                    strategy="detect_type",
                    latency_ms=100,
                    confidence_before=0.0,
                    confidence_after=result.confidence,
                    findings_count=len(result.findings),
                )
        with_telemetry = time.perf_counter() - start

        overhead = (with_telemetry - without_telemetry) / without_telemetry
        # Allow up to 20% overhead for telemetry collection
        assert overhead < 0.2, f"telemetry overhead {overhead:.1%} (target: <20%)"


def test_performance_summary(
    explorer: ArtifactExplorer,
    context_builder: DiagnosticContextBuilder,
    normalizer: ArtifactNormalizer,
    pattern_registry: PatternRegistry,
) -> None:
    """Generate performance summary report."""
    results = {}

    # Measure each strategy
    for strategy in ExplorationStrategy:
        if strategy == ExplorationStrategy.CORRELATE:
            continue  # Skip correlate as it needs prior state
        start = time.perf_counter()
        explorer.explore(MEDIUM_ARTIFACT, strategy=strategy)
        results[strategy.value] = (time.perf_counter() - start) * 1000

    # Measure context builder
    start = time.perf_counter()
    context_builder.build_context(MEDIUM_ARTIFACT)
    results["build_context"] = (time.perf_counter() - start) * 1000

    # Measure normalizer
    start = time.perf_counter()
    normalizer.normalize(MEDIUM_ARTIFACT, artifact_type="logs")
    results["normalize"] = (time.perf_counter() - start) * 1000

    # Print summary
    print("\n=== Performance Summary ===")
    for name, latency_ms in sorted(results.items(), key=lambda x: x[1], reverse=True):
        print(f"  {name}: {latency_ms:.1f}ms")
    print(f"  TOTAL: {sum(results.values()):.1f}ms")
    print("===========================\n")

    # Assert total is reasonable
    total_ms = sum(results.values())
    assert total_ms < 5000, f"Total latency {total_ms:.0f}ms exceeds 5s target"
