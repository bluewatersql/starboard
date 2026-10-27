# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Memory benchmarks for diagnostic agent.

Target: <500MB peak memory usage
"""

import gc

import pytest
from starboard.tools.domain.diagnostic import (
    ArtifactDetector,
    ArtifactExplorer,
    ArtifactNormalizer,
    DatabricksContextExtractor,
    EvidenceWindowExtractor,
    ExplorationStrategy,
)
from starboard.tools.domain.diagnostic.pattern_matcher import PatternMatcher
from starboard.tools.domain.diagnostic.patterns.registry import PatternRegistry


def get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    import resource

    # Get memory usage in bytes
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024 / 1024  # Convert to MB (macOS returns bytes)


@pytest.fixture(scope="module")
def pattern_registry() -> PatternRegistry:
    """Load pattern registry once for all tests."""
    from pathlib import Path

    pattern_dir = Path(__file__).parent.parent.parent / (
        "starboard/tools/domain/diagnostic/patterns/catalog"
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


# Generate test artifacts of various sizes
def generate_artifact(size_kb: int) -> str:
    """Generate an artifact of approximately the given size in KB."""
    line = "2024-01-15 10:30:00 INFO Processing batch 0 of 1000\n"
    line_size = len(line.encode("utf-8"))
    num_lines = (size_kb * 1024) // line_size
    return "".join(
        f"2024-01-15 10:{i // 60:02d}:{i % 60:02d} INFO Processing batch {i}\n"
        for i in range(num_lines)
    )


class TestMemoryUsage:
    """Memory usage tests."""

    @pytest.mark.benchmark
    def test_pattern_registry_memory(self, pattern_registry: PatternRegistry) -> None:
        """Pattern registry should use <10MB."""
        # Force garbage collection
        gc.collect()

        # Measure memory
        mem_before = get_memory_mb()

        # Access patterns to ensure they're loaded
        _ = pattern_registry.patterns

        gc.collect()
        mem_after = get_memory_mb()

        # Pattern registry should be small
        registry_mem = mem_after - mem_before
        assert registry_mem < 10, (
            f"Pattern registry uses {registry_mem:.1f}MB (target: <10MB)"
        )

    @pytest.mark.benchmark
    def test_explorer_memory_small_artifact(self, explorer: ArtifactExplorer) -> None:
        """Small artifact exploration should use <50MB."""
        artifact = generate_artifact(10)  # 10KB

        gc.collect()
        mem_before = get_memory_mb()

        # Run full exploration
        for strategy in ExplorationStrategy:
            if strategy != ExplorationStrategy.CORRELATE:
                explorer.explore(artifact, strategy=strategy)

        gc.collect()
        mem_after = get_memory_mb()

        delta = mem_after - mem_before
        assert delta < 50, (
            f"Small artifact exploration uses {delta:.1f}MB (target: <50MB)"
        )

    @pytest.mark.benchmark
    def test_explorer_memory_large_artifact(self, explorer: ArtifactExplorer) -> None:
        """Large artifact exploration should use <200MB."""
        artifact = generate_artifact(500)  # 500KB

        gc.collect()
        mem_before = get_memory_mb()

        # Run full exploration
        for strategy in ExplorationStrategy:
            if strategy != ExplorationStrategy.CORRELATE:
                explorer.explore(artifact, strategy=strategy)

        gc.collect()
        mem_after = get_memory_mb()

        delta = mem_after - mem_before
        assert delta < 200, (
            f"Large artifact exploration uses {delta:.1f}MB (target: <200MB)"
        )

    @pytest.mark.benchmark
    def test_normalizer_memory_huge_artifact(self) -> None:
        """Normalizing huge artifact should use <300MB."""
        normalizer = ArtifactNormalizer()
        artifact = generate_artifact(2000)  # 2MB artifact

        gc.collect()
        mem_before = get_memory_mb()

        normalizer.normalize(artifact, artifact_type="logs")

        gc.collect()
        mem_after = get_memory_mb()

        delta = mem_after - mem_before
        assert delta < 300, (
            f"Huge artifact normalization uses {delta:.1f}MB (target: <300MB)"
        )


class TestMemoryLeaks:
    """Test for memory leaks in repeated operations."""

    @pytest.mark.benchmark
    def test_no_memory_leak_repeated_exploration(
        self, explorer: ArtifactExplorer
    ) -> None:
        """Repeated explorations should not leak memory."""
        artifact = generate_artifact(50)  # 50KB

        gc.collect()
        # Initial memory baseline (not used for assertion, just warmup)
        _ = get_memory_mb()

        # Run exploration 10 times
        for _ in range(10):
            for strategy in ExplorationStrategy:
                if strategy != ExplorationStrategy.CORRELATE:
                    explorer.explore(artifact, strategy=strategy)

        gc.collect()
        mem_after_10 = get_memory_mb()

        # Run exploration 10 more times
        for _ in range(10):
            for strategy in ExplorationStrategy:
                if strategy != ExplorationStrategy.CORRELATE:
                    explorer.explore(artifact, strategy=strategy)

        gc.collect()
        mem_after_20 = get_memory_mb()

        # Memory growth should be minimal
        growth = mem_after_20 - mem_after_10
        assert growth < 10, (
            f"Memory leak detected: {growth:.1f}MB growth (target: <10MB)"
        )


def test_memory_summary(
    explorer: ArtifactExplorer,
    pattern_registry: PatternRegistry,
) -> None:
    """Generate memory usage summary."""
    results = {}

    # Measure component sizes
    gc.collect()
    mem_base = get_memory_mb()

    # Pattern registry
    _ = pattern_registry.patterns
    gc.collect()
    results["pattern_registry"] = get_memory_mb() - mem_base

    # Small artifact exploration
    artifact_small = generate_artifact(10)
    mem_before = get_memory_mb()
    for strategy in ExplorationStrategy:
        if strategy != ExplorationStrategy.CORRELATE:
            explorer.explore(artifact_small, strategy=strategy)
    gc.collect()
    results["explore_10kb"] = get_memory_mb() - mem_before

    # Large artifact exploration
    artifact_large = generate_artifact(500)
    mem_before = get_memory_mb()
    for strategy in ExplorationStrategy:
        if strategy != ExplorationStrategy.CORRELATE:
            explorer.explore(artifact_large, strategy=strategy)
    gc.collect()
    results["explore_500kb"] = get_memory_mb() - mem_before

    # Print summary
    print("\n=== Memory Usage Summary ===")
    for name, mem_mb in sorted(results.items(), key=lambda x: x[1], reverse=True):
        print(f"  {name}: {mem_mb:.1f}MB")
    print(f"  TOTAL PEAK: {get_memory_mb():.1f}MB")
    print("============================\n")

    # Assert peak is under target
    peak_mb = get_memory_mb()
    assert peak_mb < 500, f"Peak memory {peak_mb:.0f}MB exceeds 500MB target"
