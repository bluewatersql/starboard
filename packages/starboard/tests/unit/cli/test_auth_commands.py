# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for the ``starboard auth`` CLI wrapper (Phase 2 Task A0).

Covers ``auth login`` (CLI-shell-out vs. in-process external-browser fallback)
and ``auth status`` (resolved-identity display, never printing a token).
"""

from unittest.mock import MagicMock, patch

import pytest
from starboard.cli.cli.auth_commands import (
    cmd_auth_login,
    cmd_auth_status,
    run_auth,
)
from starboard.cli.cli.exit_codes import AUTH_ERROR, SUCCESS, USAGE_ERROR

_MODULE = "starboard.cli.cli.auth_commands"


# =============================================================================
# auth status
# =============================================================================


class TestAuthStatus:
    def test_status_prints_resolved_identity_no_token(self, capsys):
        """`auth status` prints host/auth_type/profile/user and NEVER a token."""
        fake_client = MagicMock()
        described = {
            "host": "https://example.cloud.databricks.com",
            "auth_type": "databricks-cli",
            "profile": "DEFAULT",
            "user": "someone@example.com",
        }
        with (
            patch(f"{_MODULE}.resolve_workspace_client", return_value=fake_client) as res,
            patch(f"{_MODULE}.describe_auth", return_value=described) as desc,
        ):
            rc = cmd_auth_status()

        assert rc == SUCCESS
        res.assert_called_once()
        desc.assert_called_once_with(fake_client)

        out = capsys.readouterr().out
        assert "https://example.cloud.databricks.com" in out
        assert "databricks-cli" in out
        assert "DEFAULT" in out
        assert "someone@example.com" in out
        # No secret material ever surfaces.
        assert "token" not in out.lower()

    def test_status_json_output_is_parseable(self, capsys):
        """`auth status --json` emits a machine-parseable object with no token."""
        import json

        described = {
            "host": "https://ws.databricks.com",
            "auth_type": "pat",
            "profile": None,
            "user": "u@example.com",
        }
        with (
            patch(f"{_MODULE}.resolve_workspace_client", return_value=MagicMock()),
            patch(f"{_MODULE}.describe_auth", return_value=described),
        ):
            rc = cmd_auth_status(as_json=True)

        assert rc == SUCCESS
        payload = json.loads(capsys.readouterr().out)
        assert payload == described
        assert "token" not in payload

    def test_status_failure_returns_auth_error(self, capsys):
        """A failed resolution surfaces an actionable error + nonzero exit."""
        with patch(
            f"{_MODULE}.resolve_workspace_client",
            side_effect=RuntimeError("no credentials"),
        ):
            rc = cmd_auth_status()

        assert rc == AUTH_ERROR
        err = capsys.readouterr().err
        assert "auth login" in err.lower() or "no credentials" in err.lower()


# =============================================================================
# auth login — Databricks CLI present (shell out)
# =============================================================================


class TestAuthLoginCliPresent:
    def test_shells_out_with_correct_args(self):
        """When the `databricks` CLI is present, shell out with the right args."""
        with (
            patch(f"{_MODULE}.shutil.which", return_value="/usr/local/bin/databricks"),
            patch(f"{_MODULE}.subprocess.run") as run,
        ):
            rc = cmd_auth_login(
                host="https://ws.databricks.com", profile="myprofile"
            )

        assert rc == SUCCESS
        run.assert_called_once()
        called_args = run.call_args.args[0]
        assert called_args == [
            "databricks",
            "auth",
            "login",
            "--host",
            "https://ws.databricks.com",
            "--profile",
            "myprofile",
        ]
        # check=True so a nonzero CLI exit raises CalledProcessError.
        assert run.call_args.kwargs.get("check") is True

    def test_failed_shell_out_returns_auth_error(self, capsys):
        """A nonzero CLI exit surfaces a clear error and a nonzero exit code."""
        import subprocess

        with (
            patch(f"{_MODULE}.shutil.which", return_value="/usr/local/bin/databricks"),
            patch(
                f"{_MODULE}.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "databricks"),
            ),
        ):
            rc = cmd_auth_login(host="https://ws.databricks.com", profile="p")

        assert rc == AUTH_ERROR
        assert "login" in capsys.readouterr().err.lower()


# =============================================================================
# auth login — Databricks CLI absent (SDK external-browser fallback)
# =============================================================================


class TestAuthLoginSdkFallback:
    def test_builds_external_browser_config(self):
        """CLI absent → construct Config(auth_type='external-browser') + me()."""
        fake_client = MagicMock()
        with (
            patch(f"{_MODULE}.shutil.which", return_value=None),
            patch(f"{_MODULE}.Config") as cfg,
            patch(f"{_MODULE}.WorkspaceClient", return_value=fake_client) as wc,
        ):
            rc = cmd_auth_login(host="https://ws.databricks.com", profile=None)

        assert rc == SUCCESS
        cfg.assert_called_once_with(
            host="https://ws.databricks.com", auth_type="external-browser"
        )
        wc.assert_called_once()
        # The browser flow is triggered by resolving the current user.
        fake_client.current_user.me.assert_called_once()

    def test_fallback_requires_host(self, capsys):
        """CLI absent and no host → usage error (cannot start browser flow)."""
        with patch(f"{_MODULE}.shutil.which", return_value=None):
            rc = cmd_auth_login(host=None, profile=None)

        assert rc == USAGE_ERROR
        assert "host" in capsys.readouterr().err.lower()

    def test_failed_browser_login_returns_auth_error(self, capsys):
        """A failed in-process login surfaces an actionable error + nonzero exit."""
        fake_client = MagicMock()
        fake_client.current_user.me.side_effect = RuntimeError("browser cancelled")
        with (
            patch(f"{_MODULE}.shutil.which", return_value=None),
            patch(f"{_MODULE}.Config"),
            patch(f"{_MODULE}.WorkspaceClient", return_value=fake_client),
        ):
            rc = cmd_auth_login(host="https://ws.databricks.com", profile=None)

        assert rc == AUTH_ERROR
        assert "login" in capsys.readouterr().err.lower()


# =============================================================================
# run_auth dispatcher
# =============================================================================


class TestRunAuthDispatch:
    def test_dispatch_login(self):
        with patch(f"{_MODULE}.cmd_auth_login", return_value=SUCCESS) as login:
            rc = run_auth(["login", "--host", "https://h", "--profile", "p"])
        assert rc == SUCCESS
        login.assert_called_once_with(host="https://h", profile="p")

    def test_dispatch_status_json(self):
        with patch(f"{_MODULE}.cmd_auth_status", return_value=SUCCESS) as status:
            rc = run_auth(["status", "--json"])
        assert rc == SUCCESS
        status.assert_called_once_with(as_json=True)

    def test_no_subcommand_is_usage_error(self):
        assert run_auth([]) == USAGE_ERROR


# =============================================================================
# main() interception of the `auth` verb
# =============================================================================


class TestMainInterceptsAuth:
    def test_main_routes_auth_verb(self):
        from starboard.cli.cli import main as main_mod

        with (
            patch.object(main_mod, "run_auth", return_value=SUCCESS) as run,
            pytest.raises(SystemExit) as exc,
        ):
            main_mod.main(["auth", "status"])
        assert exc.value.code == SUCCESS
        run.assert_called_once_with(["status"])
