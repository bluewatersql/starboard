# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Authentication infrastructure components.

This module contains infrastructure-level authentication services including
providers, middleware, and service interfaces.
"""

from starboard.infra.auth.service import AuthenticationService

__all__ = ["AuthenticationService"]
