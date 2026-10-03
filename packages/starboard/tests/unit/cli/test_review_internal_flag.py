# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ``starboard review --internal`` (no-workspace internal mode).

The flag sets ``internal_mode=True`` on the resolved config and opens the gate
via ``detect_gate_open`` WITHOUT a live workspace client. It must error clearly
when the gated internal path is not wired (the public-wheel default) and never
contact a customer workspace.
"""

from __future__ import annotations

import argparse
import json

import polars as pl
import pytest
from starboard.cli.cli.review_command import (
    _build_parser,
    _internal_preflight,
    _resolve_config,
    run_review,
)
from starboard.infra.core.config import EnvConfig
from starboard_x.contract import EXIT_API, EXIT_ARG, EXIT_AUTH, EXIT_OK


@pytest.fixture(autouse=True)
def _restore_logging():
    """``run_review`` pins structlog/stdlib logging to the (captured) stderr;
    restore both so later tests never log to a closed capture stream."""
    import logging

    import structlog

    saved = structlog.get_config()
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    structlog.configure(**saved)
    root.handlers[:] = handlers
    root.setLevel(level)


def _args(**overrides) -> argparse.Namespace:
    ns = argparse.Namespace(
        workspace=None,
        profile=None,
        host=None,
        token=None,
        internal=False,
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


@pytest.mark.unit
class TestInternalFlagParsing:
    def test_flag_defaults_false(self) -> None:
        args = _build_parser().parse_args(["--workspace", "ws"])
        assert args.internal is False

    def test_flag_sets_true(self) -> None:
        args = _build_parser().parse_args(["--internal", "--workspace", "ws"])
        assert args.internal is True


@pytest.mark.unit
class TestResolveConfigInternalMode:
    def test_internal_flag_sets_internal_mode(self, monkeypatch) -> None:
        base = EnvConfig()
        monkeypatch.setattr(
            "starboard.bootstrap.get_config", lambda: base, raising=True
        )
        cfg = _resolve_config(_args(internal=True))
        assert cfg.internal_mode is True

    def test_no_flag_leaves_internal_mode_false(self, monkeypatch) -> None:
        base = EnvConfig()
        monkeypatch.setattr(
            "starboard.bootstrap.get_config", lambda: base, raising=True
        )
        cfg = _resolve_config(_args(internal=False))
        assert cfg.internal_mode is False


@pytest.mark.unit
class TestInternalPreflight:
    def test_gate_closed_when_adapters_disabled(self) -> None:
        # Public-wheel default: enable_internal_adapters=False => gate cannot open.
        cfg = EnvConfig(internal_mode=True, enable_internal_adapters=False)
        gate_open, message = _internal_preflight(cfg)
        assert gate_open is False
        assert "ENABLE_INTERNAL_ADAPTERS" in message
        assert "STARBOARD_INTERNAL_" in message
        assert "No customer workspace was contacted" in message

    def test_gate_open_when_wired(self, monkeypatch) -> None:
        # internal_mode_active requires the installed starboard-internal package;
        # it is a workspace member here. Plus a wired deployment env var.
        pytest.importorskip("starboard_internal")
        monkeypatch.setenv("STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID", "wh-internal-1")
        cfg = EnvConfig(internal_mode=True, enable_internal_adapters=True)
        gate_open, message = _internal_preflight(cfg)
        assert gate_open is True
        assert "gate is open" in message
        assert "--internal-workspace-id" in message
        assert "deferred" not in message


@pytest.mark.unit
class TestRunReviewInternal:
    def test_internal_closed_gate_exits_auth_without_connecting(
        self, monkeypatch
    ) -> None:
        # Force a public-wheel config (gate closed) and ensure run_review returns
        # the auth exit code WITHOUT building any workspace client.
        base = EnvConfig(internal_mode=True, enable_internal_adapters=False)
        monkeypatch.setattr(
            "starboard.bootstrap.get_config", lambda: base, raising=True
        )

        def _boom(*a, **k):  # pragma: no cover - must never be reached
            raise AssertionError("run_review must not connect a workspace in --internal")

        monkeypatch.setattr(
            "starboard.bootstrap.AsyncDatabricksClient", _boom, raising=True
        )
        rc = run_review(["--internal", "--workspace", "some-customer"])
        assert rc == EXIT_AUTH

    def test_internal_closed_gate_json_envelope(self, monkeypatch, capsys) -> None:
        base = EnvConfig(internal_mode=True, enable_internal_adapters=False)
        monkeypatch.setattr(
            "starboard.bootstrap.get_config", lambda: base, raising=True
        )
        rc = run_review(["--internal", "--json", "--workspace", "cust"])
        assert rc == EXIT_AUTH
        out = capsys.readouterr().out
        assert '"ok": false' in out

    def test_bare_internal_open_gate_exits_arg_naming_scope_flags(
        self, monkeypatch
    ) -> None:
        pytest.importorskip("starboard_internal")
        monkeypatch.setenv("STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID", "wh-internal-1")
        base = EnvConfig(internal_mode=True, enable_internal_adapters=True)
        monkeypatch.setattr(
            "starboard.bootstrap.get_config", lambda: base, raising=True
        )

        def _boom(*a, **k):  # pragma: no cover - deferred path must not connect
            raise AssertionError("open-gate internal review must not connect a workspace")

        monkeypatch.setattr(
            "starboard.bootstrap.AsyncDatabricksClient", _boom, raising=True
        )
        rc = run_review(["--internal", "--workspace", "cust"])
        assert rc == EXIT_ARG


class _FakeMirrorExecutor:
    """Internal executor stand-in: serves F-01 + W-W02-shaped rows."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute_sql(self, sql: str, *args, **kwargs) -> pl.DataFrame:
        self.executed.append(sql)
        if "auto_stop_waste_pct" in sql:
            return pl.DataFrame(
                [{"warehouse_id": "wh-idle", "idle_running_hours": 12.0,
                  "auto_stop_waste_pct": 80.0, "total_dbus": 420.0}]
            )
        if "Window totals by product and usage_unit" in sql:
            return pl.DataFrame(
                [
                    {"billing_origin_product": "JOBS", "usage_unit": "DBU",
                     "usage_quantity": 610.0},
                    {"billing_origin_product": "SQL", "usage_unit": "DBU",
                     "usage_quantity": 130.0},
                    {"billing_origin_product": "DATABASE", "usage_unit": "DSU",
                     "usage_quantity": 99.0},
                ]
            )
        return pl.DataFrame([])


class _FakeMirrorSource:
    """A ``QuerySource`` that routes every query to the fake internal executor."""

    coverage_caveats: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.executor = _FakeMirrorExecutor()

    def prepare(self, query, rendered_sql, render=None):  # noqa: ARG002
        from starboard.discovery.sources import PreparedQuery

        return PreparedQuery(sql=rendered_sql, executor=self.executor)


@pytest.mark.unit
class TestRunReviewInternalMirror:
    """``--internal-workspace-id`` runs the review on the mirror (no client)."""

    @pytest.fixture
    def mirror(self, monkeypatch):
        source = _FakeMirrorSource()
        calls: list[tuple] = []

        def _resolve(workspace_ids, account=None, **_k):
            calls.append((workspace_ids, account))
            return source

        def _boom(*a, **k):  # pragma: no cover - must never be reached
            raise AssertionError("internal review must not build a customer client")

        monkeypatch.setattr("starboard.bootstrap.resolve_internal_source", _resolve)
        monkeypatch.setattr("starboard.bootstrap.AsyncDatabricksClient", _boom)
        return source, calls

    def test_parses_scope_flags(self) -> None:
        args = _build_parser().parse_args(
            ["--internal-workspace-id", "123", "--internal-account", "acct"]
        )
        assert args.internal_workspace_id == "123"
        assert args.internal_account == "acct"

    def test_manifest_since_and_json_like_profile(
        self, mirror, tmp_path, capsys
    ) -> None:
        source, calls = mirror
        m1 = tmp_path / "r1" / "findings-manifest.json"
        snap = tmp_path / "r1" / "snapshot.json"
        rc = run_review(
            ["--internal-workspace-id", "856", "--json", "--no-cache",
             "--domains", "warehouse",
             "--manifest-out", str(m1), "--snapshot-out", str(snap)]
        )
        assert rc == EXIT_OK
        assert calls == [(("856",), None)]
        assert source.executor.executed  # every query ran on the mirror executor
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] is True
        assert env["data"]["workspace"] == "ws-856"
        # DBU only — the DSU row is never summed into products_dbu.
        assert env["data"]["products_dbu"] == {"JOBS": 610.0, "SQL": 130.0}

        manifest = json.loads(m1.read_text())
        assert manifest["workspace"] == "ws-856"
        assert manifest["workspace_id"] == "856"
        assert manifest["products_dbu"] == {"JOBS": 610.0, "SQL": 130.0}
        assert manifest["findings"]
        assert snap.exists()

        m2 = tmp_path / "r2" / "findings-manifest.json"
        rc = run_review(
            ["--internal-workspace-id", "856", "--json", "--no-cache",
             "--domains", "warehouse",
             "--since", str(m1), "--manifest-out", str(m2)]
        )
        assert rc == EXIT_OK
        env = json.loads(capsys.readouterr().out)
        assert "cost_delta" in env["data"]
        assert env["data"]["cost_delta"]["persisting_count"] >= 1
        assert m2.exists()

    def test_account_scope_label(self, mirror, capsys) -> None:
        _source, calls = mirror
        rc = run_review(
            ["--internal-account", "acct-9", "--json", "--no-cache",
             "--domains", "warehouse"]
        )
        assert rc == EXIT_OK
        assert calls == [(None, "acct-9")]
        env = json.loads(capsys.readouterr().out)
        assert env["data"]["workspace"] == "acct-acct-9"

    def test_source_unavailable_exits_auth(self, monkeypatch, capsys) -> None:
        def _resolve(*a, **k):
            raise RuntimeError("internal source not available")

        monkeypatch.setattr("starboard.bootstrap.resolve_internal_source", _resolve)
        rc = run_review(["--internal-workspace-id", "856", "--json"])
        assert rc == EXIT_AUTH
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] is False
        assert "No customer workspace was contacted" in env["error"]

    def test_preflight_connection_error_is_one_clean_line(
        self, monkeypatch, capsys
    ) -> None:
        class _PreflightError(ConnectionError):
            pass

        def _resolve(*a, **k):
            raise _PreflightError("host unreachable")

        monkeypatch.setattr("starboard.bootstrap.resolve_internal_source", _resolve)
        rc = run_review(["--internal-workspace-id", "856", "--json"])
        assert rc == EXIT_API
        env = json.loads(capsys.readouterr().out)
        assert env["error"] == "Connection failed: host unreachable"
