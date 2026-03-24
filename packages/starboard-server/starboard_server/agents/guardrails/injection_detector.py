"""Prompt injection detection.

Scans user input for common prompt injection patterns and logs suspicious
inputs. This is a **log-only** guardrail — it does not block requests to
avoid false positives during the initial rollout.

Unicode text is NFKC-normalized before matching to defeat homoglyph attacks.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

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


def scan_for_injection(text: str) -> InjectionScanResult:
    """Scan text for prompt injection patterns.

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
