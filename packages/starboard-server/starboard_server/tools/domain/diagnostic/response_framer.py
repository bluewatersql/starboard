# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
ResponseFramer - Frames diagnostic responses based on confidence level.

Applies appropriate language and structure based on confidence:
- ≥90% (DEFINITIVE): Confident diagnosis with evidence
- 70-89% (LIKELY): Hedged diagnosis with confirmation steps
- 50-69% (HYPOTHESIS): Tentative diagnosis with questions
- <50% (UNCERTAIN): Multiple possibilities, requests more info
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ConfidenceLevel(StrEnum):
    """Confidence levels for diagnostic findings."""

    DEFINITIVE = "definitive"  # ≥90%
    LIKELY = "likely"  # 70-89%
    HYPOTHESIS = "hypothesis"  # 50-69%
    UNCERTAIN = "uncertain"  # <50%


@dataclass
class DiagnosticFinding:
    """A diagnostic finding to be framed.

    Attributes:
        diagnosis: The primary diagnosis.
        confidence: Confidence score (0-1).
        evidence: List of evidence supporting the diagnosis.
        root_cause: Identified root cause (if known).
        remediation: Suggested remediation steps.
        alternatives: Alternative diagnoses to consider.
    """

    diagnosis: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    root_cause: str | None = None
    remediation: list[str] | None = None
    alternatives: list[str] | None = None


@dataclass
class FramedResponse:
    """A framed diagnostic response.

    Attributes:
        framed_diagnosis: The diagnosis with appropriate language.
        confidence_level: The confidence level category.
        confidence_score: Original confidence score.
        evidence_citations: Evidence cited in the response.
        summary: Brief summary of the diagnosis.
        remediation_steps: Steps to remediate (for high confidence).
        confirmation_steps: Steps to confirm diagnosis (for medium confidence).
        clarifying_questions: Questions to ask (for low confidence).
        additional_evidence_needed: Evidence that would help.
        alternative_diagnoses: Other possible diagnoses.
    """

    framed_diagnosis: str
    confidence_level: ConfidenceLevel
    confidence_score: float
    evidence_citations: list[str] = field(default_factory=list)
    summary: str = ""
    remediation_steps: list[str] | None = None
    confirmation_steps: list[str] | None = None
    clarifying_questions: list[str] | None = None
    additional_evidence_needed: list[str] | None = None
    alternative_diagnoses: list[str] | None = None


class ResponseFramer:
    """Frames diagnostic responses based on confidence.

    Applies appropriate language patterns and response structure
    based on the confidence level of the diagnosis.
    """

    # Confidence thresholds
    DEFINITIVE_THRESHOLD = 0.90
    LIKELY_THRESHOLD = 0.70
    HYPOTHESIS_THRESHOLD = 0.50

    # Language patterns for each level
    _DEFINITIVE_PHRASES = [
        "The issue is {diagnosis}.",
        "The root cause is {root_cause}.",
        "This is caused by {root_cause}.",
    ]

    _LIKELY_PHRASES = [
        "This is most likely {diagnosis}.",
        "The issue appears to be {diagnosis}.",
        "This is probably caused by {root_cause}.",
    ]

    _HYPOTHESIS_PHRASES = [
        "This could be {diagnosis}.",
        "A possible explanation is {diagnosis}.",
        "The issue might be {root_cause}.",
        "Hypothesis: {diagnosis}.",
    ]

    _UNCERTAIN_PHRASES = [
        "Unable to determine the exact cause with current evidence.",
        "There are several possibilities based on the available information.",
        "Insufficient evidence to conclusively identify the issue.",
        "Cannot conclusively determine the root cause.",
    ]

    def get_confidence_level(self, confidence: float) -> ConfidenceLevel:
        """Determine confidence level from score.

        Args:
            confidence: Confidence score (0-1).

        Returns:
            ConfidenceLevel enum value.
        """
        # Clamp to valid range
        confidence = max(0.0, min(1.0, confidence))

        if confidence >= self.DEFINITIVE_THRESHOLD:
            return ConfidenceLevel.DEFINITIVE
        elif confidence >= self.LIKELY_THRESHOLD:
            return ConfidenceLevel.LIKELY
        elif confidence >= self.HYPOTHESIS_THRESHOLD:
            return ConfidenceLevel.HYPOTHESIS
        else:
            return ConfidenceLevel.UNCERTAIN

    def frame(self, finding: DiagnosticFinding) -> FramedResponse:
        """Frame a diagnostic finding with appropriate language.

        Args:
            finding: The diagnostic finding to frame.

        Returns:
            FramedResponse with appropriate language and structure.
        """
        level = self.get_confidence_level(finding.confidence)

        if level == ConfidenceLevel.DEFINITIVE:
            return self._frame_definitive(finding, level)
        elif level == ConfidenceLevel.LIKELY:
            return self._frame_likely(finding, level)
        elif level == ConfidenceLevel.HYPOTHESIS:
            return self._frame_hypothesis(finding, level)
        else:
            return self._frame_uncertain(finding, level)

    def _frame_definitive(
        self, finding: DiagnosticFinding, level: ConfidenceLevel
    ) -> FramedResponse:
        """Frame a definitive (≥90%) diagnosis."""
        # Build diagnosis statement
        diagnosis_text = f"The issue is {finding.diagnosis}."
        if finding.root_cause:
            diagnosis_text += f" The root cause is {finding.root_cause}."

        # Evidence citations
        citations = finding.evidence.copy() if finding.evidence else []

        # Remediation
        remediation = finding.remediation
        if not remediation:
            remediation = self._generate_default_remediation(finding)

        # Summary
        summary = (
            f"Diagnosis: {finding.diagnosis} (confidence: {finding.confidence:.0%})"
        )

        return FramedResponse(
            framed_diagnosis=diagnosis_text,
            confidence_level=level,
            confidence_score=finding.confidence,
            evidence_citations=citations,
            summary=summary,
            remediation_steps=remediation,
        )

    def _frame_likely(
        self, finding: DiagnosticFinding, level: ConfidenceLevel
    ) -> FramedResponse:
        """Frame a likely (70-89%) diagnosis."""
        # Build hedged diagnosis statement
        diagnosis_text = f"This is most likely {finding.diagnosis}."
        if finding.root_cause:
            diagnosis_text += f" The issue appears to be {finding.root_cause}."

        # Evidence citations
        citations = finding.evidence.copy() if finding.evidence else []

        # Confirmation steps
        confirmation = self._generate_confirmation_steps(finding)

        # Additional evidence that would help
        additional = self._generate_additional_evidence_needed(finding)

        # Summary
        summary = f"Likely diagnosis: {finding.diagnosis} (confidence: {finding.confidence:.0%})"

        return FramedResponse(
            framed_diagnosis=diagnosis_text,
            confidence_level=level,
            confidence_score=finding.confidence,
            evidence_citations=citations,
            summary=summary,
            remediation_steps=finding.remediation,
            confirmation_steps=confirmation,
            additional_evidence_needed=additional,
        )

    def _frame_hypothesis(
        self, finding: DiagnosticFinding, level: ConfidenceLevel
    ) -> FramedResponse:
        """Frame a hypothesis (50-69%) diagnosis."""
        # Build tentative diagnosis statement
        diagnosis_text = f"This could be {finding.diagnosis}."
        if finding.root_cause:
            diagnosis_text += f" A possible explanation is {finding.root_cause}."

        # Evidence citations
        citations = finding.evidence.copy() if finding.evidence else []

        # Clarifying questions
        questions = self._generate_clarifying_questions(finding)

        # Alternative diagnoses
        alternatives = finding.alternatives or self._generate_alternatives(finding)

        # Additional evidence needed
        additional = self._generate_additional_evidence_needed(finding)

        # Summary
        summary = (
            f"Hypothesis: {finding.diagnosis} (confidence: {finding.confidence:.0%})"
        )

        return FramedResponse(
            framed_diagnosis=diagnosis_text,
            confidence_level=level,
            confidence_score=finding.confidence,
            evidence_citations=citations,
            summary=summary,
            clarifying_questions=questions,
            alternative_diagnoses=alternatives,
            additional_evidence_needed=additional,
        )

    def _frame_uncertain(
        self, finding: DiagnosticFinding, level: ConfidenceLevel
    ) -> FramedResponse:
        """Frame an uncertain (<50%) diagnosis."""
        # Build exploratory diagnosis statement
        diagnosis_text = (
            "Unable to determine the exact cause with current evidence. "
            "There are several possibilities based on the available information."
        )

        if finding.diagnosis and finding.diagnosis.lower() not in (
            "unknown",
            "unclear",
            "ambiguous",
        ):
            diagnosis_text += f" One possibility is {finding.diagnosis}."

        # Evidence citations
        citations = finding.evidence.copy() if finding.evidence else []

        # Alternative diagnoses
        alternatives = finding.alternatives or self._generate_alternatives(finding)

        # Additional evidence needed (more extensive for uncertain)
        additional = self._generate_extensive_evidence_needed(finding)

        # Clarifying questions
        questions = self._generate_clarifying_questions(finding)

        # Summary
        summary = (
            f"Uncertain diagnosis (confidence: {finding.confidence:.0%}) - "
            f"more evidence needed"
        )

        return FramedResponse(
            framed_diagnosis=diagnosis_text,
            confidence_level=level,
            confidence_score=finding.confidence,
            evidence_citations=citations,
            summary=summary,
            clarifying_questions=questions,
            alternative_diagnoses=alternatives,
            additional_evidence_needed=additional,
        )

    def _generate_default_remediation(self, finding: DiagnosticFinding) -> list[str]:
        """Generate default remediation steps based on diagnosis."""
        diagnosis_lower = finding.diagnosis.lower()

        if "memory" in diagnosis_lower or "oom" in diagnosis_lower:
            return [
                "Increase executor memory (spark.executor.memory)",
                "Increase memory overhead (spark.executor.memoryOverhead)",
                "Review data processing patterns for memory-intensive operations",
            ]
        elif "timeout" in diagnosis_lower or "connection" in diagnosis_lower:
            return [
                "Check network connectivity between nodes",
                "Increase timeout configurations",
                "Review cluster health and resource availability",
            ]
        elif "disk" in diagnosis_lower or "storage" in diagnosis_lower:
            return [
                "Check available disk space on cluster nodes",
                "Consider using larger instance types with more storage",
                "Review data retention policies",
            ]
        else:
            return [
                "Review the error logs for more details",
                "Check cluster configuration and resource allocation",
                "Consider consulting Databricks documentation",
            ]

    def _generate_confirmation_steps(self, finding: DiagnosticFinding) -> list[str]:
        """Generate steps to confirm the diagnosis."""
        steps = ["Review the full error logs for additional context"]

        diagnosis_lower = finding.diagnosis.lower()

        if "memory" in diagnosis_lower:
            steps.append("Check Spark UI for memory usage patterns")
            steps.append("Review GC logs if available")
        elif "network" in diagnosis_lower or "connection" in diagnosis_lower:
            steps.append("Check network metrics between cluster nodes")
            steps.append("Verify firewall and security group rules")
        elif "disk" in diagnosis_lower:
            steps.append("Check disk usage on cluster nodes")
        elif "permission" in diagnosis_lower:
            steps.append("Verify user permissions on the resource")

        steps.append("Reproduce the issue with additional logging enabled")

        return steps

    def _generate_clarifying_questions(self, finding: DiagnosticFinding) -> list[str]:
        """Generate clarifying questions for low-confidence diagnoses."""
        questions = [
            "Can you provide more context about what the job was doing when it failed?",
            "Is this a recurring issue or did it happen for the first time?",
        ]

        diagnosis_lower = finding.diagnosis.lower()

        if "memory" in diagnosis_lower:
            questions.append("What is the current executor memory configuration?")
            questions.append("How large is the dataset being processed?")
        elif "network" in diagnosis_lower:
            questions.append("Are other jobs on the same cluster working correctly?")
            questions.append("Has there been any recent network or firewall changes?")

        return questions

    def _generate_alternatives(self, finding: DiagnosticFinding) -> list[str]:
        """Generate alternative diagnoses."""
        alternatives = []

        diagnosis_lower = finding.diagnosis.lower()

        if "memory" in diagnosis_lower:
            alternatives = [
                "Data skew causing memory concentration",
                "Memory leak in user code",
            ]
        elif "network" in diagnosis_lower:
            alternatives = ["DNS resolution issues", "Firewall blocking connections"]
        elif "timeout" in diagnosis_lower:
            alternatives = ["Resource contention", "Network latency issues"]
        else:
            alternatives = [
                "Configuration issue",
                "Resource contention",
                "Transient infrastructure problem",
            ]

        return alternatives

    def _generate_additional_evidence_needed(
        self, _finding: DiagnosticFinding
    ) -> list[str]:
        """Generate list of evidence that would help."""
        return [
            "Full stack trace from the error",
            "Spark UI screenshots or metrics",
            "Cluster event logs around the time of failure",
        ]

    def _generate_extensive_evidence_needed(
        self, _finding: DiagnosticFinding
    ) -> list[str]:
        """Generate extensive list of evidence for uncertain diagnoses."""
        return [
            "Full job logs from start to failure",
            "Complete stack trace with all 'Caused by' sections",
            "Spark UI task metrics and timeline",
            "Cluster configuration details",
            "Resource utilization metrics (CPU, memory, disk, network)",
            "Recent changes to the job or cluster configuration",
        ]
