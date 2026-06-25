# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Diagnostic pattern system with YAML-based pattern definitions.

This module provides:
- Pattern schema validation (Pydantic v2)
- Pattern registry with keyword indexing
- YAML pattern loading with fail-fast validation

Usage:
    from starboard_server.tools.domain.diagnostic.patterns import (
        PatternRegistry,
        get_pattern_registry,
    )

    registry = get_pattern_registry()
    candidates = registry.find_candidates_by_keywords("OutOfMemoryError")
"""

from starboard_server.tools.domain.diagnostic.patterns.registry import (
    PatternLoadError,
    PatternRegistry,
    get_pattern_registry,
    reset_global_registry,
)
from starboard_server.tools.domain.diagnostic.patterns.schema import (
    Category,
    ConfidenceFactorsYAML,
    EvidenceChecklistYAML,
    PatternCatalogYAML,
    PatternYAML,
    RecommendationYAML,
    ResponsibilityScope,
    Severity,
)

__all__ = [
    # Registry
    "PatternRegistry",
    "PatternLoadError",
    "get_pattern_registry",
    "reset_global_registry",
    # Schema
    "PatternYAML",
    "PatternCatalogYAML",
    "RecommendationYAML",
    "EvidenceChecklistYAML",
    "ConfidenceFactorsYAML",
    "Category",
    "Severity",
    "ResponsibilityScope",
]
