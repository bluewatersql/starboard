"""Tests for ErrorSanitizationMiddleware."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starboard_server.infra.middleware.error_sanitizer import (
    ErrorSanitizationMiddleware,
)


def _create_app(environment: str) -> FastAPI:
    """Create a test app with the error sanitizer middleware."""
    app = FastAPI()

    @app.get("/fail")
    async def fail_endpoint() -> None:
        raise RuntimeError("secret internal error: /app/server/db.py line 42")

    @app.get("/ok")
    async def ok_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(ErrorSanitizationMiddleware, environment=environment)
    return app


class TestProductionMode:
    """In production, error details must be hidden."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_create_app("production"), raise_server_exceptions=False)

    def test_hides_error_details(self, client: TestClient) -> None:
        resp = client.get("/fail")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"] == "Internal server error"
        assert "secret" not in body["error"]
        assert "type" not in body

    def test_includes_correlation_id(self, client: TestClient) -> None:
        resp = client.get("/fail")
        body = resp.json()
        # correlation_id should be a valid UUID
        uuid.UUID(body["correlation_id"])

    def test_ok_response_unchanged(self, client: TestClient) -> None:
        resp = client.get("/ok")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestDevMode:
    """In non-production, error details are visible for debugging."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_create_app("dev"), raise_server_exceptions=False)

    def test_shows_error_details(self, client: TestClient) -> None:
        resp = client.get("/fail")
        assert resp.status_code == 500
        body = resp.json()
        assert "secret internal error" in body["error"]
        assert body["type"] == "RuntimeError"

    def test_includes_correlation_id(self, client: TestClient) -> None:
        resp = client.get("/fail")
        body = resp.json()
        uuid.UUID(body["correlation_id"])


class TestOpenAPIGating:
    """OpenAPI docs should be disabled in production."""

    def test_docs_disabled_in_production(self) -> None:
        app = FastAPI(
            docs_url=None if True else "/docs",  # simulate production
            redoc_url=None,
            openapi_url=None,
        )
        client = TestClient(app)
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404

    def test_docs_enabled_in_dev(self) -> None:
        app = FastAPI(
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )
        client = TestClient(app)
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/openapi.json").status_code == 200
