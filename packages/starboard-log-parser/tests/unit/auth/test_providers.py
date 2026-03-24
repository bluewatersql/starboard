"""
Tests for credential providers.

Following TDD: tests written first, implementation follows.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Import will fail initially - that's expected in TDD
from starboard_log_parser.auth.exceptions import AuthenticationError
from starboard_log_parser.auth.protocols import CredentialProvider, Credentials
from starboard_log_parser.auth.providers import (
    EnvironmentCredentialProvider,
    StaticCredentialProvider,
)


class TestStaticCredentialProvider:
    """Tests for StaticCredentialProvider."""

    def test_inherits_from_credential_provider(self) -> None:
        """StaticCredentialProvider should satisfy CredentialProvider protocol."""
        provider = StaticCredentialProvider(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        assert isinstance(provider, CredentialProvider)

    def test_basic_credentials(self) -> None:
        """Should provide static credentials."""
        provider = StaticCredentialProvider(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        creds = provider.get_credentials()

        assert isinstance(creds, Credentials)
        assert creds.access_key == "AKIAIOSFODNN7EXAMPLE"
        assert creds.secret_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        assert creds.session_token is None
        assert creds.region is None
        assert creds.expires_at is None  # Static credentials don't expire

    def test_credentials_with_session_token(self) -> None:
        """Should support optional session token."""
        provider = StaticCredentialProvider(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            session_token="session123",
        )
        creds = provider.get_credentials()

        assert creds.session_token == "session123"

    def test_credentials_with_region(self) -> None:
        """Should support optional region."""
        provider = StaticCredentialProvider(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            region="us-west-2",
        )
        creds = provider.get_credentials()

        assert creds.region == "us-west-2"

    def test_missing_access_key(self) -> None:
        """Should raise AuthenticationError if access_key is empty."""
        provider = StaticCredentialProvider(
            access_key="",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )

        with pytest.raises(AuthenticationError) as exc_info:
            provider.get_credentials()
        assert "Static credentials not configured" in str(exc_info.value)

    def test_missing_secret_key(self) -> None:
        """Should raise AuthenticationError if secret_key is empty."""
        provider = StaticCredentialProvider(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="",
        )

        with pytest.raises(AuthenticationError) as exc_info:
            provider.get_credentials()
        assert "Static credentials not configured" in str(exc_info.value)

    def test_frozen_dataclass(self) -> None:
        """StaticCredentialProvider should be immutable."""
        provider = StaticCredentialProvider(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )

        with pytest.raises(AttributeError):
            provider.access_key = "new_key"  # type: ignore

    def test_refresh_credentials_returns_same(self) -> None:
        """refresh_credentials() should return same static credentials."""
        provider = StaticCredentialProvider(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )

        creds1 = provider.get_credentials()
        creds2 = provider.refresh_credentials()

        assert creds1.access_key == creds2.access_key
        assert creds1.secret_key == creds2.secret_key


class TestEnvironmentCredentialProvider:
    """Tests for EnvironmentCredentialProvider."""

    def test_inherits_from_credential_provider(self) -> None:
        """EnvironmentCredentialProvider should satisfy CredentialProvider protocol."""
        provider = EnvironmentCredentialProvider(cloud="aws")
        assert isinstance(provider, CredentialProvider)

    def test_aws_credentials_from_environment(self) -> None:
        """Should extract AWS credentials from environment variables."""
        with patch.dict(
            os.environ,
            {
                "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            },
            clear=False,
        ):
            provider = EnvironmentCredentialProvider(cloud="aws")
            creds = provider.get_credentials()

            assert creds.access_key == "AKIAIOSFODNN7EXAMPLE"
            assert creds.secret_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
            assert creds.session_token is None
            assert creds.region is None

    def test_aws_credentials_with_session_token(self) -> None:
        """Should extract AWS session token if present."""
        with patch.dict(
            os.environ,
            {
                "AWS_ACCESS_KEY_ID": "ASIATEMP",
                "AWS_SECRET_ACCESS_KEY": "tempSecret",
                "AWS_SESSION_TOKEN": "tempSession",
            },
            clear=False,
        ):
            provider = EnvironmentCredentialProvider(cloud="aws")
            creds = provider.get_credentials()

            assert creds.session_token == "tempSession"

    def test_aws_credentials_with_region(self) -> None:
        """Should extract AWS region from AWS_REGION."""
        with patch.dict(
            os.environ,
            {
                "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "AWS_REGION": "us-west-2",
            },
            clear=False,
        ):
            provider = EnvironmentCredentialProvider(cloud="aws")
            creds = provider.get_credentials()

            assert creds.region == "us-west-2"

    def test_aws_credentials_with_default_region(self) -> None:
        """Should fall back to AWS_DEFAULT_REGION if AWS_REGION not set."""
        with patch.dict(
            os.environ,
            {
                "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "AWS_DEFAULT_REGION": "eu-west-1",
            },
            clear=False,
        ):
            # Remove AWS_REGION if it exists
            env = os.environ.copy()
            env.pop("AWS_REGION", None)
            env.pop("AWS_SESSION_TOKEN", None)

            with patch.dict(os.environ, env, clear=True):
                provider = EnvironmentCredentialProvider(cloud="aws")
                creds = provider.get_credentials()

                assert creds.region == "eu-west-1"

    def test_aws_missing_access_key(self) -> None:
        """Should raise AuthenticationError if AWS_ACCESS_KEY_ID not set."""
        with patch.dict(os.environ, {}, clear=True):
            provider = EnvironmentCredentialProvider(cloud="aws")

            with pytest.raises(AuthenticationError) as exc_info:
                provider.get_credentials()
            assert "AWS credentials not found in environment" in str(exc_info.value)

    def test_aws_missing_secret_key(self) -> None:
        """Should raise AuthenticationError if AWS_SECRET_ACCESS_KEY not set."""
        with patch.dict(
            os.environ,
            {"AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE"},
            clear=True,
        ):
            provider = EnvironmentCredentialProvider(cloud="aws")

            with pytest.raises(AuthenticationError) as exc_info:
                provider.get_credentials()
            assert "AWS credentials not found in environment" in str(exc_info.value)

    def test_azure_credentials_from_environment(self) -> None:
        """Should extract Azure credentials from environment variables."""
        with patch.dict(
            os.environ,
            {
                "AZURE_STORAGE_ACCOUNT": "mystorageaccount",
                "AZURE_STORAGE_KEY": "myaccountkey==",
            },
            clear=False,
        ):
            provider = EnvironmentCredentialProvider(cloud="azure")
            creds = provider.get_credentials()

            assert creds.access_key == "mystorageaccount"
            assert creds.secret_key == "myaccountkey=="

    def test_azure_missing_account(self) -> None:
        """Should raise AuthenticationError if AZURE_STORAGE_ACCOUNT not set."""
        with patch.dict(os.environ, {}, clear=True):
            provider = EnvironmentCredentialProvider(cloud="azure")

            with pytest.raises(AuthenticationError) as exc_info:
                provider.get_credentials()
            assert "Azure credentials not found in environment" in str(exc_info.value)

    def test_azure_missing_key(self) -> None:
        """Should raise AuthenticationError if AZURE_STORAGE_KEY not set."""
        with patch.dict(
            os.environ,
            {"AZURE_STORAGE_ACCOUNT": "mystorageaccount"},
            clear=True,
        ):
            provider = EnvironmentCredentialProvider(cloud="azure")

            with pytest.raises(AuthenticationError) as exc_info:
                provider.get_credentials()
            assert "Azure credentials not found in environment" in str(exc_info.value)

    def test_gcp_credentials_from_environment(self) -> None:
        """Should extract GCP credentials file path from environment."""
        with patch.dict(
            os.environ,
            {"GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"},
            clear=False,
        ):
            provider = EnvironmentCredentialProvider(cloud="gcp")
            creds = provider.get_credentials()

            # GCP uses credentials file, not direct keys
            assert creds.access_key == ""
            assert creds.secret_key == ""
            assert creds.metadata is not None
            assert creds.metadata["credentials_file"] == "/path/to/service-account.json"

    def test_gcp_missing_credentials_file(self) -> None:
        """Should raise AuthenticationError if GOOGLE_APPLICATION_CREDENTIALS not set."""
        with patch.dict(os.environ, {}, clear=True):
            provider = EnvironmentCredentialProvider(cloud="gcp")

            with pytest.raises(AuthenticationError) as exc_info:
                provider.get_credentials()
            assert "GCP credentials not found in environment" in str(exc_info.value)

    def test_unsupported_cloud_provider(self) -> None:
        """Should raise AuthenticationError for unsupported cloud provider."""
        provider = EnvironmentCredentialProvider(cloud="digitalocean")

        with pytest.raises(AuthenticationError) as exc_info:
            provider.get_credentials()
        assert "Unsupported cloud provider" in str(exc_info.value)
        assert "digitalocean" in str(exc_info.value)

    def test_frozen_dataclass(self) -> None:
        """EnvironmentCredentialProvider should be immutable."""
        provider = EnvironmentCredentialProvider(cloud="aws")

        with pytest.raises(AttributeError):
            provider.cloud = "azure"  # type: ignore
