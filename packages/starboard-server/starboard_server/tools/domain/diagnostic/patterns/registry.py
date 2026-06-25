# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Pattern registry with YAML loading and keyword indexing.

This module provides:
- YAML pattern loading with Pydantic validation (fail-fast on invalid patterns)
- Keyword index for fast pre-filtering
- Conversion from YAML models to internal domain models

Design reference:
- changes/diagnostic_agent/IMPLEMENTATION_CHECKLIST.md
- changes/diag_patterns/merged.md Section "Matching pipeline"

Note:
    File I/O in this module uses synchronous reads because pattern loading
    occurs exclusively at startup (lazy singleton init via
    ``get_pattern_registry``). See ``changes/async/ACCEPTABLE.md`` Exception 5.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.diagnostic.models import (
    ConfidenceFactors,
    ErrorPattern,
    EvidenceChecklist,
    PatternCategory,
    PatternSignature,
    Recommendation,
)
from starboard_server.tools.domain.diagnostic.patterns.schema import (
    Category,
    PatternCatalogYAML,
    PatternYAML,
)

logger = get_logger(__name__)


class PatternLoadError(Exception):
    """Raised when pattern loading fails."""

    pass


class PatternRegistry:
    """Registry for diagnostic patterns with keyword indexing.

    Loads patterns from YAML files at startup and provides fast lookup.
    Invalid patterns cause fail-fast errors during initialization.

    Example:
        >>> registry = PatternRegistry()
        >>> registry.load_from_directory(Path("patterns_yaml"))
        >>> candidates = registry.find_candidates_by_keywords(["OutOfMemoryError"])
        >>> len(candidates) > 0
        True
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._patterns: dict[str, ErrorPattern] = {}
        self._keyword_index: dict[str, set[str]] = {}  # keyword -> pattern_ids
        self._yaml_patterns: dict[str, PatternYAML] = {}  # id -> raw YAML model

    @property
    def patterns(self) -> dict[str, ErrorPattern]:
        """All registered patterns by ID."""
        return self._patterns.copy()

    @property
    def pattern_count(self) -> int:
        """Number of registered patterns."""
        return len(self._patterns)

    def get_pattern(self, pattern_id: str) -> ErrorPattern | None:
        """Get pattern by ID."""
        return self._patterns.get(pattern_id)

    def get_yaml_pattern(self, pattern_id: str) -> PatternYAML | None:
        """Get raw YAML pattern by ID for debugging/inspection."""
        return self._yaml_patterns.get(pattern_id)

    def load_from_directory(self, directory: Path) -> int:
        """Load all YAML pattern files from a directory.

        Args:
            directory: Path to directory containing YAML files.

        Returns:
            Number of patterns loaded.

        Raises:
            PatternLoadError: If any pattern file is invalid.
        """
        if not directory.exists():
            raise PatternLoadError(f"Pattern directory not found: {directory}")

        yaml_files = list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))

        if not yaml_files:
            logger.warning("no_yaml_files_found", directory=str(directory))
            return 0

        total_loaded = 0
        for yaml_file in yaml_files:
            loaded = self.load_from_file(yaml_file)
            total_loaded += loaded

        logger.info(
            "loaded_patterns_from_directory",
            total_loaded=total_loaded,
            file_count=len(yaml_files),
            directory=str(directory),
        )
        return total_loaded

    def load_from_file(self, file_path: Path) -> int:
        """Load patterns from a single YAML file.

        Note:
            Uses synchronous I/O — called only at startup.
            See ``changes/async/ACCEPTABLE.md`` Exception 5.

        Args:
            file_path: Path to YAML file.

        Returns:
            Number of patterns loaded.

        Raises:
            PatternLoadError: If file is invalid or patterns fail validation.
        """
        if not file_path.exists():
            raise PatternLoadError(f"Pattern file not found: {file_path}")

        # Startup-only sync I/O — see ACCEPTABLE.md Exception 5
        try:
            with open(file_path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise PatternLoadError(f"Invalid YAML in {file_path}: {e}") from e

        if raw_data is None:
            logger.warning("empty_yaml_file", file_path=str(file_path))
            return 0

        try:
            catalog = PatternCatalogYAML.model_validate(raw_data)
        except ValidationError as e:
            raise PatternLoadError(
                f"Pattern validation failed in {file_path}:\n{e}"
            ) from e

        for yaml_pattern in catalog.patterns:
            self._register_pattern(yaml_pattern)

        logger.debug(
            "loaded_patterns_from_file",
            count=len(catalog.patterns),
            file_path=str(file_path),
        )
        return len(catalog.patterns)

    def load_from_yaml_string(self, yaml_content: str, source: str = "<string>") -> int:
        """Load patterns from a YAML string.

        Useful for testing and programmatic loading.

        Args:
            yaml_content: YAML content as string.
            source: Source identifier for error messages.

        Returns:
            Number of patterns loaded.

        Raises:
            PatternLoadError: If content is invalid.
        """
        try:
            raw_data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise PatternLoadError(f"Invalid YAML from {source}: {e}") from e

        if raw_data is None:
            return 0

        try:
            catalog = PatternCatalogYAML.model_validate(raw_data)
        except ValidationError as e:
            raise PatternLoadError(
                f"Pattern validation failed from {source}:\n{e}"
            ) from e

        for yaml_pattern in catalog.patterns:
            self._register_pattern(yaml_pattern)

        return len(catalog.patterns)

    def _register_pattern(self, yaml_pattern: PatternYAML) -> None:
        """Register a pattern and update the keyword index."""
        # Convert to internal model
        pattern = self._convert_to_internal(yaml_pattern)

        # Store both representations
        self._patterns[pattern.pattern_id] = pattern
        self._yaml_patterns[pattern.pattern_id] = yaml_pattern

        # Update keyword index
        for keyword in yaml_pattern.keywords:
            keyword_lower = keyword.lower()
            if keyword_lower not in self._keyword_index:
                self._keyword_index[keyword_lower] = set()
            self._keyword_index[keyword_lower].add(pattern.pattern_id)

    def _convert_to_internal(self, yaml_pattern: PatternYAML) -> ErrorPattern:
        """Convert YAML pattern to internal ErrorPattern model."""
        # Convert category
        category_map = {
            Category.MEMORY: PatternCategory.MEMORY,
            Category.EXECUTION: PatternCategory.MEMORY,  # Map to closest
            Category.SHUFFLE: PatternCategory.NETWORK,
            Category.NETWORK: PatternCategory.NETWORK,
            Category.SQL: PatternCategory.SQL,
            Category.STORAGE: PatternCategory.DATA,
            Category.DELTA: PatternCategory.DELTA,
            Category.UC: PatternCategory.UC,
            Category.STREAMING: PatternCategory.DATA,
            Category.DATA_QUALITY: PatternCategory.DATA,
            Category.CLUSTER: PatternCategory.CONFIG,
            Category.PERFORMANCE: PatternCategory.DATA,
        }
        category = category_map.get(yaml_pattern.category, PatternCategory.CONFIG)

        # Convert recommendations
        recommendations = tuple(
            Recommendation(
                id=r.id,
                priority=r.priority,  # type: ignore[arg-type]
                action=r.action,
                implementation=r.implementation,
                verification=r.verification,
                tradeoffs=r.tradeoffs,
            )
            for r in yaml_pattern.recommendations
        )

        # Build signature
        signature = PatternSignature(
            exit_code=yaml_pattern.exit_code,
            exception_class=yaml_pattern.exception_class,
            message_pattern=yaml_pattern.message_pattern,
        )

        # Build evidence checklist
        evidence_checklist = EvidenceChecklist(
            required=tuple(yaml_pattern.evidence_checklist.required),
            supporting=tuple(yaml_pattern.evidence_checklist.supporting),
        )

        # Build confidence factors
        confidence_factors = ConfidenceFactors(
            increase=tuple(yaml_pattern.confidence_factors.increase),
            decrease=tuple(yaml_pattern.confidence_factors.decrease),
        )

        return ErrorPattern(
            pattern_id=yaml_pattern.id,
            name=yaml_pattern.name,
            category=category,
            signature=signature,
            log_patterns=tuple(yaml_pattern.regex_patterns),
            root_cause=yaml_pattern.root_cause,
            symptoms=tuple(yaml_pattern.symptoms),
            evidence_checklist=evidence_checklist,
            recommendations=recommendations,
            confidence_factors=confidence_factors,
            version=yaml_pattern.version,
            databricks_runtimes=tuple(yaml_pattern.databricks_runtimes),
        )

    def find_candidates_by_keywords(self, text: str) -> list[ErrorPattern]:
        """Find candidate patterns by keyword matching.

        This is the fast pre-filter stage of the matching pipeline.
        Uses the keyword index to quickly find potentially matching patterns.

        Args:
            text: Text to search for keywords.

        Returns:
            List of candidate patterns (may contain false positives).
        """
        text_lower = text.lower()
        candidate_ids: set[str] = set()

        for keyword, pattern_ids in self._keyword_index.items():
            if keyword in text_lower:
                candidate_ids.update(pattern_ids)

        return [self._patterns[pid] for pid in candidate_ids if pid in self._patterns]

    def find_candidates_by_exit_code(self, exit_code: int) -> list[ErrorPattern]:
        """Find patterns that match a specific exit code.

        Args:
            exit_code: Exit code to match.

        Returns:
            List of matching patterns.
        """
        return [
            pattern
            for pattern in self._patterns.values()
            if pattern.signature.exit_code == exit_code
        ]

    def get_all_keywords(self) -> set[str]:
        """Get all registered keywords."""
        return set(self._keyword_index.keys())

    def clear(self) -> None:
        """Clear all registered patterns."""
        self._patterns.clear()
        self._keyword_index.clear()
        self._yaml_patterns.clear()


# Global registry instance (initialized lazily)
_global_registry: PatternRegistry | None = None


# Startup-only sync I/O — see ACCEPTABLE.md Exception 5
# The global registry is initialized lazily on first access (typically at
# application startup) and cached for the lifetime of the process.
def get_pattern_registry() -> PatternRegistry:
    """Get the global pattern registry.

    Initializes with built-in patterns on first access.

    Note:
        Uses synchronous I/O for initial load — called only once at startup.
        See ``changes/async/ACCEPTABLE.md`` Exception 5.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = PatternRegistry()
        # Load built-in patterns from the patterns_yaml directory
        patterns_dir = Path(__file__).parent / "catalog"
        if patterns_dir.exists():
            try:
                _global_registry.load_from_directory(patterns_dir)
            except PatternLoadError as e:
                logger.error("failed_to_load_built_in_patterns", error=str(e))
                raise
    return _global_registry


def reset_global_registry() -> None:
    """Reset the global registry (for testing)."""
    global _global_registry
    _global_registry = None
