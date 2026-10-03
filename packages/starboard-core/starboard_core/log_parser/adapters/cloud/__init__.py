# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Cloud storage adapters for multi-cloud log access.

This module provides adapters for accessing logs stored in cloud storage:
- AWS S3
- Azure ADLS Gen2 (future)
- GCP Cloud Storage (future)

Examples:
    >>> # AWS S3 access
    >>> from starboard_core.log_parser.adapters.cloud.s3 import S3Adapter
    >>> from starboard_core.log_parser.auth.providers import StaticCredentialProvider
    >>>
    >>> provider = StaticCredentialProvider(
    ...     access_key="MY_AWS_ACCESS_KEY_ID",
    ...     secret_key="MY_AWS_SECRET_ACCESS_KEY",
    ...     region="us-west-2",
    ... )
    >>> adapter = S3Adapter(credential_provider=provider)
    >>> exists = adapter.path_exists("s3://my-bucket/logs/eventlog.gz")
"""

from __future__ import annotations

__all__ = []  # Adapters exported directly from their modules
