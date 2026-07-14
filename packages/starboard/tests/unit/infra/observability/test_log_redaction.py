# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for credential redaction in structured logging."""

from __future__ import annotations

from starboard.infra.observability.logging import (
    _redact_value,
    redact_credentials,
)


class TestRedactValue:
    """Test individual value redaction."""

    def test_redis_url_redacted(self) -> None:
        assert _redact_value("redis://user:secret@host:6379") == "redis://***@host:6379"

    def test_postgres_url_redacted(self) -> None:
        assert (
            _redact_value("postgresql://admin:p4ss@db:5432/mydb")
            == "postgresql://***@db:5432/mydb"
        )

    def test_bearer_token_redacted(self) -> None:
        assert _redact_value("Bearer eyJhbGciOi...") == "Bearer ***"

    def test_api_key_redacted(self) -> None:
        assert _redact_value("api_key=sk-1234abcd") == "api_key=***"
        assert _redact_value("api-key: sk-1234abcd") == "api-key: ***"

    def test_password_redacted(self) -> None:
        assert _redact_value("password=mysecret") == "password=***"

    def test_token_param_redacted(self) -> None:
        assert _redact_value("token=abc123def") == "token=***"

    def test_databricks_token_redacted(self) -> None:
        assert _redact_value("DATABRICKS_TOKEN=dapi123") == "DATABRICKS_TOKEN=***"

    def test_llm_api_key_redacted(self) -> None:
        assert _redact_value("LLM_API_KEY=sk-proj-abc") == "LLM_API_KEY=***"

    def test_openai_api_key_redacted(self) -> None:
        assert _redact_value("OPENAI_API_KEY=sk-proj-abc") == "OPENAI_API_KEY=***"

    def test_non_credential_unchanged(self) -> None:
        """Non-credential strings should pass through unchanged."""
        assert _redact_value("SELECT * FROM users") == "SELECT * FROM users"
        assert _redact_value("normal log message") == "normal log message"

    def test_non_string_unchanged(self) -> None:
        """Non-string values should pass through unchanged."""
        assert _redact_value(42) == 42
        assert _redact_value(None) is None
        assert _redact_value(3.14) == 3.14


class TestRedactCredentialsProcessor:
    """Test the structlog processor function."""

    def test_redacts_event_field(self) -> None:
        event_dict = {"event": "connecting to redis://user:pass@host:6379"}
        result = redact_credentials(None, "info", event_dict)
        assert "pass" not in result["event"]
        assert "***@host:6379" in result["event"]

    def test_redacts_nested_dict(self) -> None:
        event_dict = {
            "event": "test",
            "config": {"database_url": "postgres://admin:secret@db/app"},
        }
        result = redact_credentials(None, "info", event_dict)
        assert "secret" not in result["config"]["database_url"]

    def test_redacts_list_values(self) -> None:
        event_dict = {
            "event": "test",
            "urls": ["redis://u:p1@h1:6379", "redis://u:p2@h2:6379"],
        }
        result = redact_credentials(None, "info", event_dict)
        assert all("***@" in url for url in result["urls"])

    def test_preserves_non_sensitive_fields(self) -> None:
        event_dict = {
            "event": "query_executed",
            "sql": "SELECT 1",
            "duration_ms": 42,
            "level": "info",
        }
        result = redact_credentials(None, "info", event_dict)
        assert result == event_dict
