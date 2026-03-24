"""
Authentication module for multi-cloud storage access.

This module provides a flexible authentication framework for cloud storage
connectors, supporting multiple credential providers and credential vending.

Examples:
    >>> from starboard_log_parser.auth.providers import StaticCredentialProvider
    >>> provider = StaticCredentialProvider(
    ...     access_key="AKIAIOSFODNN7EXAMPLE",
    ...     secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    ... )
    >>> credentials = provider.get_credentials()
"""

from __future__ import annotations

from starboard_log_parser.auth.exceptions import (
    AuthenticationError,
    CredentialExpiredError,
)
from starboard_log_parser.auth.protocols import (
    CredentialProvider,
    Credentials,
    DatabricksVendedCredentials,
)
from starboard_log_parser.auth.providers import (
    EnvironmentCredentialProvider,
    StaticCredentialProvider,
)

__all__ = [
    # Exceptions
    "AuthenticationError",
    "CredentialExpiredError",
    # Protocols
    "Credentials",
    "CredentialProvider",
    "DatabricksVendedCredentials",
    # Providers
    "StaticCredentialProvider",
    "EnvironmentCredentialProvider",
]
