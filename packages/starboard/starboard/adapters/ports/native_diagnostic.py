# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public ``DiagnosticBackendPort`` adapter over the native extractors (C5).

Wraps the artifact detector + evidence-window extractor (the harvested evidence
model). No new capability — just the port surface.
"""

from __future__ import annotations

from starboard_core.ports.diagnostic_backend import (
    Candidate,
    DiagnosticBackendPort,
    DiagnosticResult,
)

from starboard.tools.domain.diagnostic.artifact_detector import ArtifactDetector
from starboard.tools.domain.diagnostic.evidence_extractor import (
    EvidenceWindowExtractor,
)


class NativeDiagnosticAdapter(DiagnosticBackendPort):
    """Classify + analyze pasted diagnostic text with native components.

    Args:
        detector: Optional artifact detector (defaults to ``ArtifactDetector``).
        extractor: Optional evidence extractor (defaults to
            ``EvidenceWindowExtractor``).
    """

    def __init__(
        self,
        detector: ArtifactDetector | None = None,
        extractor: EvidenceWindowExtractor | None = None,
    ) -> None:
        self._detector = detector or ArtifactDetector()
        self._extractor = extractor or EvidenceWindowExtractor()

    def classify(self, pasted: str) -> list[Candidate]:
        if not pasted or not pasted.strip():
            return []
        detection = self._detector.detect(pasted)
        return [
            Candidate(
                kind=detection.artifact_type.value,
                raw=pasted,
                confidence=detection.confidence,
                signals=detection.signals,
            )
        ]

    async def analyze(self, candidate: Candidate) -> DiagnosticResult:
        result = self._extractor.extract(candidate.raw)
        primary = result.primary_evidence
        root_causes = (primary.content,) if primary is not None else ()
        confidence = primary.confidence if primary is not None else 0.0
        return DiagnosticResult(
            summary=result.summary,
            root_causes=root_causes,
            confidence=confidence,
            evidence=tuple(w.window_id for w in result.windows),
            metadata={
                "has_fatal": str(result.has_fatal),
                "window_count": str(result.window_count),
                "artifact_kind": candidate.kind,
            },
        )
