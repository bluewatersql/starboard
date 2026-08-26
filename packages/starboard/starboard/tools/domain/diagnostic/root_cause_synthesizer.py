# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Back-compat shim (Phase-1 B2).

The root-cause synthesizer was re-homed to the dep-light ``starboard_x``
namespace in ``starboard-core``. This module re-exports the same objects so
existing imports keep working unchanged — single source of truth, no divergence.
"""

from __future__ import annotations

from starboard_x.diagnostic.root_cause_synthesizer import (
    CONTRADICTION_PENALTY,
    MULTI_PATTERN_BOOST,
    MULTI_TOOL_BOOST,
    TOOL_CONFIRMATION_BOOST,
    TOOL_FAILURE_PENALTY,
    RootCauseSynthesizer,
    SynthesisResult,
    ToolOutput,
)

__all__ = [
    "CONTRADICTION_PENALTY",
    "MULTI_PATTERN_BOOST",
    "MULTI_TOOL_BOOST",
    "TOOL_CONFIRMATION_BOOST",
    "TOOL_FAILURE_PENALTY",
    "RootCauseSynthesizer",
    "SynthesisResult",
    "ToolOutput",
]
