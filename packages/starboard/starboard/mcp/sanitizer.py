# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""PII sanitizer for MCP responses and log entries.

Applies regex-based redaction to prevent leaking sensitive data through
the MCP protocol boundary. Input dicts are never mutated — a new dict
is returned with redacted values.
"""

from __future__ import annotations

import re
from typing import Any

# PII detection patterns — compiled once at import time
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "[IP]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[AWS_KEY]"),
    (re.compile(r"\bdapi[a-f0-9]{32,}\b"), "[TOKEN]"),
]


def _redact_string(value: str) -> str:
    """Apply all PII patterns to a single string."""
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _redact_value(value: Any) -> Any:
    """Recursively redact PII from a value."""
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


class MCPSanitizer:
    """Regex-based PII redaction for MCP protocol output.

    Redacts:
    - Email addresses → ``[EMAIL]``
    - IP addresses → ``[IP]``
    - AWS access keys (``AKIA...``) → ``[AWS_KEY]``
    - Databricks tokens (``dapi...``) → ``[TOKEN]``
    """

    def redact_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Redact PII from an MCP response payload.

        Args:
            data: Response dict (not mutated).

        Returns:
            New dict with PII values redacted.
        """
        return {k: _redact_value(v) for k, v in data.items()}

    def redact_log_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Redact PII from a structured log entry.

        Args:
            entry: Log entry dict (not mutated).

        Returns:
            New dict with PII values redacted.
        """
        return {k: _redact_value(v) for k, v in entry.items()}
