# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""MCP server exception hierarchy.

Each exception carries a ``code`` and ``message`` for structured error
reporting through the MCP protocol boundary.

All MCP exceptions inherit from :class:`StarboardError` so they can be
caught by application-wide error boundaries.
"""

from starboard_server.exceptions import StarboardError


class MCPBaseError(StarboardError):
    """Base class for all MCP server errors.

    Attributes:
        code: Machine-readable error code.
        message: Human-readable error description.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class MCPConfigurationError(MCPBaseError):
    """Raised when MCP server configuration is invalid or missing."""

    def __init__(self, message: str, *, code: str = "CONFIG_INVALID") -> None:
        super().__init__(code=code, message=message)


class MCPAuthenticationError(MCPBaseError):
    """Raised when workspace authentication fails."""

    def __init__(self, message: str, *, code: str = "AUTH_FAILED") -> None:
        super().__init__(code=code, message=message)


class MCPRateLimitError(MCPBaseError):
    """Raised when a rate limit is exceeded.

    Attributes:
        retry_after: Seconds to wait before retrying.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "RATE_LIMITED",
        retry_after: int | None = None,
    ) -> None:
        super().__init__(code=code, message=message)
        self.retry_after = retry_after


class MCPExecutionError(MCPBaseError):
    """Raised when tool or agent execution fails."""

    def __init__(self, message: str, *, code: str = "EXEC_FAILED") -> None:
        super().__init__(code=code, message=message)


# Backward-compat aliases for old names
ConfigurationError = MCPConfigurationError
AuthenticationError = MCPAuthenticationError
RateLimitError = MCPRateLimitError
ExecutionError = MCPExecutionError
