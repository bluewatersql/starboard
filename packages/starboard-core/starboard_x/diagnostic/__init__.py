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

The trio's public objects are re-exported here for convenience, but **lazily**
(PEP 562 module ``__getattr__``): merely importing this package does not pull in
evidence_extractor / exit_code_triager / models / root_cause_synthesizer. A
submodule loads only when one of its re-exported names is first accessed, so a
single verb (e.g. ``triage-exit``) still touches only the module it needs.
``python -m starboard_x.diagnostic`` and the back-compat shims import the
submodules directly and are unaffected.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Public name -> submodule that defines it. The lazy ``__getattr__`` resolves an
# attribute by importing exactly that submodule (and nothing else).
_EXPORTS: dict[str, str] = {
    # exit code triage
    "ExitCodeTriager": "exit_code_triager",
    "ExitCodeHypothesis": "exit_code_triager",
    "HypothesisType": "exit_code_triager",
    "TriageResult": "exit_code_triager",
    # evidence extraction
    "EvidenceWindowExtractor": "evidence_extractor",
    "EvidenceType": "evidence_extractor",
    "EvidenceWindow": "evidence_extractor",
    "ExtractionResult": "evidence_extractor",
    # root cause synthesis
    "RootCauseSynthesizer": "root_cause_synthesizer",
    "SynthesisResult": "root_cause_synthesizer",
    "ToolOutput": "root_cause_synthesizer",
    # model subset
    "PrimarySymptom": "models",
    "ExplorationSummary": "models",
}

# Backwards-friendly alias: the trio is referred to as "EvidenceExtractor" in
# the Phase-1 spec; the concrete class name is EvidenceWindowExtractor. Resolve
# it from the same submodule.
_ALIASES: dict[str, str] = {
    "EvidenceExtractor": "EvidenceWindowExtractor",
}

__all__ = [*_EXPORTS, *_ALIASES]


def __getattr__(name: str) -> Any:
    """Lazily resolve a public re-export to its defining submodule (PEP 562)."""
    target = _ALIASES.get(name, name)
    submodule = _EXPORTS.get(target)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f"{__name__}.{submodule}")
    value = getattr(module, target)
    globals()[name] = value  # cache so subsequent access skips __getattr__
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


if TYPE_CHECKING:  # help type-checkers/IDEs see the re-exports without eager imports
    from starboard_x.diagnostic.evidence_extractor import (
        EvidenceType as EvidenceType,
    )
    from starboard_x.diagnostic.evidence_extractor import (
        EvidenceWindow as EvidenceWindow,
    )
    from starboard_x.diagnostic.evidence_extractor import (
        EvidenceWindowExtractor as EvidenceWindowExtractor,
    )
    from starboard_x.diagnostic.evidence_extractor import (
        ExtractionResult as ExtractionResult,
    )
    from starboard_x.diagnostic.exit_code_triager import (
        ExitCodeHypothesis as ExitCodeHypothesis,
    )
    from starboard_x.diagnostic.exit_code_triager import (
        ExitCodeTriager as ExitCodeTriager,
    )
    from starboard_x.diagnostic.exit_code_triager import (
        HypothesisType as HypothesisType,
    )
    from starboard_x.diagnostic.exit_code_triager import (
        TriageResult as TriageResult,
    )
    from starboard_x.diagnostic.models import (
        ExplorationSummary as ExplorationSummary,
    )
    from starboard_x.diagnostic.models import (
        PrimarySymptom as PrimarySymptom,
    )
    from starboard_x.diagnostic.root_cause_synthesizer import (
        RootCauseSynthesizer as RootCauseSynthesizer,
    )
    from starboard_x.diagnostic.root_cause_synthesizer import (
        SynthesisResult as SynthesisResult,
    )
    from starboard_x.diagnostic.root_cause_synthesizer import (
        ToolOutput as ToolOutput,
    )

    EvidenceExtractor = EvidenceWindowExtractor
