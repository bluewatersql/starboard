# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Structured logging setup with correlation IDs and credential redaction.

This module provides structured logging using structlog with correlation IDs
for tracing requests across the system. A credential redaction processor
strips sensitive values (tokens, passwords, connection strings) from all
log output.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

# Context variable for request/trace ID
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """
    Get or generate a request ID for correlation tracking.

    Returns:
        Existing request ID or newly generated UUID
    """
    rid = request_id_var.get()
    if not rid:
        rid = str(uuid.uuid4())
        request_id_var.set(rid)
    return rid


def set_request_id(request_id: str) -> None:
    """
    Set the request ID for the current context.

    Args:
        request_id: Request ID to set
    """
    request_id_var.set(request_id)


def clear_request_id() -> None:
    """Clear the request ID from the current context."""
    request_id_var.set("")


# Credential redaction patterns: (compiled regex, replacement)
_CREDENTIAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(redis://)[^\s@]+@"), r"\1***@"),
    (re.compile(r"(postgres(?:ql)?://)[^\s@]+@"), r"\1***@"),
    (re.compile(r"(password=)[^\s&]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(token=)[^\s&]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(api[_-]?key[=:\s]+)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(DATABRICKS_TOKEN=)\S+"), r"\1***"),
    (re.compile(r"(LLM_API_KEY=)\S+"), r"\1***"),
    (re.compile(r"(OPENAI_API_KEY=)\S+"), r"\1***"),
]


def _redact_value(value: Any) -> Any:
    """Redact credential patterns from a single value."""
    if not isinstance(value, str):
        return value
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact credential patterns from dict values."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _redact_dict(v)
        elif isinstance(v, (list, tuple)):
            result[k] = type(v)(_redact_value(item) for item in v)
        else:
            result[k] = _redact_value(v)
    return result


def redact_credentials(
    logger: Any,  # noqa: ARG001
    method: str,  # noqa: ARG001
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor that redacts credentials from log event dicts.

    Must be inserted into the processor chain BEFORE the renderer
    (JSONRenderer / ConsoleRenderer).
    """
    return _redact_dict(event_dict)


def setup_structured_logging(
    level: int = logging.INFO,
    json_output: bool = False,
    enable_pii_redaction: bool = False,
) -> None:
    """
    Configure structured logging for the application.

    This replaces the standard library logging with structlog for better
    observability and structured output that's easier to parse.

    Note: This function is idempotent and can be called multiple times.
    Subsequent calls will update the logging configuration.

    Args:
        level: Logging level (default: logging.INFO)
        json_output: Whether to output JSON logs (default: False for console readability)
        enable_pii_redaction: Whether to redact credentials from log output
            (default: False). When True, the ``redact_credentials`` processor
            strips tokens, passwords, and API keys from all structured log
            events.
    """
    # Configure standard library logging
    # Use force=True to allow reconfiguration (Python 3.8+)
    logging.basicConfig(
        format="%(message)s",
        level=level,
        force=True,
    )

    # Suppress noisy loggers even in debug mode
    # Request/HTTP related loggers
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # SQLite related loggers
    logging.getLogger("sqlite3").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sqlite_vec").setLevel(logging.WARNING)

    logging.getLogger("databricks.sdk").setLevel(logging.WARNING)

    # Configure structlog processors
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    # Credential redaction is opt-in via ENABLE_PII_REDACTION.
    # When enabled, redact_credentials MUST come after content-adding
    # processors but BEFORE renderers to ensure credentials are scrubbed.
    if enable_pii_redaction:
        shared_processors.append(redact_credentials)

    if json_output:
        # JSON output for production
        # format_exc_info needed for JSON to serialize exception info
        structlog.configure(
            processors=shared_processors  # type: ignore[arg-type]
            + [
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # Console output for development
        # Note: Don't include format_exc_info here - ConsoleRenderer handles
        # exception formatting itself when pretty_exceptions=True (default)
        structlog.configure(
            processors=shared_processors  # type: ignore[arg-type]
            + [
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Optional logger name (typically __name__)

    Returns:
        Configured structlog logger instance
    """
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()
