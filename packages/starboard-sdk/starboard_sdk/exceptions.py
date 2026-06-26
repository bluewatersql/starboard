# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Exception hierarchy for the Starboard SDK.

All SDK exceptions derive from ``StarboardError`` so callers can catch the
entire family with a single ``except StarboardError`` clause while still
being able to distinguish specific failure modes.

Example::

    from starboard_sdk.exceptions import StarboardError, AuthenticationError

    try:
        client = await StarboardClient.from_env()
    except AuthenticationError as exc:
        print(f"Bad credentials: {exc}")
    except StarboardError as exc:
        print(f"SDK error: {exc}")
"""

from __future__ import annotations


class StarboardError(Exception):
    """Base class for all Starboard SDK errors.

    All exceptions raised by the SDK inherit from this class, allowing
    callers to catch any SDK error with ``except StarboardError``.
    """


class ConnectionError(StarboardError):
    """Raised when the SDK cannot reach the Starboard backend.

    Examples: network unreachable, DNS failure, refused connection.
    """


class AuthenticationError(StarboardError):
    """Raised when credentials are missing or rejected.

    Examples: missing ``DATABRICKS_TOKEN``, expired token, wrong API key.
    """


class SessionError(StarboardError):
    """Raised for session lifecycle errors.

    Examples: resuming a session that does not exist, corrupted session
    database, concurrent session conflict.
    """


class TimeoutError(StarboardError):
    """Raised when an agent operation exceeds its deadline.

    The ``ask()`` method raises this if the agent does not produce a
    ``FinalOutputEvent`` within the configured ``timeout`` seconds.
    """


class AgentError(StarboardError):
    """Raised when the agent returns a non-recoverable error event.

    Attributes:
        error_type: The agent's error classification (e.g. 'LLMError').
        raw_event: The original error event dict for debugging.
    """

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "Unknown",
        raw_event: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.raw_event = raw_event


class DiscoveryError(StarboardError):
    """Raised when workspace discovery fails.

    Examples: discovery engine crash, no data sources available,
    discovery timeout.
    """


class ConfigError(StarboardError):
    """Raised when SDK configuration is invalid or incomplete.

    Examples: missing required environment variables, invalid config
    file format, incompatible option combinations.
    """
