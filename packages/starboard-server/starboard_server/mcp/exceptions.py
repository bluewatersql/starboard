# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""MCP server exception hierarchy.

Each exception carries a ``code`` and ``message`` for structured error
reporting through the MCP protocol boundary.
"""


class MCPBaseError(Exception):
    """Base class for all MCP server errors.

    Attributes:
        code: Machine-readable error code.
        message: Human-readable error description.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ConfigurationError(MCPBaseError):
    """Raised when MCP server configuration is invalid or missing."""

    def __init__(self, message: str, *, code: str = "CONFIG_INVALID") -> None:
        super().__init__(code=code, message=message)


class AuthenticationError(MCPBaseError):
    """Raised when workspace authentication fails."""

    def __init__(self, message: str, *, code: str = "AUTH_FAILED") -> None:
        super().__init__(code=code, message=message)


class RateLimitError(MCPBaseError):
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


class ExecutionError(MCPBaseError):
    """Raised when tool or agent execution fails."""

    def __init__(self, message: str, *, code: str = "EXEC_FAILED") -> None:
        super().__init__(code=code, message=message)
