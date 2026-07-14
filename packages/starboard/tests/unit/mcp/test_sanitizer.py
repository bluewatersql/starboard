# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCPSanitizer."""

from starboard.mcp.sanitizer import MCPSanitizer


class TestRedactEmail:
    """Tests for email redaction."""

    def test_redacts_email_addresses(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"user": "contact user@example.com for help"}
        result = sanitizer.redact_output(data)
        assert result["user"] == "contact [EMAIL] for help"

    def test_redacts_multiple_emails(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"msg": "a@b.com and c@d.org"}
        result = sanitizer.redact_output(data)
        assert "[EMAIL]" in result["msg"]
        assert "a@b.com" not in result["msg"]


class TestRedactIP:
    """Tests for IP address redaction."""

    def test_redacts_ip_addresses(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"host": "Connected to 192.168.1.100"}
        result = sanitizer.redact_output(data)
        assert result["host"] == "Connected to [IP]"


class TestRedactAWSKeys:
    """Tests for AWS key redaction."""

    def test_redacts_aws_keys(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"key": "Access key: AKIAIOSFODNN7EXAMPLE"}  # pragma: allowlist secret
        result = sanitizer.redact_output(data)
        assert "[AWS_KEY]" in result["key"]
        assert "AKIAIOSFODNN7EXAMPLE" not in result["key"]


class TestRedactDatabricksTokens:
    """Tests for Databricks token redaction."""

    def test_redacts_databricks_tokens(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"auth": "Token: dapi1234567890abcdef1234567890abcdef"}
        result = sanitizer.redact_output(data)
        assert "[TOKEN]" in result["auth"]
        assert "dapi" not in result["auth"]


class TestNestedRedaction:
    """Tests for recursive redaction."""

    def test_nested_dict_redaction(self) -> None:
        sanitizer = MCPSanitizer()
        data = {
            "outer": {
                "inner": "email: test@example.com",
                "deep": {"value": "ip: 10.0.0.1"},
            }
        }
        result = sanitizer.redact_output(data)
        assert "[EMAIL]" in result["outer"]["inner"]
        assert "[IP]" in result["outer"]["deep"]["value"]

    def test_list_value_redaction(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"items": ["a@b.com", "192.168.0.1", "safe string"]}
        result = sanitizer.redact_output(data)
        assert result["items"][0] == "[EMAIL]"
        assert result["items"][1] == "[IP]"
        assert result["items"][2] == "safe string"


class TestPreservation:
    """Tests for input preservation."""

    def test_preserves_dict_keys(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"user@email.com": "value", "normal_key": "data"}
        result = sanitizer.redact_output(data)
        # Keys should be preserved as-is
        assert "user@email.com" in result
        assert "normal_key" in result

    def test_no_mutation_of_input(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"email": "test@example.com"}
        original_value = data["email"]
        sanitizer.redact_output(data)
        assert data["email"] == original_value

    def test_handles_non_string_values(self) -> None:
        sanitizer = MCPSanitizer()
        data = {"count": 42, "flag": True, "nothing": None, "rate": 3.14}
        result = sanitizer.redact_output(data)
        assert result["count"] == 42
        assert result["flag"] is True
        assert result["nothing"] is None
        assert result["rate"] == 3.14


class TestRedactLogEntry:
    """Tests for log entry redaction."""

    def test_redacts_log_entry(self) -> None:
        sanitizer = MCPSanitizer()
        entry = {"message": "User test@example.com from 10.0.0.1"}
        result = sanitizer.redact_log_entry(entry)
        assert "[EMAIL]" in result["message"]
        assert "[IP]" in result["message"]
