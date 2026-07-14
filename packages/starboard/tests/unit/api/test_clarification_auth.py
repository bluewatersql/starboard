"""Security tests for the clarification respond endpoint.

Finding F-3-p2-server-api-mcp-app-2: the endpoint previously substituted a
hard-coded ``user_id="default_user"`` when no authenticated user was available,
silently acting on behalf of a fake identity. These tests prove:

- An unauthenticated request (no ``request.state.user``) is rejected with 401.
- An authenticated request enqueues the message with the real user id and never
  the placeholder ``"default_user"``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware


def _build_app(user) -> tuple[FastAPI, MagicMock]:
    """Build an app mounting the clarification router.

    Args:
        user: Object to set on ``request.state.user``, or None to simulate an
            unauthenticated request.
    """
    from starboard.api.clarification import router
    from starboard.api.dependencies import get_state_container

    app = FastAPI()
    app.include_router(router)

    # Middleware that mimics AuthMiddleware: sets request.state.user when present.
    class SetUserMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if user is not None:
                request.state.user = user
            return await call_next(request)

    app.add_middleware(SetUserMiddleware)

    manager = MagicMock()
    manager.enqueue_message = AsyncMock(return_value=None)
    container = MagicMock()
    container.multi_agent_manager = manager
    app.dependency_overrides[get_state_container] = lambda: container

    return app, manager


def _payload(clar_id: str = "clar_abc") -> dict:
    return {
        "clarification_id": clar_id,
        "response_type": "custom_text",
        "custom_text": "use medium warehouse",
    }


def test_unauthenticated_request_returns_401() -> None:
    app, manager = _build_app(user=None)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/conversations/conv_1/clarifications/clar_abc/respond",
        json=_payload(),
    )

    assert resp.status_code == 401
    # The fake user must never be used to enqueue work.
    manager.enqueue_message.assert_not_called()


def test_authenticated_request_uses_real_user_id() -> None:
    user = SimpleNamespace(id="real_user_42", username="u@x.com")
    app, manager = _build_app(user=user)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/conversations/conv_1/clarifications/clar_abc/respond",
        json=_payload(),
    )

    assert resp.status_code == 200
    manager.enqueue_message.assert_awaited_once()
    kwargs = manager.enqueue_message.await_args.kwargs
    assert kwargs["user_id"] == "real_user_42"
    assert kwargs["user_id"] != "default_user"
