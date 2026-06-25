# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Pattern matching engine for diagnostic error patterns.

This module provides:
- Regex-based pattern matching against log/error text
- Confidence scoring with positive and negative signals
- Multi-pattern handling and ranking
- Observability event emission

Design reference:
- changes/diagnostic_agent/IMPLEMENTATION_CHECKLIST.md
- changes/diag_patterns/merged.md Section "Matching pipeline"
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from dataclasses import dataclass

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.diagnostic.models import (
    ErrorPattern,
    PatternMatch,
)
from starboard_server.tools.domain.diagnostic.patterns.registry import (
    PatternRegistry,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class MatchResult:
    """Result from pattern matching with confidence details.

    Attributes:
        matches: List of all pattern matches found.
        top_match: Highest confidence match (if any).
        match_count: Total number of patterns matched.
        processing_time_ms: Time taken for matching.
    """

    matches: tuple[PatternMatch, ...]
    top_match: PatternMatch | None
    match_count: int
    processing_time_ms: float = 0.0

    @property
    def has_matches(self) -> bool:
        """True if any patterns matched."""
        return self.match_count > 0


@dataclass(frozen=True)
class ConfidenceDetails:
    """Detailed breakdown of confidence score calculation.

    Attributes:
        base_score: Base confidence from pattern match type.
        increase_factors: Factors that increased confidence.
        decrease_factors: Factors that decreased confidence (negative signals).
        final_score: Final computed confidence score [0.0, 1.0].
    """

    base_score: float
    increase_factors: tuple[tuple[str, float], ...]  # (reason, delta)
    decrease_factors: tuple[tuple[str, float], ...]  # (reason, delta)
    final_score: float


class PatternMatcher:
    """Engine for matching error patterns against text.

    Uses a multi-stage pipeline:
    1. Candidate selection via keyword pre-filter
    2. Regex matching for candidates
    3. Confidence scoring with positive/negative signals
    4. Result ranking and deduplication

    Example:
        >>> registry = PatternRegistry()
        >>> registry.load_from_directory(Path("patterns_yaml"))
        >>> matcher = PatternMatcher(registry)
        >>> result = matcher.match("java.lang.OutOfMemoryError: Java heap space")
        >>> print(result.top_match.pattern_id)
        'java_heap_space'
    """

    # Base confidence scores by match type
    BASE_SCORE_EXIT_CODE = 0.7
    BASE_SCORE_EXCEPTION_CLASS = 0.8
    BASE_SCORE_MESSAGE_PATTERN = 0.6
    BASE_SCORE_REGEX = 0.5

    # Score adjustments
    MULTIPLE_SIGNAL_BONUS = 0.1  # Bonus for each additional signal type
    NEGATIVE_SIGNAL_PENALTY = 0.15  # Penalty per negative signal found
    INCREASE_SIGNAL_BONUS = 0.1  # Bonus per positive signal found

    def __init__(
        self,
        registry: PatternRegistry,
        *,
        max_matches: int = 5,
        min_confidence: float = 0.3,
    ) -> None:
        """Initialize matcher with pattern registry.

        Args:
            registry: Pattern registry to match against.
            max_matches: Maximum matches to return (default 5).
            min_confidence: Minimum confidence threshold (default 0.3).
        """
        self._registry = registry
        self._max_matches = max_matches
        self._min_confidence = min_confidence
        self._compiled_patterns: dict[str, list[re.Pattern[str]]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile all regex patterns for performance."""
        for pattern_id, pattern in self._registry.patterns.items():
            compiled = []
            for regex in pattern.log_patterns:
                try:
                    compiled.append(re.compile(regex, re.IGNORECASE | re.MULTILINE))
                except re.error as e:
                    logger.warning(
                        f"Failed to compile regex for {pattern_id}: {regex} - {e}"
                    )
            self._compiled_patterns[pattern_id] = compiled

            # Also compile exception_class and message_pattern
            if pattern.signature.exception_class:
                with contextlib.suppress(re.error):
                    self._compiled_patterns.setdefault(pattern_id, []).append(
                        re.compile(pattern.signature.exception_class, re.IGNORECASE)
                    )

            if pattern.signature.message_pattern:
                with contextlib.suppress(re.error):
                    self._compiled_patterns.setdefault(pattern_id, []).append(
                        re.compile(pattern.signature.message_pattern, re.IGNORECASE)
                    )

    def match(
        self,
        text: str,
        *,
        exit_code: int | None = None,
        additional_context: dict[str, str] | None = None,
    ) -> MatchResult:
        """Match patterns against text.

        Args:
            text: Log or error text to match against.
            exit_code: Optional exit code to match.
            additional_context: Optional additional context for evidence matching.

        Returns:
            MatchResult with all matches, ranked by confidence.
        """
        import time

        start_time = time.perf_counter()

        matches: list[PatternMatch] = []

        # Stage 1: Find candidates by keywords
        candidates = self._registry.find_candidates_by_keywords(text)

        # Stage 2: Add exit code candidates
        if exit_code is not None:
            exit_candidates = self._registry.find_candidates_by_exit_code(exit_code)
            candidate_ids = {c.pattern_id for c in candidates}
            for c in exit_candidates:
                if c.pattern_id not in candidate_ids:
                    candidates.append(c)

        # Stage 3: Match each candidate
        for pattern in candidates:
            match = self._match_pattern(
                pattern, text, exit_code, additional_context or {}
            )
            if match is not None and match.confidence >= self._min_confidence:
                matches.append(match)

        # Stage 4: Sort by confidence and limit
        matches.sort(key=lambda m: m.confidence, reverse=True)
        matches = matches[: self._max_matches]

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Emit observability event
        self._emit_match_event(matches, elapsed_ms)

        return MatchResult(
            matches=tuple(matches),
            top_match=matches[0] if matches else None,
            match_count=len(matches),
            processing_time_ms=elapsed_ms,
        )

    def _match_pattern(
        self,
        pattern: ErrorPattern,
        text: str,
        exit_code: int | None,
        additional_context: dict[str, str],
    ) -> PatternMatch | None:
        """Match a single pattern against text.

        Returns None if no match, PatternMatch with confidence if matched.
        """
        matched_signals: list[str] = []
        evidence_lines: list[str] = []
        captures: dict[str, str] = {}

        # Check exit code match
        if (
            exit_code is not None
            and pattern.signature.exit_code is not None
            and pattern.signature.exit_code == exit_code
        ):
            matched_signals.append("exit_code")

        # Check regex patterns
        compiled = self._compiled_patterns.get(pattern.pattern_id, [])
        for regex in compiled:
            match = regex.search(text)
            if match:
                matched_signals.append("regex")
                # Extract captures
                for name, value in match.groupdict().items():
                    if value is not None:
                        captures[name] = value
                # Get evidence line
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.end())
                if line_end == -1:
                    line_end = len(text)
                evidence_line = text[line_start:line_end].strip()
                if evidence_line and evidence_line not in evidence_lines:
                    evidence_lines.append(evidence_line)
                break  # One regex match is enough

        # Check exception class in text
        if pattern.signature.exception_class:
            try:
                exc_regex = re.compile(pattern.signature.exception_class, re.IGNORECASE)
                if exc_regex.search(text):
                    matched_signals.append("exception_class")
            except re.error:
                pass

        # Check message pattern in text
        if pattern.signature.message_pattern:
            try:
                msg_regex = re.compile(pattern.signature.message_pattern, re.IGNORECASE)
                if msg_regex.search(text):
                    matched_signals.append("message_pattern")
            except re.error:
                pass

        # No match if no signals
        if not matched_signals:
            return None

        # Calculate confidence
        confidence_details = self._calculate_confidence(
            pattern, matched_signals, text, additional_context
        )

        # Generate match ID
        match_id = self._generate_match_id(pattern.pattern_id, evidence_lines)

        return PatternMatch(
            match_id=match_id,
            pattern_id=pattern.pattern_id,
            pattern=pattern,
            confidence=confidence_details.final_score,
            evidence_refs=tuple(evidence_lines[:3]),  # Limit evidence lines
            captures=captures,
        )

    def _calculate_confidence(
        self,
        pattern: ErrorPattern,
        matched_signals: list[str],
        text: str,
        additional_context: dict[str, str],
    ) -> ConfidenceDetails:
        """Calculate confidence score with positive and negative signals.

        Returns detailed breakdown of confidence calculation.
        """
        # Determine base score
        if "exit_code" in matched_signals:
            base_score = self.BASE_SCORE_EXIT_CODE
        elif "exception_class" in matched_signals:
            base_score = self.BASE_SCORE_EXCEPTION_CLASS
        elif "message_pattern" in matched_signals:
            base_score = self.BASE_SCORE_MESSAGE_PATTERN
        else:
            base_score = self.BASE_SCORE_REGEX

        increase_factors: list[tuple[str, float]] = []
        decrease_factors: list[tuple[str, float]] = []

        # Bonus for multiple signal types
        unique_signals = set(matched_signals)
        if len(unique_signals) > 1:
            bonus = (len(unique_signals) - 1) * self.MULTIPLE_SIGNAL_BONUS
            increase_factors.append(
                (f"Multiple signal types ({len(unique_signals)})", bonus)
            )

        # Check positive signals from confidence_factors.increase
        text_lower = text.lower()
        for increase_signal in pattern.confidence_factors.increase:
            signal_lower = increase_signal.lower()
            # Simple substring check for now
            if signal_lower in text_lower:
                increase_factors.append((increase_signal, self.INCREASE_SIGNAL_BONUS))

        # Check negative signals from confidence_factors.decrease
        for decrease_signal in pattern.confidence_factors.decrease:
            signal_lower = decrease_signal.lower()
            if signal_lower in text_lower:
                decrease_factors.append((decrease_signal, self.NEGATIVE_SIGNAL_PENALTY))

        # Check additional context for negative signals
        for key, value in additional_context.items():
            value_lower = value.lower()
            for decrease_signal in pattern.confidence_factors.decrease:
                if decrease_signal.lower() in value_lower:
                    decrease_factors.append(
                        (f"{key}: {decrease_signal}", self.NEGATIVE_SIGNAL_PENALTY)
                    )

        # Calculate final score
        final_score = base_score
        for _, delta in increase_factors:
            final_score += delta
        for _, delta in decrease_factors:
            final_score -= delta

        # Clamp to [0.0, 1.0]
        final_score = max(0.0, min(1.0, final_score))

        return ConfidenceDetails(
            base_score=base_score,
            increase_factors=tuple(increase_factors),
            decrease_factors=tuple(decrease_factors),
            final_score=final_score,
        )

    def _generate_match_id(self, pattern_id: str, evidence_lines: list[str]) -> str:
        """Generate stable ID for a match based on pattern and evidence."""
        content = f"{pattern_id}:{':'.join(evidence_lines[:3])}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _emit_match_event(self, matches: list[PatternMatch], elapsed_ms: float) -> None:
        """Emit observability event for pattern matching.

        Note: In production, this would integrate with the EventEmitter.
        For now, we just log.
        """
        if matches:
            logger.debug(
                "pattern_match_completed",
                match_count=len(matches),
                top_pattern=matches[0].pattern_id if matches else None,
                top_confidence=matches[0].confidence if matches else None,
                elapsed_ms=elapsed_ms,
                patterns_matched=[m.pattern_id for m in matches],
            )
        else:
            logger.debug(
                "pattern_match_no_matches",
                elapsed_ms=elapsed_ms,
            )

    def match_with_details(
        self,
        text: str,
        *,
        exit_code: int | None = None,
    ) -> tuple[MatchResult, dict[str, ConfidenceDetails]]:
        """Match patterns and return detailed confidence breakdowns.

        Useful for explainability and debugging.

        Returns:
            Tuple of (MatchResult, dict mapping pattern_id to ConfidenceDetails).
        """
        result = self.match(text, exit_code=exit_code)

        # Re-calculate confidence details for each match (for explainability)
        details: dict[str, ConfidenceDetails] = {}
        for match in result.matches:
            pattern = self._registry.get_pattern(match.pattern_id)
            if pattern:
                # Determine which signals matched (approximation)
                matched_signals = []
                if exit_code is not None and pattern.signature.exit_code == exit_code:
                    matched_signals.append("exit_code")
                if pattern.log_patterns:
                    matched_signals.append("regex")
                if pattern.signature.exception_class:
                    matched_signals.append("exception_class")
                if pattern.signature.message_pattern:
                    matched_signals.append("message_pattern")

                conf_details = self._calculate_confidence(
                    pattern, matched_signals, text, {}
                )
                details[match.pattern_id] = conf_details

        return result, details
