"""Security test for conversation creation error handling.

Finding F-3-p2-server-api-mcp-app-1: the create_conversation 500 handler
returned ``detail=f"Failed to create conversation: {str(e)}"``, leaking internal
exception text to the client. This test proves the 500 response body no longer
contains the raw exception text (which is logged server-side instead).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware


def test_create_conversation_500_does_not_leak_exception_text() -> None:
    from starboard.api.chat.conversation_routes import router
    from starboard.api.dependencies import get_multi_agent_manager

    secret = "internal_secret_db_password_xyz"

    app = FastAPI()
    app.include_router(router)

    # Mimic AuthMiddleware: attach an authenticated user.
    class SetUserMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.user = SimpleNamespace(
                id="user_1", username="u@x.com", display_name="U"
            )
            return await call_next(request)

    app.add_middleware(SetUserMiddleware)

    manager = MagicMock()
    manager.create_conversation = AsyncMock(side_effect=RuntimeError(secret))
    app.dependency_overrides[get_multi_agent_manager] = lambda: manager

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/conversations", json={})

    assert resp.status_code == 500
    assert secret not in resp.text, f"Secret leaked in 500 body: {resp.text!r}"
    # A generic, client-safe message is returned instead.
    assert "Failed to create conversation" in resp.text
