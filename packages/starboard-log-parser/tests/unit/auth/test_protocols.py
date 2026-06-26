# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for authentication protocols.

Following TDD: tests written first, implementation follows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

# Import will fail initially - that's expected in TDD
from starboard_log_parser.auth.protocols import (
    CredentialProvider,
    Credentials,
    DatabricksVendedCredentials,
)


class TestCredentials:
    """Tests for Credentials dataclass."""

    def test_basic_credentials(self) -> None:
        """Should create credentials with access and secret keys."""
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        assert creds.access_key == "MY_AWS_ACCESS_KEY_ID"
        assert creds.secret_key == "MY_AWS_SECRET_ACCESS_KEY"
        assert creds.session_token is None
        assert creds.expires_at is None
        assert creds.region is None
        assert creds.metadata is None

    def test_credentials_with_session_token(self) -> None:
        """Should support optional session token."""
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            session_token="session123",
        )
        assert creds.session_token == "session123"

    def test_credentials_with_expiration(self) -> None:
        """Should support optional expiration timestamp."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            expires_at=expires,
        )
        assert creds.expires_at == expires

    def test_credentials_with_region(self) -> None:
        """Should support optional region hint."""
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            region="us-west-2",
        )
        assert creds.region == "us-west-2"

    def test_credentials_with_metadata(self) -> None:
        """Should support optional metadata dictionary."""
        metadata = {"provider": "aws", "account_id": "123456789012"}
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            metadata=metadata,
        )
        assert creds.metadata == metadata

    def test_credentials_frozen(self) -> None:
        """Credentials should be immutable (frozen dataclass)."""
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        with pytest.raises(AttributeError):
            creds.access_key = "new_key"  # type: ignore

    def test_is_expired_permanent_credentials(self) -> None:
        """Permanent credentials (no expires_at) should never expire."""
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        assert not creds.is_expired()

    def test_is_expired_future_expiration(self) -> None:
        """Credentials with future expiration should not be expired."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            expires_at=expires,
        )
        assert not creds.is_expired()

    def test_is_expired_past_expiration(self) -> None:
        """Credentials with past expiration should be expired."""
        expires = datetime.now(UTC) - timedelta(hours=1)
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            expires_at=expires,
        )
        assert creds.is_expired()

    def test_needs_refresh_permanent_credentials(self) -> None:
        """Permanent credentials should never need refresh."""
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        assert not creds.needs_refresh()
        assert not creds.needs_refresh(buffer_seconds=600)

    def test_needs_refresh_with_buffer(self) -> None:
        """Should refresh before expiry based on buffer."""
        # Expires in 4 minutes (240 seconds)
        expires = datetime.now(UTC) + timedelta(minutes=4)
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            expires_at=expires,
        )

        # Default buffer is 5 minutes (300 seconds), so should need refresh
        assert creds.needs_refresh()

        # With 3 minute buffer, should not need refresh yet
        assert not creds.needs_refresh(buffer_seconds=180)

        # With 5 minute buffer, should need refresh
        assert creds.needs_refresh(buffer_seconds=300)

    def test_needs_refresh_no_buffer(self) -> None:
        """Should work with zero buffer (refresh only when expired)."""
        expires = datetime.now(UTC) + timedelta(seconds=10)
        creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            expires_at=expires,
        )

        # With no buffer, should not need refresh yet
        assert not creds.needs_refresh(buffer_seconds=0)


class TestDatabricksVendedCredentials:
    """Tests for DatabricksVendedCredentials dataclass."""

    def test_inherits_from_credentials(self) -> None:
        """DatabricksVendedCredentials should inherit from Credentials."""
        vended = DatabricksVendedCredentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        assert isinstance(vended, Credentials)
        assert isinstance(vended, DatabricksVendedCredentials)

    def test_basic_vended_credentials(self) -> None:
        """Should create vended credentials with basic fields."""
        vended = DatabricksVendedCredentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        assert vended.access_key == "MY_AWS_ACCESS_KEY_ID"
        assert vended.secret_key == "MY_AWS_SECRET_ACCESS_KEY"
        assert vended.vending_endpoint is None
        assert vended.request_id is None

    def test_vended_credentials_with_endpoint(self) -> None:
        """Should support optional vending endpoint."""
        vended = DatabricksVendedCredentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            vending_endpoint="https://databricks.com/api/2.0/credentials/temporary",
        )
        assert (
            vended.vending_endpoint
            == "https://databricks.com/api/2.0/credentials/temporary"
        )

    def test_vended_credentials_with_request_id(self) -> None:
        """Should support optional request ID."""
        vended = DatabricksVendedCredentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            request_id="req-123-456",
        )
        assert vended.request_id == "req-123-456"

    def test_vended_credentials_all_fields(self) -> None:
        """Should support all fields including expiration."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        vended = DatabricksVendedCredentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            session_token="session123",
            expires_at=expires,
            region="us-west-2",
            metadata={"account": "123"},
            vending_endpoint="https://databricks.com/api/2.0/credentials/temporary",
            request_id="req-123",
        )
        assert vended.session_token == "session123"
        assert vended.expires_at == expires
        assert vended.region == "us-west-2"
        assert vended.metadata == {"account": "123"}
        assert (
            vended.vending_endpoint
            == "https://databricks.com/api/2.0/credentials/temporary"
        )
        assert vended.request_id == "req-123"

    def test_vended_credentials_frozen(self) -> None:
        """DatabricksVendedCredentials should be immutable."""
        vended = DatabricksVendedCredentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        with pytest.raises(AttributeError):
            vended.access_key = "new_key"  # type: ignore

    def test_vended_credentials_inherits_methods(self) -> None:
        """Should inherit is_expired() and needs_refresh() methods."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        vended = DatabricksVendedCredentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
            expires_at=expires,
        )
        assert not vended.is_expired()
        assert hasattr(vended, "needs_refresh")


class TestCredentialProviderProtocol:
    """Tests for CredentialProvider protocol."""

    def test_protocol_structural_subtyping(self) -> None:
        """Any class with get_credentials() and refresh_credentials() should satisfy protocol."""

        class SimpleProvider:
            def get_credentials(self) -> Credentials:
                return Credentials(
                    access_key="MY_AWS_ACCESS_KEY_ID",
                    secret_key="MY_AWS_SECRET_ACCESS_KEY",
                )

            def refresh_credentials(self) -> Credentials:
                return self.get_credentials()

        provider = SimpleProvider()

        # Should be recognized as CredentialProvider via structural subtyping
        assert isinstance(provider, CredentialProvider)

    def test_protocol_requires_get_credentials(self) -> None:
        """Class must have get_credentials() to satisfy protocol."""

        class NotAProvider:
            def some_other_method(self) -> None:
                pass

        obj = NotAProvider()

        # Should NOT satisfy protocol (missing get_credentials)
        assert not isinstance(obj, CredentialProvider)

    def test_protocol_with_refresh_credentials(self) -> None:
        """refresh_credentials() should have default implementation."""

        class ProviderWithRefresh:
            def get_credentials(self) -> Credentials:
                return Credentials(
                    access_key="MY_AWS_ACCESS_KEY_ID",
                    secret_key="MY_AWS_SECRET_ACCESS_KEY",
                )

            def refresh_credentials(self) -> Credentials:
                # Custom refresh implementation
                return self.get_credentials()

        provider = ProviderWithRefresh()
        assert isinstance(provider, CredentialProvider)

        # Should be able to call both methods
        creds1 = provider.get_credentials()
        creds2 = provider.refresh_credentials()
        assert creds1.access_key == creds2.access_key

    def test_mock_credential_provider(self) -> None:
        """Should be able to mock CredentialProvider."""
        mock_provider = Mock(spec=CredentialProvider)
        mock_creds = Credentials(
            access_key="MY_AWS_ACCESS_KEY_ID",
            secret_key="MY_AWS_SECRET_ACCESS_KEY",
        )
        mock_provider.get_credentials.return_value = mock_creds

        # Should work as protocol
        assert isinstance(mock_provider, CredentialProvider)
        result = mock_provider.get_credentials()
        assert result.access_key == "MY_AWS_ACCESS_KEY_ID"

    def test_protocol_type_checking(self) -> None:
        """Protocol should enable type checking."""

        def use_provider(provider: CredentialProvider) -> Credentials:
            """Function that accepts any CredentialProvider."""
            return provider.get_credentials()

        class MyProvider:
            def get_credentials(self) -> Credentials:
                return Credentials(
                    access_key="MY_AWS_ACCESS_KEY_ID",
                    secret_key="MY_AWS_SECRET_ACCESS_KEY",
                )

        provider = MyProvider()

        # Should work with any class that implements the protocol
        creds = use_provider(provider)
        assert creds.access_key == "MY_AWS_ACCESS_KEY_ID"
