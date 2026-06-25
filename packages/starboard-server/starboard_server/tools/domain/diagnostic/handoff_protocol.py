# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Handoff protocol for diagnostic agent.

This module implements the structured handoff mechanism for transferring
diagnostic context to specialist agents when the diagnostic agent identifies
issues that fall under another domain's expertise.

Design reference: changes/diagnostic_agent/UNIFIED_DESIGN.md Section 9
"""

from __future__ import annotations

from dataclasses import dataclass, field

from starboard_server.tools.domain.diagnostic.models import (
    DiagnosticFingerprint,
    PrimarySymptom,
)

# Minimum confidence required for handoff (below this, stay with diagnostic)
HANDOFF_CONFIDENCE_THRESHOLD = 0.5

# Symptom-specific message templates
_HANDOFF_MESSAGES: dict[PrimarySymptom, str] = {
    PrimarySymptom.OOM: (
        "Memory issue detected: {causes}. "
        "The cluster agent can analyze memory configuration and suggest optimizations."
    ),
    PrimarySymptom.EXECUTOR_LOST: (
        "Executor lost during job execution: {causes}. "
        "The cluster agent can investigate resource allocation and stability issues."
    ),
    PrimarySymptom.DRIVER_CRASH: (
        "Driver process crashed: {causes}. "
        "The cluster agent can analyze driver configuration and memory settings."
    ),
    PrimarySymptom.PERMISSION: (
        "Permission or access denied: {causes}. "
        "The UC agent can verify grants and governance policies."
    ),
    PrimarySymptom.UC_ERROR: (
        "Unity Catalog error detected: {causes}. "
        "The UC agent can investigate catalog, schema, or table configuration."
    ),
    PrimarySymptom.PARSE_ERROR: (
        "Query parse or analysis error: {causes}. "
        "The query agent can analyze SQL syntax and schema references."
    ),
    PrimarySymptom.TIMEOUT: (
        "Query or operation timeout: {causes}. "
        "The warehouse agent can investigate query performance and concurrency."
    ),
    PrimarySymptom.DATA_SKEW: (
        "Data skew detected affecting partition distribution: {causes}. "
        "The job agent can analyze task distribution and suggest repartitioning."
    ),
    PrimarySymptom.SHUFFLE_FAILURE: (
        "Shuffle operation failed: {causes}. "
        "The job agent can analyze shuffle configuration and network issues."
    ),
    PrimarySymptom.SERIALIZATION_ERROR: (
        "Task serialization error: {causes}. "
        "The job agent can identify non-serializable objects in the job code."
    ),
    PrimarySymptom.DELTA_ERROR: (
        "Delta Lake error: {causes}. "
        "The job agent can analyze Delta table operations and concurrency issues."
    ),
    PrimarySymptom.CONNECTION_ERROR: (
        "Connection or network error: {causes}. "
        "The cluster agent can investigate network configuration and connectivity."
    ),
    PrimarySymptom.UNKNOWN: (
        "Issue requires further investigation: {causes}. "
        "Continuing diagnostic analysis."
    ),
}


@dataclass
class HandoffResult:
    """Result of a diagnostic handoff.

    Contains all information needed by the receiving agent to continue
    investigation without re-analyzing the original artifact.
    """

    target_agent: str
    """The agent domain receiving the handoff (cluster, job, query, uc, warehouse)."""

    fingerprint: DiagnosticFingerprint
    """Complete diagnostic fingerprint with evidence and context."""

    handoff_message: str
    """Human-readable message explaining why handoff is happening."""

    exploration_context: str | None = None
    """Summary of exploration steps taken before handoff."""

    def to_dict(self) -> dict:
        """Convert to dictionary for agent communication.

        Returns:
            Dictionary suitable for JSON serialization and agent messaging.
        """
        result = {
            "target_agent": self.target_agent,
            "fingerprint": self.fingerprint.to_dict(),
            "handoff_message": self.handoff_message,
        }
        if self.exploration_context:
            result["exploration_context"] = self.exploration_context
        return result


@dataclass
class HandoffProtocol:
    """Protocol for structured agent handoffs.

    Determines when to handoff, to whom, and creates the handoff payload.
    """

    confidence_threshold: float = field(default=HANDOFF_CONFIDENCE_THRESHOLD)
    """Minimum confidence required to recommend handoff."""

    def should_handoff(self, fingerprint: DiagnosticFingerprint) -> bool:
        """Determine if a handoff is recommended.

        A handoff is recommended when:
        1. Confidence is above threshold
        2. The target agent differs from diagnostic
        3. The symptom is not UNKNOWN

        Args:
            fingerprint: The diagnostic fingerprint from exploration.

        Returns:
            True if handoff is recommended, False otherwise.
        """
        # Check confidence threshold
        if (
            fingerprint.exploration_summary
            and fingerprint.exploration_summary.final_confidence
            < self.confidence_threshold
        ):
            return False

        # Unknown symptoms stay with diagnostic
        if fingerprint.primary_symptom == PrimarySymptom.UNKNOWN:
            return False

        # Check if handoff target differs from diagnostic
        target = fingerprint.get_handoff_target()
        return target != "diagnostic"

    def create_handoff(self, fingerprint: DiagnosticFingerprint) -> HandoffResult:
        """Create a handoff result for the given fingerprint.

        Args:
            fingerprint: The diagnostic fingerprint with evidence.

        Returns:
            HandoffResult with target, message, and context.
        """
        target_agent = fingerprint.get_handoff_target()
        handoff_message = self._generate_message(fingerprint)
        exploration_context = self._generate_exploration_context(fingerprint)

        return HandoffResult(
            target_agent=target_agent,
            fingerprint=fingerprint,
            handoff_message=handoff_message,
            exploration_context=exploration_context,
        )

    def _generate_message(self, fingerprint: DiagnosticFingerprint) -> str:
        """Generate the handoff message for a fingerprint.

        Args:
            fingerprint: The diagnostic fingerprint.

        Returns:
            Human-readable handoff message.
        """
        symptom = fingerprint.primary_symptom
        causes = ", ".join(fingerprint.likely_root_causes[:3])  # Top 3 causes

        template = _HANDOFF_MESSAGES.get(
            symptom,
            "Issue detected: {causes}. Transferring to specialist agent.",
        )

        return template.format(causes=causes)

    def _generate_exploration_context(
        self, fingerprint: DiagnosticFingerprint
    ) -> str | None:
        """Generate exploration context summary for receiving agent.

        Args:
            fingerprint: The diagnostic fingerprint with exploration summary.

        Returns:
            Summary string or None if no exploration summary available.
        """
        summary = fingerprint.exploration_summary
        if not summary:
            return None

        parts = [
            f"Diagnostic exploration completed in {summary.steps_completed} steps",
            f"with {summary.final_confidence:.0%} confidence.",
        ]

        if summary.strategies_used:
            parts.append(f"Strategies used: {', '.join(summary.strategies_used)}.")

        if summary.patterns_matched:
            parts.append(f"Matched patterns: {', '.join(summary.patterns_matched)}.")

        if summary.tool_calls_made:
            parts.append(f"Tool calls: {', '.join(summary.tool_calls_made)}.")

        return " ".join(parts)
