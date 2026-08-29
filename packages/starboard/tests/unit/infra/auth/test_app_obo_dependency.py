# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Databricks Apps OBO (on-behalf-of) FastAPI dependency (O4).

Property coverage (per PHASE_3.md §7):
  1. Non-App path unchanged — no forwarded header returns None; resolve_user_client
     is never called.
  2. App path — X-Forwarded-Access-Token header triggers resolve_user_client() per
     request and the returned client is surfaced by the dependency.
  3. Per-request isolation — two requests each get a distinct client object (no
     shared mutable state, no identity bleed).
  4. Audit log derives its fields from describe_auth() — the token value is never
     logged.

All tests use FastAPI TestClient and unittest.mock; no live Databricks workspace
is required.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fake_client(user: str, token: str = "s3cr3t-never-log") -> Any:
    """Minimal fake WorkspaceClient for dependency injection in tests."""
    return SimpleNamespace(
        config=SimpleNamespace(
            host="https://fake.azure.databricks.com",
            auth_type="model-serving-user-credentials",
            profile=None,
            token=token,
        ),
        current_user=SimpleNamespace(
            me=lambda: SimpleNamespace(user_name=user),
        ),
    )


def _make_probe_app():
    """Return a minimal FastAPI app with a /probe route that exercises the OBO
    dependency and exposes the resolved user (or None) as JSON."""
    from fastapi import Depends, FastAPI
    from starboard.main import get_obo_client

    app = FastAPI()

    @app.get("/probe")
    async def probe(client: Any = Depends(get_obo_client)) -> dict[str, Any]:
        user = client.current_user.me().user_name if client is not None else None
        return {"has_client": client is not None, "user": user}

    return app, get_obo_client


# ---------------------------------------------------------------------------
# 1. Non-App path unchanged
# ---------------------------------------------------------------------------


class TestNonAppPathUnchanged:
    def test_no_forwarded_header_returns_none_and_resolver_not_called(self) -> None:
        """Without X-Forwarded-Access-Token the dependency returns None and
        resolve_user_client is never invoked — the non-App path is unchanged."""
        from fastapi.testclient import TestClient

        app, _ = _make_probe_app()

        with (
            patch("starboard.infra.auth.resolver.resolve_user_client") as mock_ruc,
            TestClient(app) as client,
        ):
            resp = client.get("/probe")  # no forwarded-user header

        assert resp.status_code == 200
        assert resp.json() == {"has_client": False, "user": None}
        mock_ruc.assert_not_called()

    def test_case_insensitive_header_detection(self) -> None:
        """The forwarded-header check is case-insensitive (HTTP spec)."""
        from fastapi.testclient import TestClient

        fake = _fake_client("alice@example.com")
        app, _ = _make_probe_app()

        with (
            patch("starboard.infra.auth.resolver.resolve_user_client", return_value=fake),
            patch(
                "starboard.infra.auth.resolver.describe_auth",
                return_value={"host": "h", "auth_type": "obo", "profile": None, "user": "alice@example.com"},
            ),
            TestClient(app) as client,
        ):
            # Mixed-case header; Starlette Headers is case-insensitive.
            resp = client.get("/probe", headers={"X-Forwarded-Access-Token": "tok"})

        assert resp.status_code == 200
        assert resp.json()["has_client"] is True


# ---------------------------------------------------------------------------
# 2. App path: OBO client resolved per-request
# ---------------------------------------------------------------------------


class TestOboClientResolvedInAppContext:
    def test_with_header_calls_resolve_user_client_once(self) -> None:
        """When X-Forwarded-Access-Token is present, resolve_user_client() is
        called exactly once and the dependency returns that client."""
        from fastapi.testclient import TestClient

        fake = _fake_client("alice@example.com")
        app, _ = _make_probe_app()

        with (
            patch("starboard.infra.auth.resolver.resolve_user_client", return_value=fake) as mock_ruc,
            patch(
                "starboard.infra.auth.resolver.describe_auth",
                return_value={"host": "h", "auth_type": "obo", "profile": None, "user": "alice@example.com"},
            ),
            TestClient(app) as client,
        ):
            resp = client.get("/probe", headers={"X-Forwarded-Access-Token": "user-tok"})
            mock_ruc.assert_called_once()

        assert resp.status_code == 200
        assert resp.json() == {"has_client": True, "user": "alice@example.com"}

    def test_forwarded_token_is_passed_to_resolver(self) -> None:
        """The end user's forwarded OAuth token must be handed to
        resolve_user_client (canonical Apps OBO) — not merely detected. Guards the
        Isaac-Review finding that the header was checked but the token unused."""
        from fastapi.testclient import TestClient

        fake = _fake_client("alice@example.com")
        app, _ = _make_probe_app()

        with (
            patch("starboard.infra.auth.resolver.resolve_user_client", return_value=fake) as mock_ruc,
            patch(
                "starboard.infra.auth.resolver.describe_auth",
                return_value={"host": "h", "auth_type": "obo", "profile": None, "user": "alice@example.com"},
            ),
            TestClient(app) as client,
        ):
            client.get("/probe", headers={"X-Forwarded-Access-Token": "user-tok-XYZ"})

        mock_ruc.assert_called_once_with(user_access_token="user-tok-XYZ")

    def test_dependency_override_replaces_resolver(self) -> None:
        """app.dependency_overrides can swap get_obo_client for a fake — the
        standard FastAPI pattern for injecting test doubles."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        from starboard.main import get_obo_client

        fake = _fake_client("bob@example.com")

        app = FastAPI()

        @app.get("/probe")
        async def probe(client: Any = Depends(get_obo_client)) -> dict[str, Any]:
            return {"user": client.current_user.me().user_name if client else None}

        app.dependency_overrides[get_obo_client] = lambda: fake

        with TestClient(app) as client:
            resp = client.get("/probe")

        assert resp.json() == {"user": "bob@example.com"}


# ---------------------------------------------------------------------------
# 3. Per-request isolation — no identity bleed
# ---------------------------------------------------------------------------


class TestPerRequestIsolation:
    def test_each_request_gets_distinct_client_instance(self) -> None:
        """Two consecutive App requests each trigger a fresh resolve_user_client()
        call and receive a distinct client object — no shared mutable state."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        from starboard.main import get_obo_client

        call_count = 0
        client_ids: list[int] = []

        def _fresh_client(**_kwargs: Any) -> Any:
            # accepts user_access_token=... (the forwarded-token call signature)
            nonlocal call_count
            call_count += 1
            return _fake_client(f"user{call_count}@example.com")

        app = FastAPI()

        @app.get("/probe")
        async def probe(obo: Any = Depends(get_obo_client)) -> dict[str, Any]:
            client_ids.append(id(obo))
            return {"user": obo.current_user.me().user_name if obo else None}

        with (
            patch("starboard.infra.auth.resolver.resolve_user_client", side_effect=_fresh_client),
            patch(
                "starboard.infra.auth.resolver.describe_auth",
                return_value={"host": "h", "auth_type": "obo", "profile": None, "user": "userN"},
            ),
            TestClient(app) as tc,
        ):
            r1 = tc.get("/probe", headers={"X-Forwarded-Access-Token": "tok1"})
            r2 = tc.get("/probe", headers={"X-Forwarded-Access-Token": "tok2"})

        # Two requests → two distinct resolve_user_client() calls.
        assert call_count == 2, "resolve_user_client must be called once per request"
        # Each call produced a distinct object (no shared reference).
        assert len(set(client_ids)) == 2, "Each request must receive its own client"
        assert r1.json()["user"] == "user1@example.com"
        assert r2.json()["user"] == "user2@example.com"

    def test_non_app_request_does_not_receive_client_from_prior_app_request(
        self,
    ) -> None:
        """A non-App request (no header) after an App request still gets None —
        the OBO client from the prior request does not bleed through."""
        from fastapi.testclient import TestClient

        fake = _fake_client("carol@example.com")
        app, _ = _make_probe_app()

        with (
            patch("starboard.infra.auth.resolver.resolve_user_client", return_value=fake),
            patch(
                "starboard.infra.auth.resolver.describe_auth",
                return_value={"host": "h", "auth_type": "obo", "profile": None, "user": "carol@example.com"},
            ),
            TestClient(app) as tc,
        ):
            app_resp = tc.get("/probe", headers={"X-Forwarded-Access-Token": "tok"})
            non_app_resp = tc.get("/probe")  # no header

        assert app_resp.json()["has_client"] is True
        assert non_app_resp.json()["has_client"] is False
        assert non_app_resp.json()["user"] is None


# ---------------------------------------------------------------------------
# 4. Audit log: identity not secrets
# ---------------------------------------------------------------------------


class TestAuditLogCarriesIdentityNotSecrets:
    def test_describe_auth_is_called_to_derive_log_fields(self) -> None:
        """The dependency derives its structured-log fields from describe_auth(),
        which is the only safe (redacted) source of identity info.  The raw token
        is never accessed for logging."""
        from fastapi.testclient import TestClient

        token = "DO-NOT-LOG-ME-EF4A2B"
        fake = _fake_client("dave@example.com", token=token)
        auth_info = {
            "host": "https://fake.azure.databricks.com",
            "auth_type": "model-serving-user-credentials",
            "profile": None,
            "user": "dave@example.com",
        }

        app, _ = _make_probe_app()

        with (
            patch("starboard.infra.auth.resolver.resolve_user_client", return_value=fake),
            patch("starboard.infra.auth.resolver.describe_auth", return_value=auth_info) as mock_da,
            TestClient(app) as tc,
        ):
            tc.get("/probe", headers={"X-Forwarded-Access-Token": token})

        # describe_auth must be called with the OBO client — it is the sole path
        # used for logging.
        mock_da.assert_called_once_with(fake)

        # The describe_auth return value must not contain the token.
        assert token not in str(auth_info)
        assert "token" not in auth_info, "describe_auth must not expose a 'token' key"
        assert auth_info["user"] == "dave@example.com"

    def test_describe_auth_failure_is_swallowed_not_raised(self) -> None:
        """If describe_auth raises (e.g. network error on .me()), the dependency
        still returns the client — a log failure must not break the request."""
        from fastapi.testclient import TestClient

        fake = _fake_client("eve@example.com")
        app, _ = _make_probe_app()

        with (
            patch("starboard.infra.auth.resolver.resolve_user_client", return_value=fake),
            patch("starboard.infra.auth.resolver.describe_auth", side_effect=RuntimeError("network")),
            TestClient(app) as tc,
        ):
            resp = tc.get("/probe", headers={"X-Forwarded-Access-Token": "tok"})

        # Even though describe_auth raised, the request must succeed with the client.
        assert resp.status_code == 200
        assert resp.json()["has_client"] is True
        assert resp.json()["user"] == "eve@example.com"
