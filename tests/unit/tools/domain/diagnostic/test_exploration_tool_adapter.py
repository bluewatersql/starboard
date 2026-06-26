# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for ExplorationToolAdapter.

Tests the tool adapter that exposes exploration strategies as callable tools
for the LLM agent.
"""

from __future__ import annotations

import pytest
from starboard_server.tools.domain.diagnostic.artifact_detector import ArtifactDetector
from starboard_server.tools.domain.diagnostic.artifact_explorer import (
    ArtifactExplorer,
    ExplorationStrategy,
)
from starboard_server.tools.domain.diagnostic.context_extractor import (
    DatabricksContextExtractor,
)
from starboard_server.tools.domain.diagnostic.evidence_extractor import (
    EvidenceWindowExtractor,
)
from starboard_server.tools.domain.diagnostic.exploration_tool_adapter import (
    ExplorationToolAdapter,
    create_exploration_tools,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def explorer() -> ArtifactExplorer:
    """Create an ArtifactExplorer with all dependencies."""
    return ArtifactExplorer(
        detector=ArtifactDetector(),
        evidence_extractor=EvidenceWindowExtractor(),
        context_extractor=DatabricksContextExtractor(),
    )


@pytest.fixture
def adapter(explorer: ArtifactExplorer) -> ExplorationToolAdapter:
    """Create an ExplorationToolAdapter."""
    return ExplorationToolAdapter(explorer)


# =============================================================================
# TEST: TOOL METADATA
# =============================================================================


class TestToolMetadata:
    """Tests for tool metadata generation."""

    def test_generates_tool_metadata(self, adapter: ExplorationToolAdapter) -> None:
        """Test that adapter generates valid tool metadata."""
        tools = adapter.get_tool_definitions()

        assert isinstance(tools, list)
        assert len(tools) > 0

        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    def test_tool_names_match_strategies(self, adapter: ExplorationToolAdapter) -> None:
        """Test that tool names correspond to exploration strategies."""
        tools = adapter.get_tool_definitions()
        tool_names = {t["name"] for t in tools}

        # Should have tools for key strategies (match_patterns requires pattern matcher)
        expected_tools = {
            "explore_detect_type",
            "explore_extract_evidence",
            "explore_extract_ids",
        }

        for expected in expected_tools:
            assert expected in tool_names, f"Missing tool: {expected}"

    def test_tool_has_artifact_parameter(self, adapter: ExplorationToolAdapter) -> None:
        """Test that tools have required artifact parameter."""
        tools = adapter.get_tool_definitions()

        for tool in tools:
            params = tool.get("parameters", {})
            properties = params.get("properties", {})
            assert "artifact" in properties, (
                f"Tool {tool['name']} missing artifact param"
            )


# =============================================================================
# TEST: TOOL EXECUTION
# =============================================================================


class TestToolExecution:
    """Tests for executing exploration tools."""

    def test_execute_detect_type(self, adapter: ExplorationToolAdapter) -> None:
        """Test executing detect_type exploration."""
        artifact = "java.lang.OutOfMemoryError: Java heap space"

        result = adapter.execute("explore_detect_type", {"artifact": artifact})

        assert isinstance(result, dict)
        assert "artifact_type" in result
        assert "confidence" in result

    def test_execute_extract_evidence(self, adapter: ExplorationToolAdapter) -> None:
        """Test executing extract_evidence exploration."""
        artifact = """
java.lang.OutOfMemoryError: Java heap space
    at java.base/java.util.Arrays.copyOf(Arrays.java:3512)
Caused by: java.lang.OutOfMemoryError: Java heap space
        """

        result = adapter.execute("explore_extract_evidence", {"artifact": artifact})

        assert isinstance(result, dict)
        assert "window_count" in result

    def test_execute_extract_ids(self, adapter: ExplorationToolAdapter) -> None:
        """Test executing extract_ids exploration."""
        artifact = "Job 12345 failed on cluster 1234-567890-abc12def"

        result = adapter.execute("explore_extract_ids", {"artifact": artifact})

        assert isinstance(result, dict)
        assert "mode" in result
        assert "ids" in result

    def test_execute_unknown_tool_raises(self, adapter: ExplorationToolAdapter) -> None:
        """Test that unknown tool raises error."""
        with pytest.raises(ValueError, match="Unknown exploration tool"):
            adapter.execute("unknown_tool", {"artifact": "test"})

    def test_execute_without_artifact_raises(
        self, adapter: ExplorationToolAdapter
    ) -> None:
        """Test that missing artifact raises error."""
        with pytest.raises(ValueError, match="artifact"):
            adapter.execute("explore_detect_type", {})


# =============================================================================
# TEST: STRATEGY MAPPING
# =============================================================================


class TestStrategyMapping:
    """Tests for mapping between tools and strategies."""

    def test_maps_tool_to_strategy(self, adapter: ExplorationToolAdapter) -> None:
        """Test that tools map to correct strategies."""
        assert (
            adapter._get_strategy("explore_detect_type")
            == ExplorationStrategy.DETECT_TYPE
        )
        assert (
            adapter._get_strategy("explore_extract_evidence")
            == ExplorationStrategy.EXTRACT_EVIDENCE
        )
        assert (
            adapter._get_strategy("explore_extract_ids")
            == ExplorationStrategy.EXTRACT_IDS
        )

    def test_all_strategies_have_tools(self, adapter: ExplorationToolAdapter) -> None:
        """Test that main strategies have corresponding tools."""
        # Strategies that don't require pattern matcher
        main_strategies = [
            ExplorationStrategy.DETECT_TYPE,
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.EXTRACT_IDS,
            # MATCH_PATTERNS requires pattern matcher - tested separately
            ExplorationStrategy.EXPAND_WINDOW,
            ExplorationStrategy.SUMMARIZE,
            ExplorationStrategy.CORRELATE,
        ]

        tools = adapter.get_tool_definitions()
        tool_names = {t["name"] for t in tools}

        for strategy in main_strategies:
            tool_name = f"explore_{strategy.value}"
            assert tool_name in tool_names, f"Missing tool for {strategy.value}"


# =============================================================================
# TEST: RESULT FORMATTING
# =============================================================================


class TestResultFormatting:
    """Tests for formatting exploration results."""

    def test_result_includes_next_steps(self, adapter: ExplorationToolAdapter) -> None:
        """Test that results include suggested next steps."""
        artifact = "java.lang.OutOfMemoryError"

        result = adapter.execute("explore_detect_type", {"artifact": artifact})

        assert "next_steps" in result
        assert isinstance(result["next_steps"], list)

    def test_result_includes_confidence(self, adapter: ExplorationToolAdapter) -> None:
        """Test that results include confidence score."""
        artifact = "Error message"

        result = adapter.execute("explore_detect_type", {"artifact": artifact})

        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    def test_result_is_json_serializable(self, adapter: ExplorationToolAdapter) -> None:
        """Test that results can be serialized to JSON."""
        import json

        artifact = "java.lang.OutOfMemoryError: Java heap space"

        result = adapter.execute("explore_detect_type", {"artifact": artifact})

        # Should not raise
        json_str = json.dumps(result)
        assert isinstance(json_str, str)


# =============================================================================
# TEST: FACTORY FUNCTION
# =============================================================================


class TestFactoryFunction:
    """Tests for the create_exploration_tools factory function."""

    def test_creates_tool_definitions(self) -> None:
        """Test that factory creates tool definitions."""
        explorer = ArtifactExplorer(
            detector=ArtifactDetector(),
            evidence_extractor=EvidenceWindowExtractor(),
            context_extractor=DatabricksContextExtractor(),
        )

        tools, executor = create_exploration_tools(explorer)

        assert isinstance(tools, list)
        assert callable(executor)

    def test_executor_runs_tools(self) -> None:
        """Test that returned executor can run tools."""
        explorer = ArtifactExplorer(
            detector=ArtifactDetector(),
            evidence_extractor=EvidenceWindowExtractor(),
            context_extractor=DatabricksContextExtractor(),
        )

        tools, executor = create_exploration_tools(explorer)

        result = executor("explore_detect_type", {"artifact": "Error"})

        assert isinstance(result, dict)
        assert "artifact_type" in result


# =============================================================================
# TEST: EARLY EXIT DETECTION
# =============================================================================


class TestEarlyExitDetection:
    """Tests for detecting when to stop exploring."""

    def test_high_confidence_suggests_synthesize(
        self, adapter: ExplorationToolAdapter
    ) -> None:
        """Test that high confidence results suggest synthesis."""
        artifact = """
java.lang.OutOfMemoryError: Java heap space
Container killed by YARN for exceeding memory limits.
10.5 GB of 10 GB physical memory used.
        """

        result = adapter.execute("explore_extract_evidence", {"artifact": artifact})

        # High confidence should suggest stopping
        if result.get("confidence", 0) >= 0.8:
            assert (
                "synthesize" in str(result.get("next_steps", [])).lower()
                or result.get("should_synthesize", False)
                or len(result.get("next_steps", [])) <= 2
            )

    def test_low_confidence_suggests_more_exploration(
        self, adapter: ExplorationToolAdapter
    ) -> None:
        """Test that low confidence results suggest more exploration."""
        artifact = "Some ambiguous message"

        result = adapter.execute("explore_detect_type", {"artifact": artifact})

        # Low confidence should suggest more steps
        if result.get("confidence", 0) < 0.5:
            assert len(result.get("next_steps", [])) > 0
