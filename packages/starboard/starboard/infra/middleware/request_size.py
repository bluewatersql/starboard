# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Request size limit middleware.

Prevents memory exhaustion by rejecting requests that exceed a configurable
maximum size before reading the request body.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce maximum request size limits.

    Checks the Content-Length header before reading the request body
    to prevent memory exhaustion from large payloads.

    Attributes:
        max_size: Maximum request size in bytes (default: 10MB)

    Example:
        >>> middleware = RequestSizeLimitMiddleware(max_size=10 * 1024 * 1024)
        >>> app.add_middleware(RequestSizeLimitMiddleware, max_size=10*1024*1024)
    """

    def __init__(self, app, max_size: int = 10 * 1024 * 1024) -> None:
        """Initialize request size limit middleware.

        Args:
            app: ASGI application
            max_size: Maximum request size in bytes (default: 10MB)
        """
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request and check size limit.

        Args:
            request: Starlette Request object
            call_next: Next middleware/handler in chain

        Returns:
            Response from next handler

        Raises:
            HTTPException: 413 Payload Too Large if request exceeds limit
        """
        # Check Content-Length header if present
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self.max_size:
                    # Return JSONResponse directly instead of raising HTTPException
                    # This ensures proper handling in middleware
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                f"Request too large. Maximum size: {self.max_size} bytes, "
                                f"received: {size} bytes"
                            )
                        },
                    )
            except ValueError:
                # Invalid Content-Length header, allow request to proceed
                # (will fail later if actually invalid)
                pass

        # Request is within limit, proceed
        return await call_next(request)
