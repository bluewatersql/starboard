"""Rate limiting middleware and utilities.

Provides rate limiting functionality using slowapi with support for:
- Per-user rate limiting (using user_id from request.state)
- Per-IP rate limiting (fallback)
- Configurable limits per route
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key from user_id or IP address.

    Prefers user_id from request.state (set by auth middleware),
    falls back to IP address if user_id not available.

    Args:
        request: FastAPI Request object

    Returns:
        Rate limit key string (e.g., "user:user_123" or "192.168.1.1")
    """
    # Try to get user_id from request.state (set by auth middleware)
    if hasattr(request.state, "user_id") and request.state.user_id:
        return f"user:{request.state.user_id}"

    # Fallback to IP address
    return get_remote_address(request)


def check_rate_limit(request: Request, limit: str) -> None:
    """Check rate limit for a request.

    Uses slowapi's limit decorator pattern programmatically.
    Raises RateLimitExceeded if limit is exceeded.

    Args:
        request: FastAPI Request object
        limit: Rate limit string (e.g., "10/minute")

    Raises:
        RateLimitExceeded: If rate limit is exceeded
    """
    if not hasattr(request.app.state, "limiter"):
        # Rate limiting not enabled, skip check
        return

    limiter: Limiter = request.app.state.limiter

    # Use slowapi's limit() decorator pattern programmatically
    # The decorator returns a function that checks the limit when called
    # We call it with a no-op function to trigger the check
    key = get_rate_limit_key(request)

    # Create a no-op function with required request parameter
    # slowapi's limit decorator inspects function signature for 'request' param
    def noop(request: Request) -> None:
        pass

    # Apply the limit decorator and call it
    # This will raise RateLimitExceeded if limit exceeded
    limiter.limit(limit, key_func=lambda: key)(noop)(request)
