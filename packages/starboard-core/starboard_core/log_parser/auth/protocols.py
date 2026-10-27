# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Authentication protocols for multi-cloud credential management.

This module defines the core abstractions for credential management,
including dataclasses for credentials and protocols for credential providers.

Examples:
    >>> from starboard_core.log_parser.auth.protocols import Credentials
    >>>
    >>> # Create basic credentials
    >>> creds = Credentials(
    ...     access_key="MY_AWS_ACCESS_KEY_ID",
    ...     secret_key="MY_AWS_SECRET_ACCESS_KEY"
    ... )
    >>>
    >>> # Check if credentials are expired
    >>> if creds.is_expired():
    ...     print("Credentials have expired")
    >>>
    >>> # Check if credentials need refresh (with 5-minute buffer)
    >>> if creds.needs_refresh():
    ...     print("Credentials should be refreshed soon")
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Credentials:
    """Cloud credentials with optional expiration.

    Immutable value object representing cloud storage credentials.
    Supports both permanent credentials (e.g., static keys) and
    temporary credentials (e.g., STS tokens, vended credentials).

    Attributes:
        access_key: Access key ID / Account key / Client ID
        secret_key: Secret access key / Account secret / Client secret
        session_token: Optional temporary session token (for STS/vended creds)
        expires_at: Optional expiration timestamp for temporary credentials
        region: Optional region hint (for S3)
        metadata: Optional additional provider-specific metadata

    Examples:
        >>> # Permanent credentials
        >>> creds = Credentials(
        ...     access_key="MY_AWS_ACCESS_KEY_ID",
        ...     secret_key="MY_AWS_SECRET_ACCESS_KEY"
        ... )
        >>> assert not creds.is_expired()  # Permanent credentials never expire
        >>>
        >>> # Temporary credentials with expiration
        >>> from datetime import datetime, timedelta, timezone
        >>> expires = datetime.now(timezone.utc) + timedelta(hours=1)
        >>> temp_creds = Credentials(
        ...     access_key="ASIATEMP",
        ...     secret_key="tempSecret",
        ...     session_token="tempSession",
        ...     expires_at=expires
        ... )
        >>> assert not temp_creds.is_expired()
        >>> assert temp_creds.needs_refresh(buffer_seconds=3600)  # Refresh within 1 hour
    """

    access_key: str
    secret_key: str
    session_token: str | None = None
    expires_at: datetime | None = None
    region: str | None = None
    metadata: dict[str, Any] | None = None

    def is_expired(self) -> bool:
        """Check if credentials have expired.

        Permanent credentials (without expires_at) never expire.
        Temporary credentials expire when current time >= expires_at.

        Returns:
            True if credentials have expired, False otherwise

        Examples:
            >>> from datetime import datetime, timedelta, timezone
            >>>
            >>> # Permanent credentials never expire
            >>> creds = Credentials(access_key="key", secret_key="secret")
            >>> assert not creds.is_expired()
            >>>
            >>> # Expired credentials
            >>> past = datetime.now(timezone.utc) - timedelta(hours=1)
            >>> expired_creds = Credentials(
            ...     access_key="key",
            ...     secret_key="secret",
            ...     expires_at=past
            ... )
            >>> assert expired_creds.is_expired()
        """
        if self.expires_at is None:
            return False  # Permanent credentials never expire
        return datetime.now(UTC) >= self.expires_at

    def needs_refresh(self, buffer_seconds: int = 300) -> bool:
        """Check if credentials should be refreshed.

        Credentials should be refreshed before they expire to avoid
        authentication errors. The buffer_seconds parameter specifies
        how many seconds before expiry to trigger a refresh.

        Args:
            buffer_seconds: Refresh before expiry (default: 300 = 5 minutes)

        Returns:
            True if credentials should be refreshed, False otherwise

        Examples:
            >>> from datetime import datetime, timedelta, timezone
            >>>
            >>> # Credentials expiring in 4 minutes
            >>> expires = datetime.now(timezone.utc) + timedelta(minutes=4)
            >>> creds = Credentials(
            ...     access_key="key",
            ...     secret_key="secret",
            ...     expires_at=expires
            ... )
            >>>
            >>> # Default 5-minute buffer - should refresh
            >>> assert creds.needs_refresh()
            >>>
            >>> # 3-minute buffer - no refresh needed yet
            >>> assert not creds.needs_refresh(buffer_seconds=180)
        """
        if self.expires_at is None:
            return False  # Permanent credentials never need refresh

        refresh_at = self.expires_at - timedelta(seconds=buffer_seconds)
        return datetime.now(UTC) >= refresh_at


@dataclass(frozen=True)
class DatabricksVendedCredentials(Credentials):
    """Credentials vended by Databricks for cloud storage access.

    Extended version of Credentials that includes Databricks-specific
    metadata like the vending endpoint used and request ID for audit trails.

    Attributes:
        vending_endpoint: Optional URL of the Databricks vending endpoint
        request_id: Optional request ID from the vending API call

    Examples:
        >>> from datetime import datetime, timedelta, timezone
        >>>
        >>> vended = DatabricksVendedCredentials(
        ...     access_key="ASIAVENDED",
        ...     secret_key="vendedSecret",
        ...     session_token="vendedSession",
        ...     expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ...     vending_endpoint="https://databricks.com/api/2.0/credentials/temporary",
        ...     request_id="req-123-456"
        ... )
        >>> assert vended.request_id == "req-123-456"
        >>> assert not vended.is_expired()  # Inherits methods from Credentials
    """

    vending_endpoint: str | None = None
    request_id: str | None = None


@runtime_checkable
class CredentialProvider(Protocol):
    """Protocol for credential providers.

    Defines the interface for credential providers that can fetch
    credentials from various sources (config, environment, IAM roles,
    service accounts, credential vending APIs).

    Uses structural subtyping (PEP 544) - any class that implements
    get_credentials() automatically satisfies this protocol.

    Examples:
        >>> class StaticProvider:
        ...     def __init__(self, access_key: str, secret_key: str) -> None:
        ...         self.access_key = access_key
        ...         self.secret_key = secret_key
        ...
        ...     def get_credentials(self) -> Credentials:
        ...         return Credentials(
        ...             access_key=self.access_key,
        ...             secret_key=self.secret_key
        ...         )
        >>>
        >>> provider = StaticProvider("MY_AWS_ACCESS_KEY_ID", "secret")
        >>> assert isinstance(provider, CredentialProvider)  # Structural subtyping
        >>> creds = provider.get_credentials()
        >>> assert creds.access_key == "MY_AWS_ACCESS_KEY_ID"
    """

    @abstractmethod
    def get_credentials(self) -> Credentials:
        """Get current valid credentials.

        Returns:
            Credentials object with access keys

        Raises:
            AuthenticationError: If credentials cannot be obtained
        """
        ...

    def refresh_credentials(self) -> Credentials:
        """Refresh credentials if needed.

        Default implementation just calls get_credentials().
        Override for providers that support explicit refresh logic.

        Returns:
            Fresh credentials

        Raises:
            AuthenticationError: If credentials cannot be refreshed

        Examples:
            >>> class MyProvider:
            ...     def get_credentials(self) -> Credentials:
            ...         return Credentials(access_key="key", secret_key="secret")
            ...
            >>> provider = MyProvider()
            >>> creds = provider.refresh_credentials()  # Calls get_credentials()
        """
        return self.get_credentials()
