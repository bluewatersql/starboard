# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Credential provider implementations.

This module provides concrete implementations of the CredentialProvider
protocol for various authentication methods.

Examples:
    >>> # Static credentials (development/testing)
    >>> from starboard_core.log_parser.auth.providers import StaticCredentialProvider
    >>> provider = StaticCredentialProvider(
    ...     access_key="MY_AWS_ACCESS_KEY_ID",
    ...     secret_key="MY_AWS_SECRET_ACCESS_KEY"
    ... )
    >>> creds = provider.get_credentials()
    >>>
    >>> # Environment variables (12-factor apps)
    >>> import os
    >>> os.environ["AWS_ACCESS_KEY_ID"] = "MY_AWS_ACCESS_KEY_ID"
    >>> os.environ["AWS_SECRET_ACCESS_KEY"] = "MY_AWS_SECRET_ACCESS_KEY"
    >>> provider = EnvironmentCredentialProvider(cloud="aws")
    >>> creds = provider.get_credentials()
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from starboard_core.log_parser.auth.exceptions import AuthenticationError
from starboard_core.log_parser.auth.protocols import Credentials


@dataclass(frozen=True)
class StaticCredentialProvider:
    """Provides static credentials from configuration.

    Use for:
    - Local development
    - Service accounts with permanent keys
    - Testing

    NOT recommended for production - prefer environment variables,
    IAM roles, or credential vending for better security.

    Attributes:
        access_key: Access key ID / Account key / Client ID
        secret_key: Secret access key / Account secret / Client secret
        session_token: Optional temporary session token
        region: Optional region hint (for S3)

    Examples:
        >>> provider = StaticCredentialProvider(
        ...     access_key="MY_AWS_ACCESS_KEY_ID",
        ...     secret_key="MY_AWS_SECRET_ACCESS_KEY"
        ... )
        >>> creds = provider.get_credentials()
        >>> assert creds.access_key == "MY_AWS_ACCESS_KEY_ID"
        >>>
        >>> # With optional region
        >>> provider = StaticCredentialProvider(
        ...     access_key="MY_AWS_ACCESS_KEY_ID",
        ...     secret_key="MY_AWS_SECRET_ACCESS_KEY",
        ...     region="us-west-2"
        ... )
        >>> creds = provider.get_credentials()
        >>> assert creds.region == "us-west-2"
    """

    access_key: str
    secret_key: str
    session_token: str | None = None
    region: str | None = None

    def get_credentials(self) -> Credentials:
        """Return configured static credentials.

        Returns:
            Credentials object with configured keys

        Raises:
            AuthenticationError: If access_key or secret_key is empty

        Examples:
            >>> provider = StaticCredentialProvider(
            ...     access_key="MY_AWS_ACCESS_KEY_ID",
            ...     secret_key="MY_AWS_SECRET_ACCESS_KEY"
            ... )
            >>> creds = provider.get_credentials()
            >>> assert not creds.is_expired()  # Static credentials don't expire
        """
        if not self.access_key or not self.secret_key:
            raise AuthenticationError("Static credentials not configured")

        return Credentials(
            access_key=self.access_key,
            secret_key=self.secret_key,
            session_token=self.session_token,
            region=self.region,
            expires_at=None,  # Static credentials don't expire
        )

    def refresh_credentials(self) -> Credentials:
        """Refresh credentials (returns same static credentials).

        Static credentials don't need refresh, so this just returns
        the same credentials as get_credentials().

        Returns:
            Credentials object with configured keys
        """
        return self.get_credentials()


@dataclass(frozen=True)
class EnvironmentCredentialProvider:
    """Provides credentials from environment variables.

    Follows standard cloud provider environment variable conventions:
    - AWS: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN,
           AWS_REGION (or AWS_DEFAULT_REGION)
    - Azure: AZURE_STORAGE_ACCOUNT, AZURE_STORAGE_KEY
    - GCP: GOOGLE_APPLICATION_CREDENTIALS (service account JSON file path)

    Use for:
    - 12-factor apps
    - Container/serverless deployments
    - CI/CD environments
    - Development with direnv/dotenv

    Attributes:
        cloud: Cloud provider ("aws", "azure", or "gcp")

    Examples:
        >>> import os
        >>>
        >>> # AWS credentials
        >>> os.environ["AWS_ACCESS_KEY_ID"] = "MY_AWS_ACCESS_KEY_ID"
        >>> os.environ["AWS_SECRET_ACCESS_KEY"] = "MY_AWS_SECRET_ACCESS_KEY"
        >>> provider = EnvironmentCredentialProvider(cloud="aws")
        >>> creds = provider.get_credentials()
        >>>
        >>> # Azure credentials
        >>> os.environ["AZURE_STORAGE_ACCOUNT"] = "mystorageaccount"
        >>> os.environ["AZURE_STORAGE_KEY"] = "myaccountkey=="
        >>> provider = EnvironmentCredentialProvider(cloud="azure")
        >>> creds = provider.get_credentials()
        >>>
        >>> # GCP credentials (service account file)
        >>> os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/path/to/sa.json"
        >>> provider = EnvironmentCredentialProvider(cloud="gcp")
        >>> creds = provider.get_credentials()
    """

    cloud: str  # "aws", "azure", or "gcp"

    def get_credentials(self) -> Credentials:
        """Extract credentials from environment variables.

        Returns:
            Credentials object populated from environment

        Raises:
            AuthenticationError: If required environment variables are not set
                                or if cloud provider is not supported

        Examples:
            >>> import os
            >>> os.environ["AWS_ACCESS_KEY_ID"] = "MY_AWS_ACCESS_KEY_ID"
            >>> os.environ["AWS_SECRET_ACCESS_KEY"] = "MY_AWS_SECRET_ACCESS_KEY"
            >>> os.environ["AWS_REGION"] = "us-west-2"
            >>>
            >>> provider = EnvironmentCredentialProvider(cloud="aws")
            >>> creds = provider.get_credentials()
            >>> assert creds.access_key == "MY_AWS_ACCESS_KEY_ID"
            >>> assert creds.region == "us-west-2"
        """
        if self.cloud == "aws":
            return self._get_aws_credentials()
        elif self.cloud == "azure":
            return self._get_azure_credentials()
        elif self.cloud == "gcp":
            return self._get_gcp_credentials()
        else:
            raise AuthenticationError(f"Unsupported cloud provider: {self.cloud}")

    def _get_aws_credentials(self) -> Credentials:
        """Extract AWS credentials from environment.

        Environment variables:
        - AWS_ACCESS_KEY_ID (required)
        - AWS_SECRET_ACCESS_KEY (required)
        - AWS_SESSION_TOKEN (optional)
        - AWS_REGION or AWS_DEFAULT_REGION (optional)

        Returns:
            Credentials with AWS keys

        Raises:
            AuthenticationError: If AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY not set
        """
        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        session_token = os.environ.get("AWS_SESSION_TOKEN")
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION"))

        if not access_key or not secret_key:
            raise AuthenticationError("AWS credentials not found in environment")

        return Credentials(
            access_key=access_key,
            secret_key=secret_key,
            session_token=session_token,
            region=region,
        )

    def _get_azure_credentials(self) -> Credentials:
        """Extract Azure credentials from environment.

        Environment variables:
        - AZURE_STORAGE_ACCOUNT (required)
        - AZURE_STORAGE_KEY (required)

        Returns:
            Credentials with Azure account and key

        Raises:
            AuthenticationError: If AZURE_STORAGE_ACCOUNT or AZURE_STORAGE_KEY not set
        """
        account = os.environ.get("AZURE_STORAGE_ACCOUNT")
        key = os.environ.get("AZURE_STORAGE_KEY")

        if not account or not key:
            raise AuthenticationError("Azure credentials not found in environment")

        return Credentials(
            access_key=account,
            secret_key=key,
        )

    def _get_gcp_credentials(self) -> Credentials:
        """Extract GCP credentials from environment.

        Environment variables:
        - GOOGLE_APPLICATION_CREDENTIALS (required): Path to service account JSON file

        For GCP, we return the path to the service account file in metadata.
        The actual credential loading is handled by google-cloud-storage SDK.

        Returns:
            Credentials with service account file path in metadata

        Raises:
            AuthenticationError: If GOOGLE_APPLICATION_CREDENTIALS not set
        """
        creds_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        if not creds_file:
            raise AuthenticationError("GCP credentials not found in environment")

        # For GCP, we return the path to the service account file
        # The actual credential loading is handled by google-cloud-storage
        return Credentials(
            access_key="",  # Not used for GCP
            secret_key="",  # Not used for GCP
            metadata={"credentials_file": creds_file},
        )

    def refresh_credentials(self) -> Credentials:
        """Refresh credentials (re-reads environment variables).

        Environment credentials are typically static, but re-reading
        allows for credential rotation via environment variable updates.

        Returns:
            Fresh credentials from environment
        """
        return self.get_credentials()
