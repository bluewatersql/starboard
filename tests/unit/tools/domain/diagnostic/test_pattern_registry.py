# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for pattern registry and YAML loading.

Tests cover:
- YAML file loading
- Pattern validation at load time
- Keyword indexing
- Pattern lookup
"""

from pathlib import Path
from textwrap import dedent

import pytest
from starboard_server.tools.domain.diagnostic.patterns.registry import (
    PatternLoadError,
    PatternRegistry,
    reset_global_registry,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def registry() -> PatternRegistry:
    """Create a fresh registry instance."""
    return PatternRegistry()


@pytest.fixture
def sample_yaml() -> str:
    """Valid YAML pattern for testing."""
    return dedent("""
        version: "1.0.0"
        patterns:
          - id: test_oom
            name: "Test OOM Pattern"
            category: memory
            severity: high
            responsibility: configuration
            keywords:
              - "OutOfMemoryError"
              - "Java heap space"
            regex_patterns:
              - "java\\\\.lang\\\\.OutOfMemoryError"
            exit_code: 137
            root_cause: "Memory exhausted"
            symptoms:
              - "OOM error in logs"
            remediation:
              - "Increase memory"
            evidence_checklist:
              required:
                - "OOM error present"
              supporting:
                - "GC logs show pressure"
            confidence_factors:
              increase:
                - "OOMKilled present"
              decrease:
                - "Manually cancelled"
    """)


@pytest.fixture
def multi_pattern_yaml() -> str:
    """YAML with multiple patterns for testing."""
    return dedent("""
        version: "1.0.0"
        patterns:
          - id: pattern_one
            name: "Pattern One"
            category: memory
            severity: high
            responsibility: configuration
            keywords:
              - "error one"
            exit_code: 1
            root_cause: "Cause one"

          - id: pattern_two
            name: "Pattern Two"
            category: sql
            severity: medium
            responsibility: user_code
            keywords:
              - "error two"
            message_pattern: "pattern two"
            root_cause: "Cause two"
    """)


# =============================================================================
# YAML STRING LOADING TESTS
# =============================================================================


class TestYAMLStringLoading:
    """Tests for loading patterns from YAML strings."""

    def test_load_valid_yaml(self, registry: PatternRegistry, sample_yaml: str) -> None:
        """Valid YAML is loaded successfully."""
        count = registry.load_from_yaml_string(sample_yaml)

        assert count == 1
        assert registry.pattern_count == 1

        pattern = registry.get_pattern("test_oom")
        assert pattern is not None
        assert pattern.name == "Test OOM Pattern"

    def test_load_multiple_patterns(
        self, registry: PatternRegistry, multi_pattern_yaml: str
    ) -> None:
        """Multiple patterns are loaded from single YAML."""
        count = registry.load_from_yaml_string(multi_pattern_yaml)

        assert count == 2
        assert registry.pattern_count == 2
        assert registry.get_pattern("pattern_one") is not None
        assert registry.get_pattern("pattern_two") is not None

    def test_load_empty_yaml(self, registry: PatternRegistry) -> None:
        """Empty YAML returns 0 patterns."""
        count = registry.load_from_yaml_string("")
        assert count == 0

    def test_load_invalid_yaml_syntax(self, registry: PatternRegistry) -> None:
        """Invalid YAML syntax raises PatternLoadError."""
        with pytest.raises(PatternLoadError) as exc_info:
            registry.load_from_yaml_string("{ invalid: yaml: syntax }")

        assert "Invalid YAML" in str(exc_info.value)

    def test_load_invalid_schema(self, registry: PatternRegistry) -> None:
        """Invalid pattern schema raises PatternLoadError."""
        invalid_yaml = dedent("""
            version: "1.0.0"
            patterns:
              - id: missing_required
                # Missing: name, category, severity, responsibility, keywords, root_cause
        """)

        with pytest.raises(PatternLoadError) as exc_info:
            registry.load_from_yaml_string(invalid_yaml)

        assert "validation failed" in str(exc_info.value).lower()

    def test_load_invalid_regex(self, registry: PatternRegistry) -> None:
        """Invalid regex in pattern raises PatternLoadError."""
        invalid_yaml = dedent("""
            version: "1.0.0"
            patterns:
              - id: bad_regex
                name: "Bad Regex"
                category: memory
                severity: high
                responsibility: configuration
                keywords:
                  - "test"
                regex_patterns:
                  - "[invalid(regex"
                root_cause: "Test"
        """)

        with pytest.raises(PatternLoadError) as exc_info:
            registry.load_from_yaml_string(invalid_yaml)

        assert "Invalid regex" in str(exc_info.value)


# =============================================================================
# KEYWORD INDEX TESTS
# =============================================================================


class TestKeywordIndex:
    """Tests for keyword indexing and lookup."""

    def test_keywords_indexed(
        self, registry: PatternRegistry, sample_yaml: str
    ) -> None:
        """Keywords are indexed correctly."""
        registry.load_from_yaml_string(sample_yaml)

        keywords = registry.get_all_keywords()

        assert "outofmemoryerror" in keywords
        assert "java heap space" in keywords

    def test_find_candidates_by_keywords(
        self, registry: PatternRegistry, sample_yaml: str
    ) -> None:
        """Candidates are found by keyword matching."""
        registry.load_from_yaml_string(sample_yaml)

        candidates = registry.find_candidates_by_keywords("Got OutOfMemoryError")

        assert len(candidates) == 1
        assert candidates[0].pattern_id == "test_oom"

    def test_find_candidates_case_insensitive(
        self, registry: PatternRegistry, sample_yaml: str
    ) -> None:
        """Keyword matching is case-insensitive."""
        registry.load_from_yaml_string(sample_yaml)

        candidates = registry.find_candidates_by_keywords("OUTOFMEMORYERROR")

        assert len(candidates) == 1

    def test_find_candidates_no_match(
        self, registry: PatternRegistry, sample_yaml: str
    ) -> None:
        """No candidates when keywords don't match."""
        registry.load_from_yaml_string(sample_yaml)

        candidates = registry.find_candidates_by_keywords("Something unrelated")

        assert len(candidates) == 0

    def test_multiple_patterns_share_keyword(self, registry: PatternRegistry) -> None:
        """Multiple patterns can share keywords."""
        yaml = dedent("""
            version: "1.0.0"
            patterns:
              - id: pattern_a
                name: "Pattern A"
                category: memory
                severity: high
                responsibility: configuration
                keywords:
                  - "shared keyword"
                  - "unique a"
                exit_code: 1
                root_cause: "Cause A"

              - id: pattern_b
                name: "Pattern B"
                category: memory
                severity: medium
                responsibility: configuration
                keywords:
                  - "shared keyword"
                  - "unique b"
                exit_code: 2
                root_cause: "Cause B"
        """)

        registry.load_from_yaml_string(yaml)

        candidates = registry.find_candidates_by_keywords("shared keyword")

        assert len(candidates) == 2
        ids = {c.pattern_id for c in candidates}
        assert ids == {"pattern_a", "pattern_b"}


# =============================================================================
# EXIT CODE LOOKUP TESTS
# =============================================================================


class TestExitCodeLookup:
    """Tests for finding patterns by exit code."""

    def test_find_by_exit_code(
        self, registry: PatternRegistry, sample_yaml: str
    ) -> None:
        """Pattern found by exit code."""
        registry.load_from_yaml_string(sample_yaml)

        patterns = registry.find_candidates_by_exit_code(137)

        assert len(patterns) == 1
        assert patterns[0].pattern_id == "test_oom"

    def test_find_by_exit_code_no_match(
        self, registry: PatternRegistry, sample_yaml: str
    ) -> None:
        """No patterns for non-matching exit code."""
        registry.load_from_yaml_string(sample_yaml)

        patterns = registry.find_candidates_by_exit_code(999)

        assert len(patterns) == 0


# =============================================================================
# REGISTRY STATE TESTS
# =============================================================================


class TestRegistryState:
    """Tests for registry state management."""

    def test_clear_registry(self, registry: PatternRegistry, sample_yaml: str) -> None:
        """Clear removes all patterns."""
        registry.load_from_yaml_string(sample_yaml)
        assert registry.pattern_count == 1

        registry.clear()

        assert registry.pattern_count == 0
        assert len(registry.get_all_keywords()) == 0

    def test_get_nonexistent_pattern(self, registry: PatternRegistry) -> None:
        """Getting non-existent pattern returns None."""
        assert registry.get_pattern("nonexistent") is None

    def test_get_yaml_pattern(
        self, registry: PatternRegistry, sample_yaml: str
    ) -> None:
        """Get raw YAML pattern for inspection."""
        registry.load_from_yaml_string(sample_yaml)

        yaml_pattern = registry.get_yaml_pattern("test_oom")

        assert yaml_pattern is not None
        assert yaml_pattern.id == "test_oom"
        assert len(yaml_pattern.keywords) == 2


# =============================================================================
# YAML TO INTERNAL MODEL CONVERSION TESTS
# =============================================================================


class TestModelConversion:
    """Tests for converting YAML models to internal models."""

    def test_converts_to_internal_model(
        self, registry: PatternRegistry, sample_yaml: str
    ) -> None:
        """YAML pattern converts to internal ErrorPattern."""
        registry.load_from_yaml_string(sample_yaml)

        pattern = registry.get_pattern("test_oom")

        assert pattern is not None
        # Check internal model fields
        assert pattern.pattern_id == "test_oom"
        assert pattern.name == "Test OOM Pattern"
        assert pattern.signature.exit_code == 137
        assert len(pattern.log_patterns) == 1
        assert len(pattern.symptoms) == 1
        assert pattern.evidence_checklist.required == ("OOM error present",)
        assert pattern.confidence_factors.increase == ("OOMKilled present",)
        assert pattern.confidence_factors.decrease == ("Manually cancelled",)


# =============================================================================
# GLOBAL REGISTRY TESTS
# =============================================================================


class TestGlobalRegistry:
    """Tests for global registry singleton."""

    def test_reset_global_registry(self) -> None:
        """Global registry can be reset."""
        reset_global_registry()
        # Should not raise - just ensures reset works


# =============================================================================
# FILE LOADING TESTS
# =============================================================================


class TestFileLoading:
    """Tests for loading patterns from files."""

    def test_load_nonexistent_file(self, registry: PatternRegistry) -> None:
        """Loading non-existent file raises error."""
        with pytest.raises(PatternLoadError) as exc_info:
            registry.load_from_file(Path("/nonexistent/file.yaml"))

        assert "not found" in str(exc_info.value).lower()

    def test_load_nonexistent_directory(self, registry: PatternRegistry) -> None:
        """Loading from non-existent directory raises error."""
        with pytest.raises(PatternLoadError) as exc_info:
            registry.load_from_directory(Path("/nonexistent/directory"))

        assert "not found" in str(exc_info.value).lower()


# =============================================================================
# INTEGRATION WITH CATALOG FILES
# =============================================================================


class TestCatalogIntegration:
    """Tests for loading the actual pattern catalog."""

    def test_load_tier1_memory_patterns(self, registry: PatternRegistry) -> None:
        """Load Tier 1 memory patterns from catalog."""
        catalog_dir = (
            Path(__file__).parent.parent.parent.parent.parent.parent
            / "packages"
            / "starboard-server"
            / "starboard_server"
            / "tools"
            / "domain"
            / "diagnostic"
            / "patterns"
            / "catalog"
        )

        if not catalog_dir.exists():
            pytest.skip("Catalog directory not found")

        memory_file = catalog_dir / "tier1_memory.yaml"
        if not memory_file.exists():
            pytest.skip("tier1_memory.yaml not found")

        count = registry.load_from_file(memory_file)

        assert count >= 5  # Should have at least 5 memory patterns
        assert registry.get_pattern("exit_code_137") is not None
        assert registry.get_pattern("java_heap_space") is not None
        assert registry.get_pattern("gc_overhead_limit") is not None

    def test_load_all_catalog_patterns(self, registry: PatternRegistry) -> None:
        """Load all patterns from catalog directory."""
        catalog_dir = (
            Path(__file__).parent.parent.parent.parent.parent.parent
            / "packages"
            / "starboard-server"
            / "starboard_server"
            / "tools"
            / "domain"
            / "diagnostic"
            / "patterns"
            / "catalog"
        )

        if not catalog_dir.exists():
            pytest.skip("Catalog directory not found")

        count = registry.load_from_directory(catalog_dir)

        # Should have all Tier 1 + Tier 1b patterns
        assert count >= 10

        # Verify some key patterns exist
        assert registry.get_pattern("exit_code_137") is not None
        assert registry.get_pattern("shuffle_fetch_failed") is not None
        assert registry.get_pattern("column_not_found") is not None
