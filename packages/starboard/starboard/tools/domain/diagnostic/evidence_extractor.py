# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Back-compat shim (Phase-1 B2).

The evidence-window extractor was re-homed to the dep-light ``starboard_x``
namespace in ``starboard-core``. This module re-exports the same objects so
existing imports keep working unchanged — single source of truth, no divergence.
"""

from __future__ import annotations

from starboard_x.diagnostic.evidence_extractor import (
    EvidenceType,
    EvidenceWindow,
    EvidenceWindowExtractor,
    ExtractionResult,
)

__all__ = [
    "EvidenceType",
    "EvidenceWindow",
    "EvidenceWindowExtractor",
    "ExtractionResult",
]
