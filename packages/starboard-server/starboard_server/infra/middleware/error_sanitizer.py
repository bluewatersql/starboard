"""Error sanitization middleware.

Prevents leaking stack traces, file paths, and internal state
in production error responses. Non-production environments get
full error details for debugging.

Every error response includes a correlation_id for traceability.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)


class ErrorSanitizationMiddleware(BaseHTTPMiddleware):
    """Sanitize unhandled exceptions in HTTP responses.

    In production:
        Returns ``{"error": "Internal server error", "correlation_id": "<uuid>"}``

    In non-production:
        Returns ``{"error": "<message>", "type": "<ExceptionType>", "correlation_id": "<uuid>"}``

    Always logs the full exception with structured fields for observability.
    """

    def __init__(self, app: object, environment: str = "production") -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.environment = environment

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            correlation_id = str(uuid.uuid4())

            logger.error(
                "unhandled_error",
                correlation_id=correlation_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                path=request.url.path,
                method=request.method,
                exc_info=True,
            )

            if self.environment == "production":
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "Internal server error",
                        "correlation_id": correlation_id,
                    },
                )

            return JSONResponse(
                status_code=500,
                content={
                    "error": str(exc),
                    "type": type(exc).__name__,
                    "correlation_id": correlation_id,
                },
            )
