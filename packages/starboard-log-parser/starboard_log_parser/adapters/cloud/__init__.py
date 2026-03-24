"""
Cloud storage adapters for multi-cloud log access.

This module provides adapters for accessing logs stored in cloud storage:
- AWS S3
- Azure ADLS Gen2 (future)
- GCP Cloud Storage (future)

Examples:
    >>> # AWS S3 access
    >>> from starboard_log_parser.adapters.cloud.s3 import S3Adapter
    >>> from starboard_log_parser.auth.providers import StaticCredentialProvider
    >>>
    >>> provider = StaticCredentialProvider(
    ...     access_key="AKIAIOSFODNN7EXAMPLE",
    ...     secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    ...     region="us-west-2",
    ... )
    >>> adapter = S3Adapter(credential_provider=provider)
    >>> exists = adapter.path_exists("s3://my-bucket/logs/eventlog.gz")
"""

from __future__ import annotations

__all__ = []  # Adapters exported directly from their modules
