# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Prompt injection detection.

Scans user input for common prompt injection patterns and logs suspicious
inputs.

Two operation modes:
- **Log-only** (default): Detects and logs but does not block requests.
  Used during initial rollout to avoid false positives.
- **Blocking** (opt-in): Raises ``InjectionBlockedError`` when confidence
  meets or exceeds a configurable threshold.

Unicode text is NFKC-normalized before matching to defeat homoglyph attacks.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Default confidence threshold for blocking mode.
# A value of 0.8 requires ≥3 pattern matches (3/3 = 1.0 → blocked;
# 2/3 ≈ 0.67 → not blocked at default threshold).
DEFAULT_BLOCKING_THRESHOLD: float = 0.8

# Compiled patterns for common prompt injection techniques.
# Each pattern targets a specific injection vector.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_previous",
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    ),
    ("system_prompt", re.compile(r"system\s*:\s*", re.IGNORECASE)),
    ("inst_tags", re.compile(r"\[INST\]|\[/INST\]", re.IGNORECASE)),
    ("im_start_end", re.compile(r"<\|im_start\|>|<\|im_end\|>", re.IGNORECASE)),
    ("forget_everything", re.compile(r"forget\s+(everything|all|what)", re.IGNORECASE)),
    ("new_instructions", re.compile(r"new\s+instructions?\s*:", re.IGNORECASE)),
    ("act_as_if", re.compile(r"act\s+as\s+(if\s+)?you\s+(are|were)", re.IGNORECASE)),
    ("pretend", re.compile(r"pretend\s+(you|that)", re.IGNORECASE)),
    ("disregard", re.compile(r"disregard\s+(all|the|your)", re.IGNORECASE)),
    ("dan_jailbreak", re.compile(r"\bDAN\b|jailbreak", re.IGNORECASE)),
]


@dataclass(frozen=True)
class InjectionScanResult:
    """Result of a prompt injection scan.

    Attributes:
        is_suspicious: True if any patterns matched
        matched_patterns: Names of matched patterns
        confidence: 0.0–1.0 based on number of matches (capped at 1.0)
    """

    is_suspicious: bool
    matched_patterns: tuple[str, ...]
    confidence: float


class InjectionBlockedError(ValueError):
    """Raised when blocking mode is enabled and injection confidence exceeds threshold.

    Attributes:
        scan_result: The ``InjectionScanResult`` that triggered the block.

    Example:
        >>> try:
        ...     scan_and_block(user_input, blocking_enabled=True)
        ... except InjectionBlockedError as e:
        ...     logger.warning("blocked", confidence=e.scan_result.confidence)
        ...     return rejection_response()
    """

    def __init__(self, message: str, *, scan_result: InjectionScanResult) -> None:
        super().__init__(message)
        self.scan_result = scan_result


def scan_for_injection(text: str) -> InjectionScanResult:
    """Scan text for prompt injection patterns (log-only, never raises).

    Normalizes Unicode (NFKC) before matching to defeat homoglyph
    and invisible-character attacks.

    Args:
        text: User input to scan

    Returns:
        InjectionScanResult with match details
    """
    # NFKC normalization collapses fullwidth/halfwidth chars, ligatures, etc.
    normalized = unicodedata.normalize("NFKC", text)

    matches: list[str] = []
    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            matches.append(name)

    is_suspicious = len(matches) > 0
    confidence = min(len(matches) / 3.0, 1.0)

    if is_suspicious:
        logger.warning(
            "prompt_injection_detected",
            pattern_count=len(matches),
            matched_patterns=matches,
            confidence=confidence,
            input_length=len(text),
        )

    return InjectionScanResult(
        is_suspicious=is_suspicious,
        matched_patterns=tuple(matches),
        confidence=confidence,
    )


def scan_and_block(
    text: str,
    *,
    blocking_enabled: bool = False,
    confidence_threshold: float = DEFAULT_BLOCKING_THRESHOLD,
) -> InjectionScanResult:
    """Scan text for prompt injection and optionally block high-confidence attacks.

    Performs the same pattern-matching as ``scan_for_injection``, but when
    ``blocking_enabled=True`` and the result confidence meets or exceeds
    ``confidence_threshold``, raises ``InjectionBlockedError`` instead of
    returning.

    Safe rollout path:
    - Phase 1 (default): ``blocking_enabled=False`` — log only, no blocking.
    - Phase 2 (opt-in): ``blocking_enabled=True`` — block at threshold.

    Args:
        text: User input to scan.
        blocking_enabled: When True, raises on high-confidence detections.
            Defaults to False for safe initial rollout.
        confidence_threshold: Minimum confidence score to trigger a block
            when blocking is enabled. Defaults to 0.8.

    Returns:
        InjectionScanResult if no block occurs.

    Raises:
        InjectionBlockedError: When ``blocking_enabled=True`` and
            ``result.confidence >= confidence_threshold``.

    Example:
        >>> # Log-only (safe default)
        >>> result = scan_and_block(user_input)
        >>>
        >>> # Blocking enabled (opt-in via feature flag)
        >>> try:
        ...     scan_and_block(user_input, blocking_enabled=True, confidence_threshold=0.8)
        ... except InjectionBlockedError as e:
        ...     return {"error": "Input rejected due to safety policy"}
    """
    result = scan_for_injection(text)

    if blocking_enabled and result.confidence >= confidence_threshold:
        logger.error(
            "prompt_injection_blocked",
            pattern_count=len(result.matched_patterns),
            matched_patterns=list(result.matched_patterns),
            confidence=result.confidence,
            threshold=confidence_threshold,
            input_length=len(text),
        )
        raise InjectionBlockedError(
            f"Input blocked: injection confidence {result.confidence:.2f} "
            f"exceeds threshold {confidence_threshold:.2f} "
            f"(patterns: {', '.join(result.matched_patterns)})",
            scan_result=result,
        )

    return result
