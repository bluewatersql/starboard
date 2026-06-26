# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
API client wrappers for external services.

This package provides low-level API clients for interacting with external services.

Note:
    The Databricks API client has moved to `starboard_server.adapters.databricks`.
    Use `AsyncDatabricksClient` for all new code.
"""

from starboard_server.adapters.apis.http_client import HTTPClient
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

__all__ = ["HTTPClient"]
