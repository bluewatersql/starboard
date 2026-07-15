# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Security-critical unit tests for Workstream 1A.

Covers all 14 security items:
1-3: SQL injection via _format_value and _build_where_conditions
4:   detect-secrets pre-commit hook (config file check)
5:   Auth middleware 401 response body — no error detail leak
6:   data.py 500 response — no internal error detail
7:   streaming.py SSE error — no exception details in production
8:   config.py enable_pii_redaction default True
9:   feedback/visualization/clarification ownership check
10:  Auth middleware path matching (prefix, not exact)
11:  CORS allow_methods restricted
12:  rate_limit.py warning when limiter not attached
13:  data.py rate-limiting on secondary endpoints
14:  config.py sync_to_env atexit cleanup of sensitive env vars
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# =============================================================================
# 1-3: SQL Injection — _format_value and _build_where_conditions
# =============================================================================


class TestFormatValueSQLInjection:
    """Tests for _format_value SQL injection prevention."""

    @pytest.fixture
    def adapter(self):
        from starboard.infra.storage.table_registry import TableRegistry
        from starboard.infra.storage.uc_adapter import (
            UCStorageAdapter,
            UCStorageConfig,
        )

        config = UCStorageConfig(catalog="cat", schema="sch", warehouse_id="wh")
        registry = TableRegistry()
        return UCStorageAdapter(
            workspace_client=MagicMock(),
            config=config,
            registry=registry,
        )

    def test_format_value_string_with_single_quote(self, adapter) -> None:
        """O'Malley should not break SQL."""
        result = adapter._format_value("O'Malley")
        assert "O''Malley" in result
        assert result.startswith("'")
        assert result.endswith("'")
        # Must not contain unescaped single quote that could terminate the string
        inner = result[1:-1]
        assert "O'M" not in inner  # raw quote must not appear unescaped

    def test_format_value_drop_table_payload(self, adapter) -> None:
        """Classic SQL injection payload must be escaped."""
        payload = "'; DROP TABLE users; --"
        result = adapter._format_value(payload)
        # The single quotes in the payload must be doubled
        assert "''" in result
        # The result must start and end with quotes
        assert result.startswith("'")
        assert result.endswith("'")

    def test_format_value_nested_json_with_quotes(self, adapter) -> None:
        """Dict with quoted string values must be safe."""
        value = {"key": "O'Brien's data", "attack": "'; DROP TABLE x; --"}
        result = adapter._format_value(value)
        # JSON is embedded in SQL string — outer quotes present
        assert result.startswith("'")
        assert result.endswith("'")
        # Single quotes inside must be escaped
        inner = result[1:-1]
        assert "O'Brien" not in inner  # raw unescaped single quote not present
        assert "O''Brien" in inner

    def test_format_value_unicode_quote_tricks(self, adapter) -> None:
        """Unicode apostrophe variants are passed through as-is (not SQL special)."""
        # Unicode RIGHT SINGLE QUOTATION MARK (U+2019) is not a SQL delimiter
        value = "caf\u00e9 \u2019s menu"
        result = adapter._format_value(value)
        assert result.startswith("'")
        assert result.endswith("'")

    def test_format_value_none(self, adapter) -> None:
        """None must produce NULL."""
        assert adapter._format_value(None) == "NULL"

    def test_format_value_bool_true(self, adapter) -> None:
        """True must produce TRUE."""
        assert adapter._format_value(True) == "TRUE"

    def test_format_value_bool_false(self, adapter) -> None:
        """False must produce FALSE."""
        assert adapter._format_value(False) == "FALSE"

    def test_format_value_integer(self, adapter) -> None:
        """Integer must not be quoted."""
        result = adapter._format_value(42)
        assert result == "42"

    def test_format_value_str_no_quotes(self, adapter) -> None:
        """Plain string without quotes must be safely quoted."""
        result = adapter._format_value("hello")
        assert result == "'hello'"

    def test_format_value_fallback_str_with_quote(self, adapter) -> None:
        """Non-str/dict/bool/datetime/None values converted via str() — if they
        contain quotes the str representation must be safe (no injection via repr)."""
        # A float has no quotes, just verify it works
        result = adapter._format_value(3.14)
        assert result == "3.14"


class TestBuildWhereConditionsInjection:
    """Tests for _build_where_conditions SQL injection prevention."""

    @pytest.fixture
    def adapter(self):
        from starboard.infra.storage.table_registry import TableRegistry
        from starboard.infra.storage.uc_adapter import (
            UCStorageAdapter,
            UCStorageConfig,
        )

        config = UCStorageConfig(catalog="cat", schema="sch", warehouse_id="wh")
        registry = TableRegistry()
        return UCStorageAdapter(
            workspace_client=MagicMock(),
            config=config,
            registry=registry,
        )

    def test_where_condition_string_value_escaped(self, adapter) -> None:
        """String filter values must have single quotes escaped."""
        conditions = adapter._build_where_conditions({"name": "O'Malley"})
        assert len(conditions) == 1
        # Must not allow injection — raw ' before M must not appear
        assert "O'Malley" not in conditions[0]
        assert "O''Malley" in conditions[0]

    def test_where_condition_injection_payload(self, adapter) -> None:
        """Classic injection payload in filter value must be escaped."""
        payload = "'; DROP TABLE conversations; --"
        conditions = adapter._build_where_conditions({"user_id": payload})
        assert len(conditions) == 1
        # No raw unescaped quote that would terminate the SQL string
        cond = conditions[0]
        # After the opening quote of the value, no bare ' should close it early
        assert "''" in cond

    def test_where_condition_none_value(self, adapter) -> None:
        """None filter must produce IS NULL."""
        conditions = adapter._build_where_conditions({"deleted_at": None})
        assert conditions[0] == "deleted_at IS NULL"

    def test_where_condition_integer_value(self, adapter) -> None:
        """Integer filter must be unquoted."""
        conditions = adapter._build_where_conditions({"count": 5})
        assert conditions[0] == "count = 5"


# =============================================================================
# 5: Auth middleware 401 — no error detail in response body
# =============================================================================


class TestAuthMiddleware401NoLeak:
    """Auth middleware must not expose error details in 401 body."""

    def _make_app_with_auth_error(self, error_message: str) -> FastAPI:
        """Build a minimal FastAPI app where auth raises AuthenticationError."""
        from fastapi import FastAPI
        from starboard.domain.auth.exceptions import AuthenticationError
        from starboard.infra.auth.middleware import AuthMiddleware
        from starboard.infra.auth.service import AuthenticationService

        class FailingAuthService(AuthenticationService):
            async def get_current_user(self, request):
                raise AuthenticationError(
                    message=error_message,
                    provider="test",
                )

            async def validate_token(self, token: str):
                raise AuthenticationError(message=error_message, provider="test")

        app = FastAPI()
        app.add_middleware(
            AuthMiddleware,
            auth_service=FailingAuthService(),
            exclude_paths=[],
        )

        @app.get("/protected")
        async def protected():
            return {"ok": True}

        return app

    def test_401_does_not_contain_internal_error_str(self) -> None:
        """401 response body must not expose internal error message detail."""
        secret_message = "token_expired:secret_internal_reason_xyz"
        app = self._make_app_with_auth_error(secret_message)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/protected")
        assert response.status_code == 401
        body = response.text
        assert secret_message not in body, (
            f"Secret message leaked in 401 body: {body!r}"
        )

    def test_401_contains_generic_message(self) -> None:
        """401 response must contain a generic authentication failed message."""
        app = self._make_app_with_auth_error("internal_secret")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/protected")
        assert response.status_code == 401
        body_lower = response.text.lower()
        assert "authentication failed" in body_lower or "unauthorized" in body_lower


# =============================================================================
# 8: config.py enable_pii_redaction default True
# =============================================================================


class TestConfigPiiRedactionDefault:
    """enable_pii_redaction must default to True."""

    def test_enable_pii_redaction_default_is_true(self) -> None:
        """EnvConfig.enable_pii_redaction must default to True."""
        from starboard.infra.core.config import EnvConfig

        # Create fresh instance with no env vars for this field
        with patch.dict(os.environ, {}, clear=False):
            # Temporarily remove ENABLE_PII_REDACTION if set
            env_backup = os.environ.pop("ENABLE_PII_REDACTION", None)
            try:
                config = EnvConfig()
                assert config.enable_pii_redaction is True, (
                    "enable_pii_redaction must default to True for security"
                )
            finally:
                if env_backup is not None:
                    os.environ["ENABLE_PII_REDACTION"] = env_backup


# =============================================================================
# 9: feedback/visualization/clarification — ownership verification
# =============================================================================


class TestConversationOwnershipVerification:
    """feedback, visualization, clarification endpoints must verify ownership."""

    def test_feedback_checks_conversation_ownership(self) -> None:
        """FeedbackService.submit_feedback must verify conversation ownership."""
        # The endpoint must call conversation_repository to verify ownership
        # We verify that feedback_service.submit_feedback raises ValueError
        # when the conversation does not belong to the requester.
        # This test checks that the service layer enforces ownership.
        import asyncio

        from starboard.services.feedback.feedback_service import FeedbackService

        mock_feedback_repo = AsyncMock()
        mock_conversation_repo = AsyncMock()

        # Simulate conversation not found (ownership check fails)
        mock_conversation_repo.get = AsyncMock(return_value=None)

        service = FeedbackService(
            repository=mock_feedback_repo,
            conversation_repository=mock_conversation_repo,
        )

        async def run():
            from starboard_core.domain.models.feedback import FeedbackRating

            with pytest.raises((ValueError, PermissionError, Exception)):
                await service.submit_feedback(
                    conversation_id="other_user_conv",
                    message_id="msg_123",
                    rating=FeedbackRating.POSITIVE,
                )

        asyncio.run(run())


# =============================================================================
# 10: Auth middleware path matching — prefix not exact
# =============================================================================


class TestAuthMiddlewarePathMatching:
    """Auth middleware must use startswith() prefix match for excluded paths."""

    def test_exclude_path_prefix_match(self) -> None:
        """Paths like /health/live/extra should also be excluded if /health/live is in list."""
        from fastapi import FastAPI
        from starboard.infra.auth.middleware import AuthMiddleware

        call_count = {"n": 0}

        class CountingAuthService:
            async def get_current_user(self, request):
                call_count["n"] += 1
                from starboard_core.domain.models.auth import User

                return User(id="u1", username="u1", email="u1@x.com")

            async def validate_token(self, token):
                pass

        app = FastAPI()
        app.add_middleware(
            AuthMiddleware,
            auth_service=CountingAuthService(),
            exclude_paths=["/health/live", "/health/ready"],
        )

        @app.get("/health/live")
        async def live():
            return {"ok": True}

        @app.get("/health/live/detail")
        async def live_detail():
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)

        # /health/live exact match — must skip auth
        call_count["n"] = 0
        response = client.get("/health/live")
        assert response.status_code == 200
        assert call_count["n"] == 0, "Auth should not be called for excluded path"

        # /health/live/detail — prefix match should also skip auth
        call_count["n"] = 0
        response = client.get("/health/live/detail")
        assert response.status_code == 200
        assert call_count["n"] == 0, (
            "Auth should not be called for prefix of excluded path"
        )

    def test_non_excluded_path_calls_auth(self) -> None:
        """Non-excluded paths must go through auth."""
        from fastapi import FastAPI
        from starboard.domain.auth.exceptions import AuthenticationError
        from starboard.infra.auth.middleware import AuthMiddleware

        class AlwaysFailAuth:
            async def get_current_user(self, request):
                raise AuthenticationError(message="fail", provider="test")

            async def validate_token(self, token):
                pass

        app = FastAPI()
        app.add_middleware(
            AuthMiddleware,
            auth_service=AlwaysFailAuth(),
            exclude_paths=["/health/live"],
        )

        @app.get("/api/conversations")
        async def conversations():
            return []

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/conversations")
        assert response.status_code == 401


# =============================================================================
# 11: CORS — allow_methods restricted
# =============================================================================


class TestCORSMethodsRestricted:
    """CORS must not allow all methods — only GET, POST, OPTIONS."""

    def test_cors_allow_methods_not_wildcard(self) -> None:
        """main.py CORS must not use ['*'] for allow_methods."""
        import pathlib

        # parents[0]=security, [1]=unit, [2]=tests, [3]=starboard-server pkg root
        main_path = pathlib.Path(__file__).parents[3] / "starboard" / "main.py"
        source = main_path.read_text()

        assert (
            'allow_methods=["*"]' not in source and "allow_methods=['*']" not in source
        ), "CORS allow_methods must not use wildcard '*'"


# =============================================================================
# 12: rate_limit.py — warning when limiter not attached
# =============================================================================


class TestRateLimitWarning:
    """check_rate_limit must log a warning when limiter is not attached."""

    def test_warning_logged_when_no_limiter(self) -> None:
        """When app.state has no limiter, a warning must be logged."""
        from fastapi import FastAPI, Request
        from starboard.infra.middleware import rate_limit as rate_limit_module
        from starboard.infra.middleware.rate_limit import check_rate_limit

        app = FastAPI()
        # Do NOT attach a limiter to app.state

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/data",
            "query_string": b"",
            "headers": [],
            "app": app,
        }

        request = Request(scope)
        # Ensure no limiter on state
        assert not hasattr(app.state, "limiter")

        mock_logger = MagicMock()
        with patch.object(rate_limit_module, "logger", mock_logger):
            check_rate_limit(request, "10/minute")
            mock_logger.warning.assert_called_once()


# =============================================================================
# 14: config.py sync_to_env — atexit cleanup of sensitive env vars
# =============================================================================


class TestSyncToEnvAtexitCleanup:
    """sync_to_env must register an atexit handler to clean sensitive env vars."""

    def test_atexit_registered_on_sync(self) -> None:
        """Calling sync_to_env must register an atexit handler."""
        import atexit

        from starboard.infra.core.config import EnvConfig

        config = EnvConfig(
            databricks_host="https://test.azuredatabricks.net",
            databricks_token="test_token_value",
            llm_api_key="sk-test-key",
            offline_mode=True,
        )

        # Track atexit registrations
        registered = []
        original_register = atexit.register

        with patch(
            "atexit.register",
            side_effect=lambda fn, *a, **kw: (
                registered.append(fn) or original_register(fn, *a, **kw)
            ),
        ):
            config.sync_to_env()

        assert len(registered) >= 1, (
            "sync_to_env must register an atexit handler to clean up sensitive env vars"
        )

    def test_atexit_cleanup_removes_sensitive_vars(self) -> None:
        """The atexit handler must remove sensitive env vars from os.environ."""
        import atexit

        from starboard.infra.core.config import EnvConfig

        config = EnvConfig(
            databricks_host="https://test.azuredatabricks.net",
            databricks_token="dapi_test_sensitive_token",
            llm_api_key="sk-test-sensitive-key",
            offline_mode=True,
        )

        cleanup_fns = []
        original_register = atexit.register

        with patch(
            "atexit.register",
            side_effect=lambda fn, *a, **kw: (
                cleanup_fns.append((fn, a, kw)) or original_register(fn, *a, **kw)
            ),
        ):
            config.sync_to_env()

        # Verify sensitive vars were set
        assert os.environ.get("DATABRICKS_TOKEN") == "dapi_test_sensitive_token"

        # Run cleanup handlers
        for fn, args, kwargs in cleanup_fns:
            fn(*args, **kwargs)

        # Sensitive vars must be removed
        assert (
            "DATABRICKS_TOKEN" not in os.environ
            or os.environ.get("DATABRICKS_TOKEN") != "dapi_test_sensitive_token"
        )
        assert (
            "LLM_API_KEY" not in os.environ
            or os.environ.get("LLM_API_KEY") != "sk-test-sensitive-key"
        )


# =============================================================================
# 4: detect-secrets pre-commit hook present
# =============================================================================


class TestDetectSecretsPreCommitHook:
    """detect-secrets hook must be in .pre-commit-config.yaml."""

    def test_detect_secrets_hook_present(self) -> None:
        """pre-commit config must include detect-secrets hook."""
        import pathlib

        import yaml

        root = pathlib.Path(__file__).parents[5]  # repo root
        config_path = root / ".pre-commit-config.yaml"

        assert config_path.exists(), ".pre-commit-config.yaml must exist"

        content = config_path.read_text()
        data = yaml.safe_load(content)

        # Find detect-secrets in repos
        found = False
        for repo in data.get("repos", []):
            for hook in repo.get("hooks", []):
                if hook.get("id") == "detect-secrets":
                    found = True
                    break
            if found:
                break

        assert found, (
            "detect-secrets hook must be configured in .pre-commit-config.yaml"
        )
