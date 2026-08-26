# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Back-compat shim (Phase-1 B2).

The exit-code triager was re-homed to the dep-light ``starboard_x`` namespace in
``starboard-core`` so it is importable without heavy dependencies. This module
re-exports the same objects so existing imports
(``from starboard.tools.domain.diagnostic.exit_code_triager import ...``) keep
working unchanged — single source of truth, no divergence.
"""

from __future__ import annotations

from starboard_x.diagnostic.exit_code_triager import (
    PROOF_SIGNALS,
    UNIX_SIGNALS,
    ExitCodeHypothesis,
    ExitCodeTriager,
    HypothesisType,
    ProofSignal,
    SignalInfo,
    TriageResult,
)

__all__ = [
    "PROOF_SIGNALS",
    "UNIX_SIGNALS",
    "ExitCodeHypothesis",
    "ExitCodeTriager",
    "HypothesisType",
    "ProofSignal",
    "SignalInfo",
    "TriageResult",
]
