# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.diagnostic`` — the stdlib-only diagnostic trio (``diagnostics-core``).

Re-homed from ``starboard.tools.domain.diagnostic`` (Phase-1 B2). This package
carries a **trimmed** ``__init__`` so a single verb (e.g. ``triage-exit``) does
not pull the whole diagnostic subsystem (artifact explorer, pattern registry,
etc.). Only the pure trio + its model subset live here:

- :class:`~starboard_x.diagnostic.exit_code_triager.ExitCodeTriager`
- :class:`~starboard_x.diagnostic.evidence_extractor.EvidenceWindowExtractor`
- :class:`~starboard_x.diagnostic.root_cause_synthesizer.RootCauseSynthesizer`

Importing this package imports the standard library only (no pyyaml, no
pydantic, no databricks-sdk).
"""

from starboard_x.diagnostic.evidence_extractor import (
    EvidenceType,
    EvidenceWindow,
    EvidenceWindowExtractor,
    ExtractionResult,
)
from starboard_x.diagnostic.exit_code_triager import (
    ExitCodeHypothesis,
    ExitCodeTriager,
    HypothesisType,
    TriageResult,
)
from starboard_x.diagnostic.models import (
    ExplorationSummary,
    PrimarySymptom,
)
from starboard_x.diagnostic.root_cause_synthesizer import (
    RootCauseSynthesizer,
    SynthesisResult,
    ToolOutput,
)

# Backwards-friendly alias: the trio is referred to as "EvidenceExtractor" in
# the Phase-1 spec; the concrete class name is EvidenceWindowExtractor.
EvidenceExtractor = EvidenceWindowExtractor

__all__ = [
    # exit code triage
    "ExitCodeTriager",
    "ExitCodeHypothesis",
    "HypothesisType",
    "TriageResult",
    # evidence extraction
    "EvidenceExtractor",
    "EvidenceWindowExtractor",
    "EvidenceType",
    "EvidenceWindow",
    "ExtractionResult",
    # root cause synthesis
    "RootCauseSynthesizer",
    "SynthesisResult",
    "ToolOutput",
    # model subset
    "PrimarySymptom",
    "ExplorationSummary",
]
