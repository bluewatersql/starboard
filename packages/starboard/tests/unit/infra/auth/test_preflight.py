# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""W11: Fast connectivity + auth preflight tests.

All tests use injected _http_get / monkeypatched TCP so no real network I/O
occurs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starboard.infra.auth.preflight import check_connectivity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_resp(status: int = 200) -> SimpleNamespace:
    return SimpleNamespace(status_code=status)


def _tcp_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch TCP connection to always succeed."""
    monkeypatch.setattr(
        "starboard.infra.auth.preflight._tcp_reachable",
        lambda *a, **kw: True,
    )


def _tcp_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch TCP connection to always fail (simulates DNS / network error)."""
    monkeypatch.setattr(
        "starboard.infra.auth.preflight._tcp_reachable",
        lambda *a, **kw: False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckConnectivityNetwork:
    def test_none_url_returns_ok(self) -> None:
        result = check_connectivity(None)
        assert result.ok is True

    def test_empty_url_returns_ok(self) -> None:
        result = check_connectivity("")
        assert result.ok is True

    def test_network_failure_classified_as_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _tcp_fail(monkeypatch)
        result = check_connectivity("https://myws.cloud.databricks.com")
        assert result.ok is False
        assert result.kind == "NETWORK"
        assert "myws.cloud.databricks.com" in result.message
        assert "network" in result.message.lower() or "VPN" in result.message

    def test_network_failure_host_in_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _tcp_fail(monkeypatch)
        result = check_connectivity("https://e2-demo.cloud.databricks.com")
        assert "e2-demo.cloud.databricks.com" in result.host


class TestCheckConnectivityAuth:
    def test_valid_token_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _tcp_ok(monkeypatch)
        result = check_connectivity(
            "https://myws.cloud.databricks.com",
            token="dapi-valid",
            _http_get=lambda *a, **kw: _ok_resp(200),
        )
        assert result.ok is True
        assert result.kind == ""

    def test_401_classified_as_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _tcp_ok(monkeypatch)
        result = check_connectivity(
            "https://myws.cloud.databricks.com",
            token="bad-token",
            _http_get=lambda *a, **kw: _ok_resp(401),
        )
        assert result.ok is False
        assert result.kind == "AUTH"
        assert "authentication" in result.message.lower() or "401" in result.message

    def test_403_classified_as_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _tcp_ok(monkeypatch)
        result = check_connectivity(
            "https://myws.cloud.databricks.com",
            token="bad-token",
            _http_get=lambda *a, **kw: _ok_resp(403),
        )
        assert result.ok is False
        assert result.kind == "AUTH"

    def test_no_token_skips_auth_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without a token, only TCP is checked (no auth call)."""
        _tcp_ok(monkeypatch)
        called: list[bool] = []
        result = check_connectivity(
            "https://myws.cloud.databricks.com",
            token=None,
            _http_get=lambda *a, **kw: called.append(True) or _ok_resp(200),
        )
        assert result.ok is True
        assert not called, "auth API call must not be made when token is None"

    def test_http_get_oserror_classified_as_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OSError during the API call (e.g. timeout) → NETWORK."""
        _tcp_ok(monkeypatch)

        def _raise(*a: object, **kw: object) -> None:
            raise OSError("timed out")

        result = check_connectivity(
            "https://myws.cloud.databricks.com",
            token="tok",
            _http_get=_raise,
        )
        assert result.ok is False
        assert result.kind == "NETWORK"

    def test_non_auth_http_error_is_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 404 or 500 means the host is reachable → treat as ok."""
        _tcp_ok(monkeypatch)
        result = check_connectivity(
            "https://myws.cloud.databricks.com",
            token="tok",
            _http_get=lambda *a, **kw: _ok_resp(404),
        )
        assert result.ok is True


class TestCheckConnectivityParsing:
    def test_bare_hostname_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _tcp_ok(monkeypatch)
        result = check_connectivity(
            "myws.cloud.databricks.com",
            _http_get=lambda *a, **kw: _ok_resp(200),
        )
        assert result.ok is True

    def test_host_in_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _tcp_ok(monkeypatch)
        result = check_connectivity("https://acme.azuredatabricks.net")
        assert "acme.azuredatabricks.net" in result.host


class TestPreflightTarget:
    """Review fix: preflight the host the run uses, not the ambient env host."""

    def test_profile_host_wins_over_ambient(self, tmp_path, monkeypatch):
        from starboard.infra.auth.preflight import preflight_target

        cfg = tmp_path / "databrickscfg"
        cfg.write_text("[target]\nhost = https://target.example.com\n")
        monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg))
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "target")
        assert preflight_target("https://ambient.example.com", "tok") == (
            "https://target.example.com",
            None,
        )

    def test_no_profile_uses_ambient(self, monkeypatch):
        from starboard.infra.auth.preflight import preflight_target

        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
        assert preflight_target("https://ambient.example.com", "tok") == (
            "https://ambient.example.com",
            "tok",
        )

    def test_unknown_profile_falls_back_to_ambient(self, tmp_path, monkeypatch):
        from starboard.infra.auth.preflight import preflight_target

        cfg = tmp_path / "databrickscfg"
        cfg.write_text("[other]\nhost = https://other.example.com\n")
        monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg))
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "missing")
        assert preflight_target("https://ambient.example.com", None) == (
            "https://ambient.example.com",
            None,
        )
