# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Exit code triage and signal decoding.

This module provides:
- Unix signal decoding (128+N exit codes)
- Hypothesis classification for exit codes
- Proof signal matching for root cause identification

Design reference:
- changes/diagnostic_agent/UNIFIED_DESIGN.md Section 3.2 (Exit Code Triage)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HypothesisType(str, Enum):
    """Type of exit code hypothesis."""

    OOM = "oom"
    """Out of memory kill (SIGKILL with memory evidence)."""

    CANCELLATION = "cancellation"
    """User or system cancellation (SIGTERM)."""

    CONTAINER_LIMIT = "container_limit"
    """Container resource limit exceeded."""

    CRASH = "crash"
    """Process crash or segfault."""

    UNKNOWN = "unknown"
    """Unknown cause - requires investigation."""


@dataclass(frozen=True)
class SignalInfo:
    """Information about a Unix signal.

    Attributes:
        number: Signal number (e.g., 9 for SIGKILL).
        name: Signal name (e.g., "SIGKILL").
        description: Human-readable description.
        default_hypothesis: Most likely cause for this signal.
    """

    number: int
    name: str
    description: str
    default_hypothesis: HypothesisType


# Standard Unix signals with diagnostic relevance
UNIX_SIGNALS: dict[int, SignalInfo] = {
    1: SignalInfo(1, "SIGHUP", "Hangup", HypothesisType.UNKNOWN),
    2: SignalInfo(2, "SIGINT", "Interrupt (Ctrl+C)", HypothesisType.CANCELLATION),
    3: SignalInfo(3, "SIGQUIT", "Quit with core dump", HypothesisType.CRASH),
    4: SignalInfo(4, "SIGILL", "Illegal instruction", HypothesisType.CRASH),
    6: SignalInfo(6, "SIGABRT", "Abort signal", HypothesisType.CRASH),
    7: SignalInfo(7, "SIGBUS", "Bus error", HypothesisType.CRASH),
    8: SignalInfo(8, "SIGFPE", "Floating point exception", HypothesisType.CRASH),
    9: SignalInfo(9, "SIGKILL", "Forced kill (cannot be caught)", HypothesisType.OOM),
    11: SignalInfo(11, "SIGSEGV", "Segmentation fault", HypothesisType.CRASH),
    13: SignalInfo(13, "SIGPIPE", "Broken pipe", HypothesisType.UNKNOWN),
    14: SignalInfo(14, "SIGALRM", "Alarm clock", HypothesisType.UNKNOWN),
    15: SignalInfo(15, "SIGTERM", "Graceful termination", HypothesisType.CANCELLATION),
}


@dataclass(frozen=True)
class ProofSignal:
    """Evidence that supports or contradicts a hypothesis.

    Attributes:
        pattern: Regex or substring to search for.
        supports_hypothesis: Which hypothesis this supports.
        confidence_boost: How much to increase confidence (0.0-0.3).
        description: What this signal indicates.
    """

    pattern: str
    supports_hypothesis: HypothesisType
    confidence_boost: float
    description: str


# Proof signals for exit code triage
PROOF_SIGNALS: list[ProofSignal] = [
    # OOM evidence
    ProofSignal(
        "OOMKilled",
        HypothesisType.OOM,
        0.25,
        "Container was killed by OOM killer",
    ),
    ProofSignal(
        "Killed by signal 9",
        HypothesisType.OOM,
        0.1,
        "Process killed by SIGKILL",
    ),
    ProofSignal(
        "OutOfMemoryError",
        HypothesisType.OOM,
        0.2,
        "JVM out of memory error",
    ),
    ProofSignal(
        "oom-killer",
        HypothesisType.OOM,
        0.25,
        "Linux OOM killer invoked",
    ),
    ProofSignal(
        "Cannot allocate memory",
        HypothesisType.OOM,
        0.2,
        "Memory allocation failed",
    ),
    # Container limit evidence
    ProofSignal(
        "memory limit exceeded",
        HypothesisType.CONTAINER_LIMIT,
        0.25,
        "Container memory limit hit",
    ),
    ProofSignal(
        "container killed",
        HypothesisType.CONTAINER_LIMIT,
        0.15,
        "Container was terminated",
    ),
    ProofSignal(
        "resource limit",
        HypothesisType.CONTAINER_LIMIT,
        0.1,
        "Resource limit mentioned",
    ),
    # Cancellation evidence
    ProofSignal(
        "cancelled",
        HypothesisType.CANCELLATION,
        0.2,
        "Job was cancelled",
    ),
    ProofSignal(
        "user requested",
        HypothesisType.CANCELLATION,
        0.25,
        "User-initiated action",
    ),
    ProofSignal(
        "job cancellation",
        HypothesisType.CANCELLATION,
        0.25,
        "Job explicitly cancelled",
    ),
    ProofSignal(
        "timeout exceeded",
        HypothesisType.CANCELLATION,
        0.15,
        "Timeout triggered termination",
    ),
    ProofSignal(
        "cluster shutdown",
        HypothesisType.CANCELLATION,
        0.2,
        "Cluster was shut down",
    ),
    # Crash evidence
    ProofSignal(
        "segfault",
        HypothesisType.CRASH,
        0.25,
        "Segmentation fault occurred",
    ),
    ProofSignal(
        "core dump",
        HypothesisType.CRASH,
        0.2,
        "Core dump generated",
    ),
    ProofSignal(
        "SIGSEGV",
        HypothesisType.CRASH,
        0.25,
        "Segmentation violation signal",
    ),
]


@dataclass(frozen=True)
class ExitCodeHypothesis:
    """Hypothesis about why a process exited with a given code.

    Attributes:
        hypothesis_type: Category of the hypothesis.
        confidence: Confidence level [0.0, 1.0].
        signal_info: Signal information if exit code is 128+N.
        supporting_evidence: Evidence that supports this hypothesis.
        contradicting_evidence: Evidence that contradicts this hypothesis.
        next_steps: Recommended investigation steps.
    """

    hypothesis_type: HypothesisType
    confidence: float
    signal_info: SignalInfo | None
    supporting_evidence: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    next_steps: tuple[str, ...]


@dataclass(frozen=True)
class TriageResult:
    """Complete triage result for an exit code.

    Attributes:
        exit_code: The exit code being analyzed.
        is_signal: True if exit code is 128+N (signal-based).
        signal_number: Signal number if signal-based.
        primary_hypothesis: Most likely hypothesis.
        alternative_hypotheses: Other possible hypotheses.
        raw_interpretation: Plain English interpretation.
    """

    exit_code: int
    is_signal: bool
    signal_number: int | None
    primary_hypothesis: ExitCodeHypothesis
    alternative_hypotheses: tuple[ExitCodeHypothesis, ...]
    raw_interpretation: str


class ExitCodeTriager:
    """Analyzes exit codes and generates hypotheses.

    Decodes Unix signals (128+N exit codes) and uses proof signals
    from logs/context to determine the most likely root cause.

    Example:
        >>> triager = ExitCodeTriager()
        >>> result = triager.triage(137, "Container was OOMKilled")
        >>> print(result.primary_hypothesis.hypothesis_type)
        HypothesisType.OOM
    """

    def __init__(self) -> None:
        """Initialize triager with default configuration."""
        self._proof_signals = PROOF_SIGNALS

    def triage(
        self,
        exit_code: int,
        context: str = "",
    ) -> TriageResult:
        """Analyze an exit code and generate hypotheses.

        Args:
            exit_code: Process exit code to analyze.
            context: Additional context (logs, error messages) for evidence.

        Returns:
            TriageResult with primary and alternative hypotheses.
        """
        # Decode signal if 128+N
        is_signal = exit_code > 128
        signal_number = exit_code - 128 if is_signal else None
        signal_info = UNIX_SIGNALS.get(signal_number) if signal_number else None

        # Generate hypotheses
        hypotheses = self._generate_hypotheses(
            exit_code, is_signal, signal_number, signal_info, context
        )

        # Sort by confidence
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        # Build interpretation
        raw_interpretation = self._build_interpretation(
            exit_code, is_signal, signal_info
        )

        return TriageResult(
            exit_code=exit_code,
            is_signal=is_signal,
            signal_number=signal_number,
            primary_hypothesis=hypotheses[0],
            alternative_hypotheses=tuple(hypotheses[1:3]),  # Top 2 alternatives
            raw_interpretation=raw_interpretation,
        )

    def _generate_hypotheses(
        self,
        exit_code: int,
        is_signal: bool,
        signal_number: int | None,  # noqa: ARG002
        signal_info: SignalInfo | None,
        context: str,
    ) -> list[ExitCodeHypothesis]:
        """Generate all possible hypotheses for an exit code."""
        hypotheses: list[ExitCodeHypothesis] = []
        context_lower = context.lower()

        # Get default hypothesis from signal info
        default_type = (
            signal_info.default_hypothesis if signal_info else HypothesisType.UNKNOWN
        )

        # Check each hypothesis type
        for h_type in HypothesisType:
            base_confidence = self._get_base_confidence(
                h_type, exit_code, is_signal, default_type
            )
            supporting: list[str] = []
            contradicting: list[str] = []

            # Check proof signals
            for proof in self._proof_signals:
                if proof.pattern.lower() in context_lower:
                    if proof.supports_hypothesis == h_type:
                        base_confidence += proof.confidence_boost
                        supporting.append(proof.description)
                    else:
                        # Evidence for another hypothesis is evidence against this one
                        base_confidence -= proof.confidence_boost * 0.5
                        contradicting.append(
                            f"Evidence suggests {proof.supports_hypothesis.value} instead"
                        )

            # Clamp confidence
            confidence = max(0.0, min(1.0, base_confidence))

            # Only include if has some confidence
            if confidence > 0.1:
                next_steps = self._get_next_steps(h_type)
                hypotheses.append(
                    ExitCodeHypothesis(
                        hypothesis_type=h_type,
                        confidence=confidence,
                        signal_info=signal_info,
                        supporting_evidence=tuple(supporting),
                        contradicting_evidence=tuple(contradicting),
                        next_steps=next_steps,
                    )
                )

        # Ensure at least one hypothesis (UNKNOWN)
        if not hypotheses:
            hypotheses.append(
                ExitCodeHypothesis(
                    hypothesis_type=HypothesisType.UNKNOWN,
                    confidence=0.3,
                    signal_info=signal_info,
                    supporting_evidence=(),
                    contradicting_evidence=(),
                    next_steps=self._get_next_steps(HypothesisType.UNKNOWN),
                )
            )

        return hypotheses

    def _get_base_confidence(
        self,
        h_type: HypothesisType,
        exit_code: int,
        is_signal: bool,
        default_type: HypothesisType,
    ) -> float:
        """Get base confidence for a hypothesis type given exit code."""
        # Special exit codes
        if exit_code == 137:  # SIGKILL
            if h_type == HypothesisType.OOM:
                return 0.6  # High base for OOM on 137
            elif h_type == HypothesisType.CONTAINER_LIMIT:
                return 0.4
            elif h_type == HypothesisType.CANCELLATION:
                return 0.2  # Lower - SIGKILL usually not cancellation

        elif exit_code == 143:  # SIGTERM
            if h_type == HypothesisType.CANCELLATION:
                return 0.7  # High base for cancellation on 143
            elif h_type == HypothesisType.OOM:
                return 0.1  # Low - SIGTERM not typical for OOM

        elif exit_code == 139:  # SIGSEGV
            if h_type == HypothesisType.CRASH:
                return 0.8
            else:
                return 0.1

        elif exit_code == 134:  # SIGABRT
            if h_type == HypothesisType.CRASH:
                return 0.7
            else:
                return 0.1

        # Generic signal handling
        if is_signal and h_type == default_type:
            return 0.5

        # Non-signal exit codes
        if not is_signal:
            if exit_code == 0:
                return 0.0  # Success - no hypothesis needed
            elif exit_code == 1:
                return 0.3 if h_type == HypothesisType.UNKNOWN else 0.1
            else:
                return 0.2 if h_type == HypothesisType.UNKNOWN else 0.1

        return 0.2

    def _get_next_steps(self, h_type: HypothesisType) -> tuple[str, ...]:
        """Get recommended investigation steps for a hypothesis type."""
        steps: dict[HypothesisType, tuple[str, ...]] = {
            HypothesisType.OOM: (
                "Check cluster event logs for OOMKilled events",
                "Review GC logs for memory pressure before termination",
                "Check spark.executor.memory and memoryOverhead settings",
                "Look for memory-intensive operations (collect, broadcast, cache)",
            ),
            HypothesisType.CANCELLATION: (
                "Check job history for cancellation events",
                "Verify if user cancelled the job",
                "Check for timeout configurations",
                "Review cluster events for shutdown/scaling",
            ),
            HypothesisType.CONTAINER_LIMIT: (
                "Check container resource limits in cluster configuration",
                "Review Kubernetes/container orchestrator events",
                "Compare memory usage to container limits",
                "Consider increasing container memory limits",
            ),
            HypothesisType.CRASH: (
                "Check for core dump files if available",
                "Review native library compatibility",
                "Check for memory corruption issues",
                "Review recent code changes",
            ),
            HypothesisType.UNKNOWN: (
                "Review full executor/driver logs around failure time",
                "Check cluster event logs",
                "Look for any error messages before exit",
                "Consider enabling more verbose logging",
            ),
        }
        return steps.get(h_type, ())

    def _build_interpretation(
        self,
        exit_code: int,
        is_signal: bool,
        signal_info: SignalInfo | None,
    ) -> str:
        """Build plain English interpretation of exit code."""
        if exit_code == 0:
            return "Process exited successfully (exit code 0)."

        if is_signal and signal_info:
            return (
                f"Process terminated by {signal_info.name} (signal {signal_info.number}). "
                f"Exit code {exit_code} = 128 + {signal_info.number}. "
                f"{signal_info.description}."
            )

        if is_signal:
            signal_num = exit_code - 128
            return (
                f"Process terminated by signal {signal_num}. "
                f"Exit code {exit_code} = 128 + {signal_num}."
            )

        return f"Process exited with code {exit_code}."

    def decode_exit_code(self, exit_code: int) -> str:
        """Get a quick interpretation of an exit code.

        Args:
            exit_code: Exit code to decode.

        Returns:
            Human-readable interpretation.
        """
        if exit_code == 0:
            return "Success"

        if exit_code > 128:
            signal_num = exit_code - 128
            signal = UNIX_SIGNALS.get(signal_num)
            if signal:
                return f"{signal.name} ({signal.description})"
            return f"Signal {signal_num}"

        # Common non-signal exit codes
        common_codes = {
            1: "General error",
            2: "Misuse of shell command",
            126: "Command invoked cannot execute",
            127: "Command not found",
            128: "Invalid exit argument",
        }

        return common_codes.get(exit_code, f"Exit code {exit_code}")
